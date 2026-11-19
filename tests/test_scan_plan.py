import threading
import time
from dataclasses import replace

import pytest

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.scan_plan import (
    ScanCosts,
    ScanLine,
    ScanPlan,
    ScanPlanner,
    choose_scan,
    preserves_lines,
)
from dantejp.ocr.worker import OcrSession, TextCharacter, TextRegion, recognize_planned

SIZE = (1920, 1080)
COSTS = ScanCosts(40, 30)
AREAS = tuple(Rect(x, y, 320, 108) for y in (100, 270) for x in (100, 470))
LINES = tuple(ScanLine(Rect(a.x + 20, a.y + 25, 220, 30), 0.96) for a in AREAS)


def test_cost_plan_reduces_calls_but_covers_all_original_demand():
    plan = choose_scan(AREAS, SIZE, LINES, COSTS)
    assert plan.changed and plan.areas is not None and len(plan.areas) == 1
    assert all(any(b.contains(a) for b in plan.areas) for a in AREAS)
    assert plan.expected == LINES
    assert plan.estimated_ms <= plan.baseline_ms * 0.85
    for areas in (AREAS[::-1], (AREAS[2], AREAS[0], AREAS[3], AREAS[1])):
        assert choose_scan(areas, SIZE, LINES, COSTS) == plan


def test_vertical_pair_partition_wins_when_horizontal_pairs_shrink_text():
    areas = tuple(Rect(x, y, 260, 100) for y in (100, 280) for x in (100, 1500))
    lines = tuple(ScanLine(Rect(a.x + 20, a.y + 30, 200, 24), 0.98) for a in areas)
    plan = choose_scan(areas, SIZE, lines, COSTS)
    assert plan.changed and plan.areas is not None and len(plan.areas) == 2
    assert tuple(b.size for b in plan.areas) == ((260, 280), (260, 280))
    assert plan.estimated_ms < plan.baseline_ms


def test_large_glyphs_allow_cheaper_full_scan_but_vertical_glyphs_keep_baseline():
    areas = tuple(Rect(x, y, 320, 180) for y in (100, 800) for x in (100, 1400))
    lines = tuple(ScanLine(Rect(a.x + 20, a.y + 30, 200, 100), 0.98) for a in areas)
    plan = choose_scan(areas, SIZE, lines, COSTS)
    assert plan.changed and plan.areas is None and plan.expected == lines
    assert not choose_scan(
        areas, SIZE, tuple(replace(line, vertical=True) for line in lines), COSTS
    ).changed


def test_discovery_empty_single_unknown_and_dense_input_preserve_original_policy():
    assert choose_scan(None, SIZE, LINES, COSTS).areas is None
    assert choose_scan((), SIZE, LINES, COSTS).areas == ()
    assert not choose_scan(AREAS[:1], SIZE, LINES, COSTS).changed
    assert not choose_scan(AREAS, SIZE, (), COSTS).changed
    assert not choose_scan(AREAS, SIZE, LINES[:3], COSTS).changed
    assert not choose_scan(AREAS, SIZE, LINES * 33, COSTS).changed


@pytest.mark.parametrize("confidence", [None, 0.79])
def test_weak_prior_evidence_never_justifies_rescaling(confidence):
    lines = tuple(replace(line, confidence=confidence) for line in LINES)
    assert not choose_scan(AREAS, SIZE, lines, COSTS).changed


def test_tiny_text_stops_merging_and_new_intersected_lines_are_closed():
    tiny = tuple(replace(line, bounds=replace(line.bounds, height=5)) for line in LINES)
    assert not choose_scan(AREAS, SIZE, tiny, COSTS).changed
    between = ScanLine(Rect(350, 200, 200, 30), 0.98)
    plan = choose_scan(AREAS, SIZE, (*LINES, between), COSTS)
    assert plan.changed and between in plan.expected
    assert plan.areas is None or any(b.contains(between.bounds) for b in plan.areas)


def test_guard_checks_orientation_coverage_and_confidence_but_not_prior_text():
    assert preserves_lines(LINES, LINES[::-1])
    assert not preserves_lines(LINES, LINES[:3])
    assert not preserves_lines(LINES, tuple(replace(line, vertical=True) for line in LINES))
    assert not preserves_lines(LINES, tuple(replace(line, confidence=0.7) for line in LINES))
    assert not preserves_lines(
        LINES, tuple(replace(line, bounds=Rect(0, 0, 10, 10)) for line in LINES)
    )


def test_guard_requires_distinct_support_and_finds_a_covering_assignment():
    first = ScanLine(Rect(20, 20, 120, 25), 0.98)
    second = ScanLine(Rect(20, 65, 120, 25), 0.98)
    spanning = ScanLine(Rect(20, 20, 120, 70), 0.98)
    assert not preserves_lines((first, second), (spanning,))
    # Greedily giving the spanning detection to the first line loses the valid
    # assignment: first -> first, second -> spanning. Both orders must succeed.
    assert preserves_lines((first, second), (spanning, first))
    assert preserves_lines((second, first), (first, spanning))
    unrelated = ScanLine(Rect(400, 20, 120, 25), 0.98)
    assert not preserves_lines((first, second), (spanning, unrelated))


