"""Exercise capture -> local OCR -> inspector against our own live Windows fixture."""

import argparse
import json
import os
import time
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from verify_translation import process_memory

from jp_overlay.app import create_recognizer, translation_backends
from jp_overlay.demo import DemoWindow
from jp_overlay.domain import WindowTarget
from jp_overlay.recognition import OcrState
from jp_overlay.translation import TranslationState
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a screenshot of only our test app")
    parser.add_argument(
        "--translation", action="store_true", help="Include real Sugoi and profile swapping"
    )
    args = parser.parse_args()
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow()
    demo.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    demo.show()
    window = MainWindow(
        windows,
        create_recognizer,
        translation_backends() if args.translation else (),
        cache_path=Path(__file__).resolve().parents[1]
        / "artifacts/verification-translation.sqlite3",
    )
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.show()
    target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
    window.windows_combo.addItem("OCR verification fixture", target)
    window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
    window.start_button.click()
    started = time.monotonic()
    stage = 0
    stage_started = started
    frozen = None
    initial_size = (0, 0)
    phrase_id = 0
    phrase_bounds = None
    swapped = False
    evidence: dict[str, object] = {}
    failure = ""

    def tick() -> None:
        nonlocal stage, stage_started, frozen, initial_size, failure, phrase_id, phrase_bounds
        nonlocal swapped
        now = time.monotonic()
        try:
            if now - started > 30:
                raise RuntimeError(f"Live OCR verification timed out at stage {stage}")
            if stage == 99:
                if window._session is None:
                    window.close()
                    demo.close()
                    timer.stop()
                    app.quit()
                return
            if window._ocr and window._ocr.snapshot().state == OcrState.FAILED:
                raise RuntimeError(window._ocr.snapshot().message)
            if (
                window._translation
                and window._translation.snapshot().state == TranslationState.FAILED
            ):
                raise RuntimeError(window._translation.snapshot().message)
            result = window.inspector.result
            if stage == 0 and result is not None:
                text = [r.text for r in result.regions]
                assert "新しい冒険が、ここから始まる。" in text, text
                assert window.inspector.table.rowCount() == len(result.regions)
                evidence["live_japanese_recognized"] = True
                evidence["ocr_ms"] = round(result.duration_ms, 1)
                evidence["dpi"] = result.frame.geometry.dpi
                initial_size = result.frame.geometry.client.size
                frozen = result
                tracks = window._tracker.visible(result.frame, now)
                phrase = next(t for t in tracks if t.text == "新しい冒険が、ここから始まる。")
                phrase_id, phrase_bounds = phrase.track_id, phrase.bounds
                stage = 8
            elif (
                stage == 8
                and result
                and frozen
                and result.frame.sequence >= frozen.frame.sequence + 3
            ):
                tracks = window._tracker.visible(result.frame, now)
                phrase = next(t for t in tracks if t.track_id == phrase_id)
                assert phrase.bounds == phrase_bounds, "Stationary dialogue box changed bounds"
                if args.translation:
                    if window._translation is None:
                        return
                    translated = window._translation.snapshot()
                    if not translated.results or translated.pending:
                        return
                    if not swapped:
                        window.backend_combo.setCurrentIndex(1)
                        swapped = True
                        return
                    english = next(
                        t
                        for t in translated.results
                        if t.request.source == "新しい冒険が、ここから始まる。"
                    )
                    assert "adventure" in english.english.lower()
                    evidence["english_after_backend_swap"] = english.english
                    evidence["process_memory"] = process_memory()
                    window._overlay.set_tracks(tracks)
                    window._overlay.set_translations(translated.results, enabled=True)
                    window._overlay.align(windows.geometry(target).client)
                    app.processEvents()  # Deliver the native resize before grabbing the widget.
                    if args.output:
                        args.output.parent.mkdir(parents=True, exist_ok=True)
                        window._overlay.grab().save(
                            str(args.output.with_name("english-overlay.png"))
                        )
                    window.automatic_font.setChecked(False)
                    window.font_size.setValue(24)
                    assert window._overlay._manual_size == 24
                    window.automatic_font.setChecked(True)
                    evidence["automatic_and_manual_font_controls"] = True
                evidence["repeated_ocr_keeps_dialogue_id_and_bounds"] = True
                window.stabilize_check.setChecked(False)
                frozen = result
                window.inspector.pause.setChecked(True)
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(args.output))
                stage, stage_started = 1, now
            elif stage == 1 and now - stage_started > 0.7:
                assert window.inspector.result is frozen, "Pause replaced the reviewed frame"
                assert not window._overlay.isVisible()
                assert window._session is not None
                captured = window._session.snapshot().frame
                assert captured and frozen and captured.sequence > frozen.frame.sequence
                evidence["pause_freezes_result_while_capture_continues"] = True
                window.inspector.pause.setChecked(False)
                window.stabilize_check.setChecked(True)
                evidence["raw_comparison_and_pause_toggle"] = True
                demo.resize(760, 500)
                stage = 2
            elif stage == 2 and result and result.frame.geometry.client.size != initial_size:
                assert result.frame.geometry.client.size == windows.geometry(target).client.size
                evidence["resize_produces_matching_ocr_frame"] = True
                demo.showMinimized()
                stage, stage_started = 3, now
            elif stage == 3 and now - stage_started > 0.3:
                assert window.inspector.result is None
                assert not window._overlay.isVisible()
                evidence["minimize_clears_ocr"] = True
                demo.showNormal()
                stage = 4
            elif stage == 4 and result:
                evidence["restore_resumes_ocr"] = True
                window.start_button.click()
                stage = 5
            elif stage == 5 and window._session is None:
                assert window._ocr is None
                assert window._translation is None
                assert window.inspector.result is None
                window.start_button.click()
                stage = 6
            elif stage == 6 and result:
                evidence["restart_receives_new_result"] = True
                window.close()
                stage = 7
            elif stage == 7 and window._session is None:
                assert window._ocr is None
                assert window._translation is None
                assert not window.isVisible()
                evidence["close_finishes_all_workers"] = True
                evidence["elapsed_seconds"] = round(now - started, 2)
                stage = 99
        except Exception as error:
            failure = str(error)
            print(f"FAIL: {failure}", flush=True)
            window.close()
            stage = 99
            if now - started > 35:
                timer.stop()
                app.exit(1)

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    shiboken6.delete(app)
    print(json.dumps(evidence, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
