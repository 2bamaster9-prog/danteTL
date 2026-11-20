"""Lifecycle regressions through application commands and injected worker completions."""

import time
from dataclasses import replace
from unittest.mock import Mock

import pytest
from ownership_fixtures import Replay
from test_live_session import Capture, Ocr, Visual, frame

from dantetl.application.model_inventory import InventoryData
from dantetl.application.preference_values import Preferences
from dantetl.domain import CaptureSnapshot, CaptureState, Rect
from dantetl.ocr.values import OcrResult, OcrSnapshot, OcrState, TextRegion
from dantetl.ocr.visual_values import VisualState
from dantetl.ocr.worker import OcrChoice
from dantetl.runtime.restart import RestartSnapshot
from dantetl.translation.plan import TranslationPlan
from dantetl.translation.selection import AssignmentChange
from dantetl.translation.values import TranslatedText, TranslationRequest, TranslationState
from dantetl.translation.worker import BackendChoice


@pytest.fixture
def replay(tmp_path):
    value = Replay(
        tmp_path, data=InventoryData((BackendChoice("Base", Mock(), "base"),), device="cpu")
    )
    yield value
    value.close()


def observe(replay, sequence=1):
    source = frame(sequence, sequence)
    result = OcrResult(source, (TextRegion("設定", Rect(50, 40, 100, 30)),), 25, sequence)
    replay.capture.current = CaptureSnapshot(CaptureState.RUNNING, source)
    replay.ocr.current = OcrSnapshot(OcrState.READY, result)
    replay.visual.current = VisualState(
        frame=source,
        checked_sequence=sequence,
        ocr_sequence=sequence,
    )
    replay.app.advance(sequence + 0.1)
    replay.app.advance(sequence + 0.7)
    return result


def publish(replay):
    block = replay.app.view.scene.requests[0]
    reply = TranslatedText(TranslationRequest.from_block(block), "Settings")
    replay.route_workers[-1].results = (reply,)
    replay.app.advance(1.8)
    assert replay.app.view.english == (reply,)
    return reply


def test_device_and_rate_are_frozen_until_all_old_workers_finish(tmp_path):
    cpu, gpu = Mock(), Mock()
    replay = Replay(
        tmp_path,
        loaded=False,
        preferences=Preferences(ocr_device="auto"),
        ocr_choices=(OcrChoice("CPU", cpu, key="cpu"), OcrChoice("GPU", gpu, key="auto")),
    )
    try:
        assert replay.app.start_capture(replay.capture.target, 1)
        assert replay.app.controls.capture_rate == 8 and not replay.recognizers
        replay.app.configure(replace(replay.app.values, ocr_device="cpu", capture_rate=5))
        replay.discover(InventoryData())
        replay.app.advance(2)
        assert replay.recognizers == [gpu] and len(replay.capture_calls) == 1
        replay.app.stop()
        replay.capture.finished = True
        replay.app.advance(3)
        assert not replay.app.start_capture(replay.capture.target, 4)
        assert "OCR and visual" in replay.app.view.status
        replay.ocr.finished = replay.visual.finished = True
        replay.app.advance(4)
        replay.capture, replay.ocr, replay.visual = Capture(), Ocr(), Visual()
        assert replay.app.start_capture(replay.capture.target, 5)
        assert replay.recognizers == [gpu, cpu]
        assert replay.capture_calls[-1][1] == replay.app.controls.capture_rate == 5
    finally:
        replay.close()


def test_capture_stop_waits_for_translation_then_ocr_cleanup(replay):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    assert replay.app.view.ocr and replay.app.view.ocr.result
    replay.app.stop()
    assert replay.app.view.ocr is None
    assert not replay.app.view.english and not replay.app.controls.can_stop
    replay.capture.finished = True
    replay.app.advance(2)
    assert "translation operation" in replay.app.view.status
    assert not replay.app.start_capture(replay.capture.target, 3)
    replay.route_workers[0].finish()
    replay.app.advance(3)
    assert "OCR and visual" in replay.app.view.status
    replay.ocr.finished = replay.visual.finished = True
    replay.app.advance(4)
    assert not replay.app.controls.capture_active
    assert replay.app.view.status == "Capture stopped."
    assert replay.app.view.ocr is None


