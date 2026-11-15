"""Authoritative assignment, route and classifier resolution, independent of presentation."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from jp_overlay.cloud_services import CloudServices
from jp_overlay.cloud_values import CloudProfile
from jp_overlay.live_session import LiveSession
from jp_overlay.model_inventory import ModelInventory
from jp_overlay.model_lifecycle import ModelLifecycle, RouteSelection
from jp_overlay.model_selection import (
    AssignmentChange,
    ClassifierIdentity,
    LocalIdentity,
    ModelOption,
)
from jp_overlay.preference_values import Preferences
from jp_overlay.translation import BackendChoice, TranslationSession
from jp_overlay.translation_activity import TranslationActivity, TranslationMode
from jp_overlay.translation_backend import TranslationBackend
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_routing import RoutedTranslationSession


def model_reference(choice: BackendChoice | CloudProfile | None) -> str:
    if isinstance(choice, BackendChoice):
        return "local:" + choice.preference_key
    return "cloud:" + choice.key if choice else ""


class TranslationCoordinator(ModelLifecycle):
    """The existing transition state machine, with the policy formerly owned by widgets."""

    def __init__(
        self,
        inventory: ModelInventory,
        cloud: CloudServices,
        create: Callable[[BackendChoice], TranslationSession],
        route_create: Callable[..., RoutedTranslationSession],
        cache: Path,
        preferences: Preferences,
        *,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        super().__init__(create, inventory.prepared, inventory.record_prepared)
        self.inventory, self.cloud = inventory, cloud
        self._route_create, self._cache, self._notify = route_create, cache, on_change
        self._preferences = preferences
        self._restored = False
        self._options_key = None
        self._options: tuple[ModelOption, ...] = ()
        self.game_from_window = preferences.game_from_window
        self.manual_game = preferences.game_hint
        self.window_title = ""
        self.history_enabled = preferences.history_enabled
        self.history_model = preferences.history_model
        self.restore()

    @property
    def choices(self) -> tuple[BackendChoice, ...]:
        return self.inventory.snapshot().data.backends

    @property
    def plan(self) -> TranslationPlan:
        return self.assignment or TranslationPlan()

    def restore(self) -> None:
        if self._restored or not self.inventory.snapshot().loaded:
            return
        p = self._preferences
        initial = next((c for c in self.choices if c.preference_key == p.model), None)
        if p.model == "auto":
            initial = next((c for c in self.choices if self.is_prepared(c)), None)
        self.restore_selection(initial)
        legacy = TranslationPlan.legacy(
            p.translation_route,
            self.selected.preference_key if self.selected else "",
            p.cloud_model,
        )
        self.assignment = TranslationPlan(
            legacy.short if p.short_model == "legacy" else p.short_model,
            legacy.long if p.long_model == "legacy" else p.long_model,
            p.translate_short,
            p.translate_long,
        )
        self._restored = True

    @property
    def restored(self) -> bool:
        return self._restored

    def resolve(self, reference: str) -> BackendChoice | CloudProfile | None:
        return next(
            (c for c in (*self.choices, *self.cloud.profiles) if model_reference(c) == reference),
            None,
        )

    def options(self) -> tuple[ModelOption, ...]:
        cloud = self.cloud.snapshot()
        key = (
            self.inventory.snapshot().revision,
            cloud.profiles,
            cloud.available,
            cloud.revision,
            frozenset(self._prepared_this_run),
        )
        if key == self._options_key:
            return self._options
        self._options_key = key
        self._options = tuple(
            ModelOption(
                model_reference(c),
                c.name,
                c.key,
                prepared=self.is_prepared(c),
                unavailable_reason=c.unavailable_reason,
                performance_notice=c.performance_notice,
                classifies=c.classifies,
            )
            for c in self.choices
        ) + tuple(
            ModelOption(
                model_reference(p),
                p.name,
                p.key,
                provider=p.provider,
                prepared=self.cloud.available(p.key),
                classifies=True,
            )
            for p in self.cloud.profiles
        )
        return self._options

    @property
    def active_options(self) -> tuple[ModelOption, ...]:
        options = {c.reference: c for c in self.options()}
        return tuple(options[key] for key in self.plan.active_models if key in options)

    @property
    def game(self) -> str:
        return self.window_title if self.game_from_window else self.manual_game

    def set_game(self, *, automatic: bool, manual: str, title: str) -> None:
        self.game_from_window = automatic
        self.manual_game = " ".join(manual.split())[:120]
        self.window_title = " ".join(title.split())[:120]

    def assign(self, change: AssignmentChange) -> bool:
        choice = self.resolve(change.reference)
        return self.request_assignment(
            change.plan, choice if isinstance(choice, BackendChoice) else None
        )

    def refresh_route(self, *, preserve_prepared: bool = False) -> bool:
        self.restore()
        self.refresh_choices(self.choices)
        choices = tuple(self.resolve(key) for key in self.plan.active_models)
        remote = any(isinstance(c, CloudProfile) for c in choices)
        route = RouteSelection(
            "assigned",
            game=self.game if remote else "",
            available=any(
                self.is_prepared(c)
                if isinstance(c, BackendChoice)
                else self.cloud.available(c.key)
                if isinstance(c, CloudProfile)
                else False
                for c in choices
            ),
            credential_revision=self.cloud.revision if remote else 0,
            plan=self.plan,
            identities=choices,
            model_keys=tuple(
                LocalIdentity(c.key, c.preparation_id, c.unavailable_reason)
                if isinstance(c, BackendChoice)
                else c
                for c in choices
            ),
        )
        return self.configure_route(
            route, partial(self._create_route, route), preserve_prepared=preserve_prepared
        )

    def _create_route(
        self,
        route: RouteSelection,
        local: TranslationSession | None,
    ) -> RoutedTranslationSession:
        assert route.plan is not None
        factories = {}
        for choice in route.identities:
            if isinstance(choice, BackendChoice) and self.is_prepared(choice):
                factories[model_reference(choice)] = choice.create
            elif isinstance(choice, CloudProfile) and self.cloud.available(choice.key):
                factories[model_reference(choice)] = partial(
                    self.cloud.create_backend, choice, route.game
                )
        result = self._route_create(
            route.plan,
            factories,
            self._cache,
            prepared=(model_reference(self.selected), local) if local else None,
            on_change=self._notify,
        )
        result.start()
        return result

    def configure_history(self, live: LiveSession, *, enabled: bool, reference: str) -> None:
        self.history_enabled, self.history_model = enabled, reference
        choice = self.resolve(reference)
        factory: Callable[[], TranslationBackend] | None = None
        identity = ClassifierIdentity(reference, None)
        if isinstance(choice, BackendChoice) and choice.classifies and self.is_prepared(choice):
            factory = choice.create
            identity = ClassifierIdentity(
                reference, LocalIdentity(choice.key, choice.preparation_id), available=True
            )
        elif isinstance(choice, CloudProfile) and self.cloud.available(choice.key):
            factory = partial(self.cloud.create_backend, choice, "")
            identity = ClassifierIdentity(reference, choice, self.cloud.revision, True)
        live.configure_history(enabled, identity, factory, layout_only=reference == "layout")

    def advance_activity(
        self, *, running: bool, enabled: bool, probing: bool
    ) -> TranslationActivity:
        """Resolve worker availability once, before LiveSession publishes any sources.

        Preparation, probe suspension, standby reuse and route teardown are model policy.
        The application only joins the probe permit with classifier cleanup and publishes
        through the returned worker; it never reconstructs these lifecycle decisions.
        """
        ready = self.suspend_for_probe(probing)
        if probing:
            return TranslationActivity(TranslationMode.PROBING, probe_ready=ready)
        if self.preparing:
            return TranslationActivity(TranslationMode.PREPARING)
        session = self.session
        if not running and self.standby and enabled and session and not session.finished:
            return TranslationActivity(TranslationMode.STANDBY, snapshot=session.snapshot())
        if not self.allows_translation(running=running, enabled=enabled):
            self.worker(running=running, enabled=enabled)
            message = (
                "Unloading translation model…"
                if session and not session.finished
                else "Translation needs runtime setup. Select a model for instructions."
                if self.choices and all(c.unavailable_reason for c in self.choices)
                else "English translation is off."
                if running
                else "No translation model selected. Open Settings to download one."
                if self.selected is None
                else "Translation stopped."
            )
            return TranslationActivity(
                TranslationMode.INACTIVE,
                snapshot=session.snapshot() if session else None,
                message=message,
            )
        session = self.worker(running=running, enabled=enabled)
        if session is None:
            return TranslationActivity(TranslationMode.SWITCHING)
        return TranslationActivity(
            TranslationMode.ACTIVE,
            worker=session,
            model_name=self.selected.name if self.selected else "the translation model",
        )
