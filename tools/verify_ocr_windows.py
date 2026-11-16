"""Exercise capture -> local OCR -> inspector against our own live Windows fixture."""

import argparse
import json
import os
import time
import traceback
from dataclasses import replace
from functools import partial
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication
from verification_isolation import app_owner
from verification_isolation import create_window as MainWindow
from verify_translation import process_memory

from dantejp.application.model_factories import create_recognizer, translation_backends
from dantejp.capture.windows import Windows
from dantejp.domain import CapturedFrame, WindowTarget
from dantejp.ocr.worker import OcrChoice, OcrState, TextRegion
from dantejp.translation.worker import TranslationState
from dantejp.ui.demo import DIALOGUE_LINES, DemoWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Save a screenshot of only our test app")
    parser.add_argument(
        "--translation", action="store_true", help="Include real Gemma and model swapping"
    )
    parser.add_argument("--dialogue", action="store_true", help="Verify two-line dialogue grouping")
    parser.add_argument("--ocr-delay-ms", type=int, default=0, help="Simulate a slow OCR worker")
    parser.add_argument(
        "--device", choices=("cpu", "auto", "cuda", "directml", "auto-directml"), default="cpu"
    )
    parser.add_argument(
        "--gemma", action="store_true", help="Start Gemma, swap to another Gemma model and back"
    )
    parser.add_argument(
        "--classifier",
        choices=("gemma", "gemma-e4b", "qwen35-4b"),
        help="Enable a separate prepared local history classifier",
    )
    parser.add_argument(
        "--model",
        choices=("gemma-e4b", "qwen35-4b", "plamo-2b", "plamo-0.8b"),
        help="Start a curated model, swap to another Gemma model and back",
    )
    parser.add_argument("--debug", action="store_true", help="Verify diagnostic overlay rendering")
    parser.add_argument("--transitions", action="store_true", help="Close/reopen the text panel")
    parser.add_argument(
        "--typewriter", action="store_true", help="Check gradual dialogue readiness"
    )
    args = parser.parse_args()
    selected_model = args.model or ("gemma" if args.gemma else "")
    selected_model = selected_model or "gemma"
    alternate_model = "gemma" if selected_model != "gemma" else "gemma-e4b"
    if (args.gemma or args.model) and not args.translation:
        parser.error("--gemma/--model requires --translation")
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

        @property
        def scan_costs(self):
            return getattr(self.engine, "scan_costs", None)

        def recognize(
            self, frame: CapturedFrame, *, cropped: bool = False
        ) -> tuple[TextRegion, ...]:
            time.sleep(args.ocr_delay_ms / 1000)
            return self.engine.recognize(frame, cropped=cropped)

        def close(self) -> None:
            self.engine.close()

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
    choices = (OcrChoice(args.device, factory, 8, "auto"),)
    if args.device != "cpu":
        choices += (OcrChoice("CPU", create_recognizer, 8, "cpu"),)
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
        # Pipeline fixture explicitly requests real model loading. Onboarding consent
        # is tested separately; never write a preparation receipt from this fixture.
        tuple(replace(b, preparation_id="") for b in translation_backends())
        if args.translation
        else (),
        cache_path=cache_path,
        ocr_backends=choices,
    )
    application = app_owner(window)
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    if args.dialogue:
        classifier_key = "local:" + args.classifier if args.classifier else "layout"
        classifier_index = window.history_panel.model.findData(classifier_key)
        assert classifier_index >= 0, "Requested classifier is not installed"
        window.history_panel.model.setCurrentIndex(classifier_index)
        window._settings.history_enabled.setChecked(True)
    model_index = next(
        (
            i
            for i in range(window.backend_combo.count())
            if (b := window.backend_combo.itemData(i)) and b.preference_key == selected_model
        ),
        -1,
    )
    if args.translation:
        assert model_index >= 0, "Requested model is not downloaded"
        window.backend_combo.setCurrentIndex(model_index)
    window.debug_check.setChecked(args.debug)
    window.show()
    window.advanced.setChecked(True)
    if not args.translation:
        window.translate_check.setChecked(False)
        window.raw_boxes_check.setChecked(True)
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
    swapped = 0
    grouping_stage = 0
    continuity_started = 0.0
    continuity_polls = 0
    continuity_request = None
    border_owners = None
    border_sequence = 0
    evidence: dict[str, object] = {"translation_cache_initially_empty": cache_initially_empty}
    failure = ""
    reveal_finished = 0.0
    transitions_done = False
    timeout = 180 if args.device != "cpu" or args.translation else 45

    def tick() -> None:
        nonlocal stage, stage_started, frozen, initial_size, failure, phrase_id, phrase_bounds
        nonlocal swapped, grouping_stage
        nonlocal continuity_started, continuity_polls, continuity_request
        nonlocal border_owners, border_sequence
        nonlocal reveal_finished
        nonlocal transitions_done
        now = time.monotonic()
        try:
            if now - started > timeout:
                raise RuntimeError(f"Live OCR verification timed out at stage {stage}")
            if stage == 99:
                if application.shutdown.snapshot().phase == "ready":
                    window.close()
                    demo.close()
                    timer.stop()
                    app.quit()
                return
            if application.live.ocr and application.live.ocr.snapshot().state == OcrState.FAILED:
                raise RuntimeError(application.live.ocr.snapshot().message)
            if (
                application.translation.session
                and application.translation.session.snapshot().state == TranslationState.FAILED
            ):
                raise RuntimeError(application.translation.session.snapshot().message)
            result = window.inspector.result
            if (
                args.typewriter
                and reveal_finished
                and not swapped
                and application.translation.session
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
                    if application.translation.session:
                        for translated in application.translation.session.snapshot().results:
                            assert translated.request.source == "旅人", (
                                "Premature dialogue translation: " + translated.request.source
                            )
                    return
                if not reveal_finished:
                    reveal_finished = now
                if not all(line in [r.text for r in result.regions] for line in DIALOGUE_LINES):
                    return
            if stage == 8 and phrase_id and application.live.capture:
                latest = application.live.capture.snapshot().frame
                if latest:
                    current = application.live._tracker.visible(latest, now)
                    assert any(t.track_id == phrase_id for t in current), (
                        "Track blinked between OCR passes"
                    )
                if continuity_request is not None:
                    assert application.translation.session is not None
                    assert any(
                        t.request == continuity_request
                        for t in application.translation.session.snapshot().results
                    ), "English disappeared between slow OCR passes"
                    assert any(
                        t.request == continuity_request for t in window._overlay._translations
                    ), "Overlay discarded an unchanged translation"
            if stage == 0 and result is not None:
                text = [r.text for r in result.regions]
                assert expected in text, text
                if args.dialogue:
                    assert DIALOGUE_LINES[1] in text, text
                    assert any(
                        t.text == "旅人"
                        for t in application.live._tracker.visible(result.frame, now)
                    ), "Unscanned speaker disappeared"
                assert window.inspector.table.rowCount() == len(result.regions)
                evidence["live_japanese_recognized"] = True
                evidence["ocr_ms"] = round(result.duration_ms, 1)
                evidence["dpi"] = result.frame.geometry.dpi
                if args.device in ("cuda", "directml") and not args.ocr_delay_ms:
                    provider = (
                        "CUDAExecutionProvider" if args.device == "cuda" else "DmlExecutionProvider"
                    )
                    assert (
                        application.live.ocr
                        and application.live.ocr.snapshot().provider == provider
                    )
                    evidence["actual_gpu_provider"] = application.live.ocr.snapshot().provider
                initial_size = result.frame.geometry.client.size
                frozen = result
                tracks = application.live._tracker.visible(result.frame, now)
                phrase = next((t for t in tracks if t.text == expected), None)
                if phrase is None:
                    return  # Raw OCR can complete before its source-matched track commits.
                phrase_id, phrase_bounds = phrase.track_id, phrase.bounds
                stage = 8
            elif (
                stage == 8
                and result
                and frozen
                and result.frame.sequence >= frozen.frame.sequence + 3
            ):
                tracks = application.live._tracker.visible(result.frame, now)
                phrase = next(t for t in tracks if t.track_id == phrase_id)
                assert phrase.bounds == phrase_bounds, "Stationary dialogue box changed bounds"
                if args.translation:
                    if application.translation.session is None:
                        return
                    translated = application.translation.session.snapshot()
                    if not translated.results or translated.pending:
                        return
                    if not swapped:
                        if not any(
                            t.request.source == translation_source
                            for t in window._overlay._translations
                        ):
                            return  # A partial scan can finish before the full group publishes.
                        if args.typewriter:
                            assert "typewriter_to_full_english_seconds" in evidence
                            evidence["no_partial_dialogue_translations"] = True
                        evidence["first_backend_english"] = next(
                            t.english
                            for t in window._overlay._translations
                            if t.request.source == translation_source
                        )
                        window.backend_combo.setCurrentIndex(
                            next(
                                i
                                for i in range(window.backend_combo.count())
                                if (b := window.backend_combo.itemData(i))
                                and b.preference_key == alternate_model
                            )
                        )
                        swapped = 1
                        return
                    if swapped == 1:
                        evidence["alternate_model_between_loads"] = [
                            t.english for t in translated.results
                        ]
                        window.backend_combo.setCurrentIndex(model_index)
                        swapped = 2
                        return
                    if args.dialogue and grouping_stage == 1:
                        sources = {t.request.source for t in translated.results}
                        if not all(line in sources for line in DIALOGUE_LINES):
                            return  # A serial backend may finish the speaker before lines settle.
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
                            if window.border_check.isChecked():
                                capture = application.live.capture
                                assert capture and capture.snapshot().frame
                                frame = capture.snapshot().frame
                                assert frame is not None
                                border_sequence = frame.sequence
                                border_owners = (
                                    capture,
                                    application.live.ocr,
                                    application.translation.session,
                                )
                                window.border_check.setChecked(False)
                        continuity_polls += 1
                        if now - continuity_started < 3:
                            return
                        evidence["slow_ocr_english_continuity_polls"] = continuity_polls
                        if border_owners:
                            assert border_owners == (
                                application.live.capture,
                                application.live.ocr,
                                application.translation.session,
                            ), "Border change replaced a processing owner"
                            capture = application.live.capture
                            assert capture is not None
                            frame = capture.snapshot().frame
                            assert frame and frame.sequence > border_sequence
                            evidence["border_toggle_preserves_workers_and_english"] = True
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
                        history = application.live.history.turns
                        if not history:
                            return  # Reader settling is independent of the earlier overlay result.
                        assert history[-1].source == english.request.source
                        assert history[-1].speaker in (None, "旅人")
                        assert window.start_button.property("tone") == "recording"
                        assert not window.start_button.icon().isNull()
                        evidence["history_records_complete_group_without_speaker_in_body"] = True
                        evidence["history_speaker"] = history[-1].speaker
                        evidence["history_speaker_english"] = history[-1].speaker_english
                        if history[-1].speaker:
                            name_result = next(
                                t for t in translated.results if t.request.source == "旅人"
                            )
                            assert history[-1].speaker_english == name_result.english.strip()
                        if "history_panel_independent" not in evidence:
                            assert len(history) == 1, (
                                "Grouping/model swaps duplicated the same turn"
                            )
                            before = application.translation.session
                            window.history_button.click()
                            app.processEvents()
                            assert not window.history_panel.isModal()
                            assert english.english in window.history_panel.reader.toPlainText()
                            assert window.history_panel.reader.verticalScrollBar().value() == 0
                            if history[-1].speaker_english:
                                assert (
                                    f"({history[-1].speaker_english}) 旅人"
                                    in window.history_panel.reader.toPlainText()
                                )
                            if args.output:
                                window.history_panel.grab().save(
                                    str(args.output.with_name("dialogue-history.png"))
                                )
                                window.grab().save(
                                    str(args.output.with_name("capture-running.png"))
                                )
                            window.history_panel.hide()
                            assert application.translation.session is before
                            evidence["history_panel_independent"] = True
                            demo.raise_()
                            demo.activateWindow()
                    evidence["process_memory"] = process_memory()
                    window._overlay.set_tracks(tracks)
                    window._overlay.set_translations(translated.results, enabled=True)
                    window._overlay.align(windows.geometry(target).client)
                    app.processEvents()  # Deliver the native resize before grabbing the widget.
                    if args.debug:
                        diagnostic = window._overlay._debug
                        assert diagnostic and diagnostic.scanned and "OCR" in diagnostic.text
                        evidence["debug_snapshot"] = diagnostic.text
                        before = window._overlay._translations
                        window.debug_check.setChecked(False)
                        assert window._overlay._debug is None
                        assert window._overlay._translations == before
                        window.debug_check.setChecked(True)
                        assert window._overlay._debug is not None
                        evidence["debug_toggle_preserves_english"] = True
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
                assert result is not None
                restored = next(
                    t
                    for t in application.live._tracker.visible(result.frame, now)
                    if t.text == expected
                )
                evidence["closed_panel_identity_retired"] = restored.track_id != phrase_id
                phrase_id, phrase_bounds = restored.track_id, restored.bounds
                transitions_done = True
                stage = 8
            elif stage == 1 and now - stage_started > 0.7:
                assert window.inspector.result is frozen, "Pause replaced the reviewed frame"
                # The fixture deliberately does not steal foreground focus. Exercise
                # pause rendering with foreground eligibility controlled independently.
                with patch.object(windows, "is_foreground", return_value=True):
                    window._tick()
                    assert window._overlay.isVisible(), "Inspector pause hid the live overlay"
                    workers = (
                        application.live.capture,
                        application.live.ocr,
                        application.live.visual,
                        application.translation.session,
                    )
                    english = window._overlay._translations
                    window._original_changed(True)
                    assert not window._overlay.isVisible()
                    window._tick()
                    assert not window._overlay.isVisible()
                    window._original_changed(False)
                    assert window._overlay.isVisible(), (
                        "Release did not immediately restore overlay"
                    )
                    assert window._overlay._translations == english
                    assert workers == (
                        application.live.capture,
                        application.live.ocr,
                        application.live.visual,
                        application.translation.session,
                    ), "Original hold replaced processing workers"
                    window.overlay_check.setChecked(False)
                    window._original_changed(True)
                    window._original_changed(False)
                    assert not window._overlay.isVisible(), "Release overrode the visibility switch"
                    window.overlay_check.setChecked(True)
                    evidence["original_hold_restores_english_without_worker_restart"] = True
                assert application.live.capture is not None
                captured = application.live.capture.snapshot().frame
                assert captured and frozen and captured.sequence > frozen.frame.sequence
                evidence["pause_freezes_result_while_capture_continues"] = True
                evidence["pause_preserves_live_overlay"] = True
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
            elif stage == 5 and application.live.capture is None:
                assert window.start_button.property("tone") == "idle"
                assert application.live.ocr is None
                assert application.translation.session is None
                assert application.live.visual is None
                assert window.inspector.result is None
                if args.device != "cpu":
                    window.ocr_device.setCurrentIndex(1)
                window.start_button.click()
                stage = 6
            elif stage == 6 and result:
                if args.device != "cpu":
                    assert (
                        application.live.ocr
                        and application.live.ocr.snapshot().provider == "CPUExecutionProvider"
                    )
                    evidence["cpu_selection_after_gpu_session"] = True
                evidence["restart_receives_new_result"] = True
                window.close()
                stage = 7
            elif stage == 7 and application.shutdown.snapshot().phase == "ready":
                assert application.live.ocr is None
                assert application.translation.session is None
                assert application.live.visual is None
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
                "visual_source": application.live.visual_state.ocr_sequence,
                "visual_blocked": sorted(application.live.visual_state.blocked),
                "readings": [
                    {"text": a.observation.text, "pending": a.pending, "growing": a.growing}
                    for a in application.live._tracker.translation_activity()
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
    from verification_isolation import run_isolated

    run_isolated(main)
