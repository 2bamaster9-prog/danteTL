"""Real capture/models with stationary labels, animated backgrounds, and injected OCR noise.

No game pixels are read. After initial English, deliberately corrupt or omit local OCR
observations and require the same blocks on every publication and UI poll for 12 seconds.
"""

import argparse
import json
import os
import threading
import time
from dataclasses import replace
from math import sin
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPaintEvent
from PySide6.QtWidgets import QApplication, QWidget
from verification_isolation import app_owner
from verification_isolation import create_window as MainWindow

from dantetl.application.model_factories import create_recognizer, translation_backends
from dantetl.capture.windows import Windows
from dantetl.domain import CapturedFrame, Rect, WindowTarget
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.ocr.values import OcrState, TextCharacter, TextRegion
from dantetl.ocr.worker import OcrChoice
from dantetl.translation.grouping import TextBlock
from dantetl.translation.values import TranslatedText


class CharacterScreen(QWidget):
    def __init__(self, *, low_contrast: bool = False, colored: bool = False) -> None:
        super().__init__()
        self.setWindowTitle("DanteTL stationary-label verification")
        self.resize(1200 if colored else 900, 580)
        self.phase = 0
        self.low_contrast = low_contrast
        self.colored = colored
        self.new_label = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(50)

    def advance(self) -> None:
        self.phase += 1
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        if self.low_contrast:
            brightness = round(200 + 10 * sin(self.phase / 15))
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            for stop, value in ((0, brightness), (0.5, brightness + 8), (1, brightness)):
                gradient.setColorAt(stop, QColor(value, value, value))
            p.fillRect(self.rect(), gradient)
        else:
            p.fillRect(self.rect(), QColor(20, 35, 55))
            for i in range(130):
                p.setPen(
                    QColor(245, 245, 245)
                    if self.colored
                    else QColor(45 + i % 25, 60 + i % 25, 80 + i % 25)
                )
                x, y = (i * 43 + self.phase * 3) % self.width(), i * 71 % 580
                p.drawEllipse(x, y, 4, 4)
                if self.colored:
                    p.drawLine(x - 3, y + 2, x + 7, y + 2)
                    p.drawLine(x + 2, y - 3, x + 2, y + 7)
        font = QFont("Yu Gothic UI")
        font.setPixelSize(24)
        p.setFont(font)
        p.setPen(QColor(235, 235, 235, 204) if self.low_contrast else QColor(245, 245, 245))
        labels = ("キャラクター", "装備を確認", "攻撃力", "防御力", "速度", "詳細を表示")
        if self.colored:
            p.setPen(QColor(60, 240, 170))
            labels = (
                "装備キャラの会心率が50%以上の場合",
                "追加攻撃ダメージと必殺技のダメージ",
                "装備キャラの攻撃力が48%アップする",
                "装備キャラが他の味方の対象になる時",
                "最大で2層累積できる効果を確認する",
                "必殺技を発動する時に効果を消費する",
            )
        for i, label in enumerate(labels):
            p.drawText(45 if i < 3 else 570, 90 + i % 3 * 150, label)
        if self.new_label:
            p.drawText(390, 520, "設定")
        p.end()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument(
        "--low-contrast", action="store_true", help="Faint text over smooth moving bright light"
    )
    parser.add_argument(
        "--colored", action="store_true", help="Long green descriptions over moving white glints"
    )
    parser.add_argument(
        "--appearance",
        action="store_true",
        help="Time a newly appearing menu label after retention checks",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/visual/stationary.json"))
    args = parser.parse_args()
    if args.colored and args.low_contrast:
        parser.error("Select colored or low-contrast text, not both")
    armed = threading.Event()
    passes = 0

    class NoisyRecognizer:
        def __init__(self) -> None:
            self.engine = create_recognizer(device=args.device)
            self.provider = getattr(self.engine, "provider", "")
            self.message = getattr(self.engine, "message", "")

        @property
        def scan_costs(self):
            return getattr(self.engine, "scan_costs", None)

        def recognize(
            self, frame: CapturedFrame, *, full_size: tuple[int, int] | None = None
        ) -> tuple[TextRegion, ...]:
            nonlocal passes
            regions = self.engine.recognize(frame, full_size=full_size)
            if not armed.is_set():
                return regions
            passes += 1
            if passes % 3 == 0:
                return tuple(r for r in regions if not DEFAULT_SOURCE.contains_text(r.text))
            changed = []
            for r in regions:
                if DEFAULT_SOURCE.contains_text(r.text):
                    b = r.bounds
                    b = Rect(
                        max(0, b.x - 5),
                        b.y,
                        min(b.width + 10, frame.width - max(0, b.x - 5)),
                        b.height,
                    )
                    text = "全く違う読み方" if passes % 2 else "誤った観測"
                    r = replace(r, text=text, bounds=b, characters=(TextCharacter(text, b, 0.2),))
                changed.append(r)
            return tuple(changed)

        def close(self) -> None:
            self.engine.close()

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    target = CharacterScreen(low_contrast=args.low_contrast, colored=args.colored)
    target.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    target.show()
    window = MainWindow(
        windows,
        NoisyRecognizer,
        translation_backends(),
        cache_path=Path(
            f"artifacts/appearance-{time.time_ns()}.sqlite3"
            if args.appearance
            else "artifacts/stationary.sqlite3"
        ),
        ocr_backends=(OcrChoice(args.device, NoisyRecognizer, 8),),
    )
    application = app_owner(window)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.show()
    window.advanced.setChecked(True)
    window.windows_combo.addItem(
        "Own fixture", WindowTarget(int(target.winId()), os.getpid(), target.windowTitle())
    )
    window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
    window.start_button.click()
    started, stable_since = time.monotonic(), 0.0
    baseline: tuple[tuple[TextBlock, ...] | None, tuple[TranslatedText, ...]] | None = None
    polls = 0
    finished = False
    appearance_started = 0.0
    evidence = {"low_contrast": args.low_contrast, "colored": args.colored}
    publication_checks = 0
    violations: list[str] = []
    original_scene = window._overlay.set_scene

    def audit_publication() -> None:
        nonlocal publication_checks
        if baseline is None or finished:
            return
        publication_checks += 1
        prior = {item.request for item in baseline[1]}
        current = tuple(item for item in window._overlay._translations if item.request in prior)
        if len(violations) < 8 and (
            current != baseline[1]
            or any(block not in (window._overlay._blocks or ()) for block in (baseline[0] or ()))
        ):
            violations.append("Existing English/geometry changed between timer polls")

    def audited_scene(tracks, blocks=None, translations=(), *, english=False):
        original_scene(tracks, blocks, translations, english=english)
        audit_publication()

    window._overlay.set_scene = audited_scene

    def tick() -> None:
        nonlocal stable_since, baseline, polls, finished, appearance_started
        now = time.monotonic()
        try:
            if finished:
                if application.shutdown.snapshot().phase == "ready":
                    assert (
                        application.live.visual is None
                        and application.live.ocr is None
                        and application.translation.lifecycle.publication is None
                    )
                    evidence["all_workers_stopped"] = True
                    evidence["publication_checks"] = publication_checks
                    evidence["publication_violations"] = violations
                    target.close()
                    timer.stop()
                    app.quit()
                return
            assert now - started < 70, "Stationary retention verification timed out"
            assert not violations, violations
            evidence["max_visual_ms"] = round(
                max(
                    evidence.get("max_visual_ms", 0),
                    application.live.visual_state.duration_ms,
                ),
                2,
            )
            if application.live.ocr:
                assert application.live.ocr.snapshot().state != OcrState.FAILED, (
                    application.live.ocr.snapshot().message
                )
            showing = (window._overlay._blocks, window._overlay._translations)
            if args.colored:
                # Bright glints can produce unrelated tiny OCR detections. Audit all six
                # descriptions exactly; extra detections are a different recognition test.
                showing = (
                    tuple(b for b in (showing[0] or ()) if len(b.text) >= 14),
                    tuple(
                        t
                        for t in showing[1]
                        if len(t.request.source) >= 14 or t.request.source == "設定"
                    ),
                )
            if appearance_started:
                assert baseline is not None
                prior_requests = {t.request for t in baseline[1]}
                assert tuple(t for t in showing[1] if t.request in prior_requests) == baseline[1], (
                    "New-label scan disturbed existing English"
                )
                assert all(block in (showing[0] or ()) for block in (baseline[0] or ())), (
                    "New-label scan moved an existing box"
                )
                result = application.live.accepted
                if (
                    result
                    and result.frame.captured_at >= appearance_started
                    and any(r.text == "設定" for r in result.regions)
                ):
                    evidence.setdefault("new_label_scan_was_regional", result.scanned is not None)
                    evidence.setdefault("new_label_ocr_ms", round(result.duration_ms, 1))
                    evidence.setdefault(
                        "new_label_scan_fraction",
                        round(
                            sum(a.width * a.height for a in result.scanned)
                            / (result.frame.width * result.frame.height),
                            4,
                        )
                        if result.scanned
                        else 1.0,
                    )
                assert now - appearance_started < 8, "New menu label was not translated promptly"
                if any(t.request.source == "設定" for t in showing[1]):
                    evidence["new_label_to_english_seconds"] = round(now - appearance_started, 3)
                    evidence["existing_english_retained_during_appearance"] = True
                    assert evidence.get("new_label_scan_was_regional"), (
                        "New label waited for a full-frame scan"
                    )
                    finished = True
                    window.close()
                return
            if baseline is None:
                if (
                    len(showing[1]) < 6
                    or not application.translation.lifecycle.publication
                    or application.translation.lifecycle.publication.snapshot().pending
                ):
                    return
                baseline = showing
                args.output.parent.mkdir(parents=True, exist_ok=True)
                target.grab().save(str(args.output.with_suffix(".png")))
                stable_since = now
                armed.set()
            else:
                polls += 1
                assert showing == baseline, (
                    "Stationary accepted English or geometry changed under noisy OCR"
                )
                if now - stable_since >= 4 and "advanced_collapsed" not in evidence:
                    window.advanced.setChecked(False)
                    evidence["advanced_collapsed"] = True
                if now - stable_since >= 8 and "advanced_resumed" not in evidence:
                    assert window.inspector.result is None
                    window.advanced.setChecked(True)
                    assert window.inspector.result is application.live.accepted
                    evidence["advanced_resumed"] = True
                if now - stable_since >= 12 and passes >= 6:
                    evidence.update(
                        device=args.device,
                        dpi=window.inspector.result.frame.geometry.dpi
                        if window.inspector.result
                        else 0,
                        unchanged_render_polls=polls,
                        noisy_ocr_passes=passes,
                        stable_seconds=round(now - stable_since, 2),
                        english_blocks=len(showing[1]),
                        zero_publication_changes=True,
                    )
                    if args.appearance:
                        latest = application.live.accepted
                        if (
                            latest is None
                            or latest.scanned is not None
                            or now - latest.frame.captured_at > 0.75
                        ):
                            return  # Leave time for regional discovery before the next full scan.
                        evidence["last_full_source_age_seconds"] = round(
                            now - latest.frame.captured_at, 3
                        )
                        armed.clear()
                        appearance_started = now
                        target.new_label = True
                        target.update()
                    else:
                        finished = True
                        window.close()
        except Exception as error:
            evidence["failure"] = f"{type(error).__name__}: {error}"
            evidence["noisy_ocr_passes"] = passes
            evidence["baseline"] = repr(baseline)
            evidence["showing"] = repr((window._overlay._blocks, window._overlay._translations))
            evidence["visual"] = repr(replace(application.live.visual_state, frame=None))
            evidence["tracks"] = repr(application.live._tracker.translation_activity())
            latest = window.inspector.result
            evidence["last_coverage"] = repr(latest.scanned) if latest else "none"
            evidence["last_source_age"] = now - latest.frame.captured_at if latest else None
            finished = True
            window.close()

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(33)
    app.exec()
    shiboken6.delete(app)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 1 if "failure" in evidence else 0


if __name__ == "__main__":
    from verification_isolation import run_isolated

    run_isolated(main)
