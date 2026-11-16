"""Acceptance/counterexample replays for an experiment that is not wired into tracking."""

from dataclasses import replace

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.tracking import TextTrack, TextTracker
from dantejp.ocr.worker import OcrResult, TextCharacter, TextRegion
from tools.ocr_consensus_experiment import EvidenceWindow, Reading

BOX = Rect(100, 100, 500, 30)
OLD = "東門で仲間を待ってください。"
NEW = "西門で仲間を待ってください。"
NOISY = "西門で仲間を待ってくだきい。"


def reading(sequence, text=NEW):
    return Reading(sequence, sequence / 4, text, BOX, 0.8)


def test_alternating_shared_edit_reproduces_live_fallback_and_proposes_observed_reading():
    tracker = TextTracker()
    experiment = EvidenceWindow()
    bounds = Rect(0, 0, 1000, 600)
    accepted = TextTrack(1, OLD, BOX)
    proposals = []
    for sequence in range(1, 23):
        text = OLD if sequence < 3 else (NEW if sequence % 2 else NOISY)
        score = 0.95 if sequence < 3 else 0.8
        region = TextRegion(text, BOX, tuple(TextCharacter(c, BOX, score) for c in text))
        frame = CapturedFrame(
            sequence, sequence / 4, WindowGeometry(bounds, bounds, bounds, 96), b""
        )
        tracker.observe(OcrResult(frame, (region,), 10, sequence / 4))
        (live,) = tracker.visible(frame, sequence / 4)
        assert live.text == OLD and live.text_revision == 1
        if sequence >= 3:
            proposal = experiment.observe(accepted, reading(sequence, text))
            if proposal:
                proposals.append(proposal)
    assert proposals and proposals[0].reading.text == NEW
    assert proposals[0].supported_edits == ((0, 1, "西"),)
    assert proposals[0].unresolved_edits == 0


def test_noise_mixed_with_winner_and_typewriter_growth_do_not_build_consensus():
    accepted = TextTrack(1, OLD, BOX)
    for variants in ((OLD, NEW), (NEW, OLD.replace("東", "南")), (OLD + "はい", OLD + "はい。")):
        experiment = EvidenceWindow()
        for i in range(20):
            assert experiment.observe(accepted, reading(i, variants[i % 2])) is None


def test_misses_duplicates_unscanned_frames_resets_and_stale_geometry_do_not_supply_votes():
    accepted = TextTrack(1, OLD, BOX)
    owner = EvidenceWindow()
    for _ in range(20):
        assert owner.observe(accepted, reading(1)) is None
    for i in range(2, 10):
        assert owner.observe(accepted, reading(i), covered=False) is None
    assert owner.observe(accepted, None) is None
    for i in range(10, 14):
        assert owner.observe(accepted, reading(i)) is None
    owner.reset()
    for i in range(14, 18):
        assert owner.observe(accepted, reading(i)) is None
    for i in range(18, 24):
        assert owner.observe(accepted, replace(reading(i), bounds=Rect(600, 100, 300, 30))) is None
    for i in range(24, 28):
        assert owner.observe(replace(accepted, text_revision=2), reading(i)) is None


def test_unchanged_pixels_veto_systematic_noise_but_unknown_pixels_are_a_counterexample():
    accepted = TextTrack(1, OLD, BOX)
    protected, unknown = EvidenceWindow(), EvidenceWindow()
    proposed = None
    # The actual text stays EAST. A correlated recognizer error repeatedly says WEST.
    # These readings are indistinguishable from a real edit without independent evidence.
    for i in range(20):
        assert protected.observe(accepted, reading(i), visual="same") is None
        proposed = unknown.observe(accepted, reading(i)) or proposed
    assert proposed is not None and proposed.reading.text == NEW  # Known false proposal.


def test_actual_reading_provenance_insertions_numeric_and_negation_edits():
    for old, new in (
        ("残りは100個です。", "残りは101個です。"),
        ("私は彼を信じている。", "私は彼を信じていない。"),
        ("明日の門で待ちます。", "明日の西門で待ちます。"),
    ):
        owner = EvidenceWindow()
        accepted = TextTrack(1, old, BOX)
        samples = [reading(i, new) for i in range(8)]
        proposals = [owner.observe(accepted, sample) for sample in samples]
        assert proposals[-1] and proposals[-1].reading in samples
        assert proposals[-1].reading.text == new


def test_long_inputs_are_bounded_and_processing_time_does_not_erase_observations():
    owner, accepted = EvidenceWindow(), TextTrack(1, OLD, BOX)
    proposals = [owner.observe(accepted, replace(reading(i), captured_at=i * 3)) for i in range(8)]
    assert proposals[-1] and proposals[-1].reading.text == NEW
    for i in range(8, 20):
        assert owner.observe(accepted, replace(reading(i, "文" * 2000), captured_at=i * 3)) is None


def test_slow_workers_can_accumulate_evidence_but_a_return_to_old_text_cancels_it():
    owner, accepted = EvidenceWindow(), TextTrack(1, OLD, BOX)
    proposals = []
    for i in range(20):
        proposals.append(owner.observe(accepted, replace(reading(i), captured_at=i * 0.9)))
    assert proposals[-1] and proposals[-1].reading.text == NEW
    assert owner.observe(accepted, replace(reading(20, OLD), captured_at=18)) is None
    for i in range(21, 25):
        assert owner.observe(accepted, replace(reading(i), captured_at=i * 0.9)) is None


def test_same_pixel_evidence_cannot_be_followed_by_an_older_ocr_result():
    owner, accepted = EvidenceWindow(), TextTrack(1, OLD, BOX)
    for i in range(4):
        assert owner.observe(accepted, reading(i)) is None
    assert owner.observe(accepted, reading(20), visual="same") is None
    for i in range(4, 20):
        assert owner.observe(accepted, reading(i)) is None
