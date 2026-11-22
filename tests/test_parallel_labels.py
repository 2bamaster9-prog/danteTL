import threading
from concurrent.futures import Future

import pytest

from dantetl.languages.target import ENGLISH, TARGET_LANGUAGES
from dantetl.translation.cache import TranslationCache, translation_key
from dantetl.translation.worker import TranslationSession
from tests.test_concurrent_translation import block, stop, until


class Model:
    batch_size = 1
    cache_identity = "parallel-label-fixture"

    def __init__(self):
        self.decoder = Decoder()
        self.individual = []

    def prepare_labels(self, target):
        self.preparations += 1
        return self.decoder

    label_width = 4
    preparations = 0

    def translate(self, texts, *, target=ENGLISH):
        raise AssertionError("Expected contextual calls")

    def translate_with_context(self, text, context, *, target=ENGLISH):
        self.individual.append(text)
        return "Single " + text

    def close(self):
        assert self.decoder.closed


class Decoder:
    width = 4

    def __init__(self):
        self.submitted = {}
        self.started = threading.Event()
        self.resume = threading.Event()
        self.fail = False
        self.closed = False

    def submit(self, source, target):
        future = Future()
        self.submitted[source] = future
        return future

    def step(self):
        self.started.set()
        assert self.resume.wait(3)
        if self.fail:
            raise RuntimeError("Unavailable context")
        source, future = next((s, f) for s, f in self.submitted.items() if not f.done())
        future.set_result(({source: "Label " + source[0]}, {}))

    def reset(self):
        for future in self.submitted.values():
            future.cancel()

    def close(self):
        self.closed = True


def test_cache_first_independent_labels_revalidate_between_tokens(tmp_path):
    path = tmp_path / "cache"
    model = Model()
    cache = TranslationCache(path)
    cache.put(translation_key(model.cache_identity, "既知"), "Known")
    cache.close()
    session = TranslationSession(lambda: model, path)
    known = block(1, "既知")
    original = tuple(block(i, f"項目{i}") for i in range(2, 6))
    revision = block(2, "修正")
    dialogue = block(6, "会話", dialogue=True)
    session.start()
    try:
        session.update((known, *original))
        assert model.decoder.started.wait(3)
        assert [v.english for v in session.snapshot().results] == ["Known"]
        session.update((known, revision, *original[1:], dialogue))
        model.decoder.resume.set()
        until(lambda: session.snapshot().pending == 0)
        results = {v.request.source: v.english for v in session.snapshot().results}
        assert original[0].text not in results
        assert all(results[b.text] == "Label " + b.text for b in original[1:])
        assert results[dialogue.text] == "Single " + dialogue.text
        assert results[revision.text].endswith(revision.text)
        cache = TranslationCache(path)
        try:
            assert cache.get(translation_key(model.cache_identity, original[0].text)) is None
        finally:
            cache.close()
    finally:
        model.decoder.resume.set()
        stop(session)


@pytest.mark.parametrize("fail", [False, True])
def test_sparse_work_and_recovery_use_the_same_loaded_model(tmp_path, fail):
    model = Model()
    session = TranslationSession(lambda: model, tmp_path / "cache")
    session.start()
    try:
        session.update((block(1, "単独"),))
        until(lambda: session.snapshot().pending == 0)
        assert model.individual == ["単独"]
        assert model.preparations == 0
        menu = tuple(block(i, f"画面{i}") for i in range(4))
        model.decoder.fail = fail
        model.decoder.resume.set()
        session.update(menu)
        until(lambda: session.snapshot().pending == 0)
        prefix = "Single " if fail else "Label "
        assert {v.english for v in session.snapshot().results} == {prefix + b.text for b in menu}
        assert model.decoder.closed == fail
        assert model.preparations == 1
    finally:
        stop(session)


def test_target_switch_during_decode_cancels_old_peers_and_skips_old_cache(tmp_path):
    model = Model()
    path = tmp_path / "cache"
    session = TranslationSession(lambda: model, path)
    menu = tuple(block(i, f"旧画面{i}") for i in range(4))
    session.start()
    try:
        session.update(menu)
        assert model.decoder.started.wait(3)
        old = tuple(model.decoder.submitted.values())
        target = TARGET_LANGUAGES["pt-PT"]
        session.update((block(9, "次の画面"),), target=target)
        model.decoder.resume.set()
        until(lambda: session.snapshot().pending == 0)
        assert [r.target for r in session.snapshot().results] == [target]
        assert all(f.cancelled() for f in old[1:])
        cache = TranslationCache(path)
        try:
            assert all(
                cache.get(translation_key(model.cache_identity, b.text)) is None for b in menu
            )
        finally:
            cache.close()
    finally:
        model.decoder.resume.set()
        stop(session)
