from unittest.mock import Mock

from dantejp.application.model_lifecycle import ModelPhase
from dantejp.translation.values import TranslationSnapshot, TranslationState
from dantejp.translation.worker import BackendChoice, TranslationSession


class Worker(TranslationSession):
    def __init__(self, choice):
        self.choice = choice
        self.state = TranslationState.LOADING
        self.ended = False
        self.stops = 0
        self.started = False

    @property
    def finished(self):
        return self.ended

    def start(self):
        self.started = True

    def request_stop(self):
        self.stops += 1

    def snapshot(self):
        return TranslationSnapshot(
            self.state, message="fixture failure" if self.state == TranslationState.FAILED else ""
        )

    def switch_backend(self, factory):
        self.state = TranslationState.LOADING


def setup(tmp_path):
    from ownership_fixtures import Replay

    from dantejp.application.model_inventory import InventoryData

    base = BackendChoice("Base", Mock(), "base")
    candidate = BackendChoice("New", Mock(), "new", "new")
    return Replay(tmp_path, data=InventoryData((base, candidate))), base, candidate


def propose(replay, choice):
    from dantejp.translation.plan import TranslationPlan

    return replay.translation.lifecycle.request_assignment(
        TranslationPlan("local:" + choice.key, "local:" + choice.key), choice
    )


def activate(replay):
    replay.translation.refresh_route()
    return replay.translation.advance_activity(running=True, enabled=True).worker


def test_consent_preserves_worker_then_preparation_waits_for_cleanup_and_is_adopted(tmp_path):
    replay, base, candidate = setup(tmp_path)
    lifecycle = replay.translation.lifecycle
    try:
        original = activate(replay)
        assert original is replay.route_workers[0]
        assert not propose(replay, candidate)
        assert lifecycle.snapshot().phase == ModelPhase.CONSENT
        assert lifecycle.snapshot().selected == base
        assert activate(replay) is original and replay.route_workers[0].stops == 0
        lifecycle.consent(False)
        assert lifecycle.snapshot().selected == base and not lifecycle.snapshot().preparing
        assert not propose(replay, candidate)
        lifecycle.consent(True)
        assert lifecycle.advance_preparation() is None and not replay.workers
        replay.route_workers[0].finish()
        lifecycle.advance_preparation()
        prepared = replay.workers[0]
        prepared.state = TranslationState.READY
        outcome = lifecycle.advance_preparation()
        assert outcome and outcome.committed and lifecycle.snapshot().selected == candidate
        assert replay.translation.plan.active_models == ("local:new",)
        assert lifecycle.advance_activity(running=False, enabled=True).worker is None
        assert lifecycle.publication is prepared
        replay.translation.refresh_route(preserve_prepared=True)
        assert replay.translation.advance_activity(running=True, enabled=True).worker
        assert replay.routes[-1][1]["prepared"] == ("local:new", prepared)
        assert len(replay.workers) == 1 and prepared.stops == 0
    finally:
        replay.close()


def test_failed_preparation_waits_for_cleanup_and_preserves_committed_assignment(tmp_path):
    replay, base, candidate = setup(tmp_path)
    lifecycle = replay.translation.lifecycle
    try:
        original = replay.translation.plan
        assert not propose(replay, candidate)
        lifecycle.consent(True)
        lifecycle.advance_preparation()
        prepared = replay.workers[0]
        prepared.state = TranslationState.FAILED
        assert lifecycle.advance_preparation() is None
        assert replay.translation.plan == original
        prepared.ended = True
        outcome = lifecycle.advance_preparation()
        assert outcome and not outcome.committed and outcome.error
        assert replay.translation.plan == original and lifecycle.snapshot().selected == base
        assert lifecycle.publication is None and not replay.receipts
    finally:
        replay.close()


def test_route_refresh_during_preparation_cannot_stop_prepared_owner(tmp_path):
    replay, _, candidate = setup(tmp_path)
    lifecycle = replay.translation.lifecycle
    try:
        assert not propose(replay, candidate)
        lifecycle.consent(True)
        lifecycle.advance_preparation()
        prepared = replay.workers[0]
        replay.translation.refresh_route()
        assert prepared.stops == 0
        prepared.state = TranslationState.READY
        outcome = lifecycle.advance_preparation()
        assert outcome and outcome.committed
        replay.translation.refresh_route(preserve_prepared=True)
        assert replay.translation.advance_activity(running=True, enabled=True).worker
        assert replay.routes[-1][1]["prepared"] == ("local:new", prepared)
    finally:
        replay.close()


def test_import_probe_waits_for_unload_then_resumes_committed_assignment(tmp_path):
    replay, base, _ = setup(tmp_path)
    lifecycle = replay.translation.lifecycle
    try:
        original = activate(replay)
        plan = replay.translation.plan
        assert not lifecycle.advance_activity(running=True, enabled=True, probing=True).probe_ready
        assert replay.route_workers[0].stops
        replay.route_workers[0].finish()
        assert lifecycle.suspend_for_probe(True)
        assert lifecycle.publication is None and lifecycle.snapshot().selected == base
        assert lifecycle.advance_activity(running=True, enabled=True, probing=True).probe_ready
        lifecycle.suspend_for_probe(False)
        assert activate(replay) is not original and replay.translation.plan == plan
        assert len(replay.route_workers) == 2
    finally:
        replay.close()


def test_shutdown_during_preparation_never_commits_or_starts_another_owner(tmp_path):
    replay, base, candidate = setup(tmp_path)
    lifecycle = replay.translation.lifecycle
    try:
        assert not propose(replay, candidate)
        lifecycle.consent(True)
        lifecycle.advance_preparation()
        assert not lifecycle.finish_shutdown()
        assert lifecycle.advance_activity(running=True, enabled=True).worker is None
        replay.workers[0].ended = True
        assert lifecycle.finish_shutdown()
        assert lifecycle.snapshot().selected == base and not replay.receipts
        assert len(replay.workers) == 1 and not replay.routes
    finally:
        replay.close()
