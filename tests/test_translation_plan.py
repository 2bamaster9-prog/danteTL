"""Category assignments preserve bounded work, ownership and exact-source publication."""

import threading
import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.model_lifecycle import ModelLifecycle, RouteSelection
from jp_overlay.preferences import Preferences, decode_preferences
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import BackendChoice, TranslationSession, TranslationState
from jp_overlay.translation_plan import TranslationPlan
from jp_overlay.translation_routing import RoutedTranslationSession


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def block(key, text, *, dialogue=False):
    return TextBlock((TextTrack(key, text, Rect(0, key * 40, 200, 30)),), dialogue=dialogue)


class Engine:
    batch_size = 1

    def __init__(self, identity, release=None):
        self.cache_identity = identity
        self.release = release
        self.entered = threading.Event()
        self.closed = threading.Event()
        self.calls = []

    def translate(self, texts):
        self.calls.append(texts)
        self.entered.set()
        if self.release:
            assert self.release.wait(3)
        return tuple(self.cache_identity + ": " + text for text in texts)

    def close(self):
        self.closed.set()


@pytest.mark.parametrize(
    "keys", [("local:a", "local:b"), ("cloud:a", "cloud:b"), ("cloud:a", "local:b")]
)
def test_two_assignments_progress_independently_and_remain_stable(tmp_path, keys):
    release = threading.Event()
    fast, slow = Engine("fast"), Engine("slow", release)
    session = RoutedTranslationSession.assigned(
        TranslationPlan(*keys), {keys[0]: lambda: fast, keys[1]: lambda: slow}, tmp_path / "cache"
    )
    session.start()
    short, long = block(1, "設定"), block(2, "一緒に行きましょう。", dialogue=True)
    try:
        session.update((long, short))
        assert slow.entered.wait(2)
        until(lambda: len(session.snapshot().results) == 1)
        assert session.snapshot().results[0].english == "fast: 設定"
        release.set()
        until(lambda: len(session.snapshot().results) == 2)
        original = session.snapshot().results
        for _ in range(40):
            session.update((short, long))
            assert session.snapshot().results == original
        assert len(fast.calls) == len(slow.calls) == 1
        # Geometry and category noise cannot reroute the same accepted content/revision.
        session.update((short, replace(long, dialogue=False)))
        assert session.snapshot().results == original
    finally:
        release.set()
        session.request_stop()
        until(lambda: session.finished)
        assert fast.closed.is_set() and slow.closed.is_set()


def test_same_model_uses_one_prepared_owner_and_disabled_text_is_never_requested(tmp_path):
    engine = Engine("shared")
    factory = Mock(return_value=engine)
    prepared = TranslationSession(factory, tmp_path / "cache")
    prepared.start()
    until(lambda: prepared.snapshot().state == TranslationState.READY)
    plan = TranslationPlan("local:a", "local:a", short_enabled=False)
    session = RoutedTranslationSession.assigned(
        plan, {"local:a": factory}, tmp_path / "cache", prepared=("local:a", prepared)
    )
    session.start()
    short, long = block(1, "設定"), block(2, "説明" * 24)
    try:
        session.update((short, long), retain=(short, long))
        until(lambda: bool(session.snapshot().results))
        assert factory.call_count == 1 and engine.calls == [(long.text,)]
        session.update((short,), retain=(short, long))
        assert session.snapshot().results[0].request.source == long.text
        assert not plan.two_local_models
    finally:
        session.request_stop()
        until(lambda: session.finished)


def test_reassign_waits_for_all_owners_and_rejects_previous_inflight_reply(tmp_path):
    release = threading.Event()
    old, other, new = Engine("old", release), Engine("other"), Engine("new")
    choices = {
        k: BackendChoice(k, lambda e=e: e, k) for k, e in (("a", old), ("b", other), ("c", new))
    }
    lifecycle = ModelLifecycle(
        lambda c: TranslationSession(c.create, tmp_path / "cache"), lambda c: True, lambda k: None
    )
    factories = {"local:" + k: c.create for k, c in choices.items()}

    def configure(plan):
        lifecycle.configure_route(
            RouteSelection("assigned", available=True, plan=plan), lambda prepared: start(plan)
        )

    def start(plan):
        result = RoutedTranslationSession.assigned(plan, factories, tmp_path / "cache")
        result.start()
        return result

    configure(TranslationPlan("local:a", "local:b"))
    first = lifecycle.advance_activity(running=True, enabled=True).worker
    assert isinstance(first, RoutedTranslationSession)
    text = block(1, "設定")
    try:
        first.update((text, block(2, "説明" * 24)))
        assert old.entered.wait(2)
        assert other.entered.wait(2)
        configure(TranslationPlan("local:c", "local:b"))
        assert lifecycle.advance_activity(running=True, enabled=True).worker is None
        assert not new.entered.is_set() and first.snapshot().results == ()
        release.set()
        until(lambda: first.finished)
        current = lifecycle.advance_activity(running=True, enabled=True).worker
        assert current and current is not first and old.closed.is_set() and other.closed.is_set()
        current.update((text,))
        until(lambda: bool(current.snapshot().results))
        assert current.snapshot().results[0].english == "new: 設定"
    finally:
        release.set()
        lifecycle.shutdown()
        until(lifecycle.finish_shutdown)


def test_failed_lane_does_not_take_down_other_and_missing_model_never_falls_back(tmp_path):
    engine = Engine("working")

    def fail():
        raise RuntimeError("fixture load failure")

    session = RoutedTranslationSession.assigned(
        TranslationPlan("local:a", "cloud:b"),
        {"local:a": lambda: engine, "cloud:b": fail},
        tmp_path / "cache",
    )
    session.start()
    try:
        session.update((block(1, "設定"), block(2, "説明" * 24)))
        until(lambda: bool(session.snapshot().results) and "fixture" in session.snapshot().message)
        assert session.snapshot().state == TranslationState.READY
        assert engine.calls == [("設定",)]
    finally:
        session.request_stop()
        until(lambda: session.finished)


def test_preferences_validate_new_assignments_and_keep_manual_game_on_upgrade():
    cloud = "cloud:cloud-" + "a" * 32
    decoded = decode_preferences(
        {
            "version": 1,
            "short_model": "local:gemma-e4b",
            "long_model": cloud,
            "translate_short": False,
            "game_hint": "Honkai Star Rail",
        }
    )
    assert decoded.short_model == "local:gemma-e4b" and decoded.long_model == cloud
    assert not decoded.translate_short and not decoded.game_from_window
    assert decode_preferences({"version": 1, "short_model": "../bad"}).short_model == "legacy"
    assert Preferences().game_from_window
    assert TranslationPlan.legacy("long", "gemma", cloud[6:]) == TranslationPlan(
        "local:gemma", cloud
    )


def test_two_model_owners_initialize_and_share_persistent_cache(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from jp_overlay.translation_cache import TranslationCache

    start = threading.Barrier(2)
    path = tmp_path / "new-cache.sqlite3"

    def write(key):
        start.wait(2)
        cache = TranslationCache(path)
        try:
            cache.put(key, key + " English")
            assert not cache.warning
        finally:
            cache.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(write, key) for key in ("local-a", "local-b")]
        for future in futures:
            future.result(3)
    cache = TranslationCache(path)
    try:
        assert cache.get("local-a") == "local-a English"
        assert cache.get("local-b") == "local-b English"
        assert not cache.warning
    finally:
        cache.close()
