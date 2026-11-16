"""Committed model/route transitions and worker ownership, independent of Qt presentation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from dantejp.application.translation_activity import (
    InactiveReason,
    TranslationActivity,
    TranslationMode,
)
from dantejp.translation.cloud.values import CloudProfile
from dantejp.translation.plan import TranslationPlan
from dantejp.translation.routing import RoutedTranslationSession
from dantejp.translation.selection import LocalIdentity
from dantejp.translation.values import TranslationSnapshot, TranslationState, TranslationWorker
from dantejp.translation.worker import BackendChoice, TranslationSession

Worker = TranslationSession | RoutedTranslationSession
logger = logging.getLogger(__name__)


class ModelPhase(StrEnum):
    IDLE = "idle"
    CONSENT = "consent"
    DRAINING = "draining"
    LOADING = "loading"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"
    CLOSING = "closing"


@dataclass(frozen=True)
class RouteSelection:
    mode: str = "local"
    profile: CloudProfile | None = None
    game: str = ""
    available: bool = False
    credential_revision: int = 0
    plan: TranslationPlan | None = None
    identities: tuple[BackendChoice | CloudProfile | None, ...] = field(default=(), compare=False)
    model_keys: tuple[LocalIdentity | CloudProfile | None, ...] = ()


@dataclass(frozen=True)
class ModelSnapshot:
    phase: ModelPhase
    selected: BackendChoice | None
    proposed: BackendChoice | None
    route: RouteSelection
    standby: bool
    message: str = ""
    assignment: TranslationPlan | None = None
    preparing: bool = False
    preparation_revision: int = 0
    worker: TranslationSnapshot | None = None


@dataclass(frozen=True)
class PreparationOutcome:
    committed: bool
    local_route: bool
    error: str = ""


@dataclass(frozen=True)
class PreparedWorker:
    """A live worker and the exact model it loaded, independent of current selection."""

    choice: BackendChoice
    worker: TranslationSession


RouteInput = PreparedWorker | RoutedTranslationSession | None


class ModelLifecycle:
    def __init__(
        self,
        create: Callable[[BackendChoice], TranslationSession],
        prepared: Callable[[BackendChoice], bool],
        record: Callable[[str], None],
    ) -> None:
        self._create, self._prepared, self._record = create, prepared, record
        self._session: Worker | None = None
        self._selected: BackendChoice | None = None
        self._preparing: BackendChoice | None = None
        self._standby = False
        self._proposal: BackendChoice | None = None
        self._local_intent = False
        self._started = False
        self._prepared_this_run: set[str] = set()
        self._preparation_revision = 0
        self._worker_choice: BackendChoice | None = None
        self._phase = ModelPhase.IDLE
        self._message = ""
        self._probing = False
        self._assignment: TranslationPlan | None = None
        self._pending_assignment: TranslationPlan | None = None
        self._route = RouteSelection()
        self._route_factory: Callable[[RouteInput], RoutedTranslationSession] | None = None

    def snapshot(self) -> ModelSnapshot:
        phase, message = self._phase, self._message
        worker = self._session.snapshot() if self._session else None
        if phase == ModelPhase.READY and worker:
            phase = {
                TranslationState.LOADING: ModelPhase.LOADING,
                TranslationState.STOPPING: ModelPhase.DRAINING,
                TranslationState.FAILED: ModelPhase.FAILED,
            }.get(worker.state, phase)
            message = worker.message
        return ModelSnapshot(
            phase,
            self._selected,
            self._preparing or self._proposal,
            self._route,
            self._standby,
            message,
            self._assignment,
            self._preparing is not None,
            self._preparation_revision,
            worker,
        )

    @property
    def assignment(self) -> TranslationPlan | None:
        """Committed immutable policy; reading it never polls workers."""
        return self._assignment

    @property
    def preparation_revision(self) -> int:
        """Invalidate cached model options only when this run adds a prepared model."""
        return self._preparation_revision

    @property
    def publication(self) -> TranslationWorker | None:
        """Narrow publication/invalidation port; worker lifecycle stays owned here."""
        return self._session

    def _route_input(self) -> RouteInput:
        if isinstance(self._session, TranslationSession):
            assert self._worker_choice is not None
            return PreparedWorker(self._worker_choice, self._session)
        return self._session

    def is_prepared(self, choice: BackendChoice) -> bool:
        return not choice.unavailable_reason and (
            choice.preparation_id in self._prepared_this_run or self._prepared(choice)
        )

    def restore_selection(
        self, choice: BackendChoice | None, *, assignment: TranslationPlan | None = None
    ) -> None:
        if self._session or self._preparing:
            raise ValueError("Initial selection can only be restored before loading a worker.")
        self._assignment = assignment
        self._selected = choice if choice and self.is_prepared(choice) else None
        self._phase = ModelPhase.READY if self._selected else ModelPhase.IDLE

    def refresh_choices(self, choices: tuple[BackendChoice, ...]) -> None:
        if self._selected:
            self._selected = next((b for b in choices if b.key == self._selected.key), None)

    def _allows_translation(self, *, running: bool, enabled: bool) -> bool:
        usable = (
            self._route.available
            if self._route.mode != "local"
            else bool(self._selected and self.is_prepared(self._selected))
        )
        return (
            running
            and enabled
            and usable
            and not self._preparing
            and not self._probing
            and self._phase != ModelPhase.CLOSING
        )

    def request_model(self, choice: BackendChoice | None, *, local_route: bool = False) -> bool:
        """False requests consent, without revoking the committed worker or selection."""
        if self._preparing or self._probing or self._phase == ModelPhase.CLOSING:
            raise ValueError("Wait for the current model operation to finish.")
        if choice and choice.unavailable_reason:
            raise ValueError(choice.unavailable_reason)
        self._local_intent = local_route
        if choice and not self.is_prepared(choice):
            self._proposal = choice
            self._phase = ModelPhase.CONSENT
            return False
        self._commit(choice)
        return True

    def request_assignment(self, plan: TranslationPlan, choice: BackendChoice | None) -> bool:
        """Stage a category change until its local model is prepared; decline rolls it back."""
        if self._preparing or self._probing or self._phase == ModelPhase.CLOSING:
            raise ValueError("Wait for the current model operation to finish.")
        self._pending_assignment = plan
        if choice is None:
            self._assignment, self._pending_assignment = plan, None
            if not plan.short and not plan.long:
                self._selected, self._standby = None, False
            return True
        try:
            return self.request_model(choice)
        except ValueError:
            self._pending_assignment = None
            raise

    def consent(self, accepted: bool) -> None:
        choice, self._proposal = self._proposal, None
        if self._phase != ModelPhase.CONSENT or choice is None:
            return
        if not accepted:
            self._pending_assignment = None
            self._phase = ModelPhase.READY if self._selected else ModelPhase.IDLE
            self._local_intent = False
            return
        self._preparing = choice
        self._started = False
        self._standby = True
        self._phase = ModelPhase.DRAINING
        self._message = "Finishing the previous model…"
        if self._session:
            self._session.request_stop()

    def _commit(self, choice: BackendChoice | None) -> None:
        self._proposal = None
        self._selected = choice
        self._standby = choice is not None
        self._phase = ModelPhase.READY if choice else ModelPhase.IDLE
        self._message = ""
        if self._pending_assignment is not None:
            self._assignment, self._pending_assignment = self._pending_assignment, None
            return  # configure_route owns draining and replacement for the complete plan.
        if self._session and choice:
            if self._session.finished:
                self._session = None
            else:
                self._session.switch_backend(choice.create)
                self._worker_choice = choice
        elif self._session:
            self._session.request_stop()

    def advance_preparation(self, *, closing: bool = False) -> PreparationOutcome | None:
        choice = self._preparing
        if choice is None:
            return None
        session = self._session
        committed, error = False, ""
        if closing:
            self.shutdown()
            if session and not session.finished:
                return None
        elif not self._started:
            if session and not session.finished:
                return None
            self._session = self._create(choice)
            self._worker_choice = choice
            self._started = True
            self._session.start()
            self._phase = ModelPhase.PREPARING
            self._message = "Checking model files and running a test translation…"
            return None
        elif session:
            result = session.snapshot()
            if result.state not in (TranslationState.READY, TranslationState.FAILED):
                return None
            if result.state == TranslationState.FAILED and not session.finished:
                return None
            if result.state == TranslationState.READY:
                committed = True
                if choice.preparation_id not in self._prepared_this_run:
                    self._prepared_this_run.add(choice.preparation_id)
                    self._preparation_revision += 1
                try:
                    self._record(choice.preparation_id)
                except OSError as error_record:
                    logger.warning("Could not save preparation receipt: %s", error_record)
                self._selected, self._standby = choice, True
                self._phase = ModelPhase.READY
                if self._pending_assignment is not None:
                    self._assignment = self._pending_assignment
            else:
                self._session, self._standby = None, False
                error = result.message
                self._phase = ModelPhase.FAILED
        self._message = error
        self._preparing, self._started = None, False
        self._pending_assignment = None
        outcome = PreparationOutcome(committed, self._local_intent, error)
        self._local_intent = False
        return outcome

    def configure_route(
        self,
        route: RouteSelection,
        factory: Callable[[RouteInput], RoutedTranslationSession],
        *,
        preserve_prepared: bool = False,
    ) -> bool:
        previous = self._route
        changed = route != previous
        self._route, self._route_factory = route, factory
        if changed and not preserve_prepared and not self._preparing:
            self._standby = False
            if (
                route.plan is not None
                and previous.plan is not None
                and isinstance(self._session, RoutedTranslationSession)
                and not self._session.stopping
            ):
                self._session = factory(self._route_input())
            else:
                self.drain()
        return changed

    def drain(self) -> None:
        if self._session:
            self._session.request_stop()
            if self._session.finished:
                self._session = None

    def stop_capture(self, *, closing: bool) -> None:
        self._standby = self._preparing is not None and not closing
        if not self._preparing or closing:
            self.drain()

    def shutdown(self) -> None:
        self._phase = ModelPhase.CLOSING
        self._proposal = None
        self._pending_assignment = None
        self._standby = False
        self.drain()

    def finish_shutdown(self) -> bool:
        self.shutdown()
        if self._preparing:
            self.advance_preparation(closing=True)
        return self._session is None and self._preparing is None

    def suspend_for_probe(self, active: bool) -> bool:
        """Keep committed selection; grant a probe only after inference has drained."""
        self._probing = active
        if not active or self._preparing or self._phase == ModelPhase.CLOSING:
            return False
        self._standby = False
        self.drain()
        return self._session is None

    @property
    def capture_drained(self) -> bool:
        return self._session is None or bool(self._preparing) or self._standby

    def resume_after_failed_restart(self) -> None:
        self._phase = ModelPhase.READY if self._selected else ModelPhase.IDLE

    def advance_activity(
        self, *, running: bool, enabled: bool, probing: bool = False
    ) -> TranslationActivity:
        """One decision owns probe, preparation, standby, teardown and route activation.

        Only ACTIVE exposes the publication port. Inactive and switching workers remain
        private until their native cleanup completes, even if their snapshot has failed.
        """
        probe_ready = self.suspend_for_probe(probing)
        if self._phase == ModelPhase.CLOSING:
            self.drain()
            return TranslationActivity(TranslationMode.INACTIVE)
        if probing:
            return TranslationActivity(TranslationMode.PROBING, probe_ready=probe_ready)
        if self._preparing:
            return TranslationActivity(TranslationMode.PREPARING)
        session = self._session
        if not running and self._standby and enabled and session and not session.finished:
            return TranslationActivity(TranslationMode.STANDBY, snapshot=session.snapshot())
        if not self._allows_translation(running=running, enabled=enabled):
            self.drain()
            reason = (
                InactiveReason.UNLOADING
                if session and not session.finished
                else InactiveReason.OFF
                if running
                else InactiveReason.NO_MODEL
                if self._selected is None
                else InactiveReason.STOPPED
            )
            return TranslationActivity(
                TranslationMode.INACTIVE,
                snapshot=session.snapshot() if session else None,
                reason=reason,
            )
        worker = self._activate_route()
        return TranslationActivity(
            TranslationMode.ACTIVE if worker else TranslationMode.SWITCHING,
            worker=worker,
            model_name=self._selected.name if self._selected else "the translation model",
        )

    def _activate_route(self) -> Worker | None:
        """Adopt/start the committed route only after advance_activity permits activation."""
        session, choice = self._session, self._selected
        if session and session.finished and session.snapshot().state == TranslationState.STOPPED:
            self._session = session = None
        if self._route.plan is not None:
            # No new native owners until every previous lane has finished teardown.
            if session and session.snapshot().state == TranslationState.STOPPING:
                return None
            if isinstance(session, TranslationSession):
                key = "local:" + self._worker_choice.preference_key if self._worker_choice else ""
                if key not in self._route.plan.active_models:
                    self.drain()
                    if self._session:
                        return None
                    session = None
            if session is None or isinstance(session, TranslationSession):
                assert self._route_factory
                self._session = session = self._route_factory(self._route_input())
            session.advance()
            return session
        if self._route.available and isinstance(session, TranslationSession):
            if self._route.mode == "cloud":
                self.drain()
                if self._session:
                    return None
                session = None
            else:
                assert self._route_factory
                self._session = session = self._route_factory(self._route_input())
        if session is None:
            local = None
            if self._route.mode != "cloud" and choice and self.is_prepared(choice):
                local = self._create(choice)
                local.start()
                self._worker_choice = choice
            if self._route.available:
                assert self._route_factory
                session = self._route_factory(
                    PreparedWorker(choice, local) if choice and local else None
                )
            else:
                session = local
            self._session = session
        return session
