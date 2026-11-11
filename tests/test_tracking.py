from dataclasses import replace

import pytest

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.recognition import OcrResult, TextCharacter, TextRegion
from jp_overlay.tracking import TextTrack, TextTracker, TrackingPolicy


def region(
    text: str = "新しい冒険が、ここから始まる。",
    x: int = 100,
    y: int = 700,
    width: int = 400,
    height: int = 40,
    vertical: bool = False,
) -> TextRegion:
    return TextRegion(text, Rect(x, y, width, height), vertical=vertical)


class Replay:
    def __init__(self, policy: TrackingPolicy | None = None) -> None:
        self.tracker = TextTracker(policy or TrackingPolicy())
        self.sequence = 0
        self.now = 0.0
        self.ids: tuple[int | None, ...] = ()
        self.result: OcrResult | None = None

    def step(self, *regions: TextRegion, dt: float = 0.25) -> tuple[TextTrack, ...]:
        self.sequence += 1
        self.now += dt
        bounds = Rect(0, 0, 1920, 1080)
        frame = CapturedFrame(
            self.sequence, self.now, WindowGeometry(bounds, bounds, bounds, 144), b""
        )
        self.result = OcrResult(frame, regions, 20, self.now + 0.02)
        self.ids = self.tracker.observe(self.result)
        return self.tracker.visible(frame, self.now + 0.02)


def test_jitter_and_character_score_changes_keep_exact_display_objects() -> None:
    replay = Replay()
    original = replay.step(region())
    for offset in (2, -3, 5, -4, 0, 7, -6) * 5:
        noisy = replace(
            region(x=100 + offset),
            characters=(
                TextCharacter("新", Rect(100 + offset, 700, 20, 40), 0.7 + abs(offset) / 100),
            ),
        )
        current = replay.step(noisy)
        assert current == original
        assert current[0] is original[0]


def test_small_persistent_move_confirms_once_and_slow_drift_cannot_accumulate_unseen() -> None:
    replay = Replay()
    original = replay.step(region())[0]
    assert replay.step(region(x=110))[0] is original  # outside the 8 px deadband
    moved = replay.step(region(x=111))[0]
    assert moved.track_id == original.track_id and moved.bounds.x == 111
    assert moved.text_revision == original.text_revision
    for x in range(112, 131):
        moved = replay.step(region(x=x))[0]
    assert moved.bounds.x >= 120


def test_large_move_follows_immediately_without_changing_identity() -> None:
    replay = Replay()
    original = replay.step(region())[0]
    moved = replay.step(region(x=160, y=720))[0]
    assert moved.track_id == original.track_id
    assert moved.bounds == Rect(160, 720, 400, 40)


def test_one_bad_crop_does_not_resize_display_but_persistent_resize_commits() -> None:
    replay = Replay()
    original = replay.step(region())[0]
    assert replay.step(region(width=500))[0] is original
    assert replay.step(region())[0] is original
    assert replay.step(region(width=500))[0] is original
    assert replay.step(region(width=500))[0].bounds.width == 500


def test_fuzzy_single_frame_error_is_ignored_but_persistent_change_gets_one_revision() -> None:
    replay = Replay()
    original = replay.step(region())[0]
    typo = "新しい冒険が、ここから始まろ。"
    assert replay.step(region(typo))[0] is original
    assert replay.step(region())[0] is original
    assert replay.step(region(typo))[0] is original
    updated = replay.step(region(typo))[0]
    assert updated.track_id == original.track_id
    assert updated.text == typo and updated.text_revision == 2
    assert replay.step(region(typo))[0] is updated


@pytest.mark.parametrize("old,new", [("はい", "いいえ"), ("HP 100", "HP 101"), ("猫", "犬")])
def test_meaningful_short_edits_are_confirmed_not_hidden_as_fuzzy_matches(old, new) -> None:
    replay = Replay()
    original = replay.step(region(old))[0]
    assert replay.step(region(new))[0] is original
    updated = replay.step(region(new))[0]
    assert updated.track_id == original.track_id
    assert updated.text == new and updated.text_revision == 2


def test_width_and_whitespace_normalization_do_not_revise_raw_display_text() -> None:
    replay = Replay()
    original = replay.step(region("準備はいい？"))[0]
    assert replay.step(region("準備 は いい?"))[0] is original
    assert replay.step(region("準備 は いい?"))[0] is original


def test_typewriter_prefix_growth_is_same_track_but_text_waits_until_stable() -> None:
    replay = Replay()
    original = replay.step(region("新しい冒険", width=100))[0]
    typing = replay.step(region("新しい冒険が始まる", width=210))[0]
    assert typing.track_id == original.track_id and typing.text == original.text
    finished = replay.step(region("新しい冒険が始まる", width=210))[0]
    assert finished.text == "新しい冒険が始まる"
    assert finished.text_revision == 2


def test_reordered_duplicate_labels_and_new_detection_keep_existing_ids() -> None:
    replay = Replay()
    original = replay.step(region("はい", y=200), region("はい", y=400))
    current = replay.step(region("設定", y=50), region("はい", y=402), region("はい", y=199))
    assert replay.ids == (3, 2, 1)
    assert current[:2] == original
    assert len({track.track_id for track in current}) == 3