def test_display_queries_reuse_the_published_inference_snapshots(replay, monkeypatch):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    for worker in (replay.route_workers[-1], replay.ocr):
        monkeypatch.setattr(worker, "snapshot", Mock(side_effect=AssertionError("worker polled")))
    assert replay.app.controls.capture_active
    assert not replay.app.can_setup
    assert replay.app.notices() == replay.app.notices()


def test_stop_intent_survives_delayed_capture_acknowledgement(replay):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    replay.app.stop()
    replay.route_workers[0].finish()
    # The native owner can still report its last RUNNING snapshot until it handles stop.
    assert replay.capture.current.state == CaptureState.RUNNING
    for now in (2, 3, 4):
        replay.app.advance(now)
        assert not replay.app.view.scene.tracks and not replay.app.view.english
        assert replay.app.view.overlay_bounds is None
        assert len(replay.route_workers) == 1
    replay.capture.finished = replay.ocr.finished = replay.visual.finished = True
    replay.app.advance(5)
    assert not replay.app.controls.capture_active


@pytest.mark.parametrize("cause", ["minimized", "resized", "window_error", "ocr_error"])
def test_invalid_capture_revokes_scene_and_english(replay, cause):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    if cause == "minimized":
        replay.windows.geometry.return_value = replace(frame(1).geometry, minimized=True)
    elif cause == "resized":
        replay.windows.geometry.return_value = replace(
            frame(1).geometry, client=Rect(0, 0, 600, 400)
        )
    elif cause == "window_error":
        replay.windows.geometry.side_effect = OSError("fixture target disappeared")
    else:
        replay.ocr.current = OcrSnapshot(OcrState.FAILED, message="fixture OCR failure")
    replay.app.advance(2)
    assert not replay.app.view.english and not replay.app.view.scene.tracks
    assert replay.app.view.overlay_bounds is None
    if cause in ("minimized", "resized"):
        assert replay.ocr.invalidations > 0
        assert set(replay.ocr.acknowledged) == {1}
    if cause == "window_error":
        assert replay.capture.stop_requested
    reset = replay.app.view.reset
    generations = (replay.visual.invalidations, replay.ocr.invalidations)
    for tick in range(3, 103):
        assert replay.app.advance(tick).reset == reset
    assert (replay.visual.invalidations, replay.ocr.invalidations) == generations
    if cause in ("minimized", "resized"):
        replay.windows.geometry.return_value = frame(104).geometry
        result = observe(replay, 104)
        assert replay.app.view.observation is result
        assert replay.app.view.capture is replay.capture.current


def test_failed_restart_releases_published_source_while_workers_drain(replay, tmp_path):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    assert replay.app.view.observation and replay.app.view.visual.frame
    replay.app.request_close(tmp_path / "runtime")
    reset = replay.app.view.reset

    def assert_cleared(view):
        assert view.reset == reset and view.frame is None and view.observation is None
        assert view.ocr is None and view.visual.frame is None
        assert view.capture is None or view.capture.frame is None
        assert not view.scene.tracks and not view.english and view.overlay_bounds is None

    assert_cleared(replay.app.view)
    assert_cleared(replay.app.advance(2))
    replay.capture.finished = replay.ocr.finished = replay.visual.finished = True
    replay.route_workers[-1].finish()
    replay.restart.finished = True
    replay.restart.snapshot.return_value = RestartSnapshot("failed", "fixture")
    deadline = time.monotonic() + 3
    while replay.app.closing:
        assert_cleared(replay.app.advance(3))
        assert time.monotonic() < deadline, replay.app.close_status
        time.sleep(0.001)
    assert not replay.app.closing and not replay.app.controls.capture_active
    assert replay.app.close_status.message == "fixture"
    assert_cleared(replay.app.advance(4))


