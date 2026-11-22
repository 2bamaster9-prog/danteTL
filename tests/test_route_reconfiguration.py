"""Real worker lifetimes behind the public assignment owner; no models or network."""

import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_translation_plan import Engine, block, until

from dantetl.application.cloud_services import CloudServices
from dantetl.application.model_inventory import InventoryData, InventorySnapshot, ModelInventory
from dantetl.application.preference_values import Preferences
from dantetl.application.translation_coordinator import TranslationCoordinator
from dantetl.languages.selection import source_language
from dantetl.translation.backend import BackendChoice
from dantetl.translation.cloud.values import CloudProfile
from dantetl.translation.plan import TranslationPlan
from dantetl.translation.routing import RoutedTranslationSession
from dantetl.translation.selection import AssignmentChange
from dantetl.translation.values import TranslationState
from dantetl.translation.worker import TranslationSession


def remote_ref(key):
    return "cloud:cloud-" + key * 32


class Routes:
    def __init__(self, root, *, blocked=False):
        self.release = threading.Event()
        self.local = Mock(side_effect=lambda: Engine("local"))
        self.remote = {
            key: Mock(
                side_effect=lambda key=key: Engine(
                    key, self.release if key == "a" and blocked else None
                )
            )
            for key in ("a", "b", "c")
        }
        self.profiles = tuple(
            replace(CloudProfile.new("deepseek"), key="cloud-" + key * 32) for key in self.remote
        )
        self.choice = BackendChoice(
            "Local labels", self.local, "local-cuda", "weights-v1", selection_id="local"
        )
        self.inventory = Mock(spec=ModelInventory)
        self.inventory.snapshot.return_value = InventorySnapshot(
            loaded=True, data=InventoryData((self.choice,))
        )
        self.inventory.prepared.return_value = True
        self.cloud = Mock(spec=CloudServices)
        self.cloud.profiles = self.profiles
        self.cloud.revision = 0
        self.cloud.credential_revision.return_value = 0
        self.cloud.available.return_value = True
        self.cloud.create_backend.side_effect = lambda profile, game, language: self.remote[
            profile.key[-1]
        ]()
        self.owner = TranslationCoordinator(
            self.inventory,
            self.cloud,
            lambda choice, language: TranslationSession(
                choice.create, root / "cache", language=language
            ),
            RoutedTranslationSession,
            root / "cache",
            Preferences(model="none", short_model="local:local", long_model=remote_ref("a")),
        )
        self.owner.refresh_route()
        worker = self.owner.advance_activity(running=True, enabled=True).worker
        assert isinstance(worker, RoutedTranslationSession)
        self.worker = worker

    def assign(self, plan, reference):
        assert self.owner.assign(AssignmentChange(plan, reference)) in ("committed", "unchanged")
        self.owner.refresh_route()
        assert self.owner.advance_activity(running=True, enabled=True).worker is self.worker

    def ready(self):
        self.owner.advance_activity(running=True, enabled=True)
        return all(lane.state == TranslationState.READY for lane in self.worker.snapshot().lanes)

    def close(self):
        self.release.set()
        self.owner.lifecycle.shutdown()
        until(self.owner.lifecycle.finish_shutdown)


def test_cloud_switch_keeps_local_loaded_and_republishes_exact_results(tmp_path):
    routes = Routes(tmp_path)
    short, long = block(1, "設定"), block(2, "一緒に行きましょう。", dialogue=True)
    try:
        routes.worker.update((short, long))
        until(lambda: len(routes.worker.snapshot().results) == 2)
        first_generation = routes.worker.snapshot().backend_generation
        # Rediscovery creates fresh recipes but does not change model/runtime identity.
        routes.inventory.snapshot.return_value = InventorySnapshot(
            loaded=True,
            data=InventoryData((replace(routes.choice, create=lambda: routes.local()),)),
        )
        routes.assign(TranslationPlan("local:local", remote_ref("b")), remote_ref("b"))
        assert routes.worker.snapshot().backend_generation > first_generation
        assert routes.worker.snapshot().results == ()
        until(routes.ready)
        routes.worker.update((short, long))
        until(lambda: len(routes.worker.snapshot().results) == 2)
        assert {r.english for r in routes.worker.snapshot().results} == {
            "local: 設定",
            "b: 一緒に行きましょう。",
        }
        assert (
            routes.local.call_count
            == routes.remote["a"].call_count
            == routes.remote["b"].call_count
            == 1
        )
    finally:
        routes.close()


