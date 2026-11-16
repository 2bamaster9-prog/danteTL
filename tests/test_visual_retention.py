"""Replay stationary character-screen labels with hostile OCR, not just clean demos."""

from dataclasses import replace

import cv2
import numpy as np
import pytest

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.tracking import TextTrack, TextTracker
from dantejp.ocr.visual import VisualAnalyzer
from dantejp.ocr.worker import OcrResult, TextCharacter, TextRegion
from dantejp.translation.grouping import DialogueGrouper, TextBlock
from dantejp.translation.presentation import EnglishPresentation
from dantejp.translation.worker import TranslatedText, TranslationRequest

BOX = Rect(20, 30, 220, 28)


def picture(sequence, text="HP 3204", *, stars=True, gone=False, extension=False):
    rng = np.random.default_rng(sequence)
    gray = (
        rng.integers(10, 90, (180, 400), dtype=np.uint8)
        if stars
        else np.full((180, 400), 30, np.uint8)
    )
    if not gone:
        cv2.putText(gray, text, (20, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 235, 2, cv2.LINE_AA)
    if extension:
        cv2.putText(gray, "MORE", (245, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 235, 2, cv2.LINE_AA)
    # Always animate the rest of the screen, even when local text does not change.
    gray[100:, :] = sequence * 13 % 200
    size = Rect(0, 0, 400, 180)
    return CapturedFrame(
        sequence,
        sequence * 0.25,
        WindowGeometry(size, size, size, 96),
        cv2.cvtColor(gray, cv2.COLOR_GRAY2BGRA).tobytes(),
    )


def result(sequence, text="攻撃力", score=0.96, **kwargs):
    frame = picture(sequence, **kwargs)
    return OcrResult(
        frame,
        (TextRegion(text, BOX, (TextCharacter(text, BOX, score),)),),
        250,
        frame.captured_at + 0.25,
    )


class Replay:
    def __init__(self, first):
        self.visual = VisualAnalyzer()
        self.tracker = TextTracker()
        self.result = first
        self.ids = self.tracker.observe(first)
        self.tracks = self.tracker.translation_tracks(first.frame, first.completed_at + 0.5)
        self.visual.observe(first.frame, first, self.tracks, self.ids, candidate=first)

    def step(self, incoming):
        state = self.visual.observe(
            incoming.frame,
            self.result,
            self.tracks,
            self.ids,
            self.tracker.translation_activity(),
            incoming,
        )
        self.ids = self.tracker.observe(
            incoming,
            unchanged=state.unchanged,
            visual_checked=state.checked,
            checked_sequence=state.checked_sequence,
            visually_absent=state.absent,
            visual_sequence=incoming.frame.sequence,
        )
        self.tracks = self.tracker.translation_tracks(incoming.frame, incoming.completed_at + 0.5)
        self.result = incoming
        self.visual.observe(
            incoming.frame,
            incoming,
            self.tracks,
            self.ids,
            self.tracker.translation_activity(),
            incoming,
        )
        return state


def test_stationary_labels_keep_exact_identity_layout_and_english_through_noisy_ocr():
    replay = Replay(result(1))
    original = replay.tracks
    presentation, grouper = EnglishPresentation(), DialogueGrouper()
    block = TextBlock(original)
    english = TranslatedText(TranslationRequest.from_block(block), "Attack")
    assert presentation.update((block,), (english,))
    for sequence in range(2, 40):
        incoming = result(sequence, text=("攻撃力", "防御力", "攻擊力")[sequence % 3], score=0.99)
        if sequence % 4 == 0:
            incoming = replace(incoming, regions=())
        elif sequence % 3 == 0:
            jittered = Rect(10, 28, 245, 32)
            raw = incoming.regions[0]
            incoming = replace(
                incoming,
                regions=(
                    replace(
                        raw, bounds=jittered, characters=(TextCharacter(raw.text, jittered, 0.99),)
                    ),
                ),
            )
        state = replay.step(incoming)
        assert state.unchanged == set(original)
        assert not state.hidden
        assert replay.tracks == original
        grouped = grouper.update(
            replay.tracks,
            replay.tracks,
            incoming.completed_at,
            activity=replay.tracker.translation_activity(),
        )
        published = presentation.update(grouped.blocks, (), replay.tracker.display_predecessors())
        assert len(published) == 1 and published[0].translation == english


def test_low_confidence_reviews_are_bounded_monotonic_and_keep_geometry():
    replay = Replay(result(1, score=0.60))
    original_bounds = replay.tracks[0].bounds
    for sequence, text, score in (
        (2, "攻擊力", 0.70),
        (3, "攻撃力", 0.65),
        (4, "攻撃カ", 0.80),
        (5, "攻撃力", 0.99),
    ):
        replay.step(result(sequence, text=text, score=score))
        assert replay.tracks[0].bounds == original_bounds
    assert replay.tracks[0].text == "攻撃カ"  # Three reviews consumed; no endless score chasing.
    # A genuine local edit starts a new content lifetime, regardless of the old score.
    for sequence in (6, 7):
        replay.step(result(sequence, text="防御力", score=0.50, gone=True))
    assert replay.tracks[0].text == "防御力"


@pytest.mark.parametrize("text", ["HP 3205", "HP 3201", "HP 320", "HP 9204"])
def test_one_changed_digit_unlocks_a_long_otherwise_unchanged_label(text):
    replay = Replay(result(1, text="体力3204"))
    incoming = result(2, text="体力3205")
    incoming = replace(incoming, frame=picture(2, text=text))
    state = replay.step(incoming)
    assert not state.unchanged
    assert state.checked
    assert replay.tracks[0].text == "体力3205"


def test_extension_outside_old_box_unlocks_typewriter_growth():
    replay = Replay(result(1, text="冒険の始まり"))
    state = replay.step(result(2, text="冒険の始まりです", extension=True))
    assert not state.unchanged
    assert replay.tracks[0].text == "冒険の始まりです"


def test_dim_stars_appearing_beside_text_are_not_a_typewriter_extension():
    replay = Replay(result(1, stars=False))
    incoming = result(2, stars=False, text="全く違う読み方")
    pixels = np.frombuffer(incoming.frame.bgra, np.uint8).reshape(180, 400, 4).copy()
    for x in range(244, 316, 9):
        cv2.rectangle(pixels, (x, 34), (x + 3, 42), (100, 100, 100, 255), 1)
    incoming = replace(incoming, frame=replace(incoming.frame, bgra=pixels.tobytes()))
    state = replay.step(incoming)
    assert state.unchanged
    assert replay.tracks[0].text == "攻撃力"


def test_large_reveal_after_one_glyph_is_not_mistaken_for_unchanged_content():
    box = Rect(20, 30, 20, 28)
    first = result(1, text="新", stars=False)
    first = replace(
        first, frame=picture(1, text="H", stars=False), regions=(TextRegion("新", box),)
    )
    replay = Replay(first)
    full = result(2, text="新しい文章です", stars=False)
    full = replace(full, frame=picture(2, text="HMMMMMMMMM", stars=False))
    state = replay.step(full)
    assert state.checked and not state.unchanged


def test_real_removal_still_hides_and_retires_after_visual_and_ocr_evidence():
    replay = Replay(result(1))
    for sequence in (2, 3):
        missing = replace(result(sequence, gone=True), regions=())
        state = replay.step(missing)
    assert state.hidden or not replay.tracks
    assert not replay.tracks


def test_atomic_correction_publication_requires_explicit_current_lineage_and_all_members():
    store = EnglishPresentation()
    first = TextTrack(1, "初めの文章", BOX)
    second = TextTrack(2, "次の行です。", Rect(20, 65, 220, 28))
    old = TextBlock((first, second))
    english = TranslatedText(TranslationRequest.from_block(old), "Original complete sentence.")
    store.update((old,), (english,))
    correction = replace(second, text="次の行でした。", text_revision=2)
    current = TextBlock((first, correction))
    kept = store.update((current,), (), ((correction, second),))
    assert kept[0].painted == old and kept[0].translation == english
    next_correction = replace(correction, text="次の行でした！", text_revision=3)
    final = TextBlock((first, next_correction))
    assert store.update((final,), (), ((next_correction, correction),))[0].translation == english
    replacement = TranslatedText(
        TranslationRequest.from_block(final), "Corrected complete sentence."
    )
    assert store.update((final,), (replacement,))[0].translation == replacement
    changed = TextBlock((replace(first, text="違う文章", text_revision=2), next_correction))
    assert not store.update((changed,), ())  # No permission to bridge a real edit.
    store.update((old,), (english,))
    assert not store.update((), ())
    assert not store.update((old,), ())  # Removed entries cannot resurrect old English.
    store.update((old,), (english,))
    store.reset()
    assert not store.update((old,), ())


def test_publication_retention_cannot_cross_backend_generations_or_worker_restarts():
    store = EnglishPresentation()
    block = TextBlock((TextTrack(1, "設定", BOX),))
    old = TranslatedText(TranslationRequest.from_block(block), "E4B fixture settings")
    store.update((block,), (old,), scope=("worker1", 0))
    assert store.update((block,), (), scope=("worker1", 0))[0].translation == old
    assert not store.update((block,), (), scope=("worker1", 1))
    new = replace(old, english="Gemma settings")
    assert store.update((block,), (new,), scope=("worker1", 1))[0].translation == new
    assert not store.update((block,), (), scope=("worker2", 0))


def test_stale_visual_evidence_cannot_lock_new_source_or_a_new_revision():
    tracker = TextTracker()
    first = result(1)
    tracker.observe(first)
    old = tracker.visible(first.frame, 1)[0]
    edit = result(2, text="防御力", gone=True)
    tracker.observe(
        edit, unchanged=frozenset((old,)), visual_checked=frozenset((old,)), checked_sequence=1
    )
    assert tracker.visible(edit.frame, 2)[0].text == "防御力"


def faint_result(sequence, *, text="HP 3204", gone=False, extension=False, noise=False):
    y, x = np.mgrid[:180, :400]
    gray = 204 + 12 * np.sin((x + sequence * 7) / 60) + 2 * np.cos((y + sequence) / 17)
    mask = np.zeros((180, 400), np.uint8)
    if not gone:
        cv2.putText(mask, text, (20, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2, cv2.LINE_AA)
    if extension:
        cv2.putText(mask, "MORE", (245, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.8, 255, 2, cv2.LINE_AA)
    gray += (235 - gray) * (mask / 255) * 0.8
    if noise:
        gray += np.random.default_rng(sequence).uniform(-0.4, 0.4, gray.shape)
    original = result(sequence)
    return replace(
        original,
        frame=replace(
            original.frame, bgra=cv2.cvtColor(gray.astype(np.uint8), cv2.COLOR_GRAY2BGRA).tobytes()
        ),
    )


@pytest.mark.parametrize("noise", [False, True])
def test_faint_stationary_text_retains_exact_english_over_moving_light(noise):
    replay = Replay(faint_result(1, noise=noise))
    original = replay.tracks
    presentation, grouper = EnglishPresentation(), DialogueGrouper()
    block = TextBlock(original)
    english = TranslatedText(TranslationRequest.from_block(block), "Attack")
    presentation.update((block,), (english,))
    for sequence in range(2, 40):
        incoming = faint_result(sequence, noise=noise)
        raw = incoming.regions[0]
        incoming = replace(
            incoming, regions=(replace(raw, text="誤った観測"),) if sequence % 4 else ()
        )
        state = replay.step(incoming)
        assert state.unchanged == set(original)
        assert not state.hidden
        assert replay.tracks == original
        grouped = grouper.update(
            replay.tracks,
            replay.tracks,
            incoming.completed_at,
            activity=replay.tracker.translation_activity(),
        )
        painted = presentation.update(grouped.blocks, (), replay.tracker.display_predecessors())
        assert len(painted) == 1 and painted[0].translation == english


@pytest.mark.parametrize("text", ["HP 3205", "HP 3201", "HP 320", "HP 9204"])
def test_faint_real_digit_changes_are_not_frozen(text):
    replay = Replay(faint_result(1))
    incoming = faint_result(2, text=text)
    incoming = replace(incoming, regions=(replace(incoming.regions[0], text="防御力"),))
    assert not replay.step(incoming).unchanged
    assert replay.tracks[0].text == "防御力"


def test_faint_extension_unlocks_and_real_removal_retires():
    replay = Replay(faint_result(1))
    incoming = faint_result(2, extension=True)
    incoming = replace(incoming, regions=(replace(incoming.regions[0], text="攻撃力を強化"),))
    assert not replay.step(incoming).unchanged
    assert replay.tracks[0].text == "攻撃力を強化"
    for sequence in range(3, 7):
        state = replay.step(replace(faint_result(sequence, gone=True), regions=()))
        assert not state.unchanged
    assert not replay.tracks


@pytest.mark.parametrize("score", [0.55, 0.96])
def test_detector_splits_cannot_duplicate_or_truncate_visually_unchanged_line(score):
    replay = Replay(result(1, text="新しい冒険が始まります", score=score))
    original = replay.tracks
    first, last = Rect(20, 30, 175, 28), Rect(198, 30, 42, 28)
    for sequence in range(2, 10):
        pieces = (
            TextRegion("新しい冒険が", first, (TextCharacter("新しい冒険が", first, 0.99),)),
            TextRegion("始まります", last, (TextCharacter("始まります", last, 0.99),)),
        )
        incoming = replace(result(sequence), regions=pieces if sequence % 2 else pieces[::-1])
        assert replay.step(incoming).unchanged == set(original)
        assert replay.tracks == original
        assert sum(key is not None for key in replay.ids) == 1


def test_fragment_suppression_needs_current_visual_proof_and_allows_outside_content():
    first = result(1, text="新しい冒険が始まります")
    tracker = TextTracker()
    tracker.observe(first)
    track = tracker.translation_tracks(first.frame, 1)[0]
    pieces = (
        TextRegion("新しい冒険が", Rect(20, 30, 105, 28)),
        TextRegion("始まります", Rect(130, 30, 110, 28)),
        TextRegion("設定", Rect(280, 100, 60, 28)),
    )
    incoming = replace(result(2), regions=pieces)
    # Evidence from another source cannot suppress new text tracks.
    assignments = tracker.observe(
        incoming,
        unchanged=frozenset((track,)),
        visual_checked=frozenset((track,)),
        checked_sequence=1,
    )
    assert all(key is not None for key in assignments)
    replay = Replay(first)
    replay.step(incoming)
    assert replay.tracks[0] == track
    assert {t.text for t in replay.tracks} == {track.text, "設定"}