def test_guard_reassigns_a_chain_and_rejects_a_shortage_within_one_group():
    lines = tuple(ScanLine(Rect(30 * i, 0, 10, 10), 0.95) for i in range(4))
    bridges = tuple(replace(line, bounds=replace(line.bounds, width=40)) for line in lines[:3])
    # The first three claims must all move to free the only detection for line four.
    assert preserves_lines(lines, (*bridges, lines[0]))
    # All lines have support, but only two detections can cover the first three.
    wide = replace(lines[0], bounds=Rect(0, 0, 70, 10))
    assert not preserves_lines(lines, (wide, wide, lines[3], lines[3]))


def test_guard_keeps_tall_earlier_detection_and_exact_coverage_cutoff():
    line = ScanLine(Rect(0, 100, 20, 10), 0.95)
    tall = ScanLine(Rect(7, 0, 20, 110), 0.85)
    short = ScanLine(Rect(0, 80, 20, 20), 0.95)
    assert preserves_lines((line,), (short, tall))  # Exactly 65% area, at the confidence floor.
    assert not preserves_lines((line,), (short, replace(tall, bounds=Rect(8, 0, 20, 110))))
    assert not preserves_lines((line,), (short, replace(tall, confidence=0.849)))


def test_oversized_detection_retries_original_crops_without_publishing_lost_line():
    viewport = Rect(0, 0, *SIZE)
    frame = CapturedFrame(
        9, 2.5, WindowGeometry(viewport, viewport, viewport, 96), bytes(1920 * 1080 * 4)
    )
    areas = (Rect(100, 100, 200, 80), Rect(100, 200, 200, 80))
    expected = tuple(ScanLine(Rect(a.x + 20, a.y + 20, 150, 30), 0.98) for a in areas)
    plan = ScanPlan((Rect(100, 100, 200, 180),), areas, expected)
    calls = []

    class Engine:
        def recognize(self, source, *, full_size=None):
            calls.append((source.sequence, source.captured_at, source.height))
            box = Rect(20, 20, 150, 130 if source.height == 180 else 30)
            text = "一行だけ" if source.height == 180 else "新しい文字"
            return (TextRegion(text, box, (TextCharacter(text, box, 0.98),)),)

        def close(self):
            pass

    rows, coverage, rejected = recognize_planned(Engine(), frame, plan)
    assert rejected and coverage == areas
    assert [r.text for r in rows] == ["新しい文字", "新しい文字"]
    assert [r.bounds.y for r in rows] == [120, 220]
    assert calls == [(9, 2.5, 180), (9, 2.5, 80), (9, 2.5, 80)]


@pytest.mark.parametrize("failure", ["missing", "confidence", "edge"])
def test_failed_candidate_discards_every_provisional_row_and_retries_same_source(failure):
    bounds = Rect(0, 0, *SIZE)
    source = CapturedFrame(
        7, 2.5, WindowGeometry(bounds, bounds, bounds, 144), bytes(1920 * 1080 * 4)
    )
    areas = (Rect(100, 100, 200, 100), Rect(500, 100, 200, 100))
    expected = (ScanLine(Rect(120, 120, 100, 30), 0.95),)
    plan = ScanPlan((Rect(100, 100, 600, 100),), areas, expected)
    calls = []

    class Engine:
        def recognize(self, frame, *, full_size=None):
            calls.append((frame.sequence, frame.captured_at, frame.width, full_size))
            if frame.width in (600, 1920):
                if failure == "missing":
                    return ()
                box = Rect(0 if failure == "edge" else 20, 20, 100, 30)
                return (TextRegion("仮の結果", box, (TextCharacter("仮", box, 0.5),)),)
            box = Rect(20, 20, 100, 30)
            return (TextRegion("本当の変更", box, (TextCharacter("本", box, 0.96),)),)

        def close(self):
            pass

    rows, coverage, rejected = recognize_planned(Engine(), source, plan)
    assert rejected
    assert coverage == areas
    assert [r.text for r in rows] == ["本当の変更", "本当の変更"]
    assert [r.bounds.x for r in rows] == [120, 520]
    assert all(seq == 7 and time == 2.5 for seq, time, _, _ in calls)
    assert [width for _, _, width, _ in calls] == (
        [600, 1920, 200, 200] if failure == "edge" else [600, 200, 200]
    )


