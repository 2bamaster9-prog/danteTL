"""Offline real-model smoke/replay check against an original Japanese text fixture.

Only synthetic pixels are saved. This does not claim game accuracy or general CER.
Run with --output artifacts/ocr to save a reviewable frame, inspector image, and JSON.
"""

import argparse
import json
import socket
import statistics
import time
import unicodedata
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.meiki import MeikiRecognizer
from dantejp.ocr.models import model_directory
from dantejp.ocr.presence import prepare_evidence
from dantejp.ocr.tracking import TextTracker, prepare_matching
from dantejp.ocr.values import OcrResult
from dantejp.ocr.visual import VisualAnalyzer
from dantejp.ocr.worker import recognize_regions
from dantejp.ui.inspection import OcrInspector

EXPECTED = ("新しい冒険が、ここから始まる。", "旅の準備はできましたか？", "設定")


def fixture(dense: bool = False) -> CapturedFrame:
    image = QImage(3840 if dense else 1920, 2160 if dense else 1080, QImage.Format.Format_RGB32)
    image.fill(QColor("#172d42"))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Yu Gothic UI")
    font.setPixelSize(38)
    painter.setFont(font)
    if dense:
        for row in range(10):
            for col in range(8):
                painter.drawText(40 + col * 480, 100 + row * 200, "アイテムの情報を確認")
    else:
        for text, x, y in zip(EXPECTED, (160, 160, 1550), (780, 850, 150), strict=True):
            painter.drawText(x, y, text)
    painter.end()
    bounds = Rect(0, 0, image.width(), image.height())
    return CapturedFrame(
        1, time.monotonic(), WindowGeometry(bounds, bounds, bounds, 96), bytes(image.constBits())
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dense", action="store_true", help="Benchmark 80 labels at 4K")
    parser.add_argument(
        "--device", choices=("cpu", "auto", "cuda", "directml", "auto-directml"), default="cpu"
    )
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    frame = fixture(args.dense)
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Unexpected network I/O")
    ):
        started = time.perf_counter()
        engine = MeikiRecognizer(model_directory(), device=args.device)
        load_ms = (time.perf_counter() - started) * 1000
        timings = []
        regions = ()
        for _ in range(6):
            started = time.perf_counter()
            regions = engine.recognize(frame)
            timings.append((time.perf_counter() - started) * 1000)
        regional_times = []
        alternating_times = []
        regional_regions = ()
        regional_coverage = None
        if args.dense:
            for _ in range(6):
                started = time.perf_counter()
                regional_regions, regional_coverage = recognize_regions(
                    engine, frame, (Rect(0, 25, 475, 130),)
                )
                regional_times.append((time.perf_counter() - started) * 1000)
            for _ in range(3):
                engine.recognize(frame)
                started = time.perf_counter()
                recognize_regions(engine, frame, (Rect(0, 25, 475, 130),))
                alternating_times.append((time.perf_counter() - started) * 1000)
    observed = {region.text for region in regions}

    def normalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text)

    expected = ("アイテムの情報を確認",) if args.dense else EXPECTED
    missing = {normalize(text) for text in expected} - {normalize(text) for text in observed}
    assert not missing, f"Fixture text missing after width normalization: {missing}; got {observed}"
    for region in regions:
        assert Rect(0, 0, frame.width, frame.height).contains(region.bounds)
        assert region.characters
    tracker = TextTracker()
    tracking_timings, preparation_timings = [], []
    for sequence in range(1, 7):
        source = replace(frame, sequence=sequence, captured_at=sequence * 0.25)
        result = OcrResult(source, regions, timings[-1], source.captured_at + timings[-1] / 1000)
        started = time.perf_counter()
        pixels = prepare_evidence(result, tracker.evidence_bounds())
        matching = prepare_matching(result, tracker.matching_sources(source))
        preparation_timings.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        tracker.observe(result, pixel_evidence=pixels, matching=matching)
        tracker.visible(source, result.completed_at)
        tracking_timings.append((time.perf_counter() - started) * 1000)
    evidence = {
        "fixture": f"original synthetic Japanese text, {frame.width}x{frame.height}",
        "network_blocked": True,
        "expected": expected,
        "region_count": len(regions),
        "drawn_label_count": 80 if args.dense else len(EXPECTED),
        "match_policy": "NFKC (full-width/ASCII punctuation differences); raw text preserved",
        "provider": engine.provider,
        "provider_message": engine.message,
        "cpu_threads": 2,
        "model_load_ms": round(load_ms, 1),
        "first_inference_ms": round(timings[0], 1),
        "warm_median_ms": round(statistics.median(timings[1:]), 1),
        "warm_max_ms": round(max(timings[1:]), 1),
        "tracking_worker_preparation_median_ms": round(
            statistics.median(preparation_timings[1:]), 2
        ),
        "tracking_warm_median_ms": round(statistics.median(tracking_timings[1:]), 2),
        "tracking_warm_max_ms": round(max(tracking_timings[1:]), 2),
        "regions": [asdict(region) for region in regions],
    }
    if regional_times:
        assert regional_coverage is not None, "Regional fixture unexpectedly fell back to full scan"
        assert any(normalize("アイテムの情報を確認") in normalize(r.text) for r in regional_regions)
        assert all(regional_coverage[0].contains(r.bounds) for r in regional_regions)
        evidence.update(
            regional_first_ms=round(regional_times[0], 1),
            regional_warm_median_ms=round(statistics.median(regional_times[1:]), 1),
            regional_warm_max_ms=round(max(regional_times[1:]), 1),
            regional_scanned_pixels=475 * 130,
            regional_regions=[asdict(r) for r in regional_regions],
            regional_after_full_median_ms=round(statistics.median(alternating_times), 1),
            regional_after_full_max_ms=round(max(alternating_times), 1),
        )
    visual, tracker = VisualAnalyzer(), TextTracker()
    reference = replace(frame, sequence=1, captured_at=0)
    result = OcrResult(reference, regions, timings[-1], 0.05)
    assignments = tracker.observe(
        result, pixel_evidence=prepare_evidence(result), matching=prepare_matching(result, ())
    )
    tracks = tracker.visible(reference, 0.05)
    visual_times, requests = [], 0
    for i in range(1, 17):
        state = visual.observe(
            replace(reference, sequence=i, captured_at=(i - 1) / 8),
            result,
            tracks,
            assignments,
        )
        visual_times.append(state.duration_ms)
        requests += state.request_ocr
    evidence.update(
        visual_warm_median_ms=round(statistics.median(visual_times[1:]), 2),
        visual_warm_max_ms=round(max(visual_times[1:]), 2),
        unchanged_captures=16,
        unchanged_ocr_requests=requests,
    )
    moving_times = []
    pixels = np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width, 4)
    for i in range(17, 25):
        # Stress every known crop. Frame generation is outside the visual timer.
        moving = replace(
            reference,
            sequence=i,
            captured_at=(i - 1) / 8,
            bgra=np.roll(pixels, 4 + i % 3, axis=1).tobytes(),
        )
        moving_times.append(visual.observe(moving, result, tracks, assignments).duration_ms)
    evidence.update(
        moving_visual_median_ms=round(statistics.median(moving_times), 2),
        moving_visual_max_ms=round(max(moving_times), 2),
    )
    review_times = []
    for i in range(25, 33):
        source = replace(reference, sequence=i, captured_at=(i - 1) / 8)
        candidate = replace(result, frame=source)
        state = visual.observe(source, result, tracks, assignments, candidate=candidate)
        review_times.append(state.duration_ms)
        assert len(state.unchanged) == len(tracks)
    evidence.update(
        source_review_median_ms=round(statistics.median(review_times), 2),
        source_review_max_ms=round(max(review_times), 2),
    )
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        panel = OcrInspector()
        panel.resize(1120, 540)
        panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        panel.show()
        panel.set_result(OcrResult(frame, regions, timings[-1], time.monotonic()))
        app.processEvents()
        panel.grab().save(str(args.output / "inspector.png"))
        (args.output / "result.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        panel.close()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    summary = {
        key: value for key, value in evidence.items() if key not in ("regions", "regional_regions")
    }
    summary["recognized_text"] = list(dict.fromkeys(region.text for region in regions))
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