def test_same_text_far_away_does_not_steal_old_identity() -> None:
    replay = Replay()
    first = replay.step(region())[0]
    current = replay.step(region(x=1100, y=100))
    assert replay.ids == (first.track_id + 1,)
    assert len(current) == 2  # Old region has one-frame dropout grace.
    assert len(replay.step(region(x=1100, y=100))) == 1


def test_one_missed_detection_or_empty_recognition_does_not_blink() -> None:
    replay = Replay()
    original = replay.step(region())
    assert replay.step(region("")) == original
    assert replay.ids == (None,)
    assert replay.step(region()) == original
    assert replay.step() == original
    assert replay.step() == ()
    assert replay.step(region())[0].track_id != original[0].track_id


def test_static_frame_survives_but_stalled_ocr_on_advancing_capture_expires() -> None:
    replay = Replay()
    original = replay.step(region())
    assert replay.result is not None
    source = replay.result.frame
    assert replay.tracker.visible(source, 100) == original
    advanced = replace(source, sequence=source.sequence + 1, captured_at=1)
    assert replay.tracker.visible(advanced, 1.1) == ()


def test_duplicate_or_out_of_order_results_cannot_confirm_a_text_change() -> None:
    replay = Replay()
    original = replay.step(region("猫"))
    old = replay.result
    replay.step(region("犬"))
    result = replay.result
    assert result is not None and old is not None
    for _ in range(20):
        replay.tracker.observe(result)
        replay.tracker.observe(old)
    assert replay.tracker.visible(result.frame, replay.now) == original
    assert replay.step(region("犬"))[0].text == "犬"


def test_reset_and_resize_clear_state_without_reusing_ids() -> None:
    replay = Replay()
    original = replay.step(region())[0]
    assert replay.result is not None
    resized = replace(
        replay.result.frame,
        geometry=replace(replay.result.frame.geometry, client=Rect(0, 0, 1280, 720)),
    )
    assert replay.tracker.visible(resized, replay.now) == ()
    second = replay.step(region())[0]
    assert second.track_id > original.track_id
    replay.tracker.reset()
    assert replay.step(region())[0].track_id > second.track_id


def test_scene_replacement_drops_missing_tracks_and_track_count_is_bounded() -> None:
    replay = Replay(TrackingPolicy(max_tracks=4))
    assert len(replay.step(*(region(str(i), y=i * 80) for i in range(8)))) == 4
    # Expired tracks must not crowd out fresh observations indefinitely.
    current = replay.step(region("別の場面", y=900), dt=1)
    assert len(current) == 1 and current[0].text == "別の場面"


def test_vertical_text_uses_its_width_for_jitter_tolerance() -> None:
    replay = Replay()
    original = replay.step(region("日本語", y=100, width=40, height=400, vertical=True))
    assert (
        replay.step(region("日本語", x=104, y=102, width=40, height=400, vertical=True)) == original
    )


def test_static_window_keeps_identity_when_capture_eventually_resumes() -> None:
    replay = Replay()
    original = replay.step(region())
    assert replay.result is not None
    assert replay.tracker.visible(replay.result.frame, 10) == original
    assert replay.step(region(x=102), dt=10) == original


def test_final_static_edit_settles_without_a_second_capture_frame() -> None:
    replay = Replay()
    original = replay.step(region("猫"))[0]
    replay.step(region("犬", width=420))
    assert replay.result is not None
    assert replay.tracker.visible(replay.result.frame, replay.now + 0.3)[0] is original
    settled = replay.tracker.visible(replay.result.frame, replay.now + 0.4)[0]
    assert settled.track_id == original.track_id
    assert settled.text == "犬" and settled.text_revision == 2
    assert settled.bounds.width == 420
    assert replay.tracker.visible(replay.result.frame, replay.now + 5)[0] is settled


def test_pending_edit_does_not_settle_on_unprocessed_advancing_capture() -> None:
    replay = Replay()
    original = replay.step(region("猫"))[0]
    replay.step(region("犬"))
    assert replay.result is not None
    advanced = replace(replay.result.frame, sequence=replay.sequence + 1)
    assert replay.tracker.visible(advanced, replay.now + 0.4)[0] is original


def test_long_gap_cannot_confirm_an_old_pending_candidate() -> None:
    replay = Replay()
    original = replay.step(region("猫"))[0]
    replay.step(region("犬"))
    assert replay.step(region("犬"), dt=10)[0] is original
    assert replay.step(region("犬"))[0].text == "犬"


def test_translation_waits_for_confirmation_and_preserves_committed_content_through_noise() -> None:
    replay = Replay()
    replay.step(region("新しい冒険"))
    assert replay.result is not None
    assert replay.tracker.translation_tracks(replay.result.frame, replay.now + 0.1) == ()
    stable = replay.step(region("新しい冒険"))
    assert replay.result is not None
    assert replay.tracker.translation_tracks(replay.result.frame, replay.now) == stable
    replay.step(region("新しい冒険が始まる"))
    assert replay.result is not None
    assert replay.tracker.translation_tracks(replay.result.frame, replay.now) == stable
    settled = replay.tracker.translation_tracks(replay.result.frame, replay.now + 0.4)
    assert settled[0].text == "新しい冒険が始まる"
    replay.step()
    assert replay.result is not None
    assert replay.tracker.translation_tracks(replay.result.frame, replay.now) == settled
    replay.step()
    assert replay.result is not None
    assert replay.tracker.translation_tracks(replay.result.frame, replay.now) == ()