def test_unmodified_plan_does_not_retry_negative_ocr():
    bounds = Rect(0, 0, *SIZE)
    source = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), bytes(1920 * 1080 * 4))
    calls = []

    class Engine:
        def recognize(self, frame, *, full_size=None):
            calls.append(frame)
            return ()

        def close(self):
            pass

    rows, coverage, rejected = recognize_planned(Engine(), source, ScanPlan(None, None, LINES))
    assert not rejected
    assert not rows and coverage is None and calls == [source]


def test_scope_changes_discard_hints_and_forced_full_discovery_is_never_demoted():
    for size, generation, costs in (
        (SIZE, 1, COSTS),
        ((2000, 1080), 0, COSTS),
        (SIZE, 0, ScanCosts(20, 16)),
    ):
        planner = ScanPlanner()
        initial = planner.plan(None, SIZE, 0, COSTS)
        planner.observe(LINES, None, initial)
        assert planner.plan(AREAS, SIZE, 0, COSTS).changed
        assert planner.plan(None, SIZE, 0, COSTS).areas is None
        assert not planner.plan(AREAS, size, generation, costs).changed


def test_partial_completion_preserves_unscanned_hints_and_overflow_discards_them():
    planner = ScanPlanner()
    initial = planner.plan(None, SIZE, 0, COSTS)
    planner.observe(LINES, None, initial)
    partial = planner.plan(AREAS[:1], SIZE, 0, COSTS)
    planner.observe(LINES[:1], AREAS[:1], partial)
    assert planner.plan(AREAS, SIZE, 0, COSTS).changed
    planner.observe(LINES * 33, None, initial)
    assert not planner.plan(AREAS, SIZE, 0, COSTS).changed


def test_rejected_plan_backs_off_for_three_completed_demands_and_keeps_negative_results():
    planner = ScanPlanner()
    planner.observe(LINES, None, planner.plan(None, SIZE, 0, COSTS))
    selected = planner.plan(AREAS, SIZE, 0, COSTS)
    assert selected.changed
    planner.observe(LINES, selected.baseline, selected)
    assert all(not planner.plan(AREAS, SIZE, 0, COSTS).changed for _ in range(3))
    assert planner.plan(AREAS, SIZE, 0, COSTS).changed
    planner.observe((), None, planner.plan(None, SIZE, 0, COSTS))
    assert not planner.plan(AREAS, SIZE, 0, COSTS).changed


def test_fallback_that_itself_scans_full_frame_still_backs_off():
    planner = ScanPlanner()
    planner.observe(LINES, None, planner.plan(None, SIZE, 0, COSTS))
    selected = planner.plan(AREAS, SIZE, 0, COSTS)
    planner.observe(LINES, None, selected, rejected=True)
    assert all(not planner.plan(AREAS, SIZE, 0, COSTS).changed for _ in range(3))
    assert planner.plan(AREAS, SIZE, 0, COSTS).changed


def test_worker_owns_planning_preserves_acknowledgement_and_resets_hints():
    calls = []
    owner = threading.get_ident()

    class Engine:
        scan_costs = COSTS

        def recognize(self, frame, *, full_size=None):
            assert threading.get_ident() != owner
            calls.append((frame.sequence, frame.width))
            if frame.width == SIZE[0]:
                boxes = tuple(line.bounds for line in LINES)
            elif frame.width == 690:
                boxes = tuple(
                    replace(line.bounds, x=line.bounds.x - 100, y=line.bounds.y - 100)
                    for line in LINES
                )
            else:
                boxes = (Rect(20, 25, 220, 30),)
            return tuple(TextRegion("設定", b, (TextCharacter("設定", b, 0.96),)) for b in boxes)

        def close(self):
            assert threading.get_ident() != owner

    def wait(predicate):
        deadline = time.monotonic() + 4
        while not predicate():
            assert time.monotonic() < deadline
            time.sleep(0.005)

    def source(sequence):
        bounds = Rect(0, 0, *SIZE)
        return CapturedFrame(
            sequence,
            sequence * 0.9,
            WindowGeometry(bounds, bounds, bounds, 96),
            bytes(1920 * 1080 * 4),
        )

    session = OcrSession(Engine, require_ack=True)
    session.start()
    try:
        session.submit(source(1))
        wait(lambda: session.snapshot().result is not None)
        session.submit(source(2), AREAS)
        time.sleep(0.03)
        assert calls == [(1, 1920)]
        session.acknowledge(1)
        wait(lambda: session.snapshot().processed_frames == 2)
        assert calls[-1] == (2, 690)
        result = session.snapshot().result
        assert result is not None and result.frame.sequence == 2 and result.scanned is not None
        assert tuple(r.bounds for r in result.regions) == tuple(line.bounds for line in LINES)
        session.invalidate()
        session.submit(source(1), AREAS)
        wait(lambda: session.snapshot().processed_frames == 3)
        assert calls[-4:] == [(1, 320)] * 4
    finally:
        session.request_stop()
        wait(lambda: session.finished)