def test_rapid_switch_coalesces_replacements_while_unchanged_lane_progresses(tmp_path):
    routes = Routes(tmp_path, blocked=True)
    long = block(2, "一緒に行きましょう。", dialogue=True)
    try:
        routes.worker.update((long,))
        until(lambda: routes.worker.snapshot().processing_since is not None)
        routes.assign(TranslationPlan("local:local", remote_ref("b")), remote_ref("b"))
        routes.assign(TranslationPlan("local:local", remote_ref("c")), remote_ref("c"))
        # A pending replacement is visible even though the local worker is ready.
        snapshot = routes.worker.snapshot()
        assert any(
            lane.reference == remote_ref("c") and lane.state == TranslationState.LOADING
            for lane in snapshot.lanes
        )
        routes.worker.update((block(1, "設定"), long))
        until(lambda: bool(routes.worker.snapshot().results))
        assert routes.worker.snapshot().results[0].english == "local: 設定"
        assert not routes.remote["b"].called and not routes.remote["c"].called
        routes.release.set()
        until(routes.ready)
        routes.worker.update((block(1, "設定"), long))
        until(lambda: len(routes.worker.snapshot().results) == 2)
        assert all(not r.english.startswith("a:") for r in routes.worker.snapshot().results)
        assert routes.local.call_count == 1 and not routes.remote["b"].called
        assert routes.remote["c"].call_count == 1
    finally:
        routes.close()


@pytest.mark.parametrize("change", ["runtime", "credentials", "game"])
def test_identity_changes_replace_only_the_affected_model(tmp_path, change):
    routes = Routes(tmp_path)
    try:
        until(routes.ready)
        if change == "runtime":
            routes.inventory.snapshot.return_value = InventorySnapshot(
                loaded=True,
                data=InventoryData(
                    (replace(routes.choice, key="local-cpu", preparation_id="weights-v2"),)
                ),
            )
        elif change == "credentials":
            routes.cloud.credential_revision.return_value += 1
        else:
            routes.owner.set_game(automatic=False, manual="A new game", title="")
        assert routes.owner.refresh_route()
        until(routes.ready)
        assert routes.local.call_count == (2 if change == "runtime" else 1)
        assert routes.remote["a"].call_count == (1 if change == "runtime" else 2)
    finally:
        routes.close()


def test_source_switch_retires_only_the_incompatible_local_lane(tmp_path):
    class Multilingual(Engine):
        def set_source(self, language):
            self.cache_identity = language.code

    compatible, restricted = Multilingual("ja"), Engine("restricted")
    choices = (
        BackendChoice("Multilingual", Mock(return_value=compatible), "multi"),
        BackendChoice("Restricted", Mock(return_value=restricted), "restricted"),
    )
    inventory = Mock(spec=ModelInventory)

    def discover(backends):
        inventory.snapshot.return_value = InventorySnapshot(
            loaded=True, data=InventoryData(backends)
        )

    discover(choices)
    cloud = Mock(spec=CloudServices)
    cloud.profiles = ()
    owner = TranslationCoordinator(
        inventory,
        cloud,
        Mock(),
        RoutedTranslationSession,
        tmp_path / "cache",
        Preferences(short_model="local:multi", long_model="local:restricted"),
    )
    owner.refresh_route()
    route = owner.advance_activity(running=True, enabled=True).worker
    assert isinstance(route, RoutedTranslationSession)
    try:
        until(lambda: all(lane.state == TranslationState.READY for lane in route.snapshot().lanes))
        owner.language = source_language("pt")
        discover((choices[0], replace(choices[1], unavailable_reason="Unsupported source")))
        assert owner.refresh_route()
        assert owner.advance_activity(running=True, enabled=True).worker is route
        route.update((block(1, "Menu"), block(2, "Uma fala.", dialogue=True)))
        until(lambda: restricted.closed.is_set() and route.snapshot().results)
        assert [r.english for r in route.snapshot().results] == ["pt: Menu"]
        assert not compatible.closed.is_set()
        assert owner.plan.long == "local:restricted"
    finally:
        owner.lifecycle.shutdown()
        until(owner.lifecycle.finish_shutdown)


def test_shared_model_survives_lane_changes_until_last_assignment_removed(tmp_path):
    routes = Routes(tmp_path)
    try:
        until(routes.ready)
        routes.assign(TranslationPlan("local:local", "local:local"), "local:local")
        until(routes.ready)
        routes.assign(
            TranslationPlan("local:local", "local:local", short_enabled=False), "local:local"
        )
        until(routes.ready)
        routes.worker.update((block(1, "設定"), block(2, "説明" * 24)))
        until(lambda: bool(routes.worker.snapshot().results))
        assert len(routes.worker.snapshot().results) == 1
        assert len(routes.worker.snapshot().lanes) == 1 and routes.local.call_count == 1
    finally:
        routes.close()


def test_shutdown_drains_retirement_without_starting_pending_model(tmp_path):
    routes = Routes(tmp_path, blocked=True)
    try:
        routes.worker.update((block(2, "説明" * 24),))
        until(lambda: routes.worker.snapshot().processing_since is not None)
        routes.assign(TranslationPlan("local:local", remote_ref("b")), remote_ref("b"))
        routes.owner.lifecycle.shutdown()
        assert not routes.owner.lifecycle.finish_shutdown()
        assert not routes.worker.finished and not routes.remote["b"].called
    finally:
        routes.close()
    assert not routes.remote["b"].called


