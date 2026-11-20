"""Joint English placement with bounded candidates and deterministic local descent.

Qt measures text, then a geometric broad phase limits collision scoring to nearby
candidate envelopes. This presentation-only owner never changes translation demand.
"""

from dataclasses import dataclass, replace

import numpy as np
from numpy.typing import NDArray

from dantetl.domain import MAX_OVERLAY_LABELS, Rect, union_bounds
from dantetl.i18n import tr
from dantetl.ui.text_layout import EnglishLayout, layout_english


@dataclass(frozen=True, slots=True)
class EnglishLabel:
    key: tuple[tuple[int, int, str], ...]
    text: str
    source: Rect
    line_height: int
    vertical: bool = False


def _overlap(a: Rect, b: Rect) -> float:
    width = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    return width * height / max(1, min(a.width * a.height, b.width * b.height))


def _rectangles(boxes: tuple[Rect, ...]) -> NDArray[np.float64]:
    return np.array(
        [(b.x, b.y, b.x + b.width, b.y + b.height) for b in boxes], dtype=np.float64
    ).reshape(-1, 4)


def _overlaps(a: NDArray[np.float64], b: NDArray[np.float64]) -> NDArray[np.float64]:
    # At most 12 candidates x 127 neighbors; dense components stay off Python's
    # inner loop without allocating an all-candidate scene collision matrix.
    sizes = np.maximum(
        0, np.minimum(a[:, None, 2:], b[None, :, 2:]) - np.maximum(a[:, None, :2], b[None, :, :2])
    )
    areas_a = np.prod(a[:, 2:] - a[:, :2], axis=1)
    areas_b = np.prod(b[:, 2:] - b[:, :2], axis=1)
    return np.prod(sizes, axis=2) / np.maximum(1, np.minimum(areas_a[:, None], areas_b[None, :]))


class _Index:
    """Exact rectangle broad phase; oversized boxes have a bounded all-pairs fallback."""

    def __init__(self, boxes: tuple[Rect, ...]) -> None:
        self.boxes = boxes
        self.grid: dict[tuple[int, int], set[int]] = {}
        self.wide: set[int] = set()
        for i, box in enumerate(boxes):
            cells = self._cells(box)
            if cells is None:
                self.wide.add(i)
            else:
                for cell in cells:
                    self.grid.setdefault(cell, set()).add(i)

    @staticmethod
    def _cells(box: Rect) -> tuple[tuple[int, int], ...] | None:
        left, top = box.x // 256, box.y // 256
        right, bottom = (box.x + box.width) // 256, (box.y + box.height) // 256
        if (right - left + 1) * (bottom - top + 1) > 64:
            return None
        return tuple((x, y) for y in range(top, bottom + 1) for x in range(left, right + 1))

    def neighbors(self, box: Rect) -> tuple[int, ...]:
        cells = self._cells(box)
        candidates = self.wide.copy() if cells is not None else set(range(len(self.boxes)))
        for cell in cells or ():
            candidates.update(self.grid.get(cell, ()))
        return tuple(i for i in sorted(candidates) if _overlap(box, self.boxes[i]))


def _candidates(
    label: EnglishLabel,
    viewport: tuple[int, int],
    automatic: bool,
    pixels: int,
    base: EnglishLayout,
    rewrap: bool,
) -> tuple[EnglishLayout, ...]:
    layouts = [base]
    for width in (label.source.width, round(base.bounds.width * 1.5)) if rewrap else ():
        alternate = layout_english(
            label.text,
            label.source,
            viewport,
            automatic=automatic,
            manual_pixels=pixels,
            vertical=label.vertical,
            source_line_height=label.line_height,
            wrap_width=width,
        )
        # Avoid solving collisions by throwing away more English or lowering its font.
        if alternate.pixel_size >= base.pixel_size and (
            not alternate.truncated
            or (base.truncated and sum(map(len, alternate.lines)) >= sum(map(len, base.lines)))
        ):
            layouts.append(alternate)
    result = [base]
    for layout in layouts:
        width, height = layout.bounds.size
        for y in (label.source.y, label.source.y + label.source.height - height):
            for x in (label.source.x, label.source.x + label.source.width - width):
                bounds = Rect(
                    max(0, min(x, viewport[0] - width)),
                    max(0, min(y, viewport[1] - height)),
                    width,
                    height,
                )
                candidate = replace(layout, bounds=bounds)
                if candidate not in result:
                    result.append(candidate)
    return tuple(result)


