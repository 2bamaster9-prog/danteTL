"""Owned offline layout images and bounded rebuild/repaint measurements; no capture."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

import shiboken6
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from dantetl.domain import Rect
from dantetl.ocr.regions import intersects
from dantetl.ui.english_placement import EnglishLabel, EnglishPlacement
from dantetl.ui.text_layout import EnglishLayout, layout_english


def paint(painter: QPainter, layouts: tuple[EnglishLayout, ...]) -> None:
    for layout in layouts:
        box = layout.bounds
        painter.fillRect(QRectF(box.x, box.y, box.width, box.height), QColor(12, 20, 31, 240))
        font = QFont("Segoe UI")
        font.setPixelSize(layout.pixel_size)
        painter.setFont(font)
        painter.setPen(QColor("#f1f5f9"))
        for i, line in enumerate(layout.lines):
            painter.drawText(
                QPointF(box.x + 4, box.y + 4 + layout.ascent + i * layout.line_height), line
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    labels = tuple(
        EnglishLabel(((i, 1, "日本語"),), text, box, 24)
        for i, (text, box) in enumerate(
            (
                (
                    "This is the first longer English translation for the small label.",
                    Rect(180, 160, 150, 24),
                ),
                (
                    "This is the second longer English translation for the small label.",
                    Rect(180, 190, 150, 24),
                ),
                ("Inventory", Rect(580, 80, 150, 24)),
                ("A longer description near the corner of the screen.", Rect(650, 540, 150, 24)),
                (
                    "Prepare for a new adventure. There is much more to discover.",
                    Rect(120, 400, 550, 60),
                ),
            )
        )
    )
    before = tuple(
        layout_english(item.text, item.source, (800, 600), source_line_height=item.line_height)
        for item in labels
    )
    placements = EnglishPlacement().arrange(
        labels, (800, 600), tuple(item.source for item in labels)
    )
    after = tuple(layout for layout in placements if layout is not None)
    assert len(after) == len(labels)
    image = QImage(1600, 640, QImage.Format.Format_RGB32)
    image.fill(QColor("#45576a"))
    painter = QPainter(image)
    for offset, title, layouts in (
        (0, "Independent layout", before),
        (800, "Joint placement", after),
    ):
        painter.save()
        painter.translate(offset, 0)
        painter.setPen(QColor("white"))
        font = QFont("Segoe UI")
        font.setPixelSize(22)
        painter.setFont(font)
        painter.drawText(20, 30, title)
        painter.translate(0, 40)
        paint(painter, layouts)
        painter.setPen(QColor("#5eead4"))
        for label in labels:
            b = label.source
            painter.drawRect(QRectF(b.x, b.y, b.width, b.height))
        painter.restore()
    painter.end()
    assert image.save(str(args.output / "comparison.png"))
    results = []
    for count, crowded in ((16, False), (64, False), (128, False), (128, True)):
        items = tuple(
            EnglishLabel(
                ((i, 1, "日本語"),),
                f"Translation {i}: prepare for a new adventure.",
                Rect(200 if crowded else i % 8 * 440, 100 if crowded else i // 8 * 120, 150, 24),
                24,
            )
            for i in range(count)
        )
        owner = EnglishPlacement()
        sources = tuple(item.source for item in items)
        started = perf_counter()
        placed = owner.arrange(items, (3840, 2160), sources)
        first = (perf_counter() - started) * 1000
        boxes = [layout.bounds for layout in placed if layout is not None]
        assert len(boxes) == (1 if crowded else count)
        assert all(not intersects(a, b) for i, a in enumerate(boxes) for b in boxes[:i])
        repeats = []
        for _ in range(20):
            started = perf_counter()
            owner.arrange(items, (3840, 2160), sources)
            repeats.append((perf_counter() - started) * 1000)
        rebuilds = []
        for _ in range(5):
            owner.clear()
            started = perf_counter()
            owner.arrange(items, (3840, 2160), sources)
            rebuilds.append((perf_counter() - started) * 1000)
        results.append(
            dict(
                labels=count,
                visible=len(boxes),
                crowded=crowded,
                first_ms=first,
                rebuild_ms=median(rebuilds),
                unchanged_ms=median(repeats),
            )
        )
    (args.output / "results.json").write_text(
        json.dumps(
            dict(
                before=[asdict(p) for p in before],
                after=[asdict(p) for p in after],
                timings=results,
            ),
            indent=2,
        ),
        "utf-8",
    )
    print(json.dumps(results, indent=2))
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