def test_hidden_overlay_and_focus_loss_preserve_the_processing_scene(replay):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    english = publish(replay)
    before = replay.app.view.scene
    replay.windows.is_foreground.return_value = False
    replay.app.advance(2)
    assert replay.app.view.overlay_bounds is None
    assert replay.app.view.scene == before and replay.app.view.english == (english,)
    replay.app.configure(replace(replay.app.values, show_overlay=False))
    replay.windows.is_foreground.return_value = True
    replay.app.advance(3)
    assert replay.app.view.scene == before and set(replay.ocr.acknowledged) == {1}


def test_pending_consent_keeps_old_route_and_failure_preserves_assignment(replay):
    base = replay.source.data.backends[0]
    candidate = BackendChoice("Candidate", Mock(), "new", "weights")
    replay.discover(InventoryData((base, candidate)))
    replay.app.start_capture(replay.capture.target, 0)
    replay.app.advance(1)
    old = replay.route_workers[0]
    prompt = replay.app.assign(AssignmentChange(TranslationPlan("local:new"), "local:new"))
    assert prompt
    replay.app.advance(2)  # A nested consent event loop uses the same public pump.
    assert not old.stops and replay.app.controls.assignment == TranslationPlan(
        "local:base", "local:base"
    )
    replay.app.consent(prompt.token, True)
    replay.app.advance(3)
    assert old.stops and not replay.workers
    old.finish()
    replay.app.advance(4)
    candidate_worker = replay.workers[0]
    candidate_worker.state = TranslationState.FAILED
    replay.app.advance(5)
    assert replay.app.controls.preparing  # An error reply is not completed cleanup.
    candidate_worker.ended = True
    replay.app.advance(6)
    assert not replay.app.controls.preparing and replay.app.error == "fixture failure"
    assert replay.app.controls.assignment == TranslationPlan("local:base", "local:base")
    assert not replay.receipts


def test_removed_model_revokes_publication_and_drains_old_worker(replay):
    replay.app.start_capture(replay.capture.target, 0)
    observe(replay)
    publish(replay)
    old = replay.route_workers[0]
    replay.discover(InventoryData())
    replay.app.advance(2)
    assert not replay.app.view.english and old.stops
    assert replay.app.controls.options == ()


def test_probe_waits_for_both_owners_and_resumes_committed_route(replay):
    replay.app.start_capture(replay.capture.target, 0)
    replay.app.advance(1)
    old = replay.route_workers[0]
    plan = replay.app.controls.assignment
    assert replay.setup.test_import("fixture.gguf", "auto")
    gate = replay.dependencies.probe.call_args.args[3]
    replay.live.suspend_history = Mock(return_value=False)
    replay.app.advance(2)
    assert old.stops and not gate.is_set()
    replay.app.assign(AssignmentChange(TranslationPlan(), ""))
    assert replay.app.controls.assignment == plan
    old.finish()
    replay.app.advance(3)
    assert not gate.is_set()
    replay.live.suspend_history.return_value = True
    replay.app.advance(4)
    assert gate.is_set() and len(replay.route_workers) == 1
    replay.operations[-1].finish(cancelled=True)
    replay.app.advance(5)
    assert len(replay.route_workers) == 2 and replay.app.controls.assignment == plan


def test_relocated_same_model_updates_next_factory_without_restarting(replay):
    replay.app.start_capture(replay.capture.target, 0)
    replay.app.advance(1)
    old = replay.route_workers[0]
    moved = replace(replay.source.data.backends[0], create=Mock())
    replay.discover(InventoryData((moved,)))
    replay.app.advance(2)
    assert not old.stops and len(replay.route_workers) == 1
    replay.app.stop()
    old.finish()
    replay.capture.finished = replay.ocr.finished = replay.visual.finished = True
    replay.app.advance(3)
    replay.capture, replay.ocr, replay.visual = Capture(), Ocr(), Visual()
    replay.app.start_capture(replay.capture.target, 4)
    replay.app.advance(4)
    assert replay.routes[-1][0][1]["local:base"] is moved.create


def test_nested_advance_is_coalesced_and_never_runs_owners_reentrantly(replay):
    advance = replay.setup.advance
    calls = []

    def complete():
        calls.append(True)
        replay.app.advance(1)
        advance()

    replay.setup.advance = complete
    replay.app.advance(1)
    assert len(calls) == 1
