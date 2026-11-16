"""Committed model/route transitions and worker ownership, independent of Qt presentation."""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from jp_overlay.cloud_values import CloudProfile
from jp_overlay.model_selection import LocalIdentity
from jp_overlay.translation import BackendChoice, TranslationSession
from jp_overlay.translation_activity import InactiveReason, TranslationActivity, TranslationMode
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_routing import RoutedTranslationSession
from jp_overlay.translation_values import TranslationState

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


@dataclass(frozen=True)
class PreparationOutcome:
    committed: bool
    local_route: bool
    error: str = ""


class ModelLifecycle:
    def __init__(
        self,
        create: Callable[[BackendChoice], TranslationSession],
        prepared: Callable[[BackendChoice], bool],
        record: Callable[[str], None],
    ) -> None:
        self._create, self._prepared, self._record = create, prepared, record
        self.session: Worker | None = None
        self.selected: BackendChoice | None = None
        self.preparing: BackendChoice | None = None
        self.standby = False
        self._proposal: BackendChoice | None = None
        self._local_intent = False
        self._started = False
        self._prepared_this_run: set[str] = set()
        self._phase = ModelPhase.IDLE
        self._message = ""
        self._probing = False
        self.assignment: TranslationPlan | None = None
        self._pending_assignment: TranslationPlan | None = None
        self._route = RouteSelection()
        self._route_factory: (
            Callable[[TranslationSession | None], RoutedTranslationSession] | None
        ) = None

    def snapshot(self) -> ModelSnapshot:
        phase, message = self._phase, self._message
        if phase == ModelPhase.READY and self.session:
            worker = self.session.snapshot()
            phase = {
                TranslationState.LOADING: ModelPhase.LOADING,
                TranslationState.STOPPING: ModelPhase.DRAINING,
                TranslationState.FAILED: ModelPhase.FAILED,
            }.get(worker.state, phase)
            message = worker.message
        return ModelSnapshot(
            phase,
            self.selected,
            self.preparing or self._proposal,
            self._route,
            self.standby,
            message,
        )

    def is_prepared(self, choice: BackendChoice) -> bool:
        return not choice.unavailable_reason and (
            choice.preparation_id in self._prepared_this_run or self._prepared(choice)
        )

    def restore_selection(self, choice: BackendChoice | None) -> None:
        if self.session or self.preparing:
            raise ValueError("Initial selection can only be restored before loading a worker.")
        self.selected = choice if choice and self.is_prepared(choice) else None
        self._phase = ModelPhase.READY if self.selected else ModelPhase.IDLE

    def refresh_choices(self, choices: tuple[BackendChoice, ...]) -> None:
        if self.selected:
            self.selected = next((b for b in choices if b.key == self.selected.key), None)

    def _allows_translation(self, *, running: bool, enabled: bool) -> bool:
        usable = (
            self._route.available
            if self._route.mode != "local"
            else bool(self.selected and self.is_prepared(self.selected))
        )
        return (
            running
            and enabled
            and usable
            and not self.preparing
            and not self._probing
            and self._phase != ModelPhase.CLOSING
        )

    def request_model(self, choice: BackendChoice | None, *, local_route: bool = False) -> bool:
        """False requests consent, without revoking the committed worker or selection."""
        if self.preparing or self._probing or self._phase == ModelPhase.CLOSING:
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
        if self.preparing or self._probing or self._phase == ModelPhase.CLOSING:
            raise ValueError("Wait for the current model operation to finish.")
        self._pending_assignment = plan
        if choice is None:
            self.assignment, self._pending_assignment = plan, None
            if not plan.short and not plan.long:
                self.selected, self.standby = None, False
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
            self._phase = ModelPhase.READY if self.selected else ModelPhase.IDLE
            self._local_intent = False
            return
        self.preparing = choice
        self._started = False
        self.standby = True
        self._phase = ModelPhase.DRAINING
        self._message = "Finishing the previous model…"
        if self.session:
            self.session.request_stop()

    def _commit(self, choice: BackendChoice | None) -> None:
        self._proposal = None
        self.selected = choice
        self.standby = choice is not None
        self._phase = ModelPhase.READY if choice else ModelPhase.IDLE
        self._message = ""
        if self._pending_assignment is not None:
            self.assignment, self._pending_assignment = self._pending_assignment, None
            return  # configure_route owns draining and replacement for the complete plan.
        if self.session and choice:
            if self.session.finished:
                self.session = None
            else:
                self.session.switch_backend(choice.create)
        elif self.session:
            self.session.request_stop()

    def advance_preparation(self, *, closing: bool = False) -> PreparationOutcome | None:
        choice = self.preparing
        if choice is None:
            return None
        session = self.session
        committed, error = False, ""
        if closing:
            self.shutdown()
            if session and not session.finished:
                return None
        elif not self._started:
            if session and not session.finished:
                return None
            self.session = self._create(choice)
            self._started = True
            self.session.start()
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
                self._prepared_this_run.add(choice.preparation_id)
                try:
                    self._record(choice.preparation_id)
                except OSError as error_record:
                    logger.warning("Could not save preparation receipt: %s", error_record)
                self.selected, self.standby = choice, True
                self._phase = ModelPhase.READY
                if self._pending_assignment is not None:
                    self.assignment = self._pending_assignment
            else:
                self.session, self.standby = None, False
                error = result.message
                self._phase = ModelPhase.FAILED
        self._message = error
        self.preparing, self._started = None, False
        self._pending_assignment = None
        outcome = PreparationOutcome(committed, self._local_intent, error)
        self._local_intent = False
        return outcome

    def configure_route(
        self,
        route: RouteSelection,
        factory: Callable[[TranslationSession | None], RoutedTranslationSession],
        *,
        preserve_prepared: bool = False,
    ) -> bool:
        changed = route != self._route
        self._route, self._route_factory = route, factory
        if changed and not preserve_prepared and not self.preparing:
            self.standby = False
            self.drain()
        return changed

    def drain(self) -> None:
        if self.session:
            self.session.request_stop()
            if self.session.finished:
                self.session = None

    def stop_capture(self, *, closing: bool) -> None:
        self.standby = self.preparing is not None and not closing
        if not self.preparing or closing:
            self.drain()

    def shutdown(self) -> None:
        self._phase = ModelPhase.CLOSING
        self._proposal = None
        self._pending_assignment = None
        self.standby = False
        self.drain()

    def finish_shutdown(self) -> bool:
        self.shutdown()
        if self.preparing:
            self.advance_preparation(closing=True)
        return self.session is None and self.preparing is None

    def suspend_for_probe(self, active: bool) -> bool:
        """Keep committed selection; grant a probe only after inference has drained."""
        self._probing = active
        if not active or self.preparing or self._phase == ModelPhase.CLOSING:
            return False
        self.standby = False
        self.drain()
        return self.session is None

    @property
    def capture_drained(self) -> bool:
        return self.session is None or bool(self.preparing) or self.standby

    def resume_after_failed_restart(self) -> None:
        self._phase = ModelPhase.READY if self.selected else ModelPhase.IDLE

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
        if self.preparing:
            return TranslationActivity(TranslationMode.PREPARING)
        session = self.session
        if not running and self.standby and enabled and session and not session.finished:
            return TranslationActivity(TranslationMode.STANDBY, snapshot=session.snapshot())
        if not self._allows_translation(running=running, enabled=enabled):
            self.drain()
            reason = (
                InactiveReason.UNLOADING
                if session and not session.finished
                else InactiveReason.OFF
                if running
                else InactiveReason.NO_MODEL
                if self.selected is None
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
            model_name=self.selected.name if self.selected else "the translation model",
        )

    def _activate_route(self) -> Worker | None:
        """Adopt/start the committed route only after advance_activity permits activation."""
        session, choice = self.session, self.selected
        if session and session.finished and session.snapshot().state == TranslationState.STOPPED:
            self.session = session = None
        if self._route.plan is not None:
            # No new native owners until every previous lane has finished teardown.
            if session and session.snapshot().state == TranslationState.STOPPING:
                return None
            if isinstance(session, TranslationSession):
                key = "local:" + choice.preference_key if choice else ""
                if key not in self._route.plan.active_models:
                    self.drain()
                    if self.session:
                        return None
                    session = None
            if session is None or isinstance(session, TranslationSession):
                assert self._route_factory
                self.session = session = self._route_factory(session)
            return session
        if self._route.available and isinstance(session, TranslationSession):
            if self._route.mode == "cloud":
                self.drain()
                if self.session:
                    return None
                session = None
            else:
                assert self._route_factory
                self.session = session = self._route_factory(session)
        if session is None:
            local = None
            if self._route.mode != "cloud" and choice and self.is_prepared(choice):
                local = self._create(choice)
                local.start()
            if self._route.available:
                assert self._route_factory
                session = self._route_factory(local)
            else:
                session = local
            self.session = session
        return session
