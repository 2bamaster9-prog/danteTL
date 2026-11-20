"""Offline small-crop OCR regression on owned pixels; no downloads or game captures."""

import argparse
import json
import socket
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from dantetl.domain import CapturedFrame, Rect, WindowGeometry
from dantetl.ocr.meiki import MeikiRecognizer
from dantetl.ocr.models import model_directory
from dantetl.ocr.worker import recognize_regions


def fixture(font_size: int, light: bool, kind: str) -> tuple[CapturedFrame, Rect, tuple[str, ...]]:
    image = QImage(1575, 1015, QImage.Format.Format_RGB32)
    image.fill(QColor(245, 245, 245) if light else QColor(20, 35, 55))
    painter = QPainter(image)
    painter.setPen(QColor(20, 35, 55) if light else QColor(245, 245, 245))
    font = QFont("Yu Gothic UI")
    font.setPixelSize(font_size)
    painter.setFont(font)
    lines = ("設定",)
    area = Rect(50, 64, 195, 210)
    if kind == "dialogue":
        lines = ("旅の準備をしてから、", "一緒に出かけましょう。")
        area = Rect(50, 64, 620, 210)
    elif kind == "blank":
        lines = ()
    elif kind == "icon":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRect(65, 145, 22, 22))
    for i, line in enumerate(lines):
        painter.drawText(105, 175 + i * (font_size + 14), line)
    painter.end()
    bounds = Rect(0, 0, image.width(), image.height())
    frame = CapturedFrame(
        1, 0, WindowGeometry(bounds, bounds, bounds, 168), bytes(image.constBits())
    )
    return frame, area, lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication([])
    results = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        engine = MeikiRecognizer(model_directory(), device=args.device)
        try:
            cases = [
                (size, light, "label")
                for size in (16, 24, 26, 28, 32, 38, 46, 56)
                for light in (False, True)
            ]
            cases += [(26, False, kind) for kind in ("icon", "dialogue", "blank")]
            for size, light, kind in cases:
                frame, area, expected = fixture(size, light, kind)
                started = time.perf_counter()
                regions, coverage = recognize_regions(engine, frame, (area,))
                elapsed = (time.perf_counter() - started) * 1000
                text = tuple(r.text for r in regions)
                assert coverage == (area,), (kind, "Unexpected full-frame fallback")
                assert all(area.contains(r.bounds) for r in regions)
                assert all(area.contains(c.bounds) for r in regions for c in r.characters)
                assert all(any(line in found for found in text) for line in expected), (
                    size,
                    light,
                    kind,
                    text,
                )
                if not expected:
                    assert not regions, "Padding invented a detection in a blank crop"
                results.append(
                    dict(
                        font_px=size,
                        light=light,
                        kind=kind,
                        ms=round(elapsed, 1),
                        regions=[asdict(r) for r in regions],
                    )
                )
        finally:
            engine.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(dict(device=args.device, cases=results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Passed {len(results)} small-crop cases on {args.device}")
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
