"""Authoritative assignment, route and classifier resolution, independent of presentation."""

from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path

from dantetl.application.cloud_services import CloudServices
from dantetl.application.live_session import LiveSession
from dantetl.application.model_inventory import ModelInventory
from dantetl.application.model_lifecycle import (
    ModelLifecycle,
    PreparedWorker,
    RouteInput,
    RouteSelection,
)
from dantetl.application.preference_values import Preferences
from dantetl.application.translation_activity import (
    InactiveReason,
    TranslationActivity,
    TranslationMode,
)
from dantetl.languages.selection import source_language
from dantetl.languages.source import SourceLanguage
from dantetl.translation.backend import TranslationBackend
from dantetl.translation.cloud.values import CloudProfile
from dantetl.translation.plan import TranslationPlan
from dantetl.translation.routing import ModelIdentity, RoutedTranslationSession
from dantetl.translation.selection import (
    AssignmentChange,
    ClassifierIdentity,
    CloudIdentity,
    LocalIdentity,
    ModelOption,
)
from dantetl.translation.worker import BackendChoice, TranslationSession


def model_reference(choice: BackendChoice | CloudProfile | None) -> str:
    if isinstance(choice, BackendChoice):
        return "local:" + choice.preference_key
    return "cloud:" + choice.key if choice else ""


class TranslationCoordinator:
    """Resolve model policy; an owned lifecycle exclusively commits and operates workers."""

    def __init__(
        self,
        inventory: ModelInventory,
        cloud: CloudServices,
        create: Callable[[BackendChoice, SourceLanguage], TranslationSession],
        route_create: Callable[..., RoutedTranslationSession],
        cache: Path,
        preferences: Preferences,
        *,
        on_change: Callable[[], None] = lambda: None,
    ) -> None:
        self.language = source_language(preferences.source_language)
        self._lifecycle = ModelLifecycle(
            lambda choice: create(choice, self.language),
            inventory.prepared,
            inventory.record_prepared,
        )
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
    def lifecycle(self) -> ModelLifecycle:
        return self._lifecycle

    @property
    def choices(self) -> tuple[BackendChoice, ...]:
        return self.inventory.snapshot().data.backends

    @property
    def plan(self) -> TranslationPlan:
        return self._lifecycle.assignment or TranslationPlan()

    def restore(self) -> None:
        if self._restored or not self.inventory.snapshot().loaded:
            return
        p = self._preferences
        initial = next((c for c in self.choices if c.preference_key == p.model), None)
        if p.model == "auto":
            initial = next((c for c in self.choices if self._lifecycle.is_prepared(c)), None)
        selected = initial if initial and self._lifecycle.is_prepared(initial) else None
        legacy = TranslationPlan.legacy(
            p.translation_route,
            selected.preference_key if selected else "",
            p.cloud_model,
        )
        plan = TranslationPlan(
            legacy.short if p.short_model == "legacy" else p.short_model,
            legacy.long if p.long_model == "legacy" else p.long_model,
            p.translate_short,
            p.translate_long,
        )
        self._lifecycle.restore_selection(initial, assignment=plan)
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
            self._lifecycle.preparation_revision,
        )
        if key == self._options_key:
            return self._options
        self._options_key = key
        self._options = tuple(
            ModelOption(
                model_reference(c),
                c.name,
                c.key,
                prepared=self._lifecycle.is_prepared(c),
                unavailable_reason=c.unavailable_reason,
                performance_notice=c.performance_notice,
                classifies=c.classifies,
                output_codes=c.output_codes,
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
        return self._lifecycle.request_assignment(
            change.plan, choice if isinstance(choice, BackendChoice) else None
        )

    def refresh_route(self, *, preserve_prepared: bool = False) -> bool:
        self.restore()
        self._lifecycle.refresh_choices(self.choices)
        choices = tuple(self.resolve(key) for key in self.plan.active_models)
        remote = any(isinstance(c, CloudProfile) for c in choices)
        route = RouteSelection(
            language=self.language,
            game=self.game if remote else "",
            available_models=frozenset(
                model_reference(c)
                for c in choices
                if (isinstance(c, BackendChoice) and self._lifecycle.is_prepared(c))
                or (isinstance(c, CloudProfile) and self.cloud.available(c.key))
            ),
            plan=self.plan,
            identities=choices,
            model_keys=tuple(
                LocalIdentity(c.key, c.preparation_id, c.unavailable_reason)
                if isinstance(c, BackendChoice)
                else CloudIdentity.from_profile(c, self.game, self.cloud.credential_revision(c))
                if isinstance(c, CloudProfile)
                else None
                for c in choices
            ),
        )
        return self._lifecycle.configure_route(
            route, partial(self._create_route, route), preserve_prepared=preserve_prepared
        )

    def _create_route(
        self,
        route: RouteSelection,
        local: RouteInput,
    ) -> RoutedTranslationSession:
        factories = {}
        identities: dict[str, ModelIdentity] = {}
        names = {}
        for choice, identity in zip(route.identities, route.model_keys, strict=True):
            reference = model_reference(choice)
            if reference not in route.available_models:
                continue
            assert choice is not None and identity is not None
            factories[reference] = (
                choice.create
                if isinstance(choice, BackendChoice)
                else partial(self.cloud.create_backend, choice, route.game, route.language)
            )
            identities[reference] = identity
            names[reference] = choice.name
        if isinstance(local, RoutedTranslationSession):
            local.reconfigure(
                route.plan, factories, language=route.language, identities=identities, names=names
            )
            return local
        result = self._route_create(
            route.plan,
            factories,
            self._cache,
            language=route.language,
            prepared=(model_reference(local.choice), local.worker)
            if isinstance(local, PreparedWorker)
            else None,
            on_change=self._notify,
            identities=identities,
            names=names,
        )
        result.start()
        return result

    def configure_history(self, live: LiveSession, *, enabled: bool, reference: str) -> None:
        self.history_enabled, self.history_model = enabled, reference
        choice = self.resolve(reference)
        factory: Callable[[], TranslationBackend] | None = None
        identity = ClassifierIdentity(reference, None)
        if (
            isinstance(choice, BackendChoice)
            and choice.classifies
            and self._lifecycle.is_prepared(choice)
        ):
            factory = choice.create
            identity = ClassifierIdentity(
                reference, LocalIdentity(choice.key, choice.preparation_id), available=True
            )
        elif isinstance(choice, CloudProfile) and self.cloud.available(choice.key):
            factory = partial(self.cloud.create_backend, choice, "", self.language)
            identity = ClassifierIdentity(
                reference,
                CloudIdentity.from_profile(choice, "", self.cloud.credential_revision(choice)),
                available=True,
            )
        live.configure_history(enabled, identity, factory, layout_only=reference == "layout")

    def advance_activity(
        self, *, running: bool, enabled: bool, probing: bool = False
    ) -> TranslationActivity:
        activity = self._lifecycle.advance_activity(
            running=running, enabled=enabled, probing=probing
        )
        if (
            activity.mode == TranslationMode.INACTIVE
            and activity.reason != InactiveReason.UNLOADING
            and self.choices
            and all(c.unavailable_reason for c in self.choices)
        ):
            return replace(activity, reason=InactiveReason.NEEDS_RUNTIME)
        return activity
