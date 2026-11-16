"""Real worker lifetimes behind the public assignment owner; no models or network."""

import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest
from test_translation_plan import Engine, block, until

from jp_overlay.cloud_services import CloudServices
from jp_overlay.cloud_values import CloudProfile
from jp_overlay.model_inventory import InventoryData, InventorySnapshot, ModelInventory
from jp_overlay.model_selection import AssignmentChange
from jp_overlay.preference_values import Preferences
from jp_overlay.translation import BackendChoice, TranslationSession
from jp_overlay.translation_coordinator import TranslationCoordinator
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_routing import RoutedTranslationSession
from jp_overlay.translation_values import TranslationState


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
        self.cloud.available.return_value = True
        self.cloud.create_backend.side_effect = lambda profile, game: self.remote[profile.key[-1]]()
        self.owner = TranslationCoordinator(
            self.inventory,
            self.cloud,
            lambda choice: TranslationSession(choice.create, root / "cache"),
            RoutedTranslationSession.assigned,
            root / "cache",
            Preferences(model="none", short_model="local:local", long_model=remote_ref("a")),
        )
        self.owner.refresh_route()
        worker = self.owner.advance_activity(running=True, enabled=True).worker
        assert isinstance(worker, RoutedTranslationSession)
        self.worker = worker

    def assign(self, plan, reference):
        assert self.owner.assign(AssignmentChange(plan, reference))
        self.owner.refresh_route()
        assert self.owner.advance_activity(running=True, enabled=True).worker is self.worker

    def ready(self):
        self.owner.advance_activity(running=True, enabled=True)
        return all(lane.state == TranslationState.READY for lane in self.worker.snapshot().lanes)

    def close(self):
        self.release.set()
        self.owner.shutdown()
        until(self.owner.finish_shutdown)


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
            routes.cloud.revision += 1
        else:
            routes.owner.set_game(automatic=False, manual="A new game", title="")
        assert routes.owner.refresh_route()
        until(routes.ready)
        assert routes.local.call_count == (2 if change == "runtime" else 1)
        assert routes.remote["a"].call_count == (1 if change == "runtime" else 2)
    finally:
        routes.close()


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
        routes.owner.shutdown()
        assert not routes.owner.finish_shutdown()
        assert not routes.worker.finished and not routes.remote["b"].called
    finally:
        routes.close()
    assert not routes.remote["b"].called
