"""Bounded physical-pixel scan coverage, independent of models and the UI."""

from dantetl.domain import Rect, union_bounds


def intersects(a: Rect, b: Rect) -> bool:
    return (
        a.x < b.x + b.width
        and b.x < a.x + a.width
        and a.y < b.y + b.height
        and b.y < a.y + a.height
    )


def padded(bounds: Rect, size: tuple[int, int], amount: int = 32) -> Rect:
    x, y = max(0, bounds.x - amount), max(0, bounds.y - amount)
    right, bottom = (
        min(size[0], bounds.x + bounds.width + amount),
        min(size[1], bounds.y + bounds.height + amount),
    )
    return Rect(x, y, max(0, right - x), max(0, bottom - y))


def scan_regions(
    areas: tuple[Rect, ...] | None,
    size: tuple[int, int],
    whole_lines: tuple[Rect, ...] = (),
) -> tuple[Rect, ...] | None:
    """Merge overlapping crops, close over whole lines, or choose one full scan.

    None means full coverage; () means no requested area. The model sees at most
    four disjoint crops and 45% of the image before broader work uses a full scan.
    """
    if areas is None or len(areas) > 128:
        return None
    pending = [padded(a, size, 0) for a in areas if min(a.size) > 0]
    pending = [a for a in pending if min(a.size) > 0]
    # Each iteration merges rectangles or expands to include a known line. Bounds
    # grow monotonically, and the work budget also protects pathological layouts.
    for _ in range(256):
        changed = False
        for i, area in enumerate(pending):
            additions = [
                line
                for line in whole_lines[:128]
                if intersects(area, line) and not area.contains(line)
            ]
            if additions:
                pending[i] = union_bounds((area, *(padded(line, size) for line in additions)))
                changed = True
            for j in range(i):
                if intersects(pending[i], pending[j]):
                    pending[j] = union_bounds((pending[j], pending.pop(i)))
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    else:
        return None
    if len(pending) > 4 or sum(a.width * a.height for a in pending) > size[0] * size[1] * 0.45:
        return None
    return tuple(sorted(pending, key=lambda a: (a.y, a.x)))
