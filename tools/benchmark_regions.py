"""Offline regional scan cost/accuracy experiment; does not change live scan policy."""

import argparse
import json
import socket
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any
from unittest.mock import patch

import shiboken6
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry, union_bounds
from jp_overlay.meiki import MeikiRecognizer
from jp_overlay.models import model_directory
from jp_overlay.recognition import recognize_regions


def fixture(kind: str) -> tuple[CapturedFrame, tuple[Rect, ...], tuple[str, ...]]:
    image = QImage(1920, 1080, QImage.Format.Format_RGB32)
    image.fill(QColor(20, 35, 55))
    painter = QPainter(image)
    painter.setPen(QColor(245, 245, 245))
    font = QFont("Yu Gothic UI")
    font.setPixelSize(26)
    painter.setFont(font)
    spread = kind == "spread_dense"
    positions = (
        (100, 100),
        (1400 if spread else 470, 100),
        (100, 800 if spread else 270),
        (1400 if spread else 470, 800 if spread else 270),
    )
    areas = tuple(Rect(x, y, 320, 108) for x, y in positions)
    phrases = (
        "旅の準備をしよう。",
        "新しい冒険が始まる。",
        "一緒に出かけよう。",
        "明日また会いましょう。",
    )
    if kind != "blank":
        for i, (box, phrase) in enumerate(zip(areas, phrases, strict=True)):
            # Final requested crop deliberately cuts a line; the real edge safeguard
            # may retry full frame. Record what actually happened, never fake timings.
            x = box.x + (260 if kind == "clipped" and i == 3 else 20)
            painter.drawText(x, box.y + 60, phrase)
    if spread:
        for y in range(300, 730, 70):
            for x in range(100, 1700, 400):
                painter.drawText(x, y, "これは周囲の説明です。")
    painter.end()
    bounds = Rect(0, 0, 1920, 1080)
    return (
        CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), bytes(image.constBits())),
        areas,
        () if kind == "blank" else phrases,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 2 <= args.repeats <= 20:
        parser.error("Use 2..20 measured repetitions.")
    app = QApplication([])
    reports = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        engine = MeikiRecognizer(model_directory(), device=args.device)
        detected: list[float] = []
        recognized: list[float] = []
        detection = engine._engine.run_detection
        recognition = engine._engine._run_recognition_inference

        def detect(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            result = detection(*args, **kwargs)
            detected.append((perf_counter() - started) * 1000)
            return result

        def recognize(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            result = recognition(*args, **kwargs)
            recognized.append((perf_counter() - started) * 1000)
            return result

        try:
            assert args.device != "cuda" or engine.provider == "CUDAExecutionProvider"
            with (
                patch.object(engine._engine, "run_detection", detect),
                patch.object(engine._engine, "_run_recognition_inference", recognize),
            ):
                for kind in ("nearby", "spread_dense", "clipped", "blank"):
                    frame, areas, expected = fixture(kind)
                    plans = {
                        "separate": areas,
                        "paired": (union_bounds(areas[:2]), union_bounds(areas[2:])),
                        "merged": (union_bounds(areas),),
                        "full": None,
                    }
                    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in plans}
                    # First-use/shape warm-up separate from measured work. Rotate plan
                    # order to avoid always rewarding the last warmed scan shape.
                    for trial in range(args.repeats + 1):
                        order = list(plans)
                        order = order[trial % 4 :] + order[: trial % 4]
                        for name in order:
                            detected.clear()
                            recognized.clear()
                            started = perf_counter()
                            regions, coverage = recognize_regions(engine, frame, plans[name])
                            elapsed = (perf_counter() - started) * 1000
                            samples[name].append(
                                dict(
                                    ms=elapsed,
                                    detector_ms=sum(detected),
                                    detector_calls=len(detected),
                                    recognition_ms=sum(recognized),
                                    recognition_batches=len(recognized),
                                    full_coverage=coverage is None,
                                    coverage=None
                                    if coverage is None
                                    else [asdict(b) for b in coverage],
                                    target_hits=sum(
                                        any(p in r.text for r in regions) for p in expected
                                    ),
                                    regions=[asdict(r) for r in regions],
                                )
                            )
                    for name, runs in samples.items():
                        warm = runs[1:]
                        reports.append(
                            dict(
                                case=kind,
                                plan=name,
                                expected=expected,
                                first_ms=runs[0]["ms"],
                                median_ms=median(r["ms"] for r in warm),
                                detector_ms=median(r["detector_ms"] for r in warm),
                                detector_calls=[r["detector_calls"] for r in warm],
                                recognition_ms=median(r["recognition_ms"] for r in warm),
                                recognition_batches=[r["recognition_batches"] for r in warm],
                                full_scans=sum(r["full_coverage"] for r in warm),
                                target_hits=[r["target_hits"] for r in warm],
                                trials=runs,
                            )
                        )
                        print(
                            f"{kind}/{name}: {reports[-1]['median_ms']:.1f} ms; "
                            f"hits {reports[-1]['target_hits']}",
                            flush=True,
                        )
        finally:
            engine.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(device=args.device, cases=reports), indent=2), "utf-8")
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
