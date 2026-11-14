"""Bounded cost-based scan planning over already closed, disjoint requested crops.

At most four inputs have only fifteen set partitions. Enumerate those partitions
exactly rather than greedily merging a pair that prevents a better grouping.
Geometry/quality gates precede cost comparison; the original plan is always valid.
"""

from dataclasses import dataclass
from math import ceil

from jp_overlay.domain import Rect, union_bounds
from jp_overlay.regions import intersects, scan_regions


@dataclass(frozen=True, slots=True)
class ScanLine:
    bounds: Rect
    confidence: float | None = None
    vertical: bool = False


@dataclass(frozen=True, slots=True)
class ScanCosts:
    detector_ms: float
    recognition_batch_ms: float
    frame_copy_ms: float = 2.0
    batch_size: int = 4
    detector_size: tuple[int, int] = (960, 544)


class ScanPlanner:
    """Worker-owned, bounded geometry hints; never stores pixels, text or absence state."""

    def __init__(self) -> None:
        self._scope: tuple[int, tuple[int, int], ScanCosts | None] | None = None
        self._lines: tuple[ScanLine, ...] = ()
        self._backoff = 0

    def plan(
        self,
        areas: tuple[Rect, ...] | None,
        size: tuple[int, int],
        generation: int,
        costs: ScanCosts | None,
    ) -> "ScanPlan":
        scope = generation, size, costs
        if self._scope != scope:
            self._scope, self._lines, self._backoff = scope, (), 0
        if costs is None or self._backoff:
            self._backoff = max(0, self._backoff - 1)
            baseline = scan_regions(areas, size)
            return ScanPlan(baseline, baseline)
        return choose_scan(areas, size, self._lines, costs)

    def observe(
        self,
        lines: tuple[ScanLine, ...],
        coverage: tuple[Rect, ...] | None,
        plan: "ScanPlan",
        *,
        rejected: bool = False,
    ) -> None:
        # Only called for generation-valid completed work. Unscanned hints survive;
        # misses may discard hints but cannot retire tracks or alter English.
        remaining = tuple(
            line
            for line in self._lines
            if coverage is not None and not any(intersects(a, line.bounds) for a in coverage)
        )
        updated = (*remaining, *lines)
        self._lines = updated if len(updated) <= 128 else ()
        if rejected or (plan.changed and coverage == plan.baseline):
            self._backoff = 3  # A rejected shape must not immediately repeat its retry cost.


@dataclass(frozen=True, slots=True)
class ScanPlan:
    areas: tuple[Rect, ...] | None
    baseline: tuple[Rect, ...] | None
    expected: tuple[ScanLine, ...] = ()
    estimated_ms: float = 0
    baseline_ms: float = 0

    @property
    def changed(self) -> bool:
        return self.areas != self.baseline


def _partitions(count: int) -> tuple[tuple[tuple[int, ...], ...], ...]:
    partitions: list[tuple[tuple[int, ...], ...]] = [()]
    for index in range(count):
        partitions = [
            updated
            for groups in partitions
            for updated in (
                (*groups, (index,)),
                *(
                    groups[:i] + ((*group, index),) + groups[i + 1 :]
                    for i, group in enumerate(groups)
                ),
            )
        ]
    return tuple(partitions)


def choose_scan(
    areas: tuple[Rect, ...] | None,
    size: tuple[int, int],
    lines: tuple[ScanLine, ...],
    costs: ScanCosts,
) -> ScanPlan:
    """Select a cheaper safe-shape partition, keeping discovery and unknown crops intact.

    Known geometry is only a planning hint, never OCR output or absence evidence.
    Empty/unknown requested areas retain their baseline scan. Merged crops close over
    all intersected known lines, remain disjoint, and keep projected glyphs >=24 px.
    Native caller must validate returned OCR before accepting a changed plan.
    """
    baseline = scan_regions(areas, size)
    if baseline is None or len(baseline) < 2 or len(lines) > 128:
        return ScanPlan(baseline, baseline)
    viewport = Rect(0, 0, *size)
    detector_width, detector_height = costs.detector_size

    def estimate(plan: tuple[Rect, ...] | None) -> float:
        value = 0.0
        for area in plan if plan is not None else (viewport,):
            count = sum(intersects(area, line.bounds) for line in lines)
            # Empty tiny crops invoke Meiki's natural-scale padding retry. Edge
            # risk is costed too, even though closed alternatives usually avoid it.
            blank_retry = (
                count == 0 and area.width < detector_width and area.height < detector_height
            )
            edge_risk = any(
                intersects(area, line.bounds) and not area.contains(line.bounds) for line in lines
            )
            value += costs.detector_ms * (1 + blank_retry + 0.5 * edge_risk)
            value += costs.recognition_batch_ms * ceil(count / costs.batch_size)
            value += costs.frame_copy_ms * area.width * area.height / (size[0] * size[1])
        return value

    base_cost = estimate(baseline)
    best = ScanPlan(baseline, baseline, estimated_ms=base_cost, baseline_ms=base_cost)
    if any(line.vertical and any(intersects(a, line.bounds) for a in baseline) for line in lines):
        return best  # Rescaling regrouped vertical glyphs and incurred systematic retries.
    if any(not any(area.contains(line.bounds) for line in lines) for area in baseline):
        return best  # New/unknown text has no defensible scale or quality estimate.
    candidates: set[tuple[Rect, ...] | None] = {None}
    for groups in _partitions(len(baseline)):
        merged = tuple(union_bounds(tuple(baseline[i] for i in group)) for group in groups)
        closed = scan_regions(merged, size, tuple(line.bounds for line in lines))
        candidates.add(closed)
    ordered = sorted(
        (p for p in candidates if p is not None),
        key=lambda p: (len(p), tuple((b.y, b.x, *b.size) for b in p)),
    )
    for plan in (*ordered, None):
        if plan == baseline:
            continue
        expected = tuple(
            line
            for line in lines
            if plan is None or any(intersects(area, line.bounds) for area in plan)
        )
        safe = True
        for area in plan if plan is not None else (viewport,):
            if area in baseline:
                continue
            scale = min(detector_width / area.width, detector_height / area.height)
            for line in expected:
                if intersects(area, line.bounds) and (
                    not area.contains(line.bounds)
                    or line.confidence is None
                    or line.confidence < 0.8
                    or (line.bounds.width if line.vertical else line.bounds.height) * scale < 24
                ):
                    safe = False
                    break
        cost = estimate(plan)
        if safe and cost < best.estimated_ms and cost <= base_cost * 0.85:
            best = ScanPlan(plan, baseline, expected, cost, base_cost)
    return best


def preserves_lines(expected: tuple[ScanLine, ...], observed: tuple[ScanLine, ...]) -> bool:
    """Conservative post-scan veto; failure means retry the original plan on that frame."""
    for previous in expected:
        a = previous.bounds
        matches = []
        for current in observed:
            b = current.bounds
            width = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
            height = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
            if (
                previous.vertical == current.vertical
                and width * height >= a.width * a.height * 0.65
            ):
                matches.append(current)
        if not any(
            line.confidence is not None
            and line.confidence >= min(0.85, (previous.confidence or 0.9) - 0.05)
            for line in matches
        ):
            return False
    return True
