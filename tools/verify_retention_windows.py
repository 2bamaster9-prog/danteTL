"""Real capture/models with stationary labels, animated backgrounds, and injected OCR noise.

No game pixels are read. After initial English, deliberately corrupt or omit local OCR
observations and require the same rendered blocks on every UI poll for 12 seconds.
"""

import argparse
import json
import os
import threading
import time
from dataclasses import replace
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QApplication, QWidget

from jp_overlay.app import create_recognizer, translation_backends
from jp_overlay.domain import CapturedFrame, Rect, WindowTarget
from jp_overlay.recognition import OcrChoice, OcrState, TextCharacter, TextRegion
from jp_overlay.text_content import has_japanese
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


class CharacterScreen(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("JP Overlay stationary-label verification")
        self.resize(900, 580)
        self.phase = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self.timer.start(50)

    def advance(self) -> None:
        self.phase += 1
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 35, 55))
        for i in range(130):
            p.setPen(QColor(45 + i % 25, 60 + i % 25, 80 + i % 25))
            p.drawEllipse((i * 43 + self.phase * 3) % 900, i * 71 % 580, 4, 4)
        font = QFont("Yu Gothic UI")
        font.setPixelSize(24)
        p.setFont(font)
        p.setPen(QColor(245, 245, 245))
        for i, label in enumerate(
            ("キャラクター", "装備を確認", "攻撃力", "防御力", "速度", "詳細を表示")
        ):
            p.drawText(45 if i < 3 else 570, 90 + i % 3 * 150, label)
        p.end()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--output", type=Path, default=Path("artifacts/visual/stationary.json"))
    args = parser.parse_args()
    armed = threading.Event()
    passes = 0

    class NoisyRecognizer:
        def __init__(self) -> None:
            self.engine = create_recognizer(device=args.device)
            self.provider = getattr(self.engine, "provider", "")
            self.message = getattr(self.engine, "message", "")

        def recognize(self, frame: CapturedFrame) -> tuple[TextRegion, ...]:
            nonlocal passes
            regions = self.engine.recognize(frame)
            if not armed.is_set():
                return regions
            passes += 1
            if passes % 3 == 0:
                return tuple(r for r in regions if not has_japanese(r.text))
            changed = []
            for r in regions:
                if has_japanese(r.text):
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

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    target = CharacterScreen()
    target.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    target.show()
    window = MainWindow(
        windows,
        NoisyRecognizer,
        translation_backends(),
        cache_path=Path("artifacts/stationary.sqlite3"),
        ocr_backends=(OcrChoice(args.device, NoisyRecognizer, 8),),
    )
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.show()
    window.windows_combo.addItem(
        "Own fixture", WindowTarget(int(target.winId()), os.getpid(), target.windowTitle())
    )
    window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
    window.start_button.click()
    started, stable_since = time.monotonic(), 0.0
    baseline = None
    polls = 0
    finished = False
    evidence = {}

    def tick() -> None:
        nonlocal stable_since, baseline, polls, finished
        now = time.monotonic()
        try:
            if finished:
                if window._session is None:
                    assert (
                        window._visual is None
                        and window._ocr is None
                        and window._translation is None
                    )
                    evidence["all_workers_stopped"] = True
                    target.close()
                    timer.stop()
                    app.quit()
                return
            assert now - started < 70, "Stationary retention verification timed out"
            if window._ocr:
                assert window._ocr.snapshot().state != OcrState.FAILED, (
                    window._ocr.snapshot().message
                )
            showing = (window._overlay._blocks, window._overlay._translations)
            if baseline is None:
                if (
                    len(showing[1]) < 6
                    or not window._translation
                    or window._translation.snapshot().pending
                ):
                    return
                baseline = showing
                stable_since = now
                armed.set()
            else:
                polls += 1
                assert showing == baseline, (
                    "Stationary accepted English or geometry changed under noisy OCR"
                )
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
                    finished = True
                    window.close()
        except Exception as error:
            evidence["failure"] = f"{type(error).__name__}: {error}"
            evidence["noisy_ocr_passes"] = passes
            evidence["baseline"] = repr(baseline)
            evidence["showing"] = repr((window._overlay._blocks, window._overlay._translations))
            evidence["visual"] = repr(replace(window._visual_state, frame=None))
            evidence["tracks"] = repr(window._tracker.translation_activity())
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
    raise SystemExit(main())
