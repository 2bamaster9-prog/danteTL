"""Read a game-menu label for every registered Latin source using the selected local provider."""

import argparse
import time

from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QRawFont
from verification_isolation import run_isolated

from dantejp.application.model_factories import create_recognizer
from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.languages.selection import LATIN_SOURCES, source_language
from dantejp.ocr.tracking import TextTrack
from dantejp.ocr.worker import Recognizer, recognize_regions
from dantejp.runtime.ocr import CPU, CUDA
from dantejp.translation.grouping import DialogueGrouper


def verify_profile(engine: Recognizer) -> None:
    title = "Character record"
    rows = (
        "The captain of the guard",
        "stood beside the river as",
        "the morning mist rose.",
        "Across the bridge she saw",
        "the gates of the city and",
        "the towers beyond them.",
    )
    image = QImage(3840, 2160, QImage.Format.Format_RGB32)
    image.fill(QColor("#202d43"))
    painter = QPainter(image)
    font = QFont("Segoe UI")
    font.setPixelSize(48)
    painter.setFont(font)
    painter.setPen(QColor("#fff9df"))
    painter.drawText(2980, 805, title)
    for i, row in enumerate(rows):
        painter.drawText(2980, 880 + i * 65, row)
    painter.end()
    bounds = Rect(0, 0, image.width(), image.height())
    frame = CapturedFrame(
        1, 0, WindowGeometry(bounds, bounds, bounds, 96), bytes(image.constBits())
    )
    for coverage in (None, (Rect(2880, 715, 900, 600),)):
        lines, scanned = recognize_regions(engine, frame, coverage)
        assert scanned == coverage
        tracks = tuple(TextTrack(i, r.text, r.bounds) for i, r in enumerate(lines))
        blocks = DialogueGrouper(language=source_language("en")).update(tracks, tracks, 0).blocks
        members = [tuple(t.text for t in b.lines) for b in blocks]
        assert members == [(title,), rows], (coverage, members)
    print("4K heading and paragraph in reading order on full and regional scans.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    args = parser.parse_args()
    app = QGuiApplication([])
    font = QFont("Segoe UI")
    font.setPixelSize(28)
    glyphs = QRawFont.fromFont(font)
    engine = create_recognizer(device=args.device, language=LATIN_SOURCES[0])
    try:
        assert getattr(engine, "provider", "") == (CUDA if args.device == "cuda" else CPU)
        for language in LATIN_SOURCES:
            label = language.warmup_text
            assert all(glyphs.supportsCharacter(ord(c)) for c in label)
            image = QImage(1280, 720, QImage.Format.Format_RGB32)
            image.fill(QColor("#202d43"))
            painter = QPainter(image)
            painter.setFont(font)
            painter.setPen(QColor("#fff9df"))
            painter.drawText(100, 160, label)
            painter.end()
            bounds = Rect(0, 0, 1280, 720)
            frame = CapturedFrame(
                1,
                time.monotonic(),
                WindowGeometry(bounds, bounds, bounds, 96),
                bytes(image.constBits()),
            )
            area = Rect(50, 85, 500, 130)
            for coverage in (None, (area,)):
                lines, scanned = recognize_regions(engine, frame, coverage)
                assert [r.text for r in lines] == [label], (language.code, coverage, lines)
                assert scanned == coverage and area.contains(lines[0].bounds)
                assert lines[0].confidence is not None and 0 < lines[0].confidence <= 1
            print(language.code, ascii(label), flush=True)
        verify_profile(engine)
    finally:
        engine.close()
        app.quit()


if __name__ == "__main__":
    run_isolated(main)