def test_cloud_edits_preserve_unaffected_work_and_scope_credential_changes(tmp_path, monkeypatch):
    from collections import Counter

    from test_cloud_services import create, finish

    from dantetl.translation.cloud.state import CloudDraft

    service, _ = create(tmp_path)
    a, b, c = (replace(CloudProfile.new("deepseek"), name=name) for name in ("A", "B", "C"))

    def save(profile, connection="", secret=""):
        service.save(CloudDraft(profile, connection, secret))
        snapshot = finish(service)
        assert not snapshot.problem
        return next(p for p in service.profiles if p.key == profile.key)

    a = save(a, secret="first-key")
    b = save(b, a.credential_key)  # Unassigned B shares A's credentials.
    c = save(c, secret="separate-key")
    release = threading.Event()
    counts = Counter()
    engines = []

    def create_backend(profile, game, language):
        counts[profile.key] += 1
        engine = Engine(
            profile.key, release if profile.key == a.key and counts[a.key] == 1 else None
        )
        engines.append(engine)
        return engine

    monkeypatch.setattr(service, "create_backend", create_backend)
    inventory = ModelInventory(lambda: InventoryData(), lambda _: None, initial=InventoryData())
    owner = TranslationCoordinator(
        inventory,
        service,
        Mock(),
        RoutedTranslationSession,
        tmp_path / "cache",
        Preferences(model="none", short_model="cloud:" + a.key, long_model="cloud:" + c.key),
    )
    owner.refresh_route()
    worker = owner.advance_activity(running=True, enabled=True).worker
    assert isinstance(worker, RoutedTranslationSession)
    history = Mock()
    owner.configure_history(history, enabled=True, reference="cloud:" + a.key)
    classifier_identity = history.configure_history.call_args.args[1]
    short, long = block(1, "設定"), block(2, "説明" * 24)
    try:
        worker.update((short, long))
        until(lambda: any(e.cache_identity == a.key and e.entered.is_set() for e in engines))
        until(lambda: counts[c.key] == 1)
        generation = worker.snapshot().backend_generation
        b = save(replace(b, name="B renamed"), b.credential_key)
        assert not owner.refresh_route()
        assert counts[a.key] == counts[c.key] == 1
        assert not any(e.closed.is_set() for e in engines)
        release.set()
        until(lambda: len(worker.snapshot().results) == 2)
        results = worker.snapshot().results
        a = save(replace(a, name="A renamed"), a.credential_key)
        assert not owner.refresh_route()
        assert worker.snapshot().results == results
        assert worker.snapshot().backend_generation == generation
        assert any(lane.name == "A renamed" for lane in worker.snapshot().lanes)
        owner.configure_history(history, enabled=True, reference="cloud:" + a.key)
        assert history.configure_history.call_args.args[1] == classifier_identity
        # Actual credential replacement affects every assigned model on that connection.
        b = save(b, b.credential_key, "replacement-key")
        assert owner.refresh_route()
        owner.configure_history(history, enabled=True, reference="cloud:" + a.key)
        assert history.configure_history.call_args.args[1] != classifier_identity

        def ready():
            owner.advance_activity(running=True, enabled=True)
            return all(lane.state == TranslationState.READY for lane in worker.snapshot().lanes)

        until(ready)
        assert counts[a.key] == 2 and counts[c.key] == 1 and counts[b.key] == 0
        # Re-saving the same secret is not a credential change.
        b = save(b, b.credential_key, "replacement-key")
        assert not owner.refresh_route()
        a = save(replace(a, request_limit=20), a.credential_key)
        assert owner.refresh_route()  # Active safety limits must reach the backend.
        until(ready)
        assert counts[a.key] == 3 and counts[c.key] == 1
        # Revocation takes effect before the credential operation is adopted.
        service.forget_key(a.credential_key)
        assert not service.available(a.key) and service.available(c.key)
        assert owner.refresh_route()
        assert owner.advance_activity(running=True, enabled=True).worker is worker
        new_short, new_long = block(3, "戻る"), block(4, "続き" * 24)
        worker.update((new_short, new_long))
        until(
            lambda: any(
                r.english == c.key + ": " + new_long.text for r in worker.snapshot().results
            )
        )
        assert all(not r.english.startswith(a.key) for r in worker.snapshot().results)
        assert all(
            new_short.text not in batch
            for engine in engines
            if engine.cache_identity == a.key
            for batch in engine.calls
        )
        finish(service)
    finally:
        release.set()
        owner.lifecycle.shutdown()
        until(owner.lifecycle.finish_shutdown)
        service.close()
