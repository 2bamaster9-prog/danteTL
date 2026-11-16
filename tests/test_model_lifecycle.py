from unittest.mock import Mock

from jp_overlay.model_lifecycle import ModelLifecycle, ModelPhase, RouteSelection
from jp_overlay.translation import (
    BackendChoice,
    TranslationSession,
    TranslationSnapshot,
    TranslationState,
)


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


def setup():
    created, receipts = [], []

    def create(choice):
        worker = Worker(choice)
        created.append(worker)
        return worker

    lifecycle = ModelLifecycle(create, lambda c: not c.preparation_id, receipts.append)
    base, candidate = (
        BackendChoice("Base", Mock(), "base"),
        BackendChoice("New", Mock(), "new", "new"),
    )
    lifecycle.request_model(base)
    return lifecycle, base, candidate, created, receipts


def test_consent_preserves_committed_worker_and_preparation_waits_for_teardown_then_reuses():
    lifecycle, base, candidate, created, receipts = setup()
    original = lifecycle.advance_activity(running=True, enabled=True).worker
    assert original
    assert lifecycle.snapshot().phase == ModelPhase.LOADING
    assert not lifecycle.request_model(candidate, local_route=True)
    assert lifecycle.snapshot().phase == ModelPhase.CONSENT and lifecycle.selected == base
    assert lifecycle.advance_activity(running=True, enabled=True).worker is original
    assert created[0].stops == 0
    lifecycle.consent(False)
    assert lifecycle.selected == base and not lifecycle.preparing
    assert not lifecycle.request_model(candidate, local_route=True)
    lifecycle.consent(True)
    assert lifecycle.snapshot().proposed == candidate
    assert lifecycle.advance_preparation() is None and len(created) == 1
    created[0].ended = True
    assert lifecycle.advance_preparation() is None and len(created) == 2
    ready = created[1]
    ready.state = TranslationState.READY
    outcome = lifecycle.advance_preparation()
    assert outcome and outcome.committed and outcome.local_route
    assert lifecycle.selected == candidate and receipts == ["new"]
    assert lifecycle.advance_activity(running=False, enabled=True).worker is None
    assert lifecycle.session is ready
    assert (
        lifecycle.advance_activity(running=True, enabled=True).worker is ready and len(created) == 2
    )


def test_failure_and_shutdown_wait_for_preparation_cleanup_without_committing():
    lifecycle, base, candidate, created, receipts = setup()
    lifecycle.request_model(candidate)
    lifecycle.consent(True)
    lifecycle.advance_preparation()
    created[0].state = TranslationState.FAILED
    assert lifecycle.advance_preparation() is None  # Error alone is not completion.
    created[0].ended = True
    outcome = lifecycle.advance_preparation()
    assert outcome and not outcome.committed and outcome.error
    assert lifecycle.selected == base and not receipts
    lifecycle.request_model(candidate)
    lifecycle.consent(True)
    lifecycle.advance_preparation()
    assert lifecycle.advance_preparation(closing=True) is None
    assert created[1].stops and lifecycle.snapshot().phase == ModelPhase.CLOSING
    created[1].ended = True
    outcome = lifecycle.advance_preparation(closing=True)
    assert outcome and not outcome.committed and not receipts
    assert lifecycle.selected == base and lifecycle.session is None


def test_route_change_drains_old_worker_and_refresh_during_preparation_does_not_stop_it():
    lifecycle, base, candidate, created, receipts = setup()
    old = lifecycle.advance_activity(running=True, enabled=True).worker
    remote = Mock()
    factory = Mock(return_value=remote)
    assert lifecycle.configure_route(RouteSelection("cloud", available=True), factory)
    assert lifecycle.advance_activity(running=True, enabled=True).worker is None
    factory.assert_not_called()
    created[0].ended, created[0].state = True, TranslationState.STOPPED
    assert lifecycle.advance_activity(running=True, enabled=True).worker is remote
    remote.finished = False
    lifecycle.request_model(candidate)
    lifecycle.consent(True)
    remote.finished = True
    lifecycle.advance_preparation()
    prepared = created[-1]
    lifecycle.configure_route(
        RouteSelection("cloud", available=True, credential_revision=1), factory
    )
    assert prepared.stops == 0
    prepared.state = TranslationState.READY
    outcome = lifecycle.advance_preparation()
    assert outcome and outcome.committed
    lifecycle.configure_route(RouteSelection(), factory, preserve_prepared=True)
    assert (
        lifecycle.advance_activity(running=True, enabled=True).worker is prepared
        and old is not prepared
    )


def test_import_probe_waits_for_unload_and_resumes_committed_selection_afterward():
    lifecycle, base, candidate, created, receipts = setup()
    original = lifecycle.advance_activity(running=True, enabled=True).worker
    assert original
    assert not lifecycle.advance_activity(running=True, enabled=True, probing=True).probe_ready
    assert len(created) == 1 and created[0].stops
    created[0].ended = True
    assert lifecycle.suspend_for_probe(True)
    assert lifecycle.selected == base and lifecycle.session is None
    assert lifecycle.advance_activity(running=True, enabled=True, probing=True).probe_ready
    lifecycle.suspend_for_probe(False)
    assert lifecycle.advance_activity(running=True, enabled=True).worker is not original
    assert created[1].choice == base and not receipts


def test_shutdown_during_preparation_does_not_commit_or_load_another_worker():
    lifecycle, base, candidate, created, receipts = setup()
    lifecycle.request_model(candidate)
    lifecycle.consent(True)
    lifecycle.advance_preparation()
    assert not lifecycle.finish_shutdown()
    assert lifecycle.advance_activity(running=True, enabled=True).worker is None
    created[0].ended = True
    assert lifecycle.finish_shutdown()
    assert lifecycle.selected == base and not receipts and len(created) == 1


def test_category_assignment_consent_and_failed_preparation_keep_previous_plan():
    from jp_overlay.translation_plan import TranslationPlan

    lifecycle, base, candidate, created, receipts = setup()
    original = TranslationPlan("local:base", "cloud:configured")
    proposed = TranslationPlan("local:new", "cloud:configured")
    assert lifecycle.request_assignment(original, base)
    assert not lifecycle.request_assignment(proposed, candidate)
    assert lifecycle.assignment == original
    lifecycle.consent(False)
    assert lifecycle.assignment == original and lifecycle.selected == base
    assert not lifecycle.request_assignment(proposed, candidate)
    lifecycle.consent(True)
    lifecycle.advance_preparation()
    created[0].state = TranslationState.FAILED
    assert lifecycle.advance_preparation() is None
    assert lifecycle.assignment == original
    created[0].ended = True
    outcome = lifecycle.advance_preparation()
    assert outcome and not outcome.committed
    assert lifecycle.assignment == original and lifecycle.selected == base and not receipts


def test_category_assignment_commits_atomically_after_preparation():
    from jp_overlay.translation_plan import TranslationPlan

    lifecycle, base, candidate, created, receipts = setup()
    original = TranslationPlan("local:base", "local:base")
    proposed = TranslationPlan("local:base", "local:new")
    lifecycle.request_assignment(original, base)
    assert not lifecycle.request_assignment(proposed, candidate)
    lifecycle.consent(True)
    lifecycle.advance_preparation()
    assert lifecycle.assignment == original
    created[0].state = TranslationState.READY
    outcome = lifecycle.advance_preparation()
    assert outcome and outcome.committed and lifecycle.assignment == proposed
    assert lifecycle.session is created[0] and lifecycle.standby and receipts == ["new"]
