"""Exercise capture -> local OCR -> inspector against our own live Windows fixture."""

import argparse
import json
import os
import time
import traceback
from functools import partial
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from verify_translation import process_memory

from jp_overlay.app import create_recognizer, translation_backends
from jp_overlay.demo import DIALOGUE_LINES, DemoWindow
from jp_overlay.domain import CapturedFrame, WindowTarget
from jp_overlay.recognition import OcrChoice, OcrState, TextRegion
from jp_overlay.translation import TranslationState
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a screenshot of only our test app")
    parser.add_argument(
        "--translation", action="store_true", help="Include real Sugoi and profile swapping"
    )
    parser.add_argument("--dialogue", action="store_true", help="Verify two-line dialogue grouping")
    parser.add_argument("--ocr-delay-ms", type=int, default=0, help="Simulate a slow OCR worker")
    parser.add_argument("--device", choices=("cpu", "auto", "cuda"), default="cpu")
    parser.add_argument("--transitions", action="store_true", help="Close/reopen the text panel")
    parser.add_argument(
        "--typewriter", action="store_true", help="Check gradual dialogue readiness"
    )
    args = parser.parse_args()
    if args.dialogue and not args.translation:
        parser.error("--dialogue requires --translation")
    if args.typewriter and not args.dialogue:
        parser.error("--typewriter requires --dialogue")
    if args.transitions and not args.dialogue:
        parser.error("--transitions requires --dialogue")
    if not 0 <= args.ocr_delay_ms <= 1500:
        parser.error("--ocr-delay-ms must be between 0 and 1500")

    class DelayedRecognizer:
        def __init__(self) -> None:
            self.engine = create_recognizer(device=args.device)

        def recognize(self, frame: CapturedFrame) -> tuple[TextRegion, ...]:
            time.sleep(args.ocr_delay_ms / 1000)
            return self.engine.recognize(frame)

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow(dialogue=args.dialogue, typewriter=args.typewriter)
    if args.typewriter:
        demo.reveal_active = False  # Begin after model initialization/first inference.
    expected = DIALOGUE_LINES[0] if args.dialogue else "新しい冒険が、ここから始まる。"
    translation_source = "".join(DIALOGUE_LINES) if args.dialogue else expected
    demo.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    demo.show()
    factory = (
        DelayedRecognizer if args.ocr_delay_ms else partial(create_recognizer, device=args.device)
    )
    choices = (OcrChoice(args.device, factory, 8),)
    if args.device != "cpu":
        choices += (OcrChoice("CPU", create_recognizer, 8),)
    cache_path = (
        Path(__file__).resolve().parents[1]
        / "artifacts"
        / (
            f"typewriter-{time.time_ns()}.sqlite3"
            if args.typewriter
            else "verification-translation.sqlite3"
        )
    )
    cache_initially_empty = not cache_path.exists()
    window = MainWindow(
        windows,
        factory,
        translation_backends() if args.translation else (),
        cache_path=cache_path,
        ocr_backends=choices,
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
    grouping_stage = 0
    continuity_started = 0.0
    continuity_polls = 0
    continuity_request = None
    evidence: dict[str, object] = {"translation_cache_initially_empty": cache_initially_empty}
    failure = ""
    reveal_finished = 0.0
    transitions_done = False
    timeout = 180 if args.device != "cpu" else 45

    def tick() -> None:
        nonlocal stage, stage_started, frozen, initial_size, failure, phrase_id, phrase_bounds
        nonlocal swapped, grouping_stage
        nonlocal continuity_started, continuity_polls, continuity_request
        nonlocal reveal_finished
        nonlocal transitions_done
        now = time.monotonic()
        try:
            if now - started > timeout:
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
            if (
                args.typewriter
                and reveal_finished
                and not swapped
                and window._translation
                and any(
                    t.request.source == translation_source for t in window._overlay._translations
                )
            ):
                evidence.setdefault(
                    "typewriter_to_full_english_seconds", round(now - reveal_finished, 3)
                )
            if stage == 0 and args.typewriter and result is not None:
                demo.reveal_active = True
                if demo.revealed < sum(map(len, DIALOGUE_LINES)):
                    if window._translation:
                        for translated in window._translation.snapshot().results:
                            assert translated.request.source == "旅人", (
                                "Premature dialogue translation: " + translated.request.source
                            )
                    return
                if not reveal_finished:
                    reveal_finished = now
                if not all(line in [r.text for r in result.regions] for line in DIALOGUE_LINES):
                    return
            if stage == 8 and phrase_id and window._session:
                latest = window._session.snapshot().frame
                if latest:
                    current = window._tracker.visible(latest, now)
                    assert any(t.track_id == phrase_id for t in current), (
                        "Track blinked between OCR passes"
                    )
                if continuity_request is not None:
                    assert window._translation is not None
                    assert any(
                        t.request == continuity_request
                        for t in window._translation.snapshot().results
                    ), "English disappeared between slow OCR passes"
                    assert any(
                        t.request == continuity_request for t in window._overlay._translations
                    ), "Overlay discarded an unchanged translation"
            if stage == 0 and result is not None:
                text = [r.text for r in result.regions]
                assert expected in text, text
                if args.dialogue:
                    assert DIALOGUE_LINES[1] in text and "旅人" in text, text
                assert window.inspector.table.rowCount() == len(result.regions)
                evidence["live_japanese_recognized"] = True
                evidence["ocr_ms"] = round(result.duration_ms, 1)
                evidence["dpi"] = result.frame.geometry.dpi
                if args.device == "cuda" and not args.ocr_delay_ms:
                    assert (
                        window._ocr and window._ocr.snapshot().provider == "CUDAExecutionProvider"
                    )
                    evidence["actual_gpu_provider"] = window._ocr.snapshot().provider
                initial_size = result.frame.geometry.client.size
                frozen = result
                tracks = window._tracker.visible(result.frame, now)
                phrase = next(t for t in tracks if t.text == expected)
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
                        if args.typewriter:
                            assert "typewriter_to_full_english_seconds" in evidence
                            evidence["no_partial_dialogue_translations"] = True
                        window.backend_combo.setCurrentIndex(1)
                        swapped = True
                        return
                    if args.dialogue and grouping_stage == 1:
                        sources = {t.request.source for t in translated.results}
                        assert all(line in sources for line in DIALOGUE_LINES), sources
                        assert not any(t.request.members for t in translated.results), translated
                        window.group_dialogue.setChecked(True)
                        grouping_stage = 2
                        return
                    english = next(
                        (t for t in translated.results if t.request.source == translation_source),
                        None,
                    )
                    if english is None:
                        return  # Other blocks can finish while a newly regrouped passage settles.
                    if not any(t.request == english.request for t in window._overlay._translations):
                        return  # Publication occurs on the next UI poll after worker completion.
                    if args.ocr_delay_ms and (not args.dialogue or grouping_stage == 2):
                        if not continuity_started:
                            if not any(
                                t.request == english.request for t in window._overlay._translations
                            ):
                                return  # The worker can finish between two UI polls.
                            continuity_started = now
                            continuity_request = english.request
                        continuity_polls += 1
                        if now - continuity_started < 3:
                            return
                        evidence["slow_ocr_english_continuity_polls"] = continuity_polls
                    assert "adventure" in english.english.lower()
                    evidence["english_after_backend_swap"] = english.english
                    if args.dialogue:
                        assert len(english.request.members) == 2
                        if grouping_stage == 0:
                            window.group_dialogue.setChecked(False)
                            grouping_stage = 1
                            return
                        assert any(t.request.source == "旅人" for t in translated.results)
                        blocks = window._overlay._blocks
                        assert blocks and sum(len(b.lines) == 2 for b in blocks) == 1
                        evidence["dialogue_translated_as_one_block_with_separate_speaker"] = True
                        evidence["grouping_off_on_rebuilds_current_requests"] = True
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
                    if args.transitions and not transitions_done:
                        demo.panel_visible = False
                        demo.update()
                        continuity_request = None
                        stage, stage_started = 10, now
                        return
                evidence["repeated_ocr_keeps_dialogue_id_and_bounds"] = True
                window.stabilize_check.setChecked(False)
                window.inspector.pause.setChecked(True)
                # Events drained for the grab may have advanced OCR.
                frozen = window.inspector.result
                if args.output:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    window.grab().save(str(args.output))
                stage, stage_started = 1, now
            elif stage == 10:
                if any(len(b.lines) > 1 for b in window._overlay._blocks or ()):
                    assert now - stage_started < 1.0, "Closed panel retained its English too long"
                    return
                evidence["panel_hide_seconds"] = round(now - stage_started, 3)
                evidence["hidden_before_new_ocr"] = bool(
                    result and result.frame.captured_at < stage_started
                )
                if args.ocr_delay_ms:
                    assert evidence["hidden_before_new_ocr"]
                demo.panel_visible = True
                demo.update()
                stage, stage_started = 11, now
            elif stage == 11:
                if not any(len(b.lines) > 1 for b in window._overlay._blocks or ()):
                    assert now - stage_started < 3, "Reopened panel never restored English"
                    return
                evidence["panel_restore_seconds"] = round(now - stage_started, 3)
                transitions_done = True
                stage = 8
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
                assert window._visual is None
                assert window.inspector.result is None
                if args.device != "cpu":
                    window.ocr_device.setCurrentIndex(1)
                window.start_button.click()
                stage = 6
            elif stage == 6 and result:
                if args.device != "cpu":
                    assert window._ocr and window._ocr.snapshot().provider == "CPUExecutionProvider"
                    evidence["cpu_selection_after_gpu_session"] = True
                evidence["restart_receives_new_result"] = True
                window.close()
                stage = 7
            elif stage == 7 and window._session is None:
                assert window._ocr is None
                assert window._translation is None
                assert window._visual is None
                assert not window.isVisible()
                evidence["close_finishes_all_workers"] = True
                evidence["elapsed_seconds"] = round(now - started, 2)
                stage = 99
        except Exception as error:
            failure = f"{type(error).__name__}: {error}"
            evidence["failure"] = failure
            evidence["failure_state"] = {
                "stage": stage,
                "revealed": demo.revealed,
                "visual_source": window._visual_state.ocr_sequence,
                "visual_blocked": sorted(window._visual_state.blocked),
                "readings": [
                    {"text": a.observation.text, "pending": a.pending, "growing": a.growing}
                    for a in window._tracker.translation_activity()
                ],
            }
            traceback.print_exc()
            window.close()
            stage = 99
            print(f"FAIL: {failure!a}", flush=True)
            if now - started > timeout + 5:
                timer.stop()
                app.exit(1)

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    shiboken6.delete(app)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.with_suffix(".json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
    print(json.dumps(evidence, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