class EnglishPlacement:
    """Cache one live scene and at most 128 placements, scoped to exact published content.

    Every candidate remains anchored over its source, inside the viewport, with the
    existing readability floor. Four deterministic coordinate-descent sweeps reduce
    label/label and label/source overlap, displacement and changes to prior placements.
    Dense impossible layouts retain all labels; this is not a global optimality claim.
    """

    def __init__(self) -> None:
        self._scene: tuple[object, ...] = ()
        self._style: tuple[object, ...] = ()
        self._placed: dict[EnglishLabel, EnglishLayout] = {}

    def clear(self) -> None:
        self._scene, self._style = (), ()
        self._placed.clear()

    def arrange(
        self,
        labels: tuple[EnglishLabel, ...],
        viewport: tuple[int, int],
        obstacles: tuple[Rect, ...] = (),
        *,
        automatic: bool = True,
        pixels: int = 20,
    ) -> tuple[EnglishLayout, ...]:
        if len(labels) > MAX_OVERLAY_LABELS or len(obstacles) > MAX_OVERLAY_LABELS:
            raise ValueError(tr("Translation placement exceeds the live track bound."))
        ordered = tuple(sorted(labels, key=lambda label: label.key))
        obstacles = tuple(sorted(set(obstacles), key=lambda box: (box.y, box.x, *box.size)))
        style = (viewport, automatic, pixels)
        scene = (ordered, obstacles, style)
        if scene == self._scene:
            return tuple(self._placed[label] for label in labels)
        previous = self._placed if style == self._style else {}
        bases = tuple(
            previous.get(label)
            or layout_english(
                label.text,
                label.source,
                viewport,
                automatic=automatic,
                manual_pixels=pixels,
                vertical=label.vertical,
                source_line_height=label.line_height,
            )
            for label in ordered
        )
        base_index, sources = _Index(tuple(b.bounds for b in bases)), _Index(obstacles)
        base_neighbors = [base_index.neighbors(base.bounds) for base in bases]
        # Isolated labels keep the existing one-box layout without measuring options.
        # Previously placed labels keep their exact layout while neighbors change.
        # Extremely crowded sources only try four anchor directions, bounding font
        # work where extra wrapping cannot make all the overlapping anchors disjoint.
        choices = [
            _candidates(label, viewport, automatic, pixels, base, len(base_neighbors[i]) <= 16)
            if label not in previous
            and (
                any(j != i for j in base_neighbors[i])
                or any(obstacles[j] != label.source for j in sources.neighbors(base.bounds))
            )
            else (base,)
            for i, (label, base) in enumerate(zip(ordered, bases, strict=True))
        ]
        selected = [0] * len(choices)
        envelopes = tuple(union_bounds(tuple(c.bounds for c in options)) for options in choices)
        index = _Index(envelopes)
        neighbors = [
            tuple(j for j in index.neighbors(box) if j != i) for i, box in enumerate(envelopes)
        ]
        coordinates = [_rectangles(tuple(c.bounds for c in options)) for options in choices]
        current = _rectangles(
            tuple(options[k].bounds for options, k in zip(choices, selected, strict=True))
        )
        unary: list[NDArray[np.float64]] = []
        for label, options, envelope in zip(ordered, choices, envelopes, strict=True):
            nearby = [
                obstacles[j] for j in sources.neighbors(envelope) if obstacles[j] != label.source
            ]
            base = options[0].bounds
            costs = []
            for option in options:
                box = option.bounds
                displacement = (abs(box.x - base.x) + abs(box.y - base.y)) / max(
                    12, label.line_height
                )
                costs.append(displacement + abs(box.width - base.width) / max(1, base.width))
            unary.append(
                np.array(costs)
                + 1000
                * _overlaps(
                    _rectangles(tuple(c.bounds for c in options)), _rectangles(tuple(nearby))
                ).sum(axis=1)
            )
        # Exact scene cache prevents repeat work or progressive movement on repaint.
        for _ in range(4):
            changed = False
            for i in range(len(choices)):
                if len(choices[i]) == 1:
                    continue
                costs = unary[i] + 1000 * _overlaps(
                    coordinates[i], current[list(neighbors[i])]
                ).sum(axis=1)
                best = int(np.argmin(costs))
                if costs[best] < costs[selected[i]]:
                    selected[i], changed = best, True
                    current[i] = coordinates[i][best]
            if not changed:
                break
        self._placed = {label: choices[i][selected[i]] for i, label in enumerate(ordered)}
        self._scene, self._style = scene, style
        return tuple(self._placed[label] for label in labels)
