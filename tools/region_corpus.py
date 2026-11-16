"""Owned Japanese scan-planning fixtures and geometry-aware accuracy measurements."""

import unicodedata
from dataclasses import dataclass
from math import ceil, floor

from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.regions import intersects
from dantejp.ocr.worker import TextRegion


@dataclass(frozen=True, slots=True)
class Target:
    text: str
    bounds: Rect


@dataclass(frozen=True, slots=True)
class Case:
    name: str
    font: int = 26
    size: tuple[int, int] = (1920, 1080)
    spread: bool = False
    dense: bool = False
    light: bool = False
    faint: bool = False
    clipped: bool = False
    blank: bool = False
    vertical: bool = False
    multiline: bool = False
    mixed: bool = False
    offset: tuple[int, int] = (0, 0)
    phrases: tuple[str, ...] = (
        "旅の準備をしよう。",
        "新しい冒険が始まる。",
        "一緒に出かけよう。",
        "明日また会いましょう。",
    )


CASES = (
    Case("nearby"),
    Case("spread_dense", spread=True, dense=True),
    Case("clipped", clipped=True),
    Case("blank", blank=True),
    *(Case(f"font_{size}", font=size) for size in (14, 18, 22, 38, 56)),
    Case("light", light=True),
    Case("faint", light=True, faint=True),
    Case("mixed_heights", mixed=True),
    Case("vertical", vertical=True),
    Case("multiline", multiline=True),
    Case("window_edge", offset=(-100, -100)),
    Case("dense_nearby", dense=True),
    Case("720p", size=(1280, 720)),
    Case("1440p", size=(2560, 1440)),
    Case("4k", size=(3840, 2160)),
    Case("4k_small", size=(3840, 2160), font=14),
    Case(
        "digits",
        phrases=(
            "残り時間：３０秒",
            "所持金：１２３４５６",
            "経験値１００／２００",
            "レベル：９９",
        ),
    ),
    Case("short_names", phrases=("設定", "旅人", "西門", "東門")),
    Case(
        "negation",
        phrases=(
            "私は彼を信じている。",
            "私は彼を信じていない。",
            "行くな！危険だ。",
            "行こう！準備はいい？",
        ),
    ),
    Case(
        "kana",
        phrases=(
            "おはようございます。",
            "ありがとうございます。",
            "ちょっとまってください。",
            "またあしたあいましょう。",
        ),
    ),
)


def fixture(case: Case) -> tuple[CapturedFrame, tuple[Rect, ...], tuple[Target, ...]]:
    width, height = case.size
    factor = width / 1920
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(245, 245, 245) if case.light else QColor(20, 35, 55))
    painter = QPainter(image)
    painter.setPen(
        QColor(185, 185, 185)
        if case.faint
        else (QColor(20, 35, 55) if case.light else QColor(245, 245, 245))
    )
    font = QFont("Yu Gothic UI")
    targets = []

    def draw(text: str, x: int, y: int, pixels: int, target: bool = True) -> None:
        font.setPixelSize(pixels)
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        ink = metrics.tightBoundingRect(text)
        painter.drawText(x, y, text)
        if target:
            targets.append(
                Target(
                    text,
                    Rect(
                        x + floor(ink.x()),
                        y + floor(ink.y()),
                        ceil(ink.width()) + 2,
                        ceil(ink.height()) + 2,
                    ),
                )
            )

    positions = (
        (100, 100),
        (1400 if case.spread else 470, 100),
        (100, 800 if case.spread else 270),
        (1400 if case.spread else 470, 800 if case.spread else 270),
    )
    areas = []
    for i, ((x, y), phrase) in enumerate(zip(positions, case.phrases, strict=True)):
        x, y = round((x + case.offset[0]) * factor), round((y + case.offset[1]) * factor)
        box = Rect(x, y, round(320 * factor), round(108 * factor))
        pixels = round((16 if case.mixed and i == 3 else case.font) * factor)
        if case.vertical:
            box = Rect(x, y, round(100 * factor), round(155 * factor))
        elif case.font > 26:
            # Keep large-font text wholly inside each requested crop without overlapping
            # the next crop. Font-size cases use shorter content, not clipped ground truth.
            phrase = ("旅の準備", "冒険開始", "出発する", "明日会う")[i]
        areas.append(box)
        if case.blank:
            continue
        if case.vertical:
            phrase = ("冒険開始", "出発準備", "東門集合", "西門到着")[i]
            # Retain one target per glyph; detector may group vertical text differently.
            for j, char in enumerate(phrase):
                draw(char, x + round(30 * factor), y + round((32 + j * 28) * factor), pixels)
        else:
            start = 260 if case.clipped and i == 3 else 20
            draw(phrase, x + round(start * factor), y + round(60 * factor), pixels)
            if case.multiline:
                draw("準備はできましたか？", x + round(20 * factor), y + round(95 * factor), pixels)
    if case.dense:
        for y in range(430 if not case.spread else 300, 730, 70):
            for x in range(100, 1700, 400):
                draw(
                    "これは周囲の説明です。",
                    round(x * factor),
                    round(y * factor),
                    round(26 * factor),
                    False,
                )
    painter.end()
    bounds = Rect(0, 0, width, height)
    return (
        CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), bytes(image.constBits())),
        tuple(areas),
        tuple(targets),
    )


def normalized(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]


def accuracy(targets: tuple[Target, ...], regions: tuple[TextRegion, ...]) -> dict[str, object]:
    readings = []
    for target in targets:
        box = target.bounds
        # Character centers localize each expected line, avoiding cross-column credit
        # or duplicated phrases hiding a missing target. Preserve exact raw results too.
        chars = [
            c
            for r in regions
            for c in r.characters
            if box.x - 4 <= c.bounds.x + c.bounds.width / 2 <= box.x + box.width + 4
            and box.y - 4 <= c.bounds.y + c.bounds.height / 2 <= box.y + box.height + 4
        ]
        if chars:
            observed = "".join(
                c.text for c in sorted(chars, key=lambda c: (c.bounds.x, c.bounds.y))
            )
        else:
            observed = "".join(
                r.text for r in regions if intersects(r.bounds, box) and box.contains(r.bounds)
            )
        wanted, observed = normalized(target.text), normalized(observed)
        readings.append(dict(expected=wanted, observed=observed, errors=distance(wanted, observed)))
    return dict(
        exact=sum(r["expected"] == r["observed"] for r in readings),
        errors=sum(int(r["errors"]) for r in readings),
        targets=readings,
        extra_regions=len(regions) if not targets else 0,
    )
