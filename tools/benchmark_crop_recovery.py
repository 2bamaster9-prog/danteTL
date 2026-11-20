"""Offline differential crop-accuracy gate against a saved pre-change app wheel."""

import argparse
import json
import socket
import types
import zipfile
from dataclasses import asdict, dataclass
from itertools import chain
from math import ceil, floor
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import shiboken6
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter
from PySide6.QtWidgets import QApplication
from region_corpus import CASES, Target, accuracy
from region_corpus import fixture as regional_fixture

from dantetl.domain import CapturedFrame, Rect, WindowGeometry
from dantetl.ocr.meiki import MeikiRecognizer
from dantetl.ocr.models import model_directory
from dantetl.ocr.worker import recognize_regions


@dataclass(frozen=True)
class Case:
    name: str
    font: int = 24
    light: bool = True
    text: tuple[str, ...] = ("設定",)
    offset: tuple[int, int] = (0, 0)
    size: tuple[int, int] = (195, 210)
    gap: int = 14
    faint: bool = False
    icon: bool = False
    vertical: bool = False


def cases() -> tuple[Case, ...]:
    result = [Case("reported")]
    result += [Case(f"phase-{x}-{y}", offset=(x, y)) for x in (0, 1, 3, 7) for y in range(8)]
    result += [
        Case(f"font-{font}-{light}-{text}", font, light, (text,), size=(300, 210))
        for font in (12, 16, 20, 24, 26, 32, 38, 48)
        for light in (False, True)
        for text in ("冒険", "東門", "約束", "１２３")
    ]
    result += [
        Case(f"crop-{w}-{h}-{font}", font, size=(w, h))
        for w in (143, 194, 211, 300)
        for h in (160, 209, 230)
        for font in (24, 38)
    ]
    result += [
        Case(f"rows-{font}-{gap}-{light}", font, light, ("設定", "冒険"), gap=gap)
        for font in (12, 18, 24)
        for gap in (0, 2, 8)
        for light in (False, True)
    ]
    result += [
        Case("unrelated-line", text=("設定", "所持金１２３４"), size=(350, 210)),
        Case("faint", faint=True),
        Case("faint-dark", light=False, faint=True),
        Case("blank", text=()),
        Case("blank-dark", light=False, text=()),
        Case("icon", icon=True),
        Case("icon-only", text=(), icon=True),
        Case("vertical", text=("冒険開始",), vertical=True),
        Case("vertical-dark", light=False, text=("冒険開始",), vertical=True),
    ]
    return tuple(result)


def fixture(case: Case) -> tuple[CapturedFrame, tuple[Rect, ...], tuple[Target, ...]]:
    image = QImage(1575, 1015, QImage.Format.Format_RGB32)
    image.fill(QColor(245, 245, 245) if case.light else QColor(20, 35, 55))
    painter = QPainter(image)
    color = (185, 185, 185) if case.light else (90, 90, 90)
    painter.setPen(
        QColor(*color)
        if case.faint
        else QColor(20, 35, 55)
        if case.light
        else QColor(245, 245, 245)
    )
    font = QFont("Yu Gothic UI")
    font.setPixelSize(case.font)
    painter.setFont(font)
    targets = []
    x, y = 105 + case.offset[0], 175 + case.offset[1]
    for text in case.text:
        parts = tuple(text) if case.vertical else (text,)
        for part in parts:
            ink = QFontMetricsF(font).tightBoundingRect(part)
            painter.drawText(x, y, part)
            targets.append(
                Target(
                    part,
                    Rect(
                        x + floor(ink.x()),
                        y + floor(ink.y()),
                        ceil(ink.width()) + 2,
                        ceil(ink.height()) + 2,
                    ),
                )
            )
            y += case.font + (2 if case.vertical else case.gap)
    if case.icon:
        painter.drawEllipse(65, 145, 22, 22)
    painter.end()
    bounds = Rect(0, 0, image.width(), image.height())
    source = CapturedFrame(
        1, 0, WindowGeometry(bounds, bounds, bounds, 168), bytes(image.constBits())
    )
    return source, (Rect(50, 64, *case.size),), tuple(targets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.repeats <= 5:
        parser.error("Use 1..5 repeats")
    # Baseline comes from our saved local build, not a downloaded executable.
    with zipfile.ZipFile(args.baseline_wheel) as archive:
        code = archive.read("dantetl/ocr/meiki.py").decode("utf-8")
    previous = types.ModuleType("prior_meiki")
    exec(
        compile(code, str(args.baseline_wheel) + "/dantetl/ocr/meiki.py", "exec"), previous.__dict__
    )
    app = QApplication([])
    reports = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        baseline = previous.MeikiRecognizer(model_directory(), device=args.device)
        current = MeikiRecognizer(model_directory(), device=args.device)
        try:
            assert (
                args.device != "cuda"
                or baseline.provider == current.provider == "CUDAExecutionProvider"
            )
            count = len(cases()) + len(CASES)
            work = chain(
                ((c.name, fixture(c)) for c in cases()),
                (("regional-" + c.name, regional_fixture(c)) for c in CASES),
            )
            for number, (name, (frame, areas, targets)) in enumerate(work):
                samples = {"baseline": [], "current": []}
                for trial in range(args.repeats):
                    order = (
                        ("baseline", "current") if (number + trial) % 2 else ("current", "baseline")
                    )
                    for key in order:
                        engine = baseline if key == "baseline" else current
                        started = perf_counter()
                        rows, coverage = recognize_regions(engine, frame, areas)
                        elapsed = (perf_counter() - started) * 1000
                        samples[key].append(
                            dict(
                                ms=elapsed,
                                accuracy=accuracy(targets, rows),
                                coverage=None
                                if coverage is None
                                else [asdict(b) for b in coverage],
                                regions=[asdict(r) for r in rows],
                            )
                        )
                regressions = []
                for trial, (old, new) in enumerate(
                    zip(samples["baseline"], samples["current"], strict=True)
                ):
                    for i, (a, b) in enumerate(
                        zip(old["accuracy"]["targets"], new["accuracy"]["targets"], strict=True)
                    ):
                        if b["errors"] > a["errors"]:
                            regressions.append(dict(trial=trial, target=i, before=a, after=b))
                    if old["coverage"] != new["coverage"]:
                        regressions.append(dict(trial=trial, coverage_changed=True))
                    if new["accuracy"]["extra_regions"] > old["accuracy"]["extra_regions"]:
                        regressions.append(dict(trial=trial, extra_blank_detections=True))
                reports.append(
                    dict(
                        case=name,
                        targets=[asdict(t) for t in targets],
                        samples=samples,
                        regressions=regressions,
                    )
                )
                if regressions or number % 20 == 0:
                    print(
                        f"{number + 1}/{count} {name!a}: regressions={len(regressions)}",
                        flush=True,
                    )
        finally:
            baseline.close()
            current.close()
    failed = [c["case"] for c in reports if c["regressions"]]
    improved = [
        c["case"]
        for c in reports
        if c["samples"]["current"][0]["accuracy"]["errors"]
        < c["samples"]["baseline"][0]["accuracy"]["errors"]
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            dict(
                device=args.device,
                gate_passed=not failed,
                failed=failed,
                improved=improved,
                cases=reports,
            ),
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    shiboken6.delete(app)
    print(f"{len(reports)} cases: {len(failed)} regressions, {len(improved)} improved")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
