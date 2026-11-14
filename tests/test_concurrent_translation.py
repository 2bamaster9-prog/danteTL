import time
from concurrent.futures import Future

from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslationSession
from jp_overlay.translation_cache import TranslationCache, translation_key


class Deferred:
    cache_identity = "controlled-concurrent-fixture"
    batch_size = 1
    max_in_flight = 2

    def __init__(self):
        self.calls = []
        self.closed = False

    def translate(self, texts):
        raise AssertionError("Must use deferred submission")

    def translate_with_context(self, text, context):
        raise AssertionError("Must use deferred submission")

    def submit_translation(self, sources):
        future = Future()
        self.calls.append((sources[0], future))
        return future

    def cancel_pending(self):
        for _, future in self.calls:
            future.cancel()

    def close(self):
        self.cancel_pending()
        self.closed = True

    def finish(self, index):
        source, future = self.calls[index]
        future.set_result(({source: "English: " + source[0]}, {}))


def until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.005)


def block(key, text, *, dialogue=False):
    return TextBlock((TextTrack(key, text, Rect(20, key * 50, 300, 30)),), dialogue=dialogue)


def stop(session):
    session.request_stop()
    until(lambda: session.finished)


def test_independent_answers_publish_out_of_order_with_two_slots_cache_and_source_dedup(tmp_path):
    backend = Deferred()
    path = tmp_path / "cache"
    cache = TranslationCache(path)
    cache.put(translation_key(backend.cache_identity, "設定"), "Settings")
    cache.close()
    session = TranslationSession(lambda: backend, path)
    session.start()
    try:
        items = (block(1, "攻撃力"), block(2, "会心率"), block(3, "防御力"), block(4, "会心率"))
        session.update(items)
        until(lambda: len(backend.calls) == 2)
        session.update((*items, block(5, "設定")))
        until(lambda: len(session.snapshot().results) == 1)
        assert len(backend.calls) == 2
        backend.finish(1)
        until(lambda: len(session.snapshot().results) == 3)
        until(lambda: len(backend.calls) == 3)
        # The slow first term does not block the second term or its duplicate's cache hit.
        assert {r.request.track_id for r in session.snapshot().results} == {2, 4, 5}
        snapshot = session.snapshot().results
        for _ in range(20):
            session.update((*items, block(5, "設定")))
            assert session.snapshot().results == snapshot
        backend.finish(0)
        backend.finish(2)
        until(lambda: len(session.snapshot().results) == 5)
        assert len(backend.calls) == 3
    finally:
        stop(session)
    assert backend.closed


def test_dialogue_is_serial_but_does_not_block_an_independent_menu(tmp_path):
    backend = Deferred()
    session = TranslationSession(lambda: backend, tmp_path / "cache")
    session.start()
    try:
        session.update(
            (
                block(1, "最初の会話です。", dialogue=True),
                block(2, "次の会話です。", dialogue=True),
                block(3, "設定"),
            )
        )
        until(lambda: len(backend.calls) == 2)
        assert [source[0] for source, _ in backend.calls] == ["最初の会話です。", "設定"]
        backend.finish(1)
        until(lambda: len(session.snapshot().results) == 1)
        assert len(backend.calls) == 2
        backend.finish(0)
        until(lambda: len(backend.calls) == 3)
        assert backend.calls[2][0][0] == "次の会話です。"
        backend.finish(2)
        until(lambda: len(session.snapshot().results) == 3)
    finally:
        stop(session)


def test_swap_cancels_every_inflight_request_and_never_reuses_old_english(tmp_path):
    old, new = Deferred(), Deferred()
    new.cache_identity = "replacement"
    session = TranslationSession(lambda: old, tmp_path / "cache")
    session.start()
    try:
        session.update((block(1, "攻撃力"), block(2, "会心率")))
        until(lambda: len(old.calls) == 2)
        session.switch_backend(lambda: new)
        until(lambda: len(new.calls) == 2)
        assert old.closed and all(f.cancelled() for _, f in old.calls)
        assert not session.snapshot().results
        new.finish(1)
        until(lambda: len(session.snapshot().results) == 1)
        session.invalidate()
        until(lambda: new.calls[0][1].cancelled())
        assert not session.snapshot().results
    finally:
        stop(session)
