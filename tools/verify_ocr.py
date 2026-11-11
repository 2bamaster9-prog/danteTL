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
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.inspection import OcrInspector
from jp_overlay.meiki import MeikiRecognizer
from jp_overlay.models import model_directory
from jp_overlay.recognition import OcrResult

EXPECTED = ("新しい冒険が、ここから始まる。", "旅の準備はできましたか？", "設定")


def fixture() -> CapturedFrame:
    image = QImage(1920, 1080, QImage.Format.Format_RGB32)
    image.fill(QColor("#172d42"))
    painter = QPainter(image)
    painter.setPen(QColor("#ffffff"))
    font = QFont("Yu Gothic UI")
    font.setPixelSize(38)
    painter.setFont(font)
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
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    frame = fixture()
    with patch.object(
        socket.socket, "connect", side_effect=AssertionError("Unexpected network I/O")
    ):
        started = time.monotonic()
        engine = MeikiRecognizer(model_directory())
        load_ms = (time.monotonic() - started) * 1000
        timings = []
        regions = ()
        for _ in range(6):
            started = time.monotonic()
            regions = engine.recognize(frame)
            timings.append((time.monotonic() - started) * 1000)
    observed = {region.text for region in regions}

    def normalize(text: str) -> str:
        return unicodedata.normalize("NFKC", text)

    missing = {normalize(text) for text in EXPECTED} - {normalize(text) for text in observed}
    assert not missing, f"Fixture text missing after width normalization: {missing}; got {observed}"
    for region in regions:
        assert Rect(0, 0, frame.width, frame.height).contains(region.bounds)
        assert region.characters
    evidence = {
        "fixture": "original synthetic Japanese text, 1920x1080",
        "network_blocked": True,
        "expected": EXPECTED,
        "match_policy": "NFKC (full-width/ASCII punctuation differences); raw text preserved",
        "provider": "CPUExecutionProvider",
        "cpu_threads": 2,
        "model_load_ms": round(load_ms, 1),
        "first_inference_ms": round(timings[0], 1),
        "warm_median_ms": round(statistics.median(timings[1:]), 1),
        "warm_max_ms": round(max(timings[1:]), 1),
        "regions": [asdict(region) for region in regions],
    }
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
    summary = {key: value for key, value in evidence.items() if key != "regions"}
    summary["recognized_text"] = [region.text for region in regions]
    print(json.dumps(summary, ensure_ascii=True, indent=2))
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
