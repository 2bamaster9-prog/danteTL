"""Propose reading paths between mutual nearest rows, then admit bounded prose segments."""

import re
from collections.abc import Callable, Iterator, Mapping, Sequence

from dantejp.ocr.lettering import Lettering
from dantejp.ocr.text_content import has_japanese
from dantejp.ocr.tracking import TextTrack

_TERMINAL = tuple("。！？!?")
_END = (*_TERMINAL, "」", "』")
_NUMERIC = re.compile(r"[*+＋]?\d+(\.\d+)?[%％][。.]?")
_SET = re.compile(r"^[0-9０-９]+セット[:：]")
_OPERATION = re.compile(
    r"^[一-龯々ァ-ヺーA-Za-z0-9０-９]{0,16}(?:発動|起動|実行|使用|終了|解除)(?:中|時|後|前|間)(?:には|に|は)?[、，,]"
)
_PREDICATE = re.compile(r"を[^、，,。！？!?「」『』\s]{1,12}[うくぐすつぬぶむる]。$")


def _paths(rows: Sequence[TextTrack]) -> Iterator[list[TextTrack]]:
    # Sort once, skip distant rows before scoring, and keep only each direction's best edge.
    eligible = sorted(
        (
            r
            for r in rows
            if not r.vertical
            and min(r.bounds.size) > 0
            and (has_japanese(r.text) or _NUMERIC.fullmatch(r.text.strip()))
        ),
        key=lambda r: (r.bounds.y, r.bounds.x, r.track_id),
    )
    incoming: dict[TextTrack, tuple[float, float, int, int]] = {}
    outgoing: dict[TextTrack, tuple[float, float, int, int]] = {}
    competing_in: set[tuple[TextTrack, float]] = set()
    competing_out: set[tuple[TextTrack, float]] = set()
    for i, upper in enumerate(eligible):
        first, a = upper.text.strip(), upper.bounds
        if not has_japanese(first):
            continue
        for j in range(i + 1, len(eligible)):
            lower = eligible[j]
            b = lower.bounds
            if b.y - a.y > 2.3 * a.height:
                break
            unit = min(a.height, b.height)
            pitch = (b.y - a.y + (b.height - a.height) / 2) / unit
            if not (0.9 <= pitch <= 1.8 and max(a.height, b.height) <= 1.55 * unit):
                continue
            overlap = min(a.x + a.width, b.x + b.width) - max(a.x, b.x)
            align = min(abs(a.x - b.x), abs(a.x - b.x + (a.width - b.width) / 2)) / unit
            if overlap < 0.78 * min(a.width, b.width) or align > 2.25:
                continue
            if abs(a.x - b.x) > 2 * unit and align > 0.5:
                continue
            growth = max(0.0, (b.width - a.width) / unit)
            cost = (pitch - 1.35) * 0.85 + align * 0.30 + abs(a.height / b.height - 1) * 1.15
            cost += max(0, 7.5 - a.width / unit) * 0.33 + min(growth, 8) * 0.16
            if first.endswith(_END):
                cost += 0.34 + min(6, growth) * 0.30
            if first.endswith(("：", ":")) or _SET.match(lower.text.strip()):
                cost += 0.9
            if first.endswith(("、", "，", ",")):
                cost -= 0.24
            edge = (pitch, cost, i, j)
            if upper in outgoing and outgoing[upper][0] == pitch:
                competing_out.add((upper, pitch))
            if lower in incoming and incoming[lower][0] == pitch:
                competing_in.add((lower, pitch))
            if upper not in outgoing or edge < outgoing[upper]:
                outgoing[upper] = edge
            if lower not in incoming or edge < incoming[lower]:
                incoming[lower] = edge
    chain = {}
    for row, edge in outgoing.items():
        pitch, cost, _, j = edge
        successor = eligible[j]
        if (
            cost <= 0.85
            and incoming[successor] == edge
            and (row, pitch) not in competing_out
            and (successor, pitch) not in competing_in
        ):
            chain[row] = successor
    children = set(chain.values())
    for row in eligible:
        if row in chain and row not in children:
            path = [row]
            while path[-1] in chain:
                path.append(chain[path[-1]])
            yield path


def _headed_panel(rows: Sequence[TextTrack], part: list[TextTrack]) -> bool:
    first = part[0].bounds
    unit = first.height
    column = sorted(
        (
            r
            for r in rows
            if not r.vertical
            and has_japanese(r.text)
            and abs(r.bounds.x - first.x) <= 0.8 * unit
            and 0.70 * unit <= r.bounds.height <= 1.45 * unit
        ),
        key=lambda r: (r.bounds.y, r.bounds.x, r.track_id),
    )

    def gap(a: TextTrack, b: TextTrack) -> float:
        return (b.bounds.y - a.bounds.y - a.bounds.height) / unit

    panel: list[TextTrack] = []
    for row in column:
        if panel and gap(panel[-1], row) > 3:
            if part[0] in panel:
                break
            panel.clear()
        panel.append(row)
    if not set(part).issubset(panel):
        return False
    headings = [
        head
        for above, head, below in zip(panel, panel[1:], panel[2:], strict=False)
        if gap(above, head) >= 1.2
        and 0 <= gap(head, below) <= 1.1
        and not head.text.rstrip().endswith(_TERMINAL)
        and head.bounds.width <= 0.75 * below.bounds.width
    ]
    return len(headings) >= 2 and headings[0].bounds.y < first.y


def _skill_pair(first: TextTrack, second: TextTrack, styles: Mapping[TextTrack, Lettering]) -> bool:
    a, b = first.bounds, second.bounds
    upper, lower = styles.get(first), styles.get(second)
    return bool(
        upper
        and lower
        and upper.inline_accent
        and lower.neutral
        and abs(a.x - b.x) <= 0.55 * min(a.height, b.height)
        and _OPERATION.match(second.text.strip())
        and _PREDICATE.search(first.text.strip())
        and _PREDICATE.search(second.text.strip())
    )


def _admit(
    rows: Sequence[TextTrack],
    part: list[TextTrack],
    styles: Mapping[TextTrack, Lettering],
    starts_item: Callable[[str], bool],
) -> bool:
    if len(part) < 2:
        return False
    first, second = part[:2]
    text = first.text.strip()
    if (
        len(text) < 10
        or starts_item(text)
        or not any(c in "、，。！？!?,…" for c in text)
        or not any("ぁ" <= c <= "ゖ" for c in text)
    ):
        return False
    if (
        second.bounds.width < 0.60 * first.bounds.width
        and "。" not in second.text
        and not second.text.startswith(("は", "を", "に", "が"))
    ):
        return False
    if all(row.text.rstrip().endswith(_TERMINAL) for row in part) and _headed_panel(rows, part):
        return False
    return len(part) != 2 or not _skill_pair(first, second, styles)


def _boundary(
    part: list[TextTrack],
    row: TextTrack,
    widest: int,
    styles: Mapping[TextTrack, Lettering],
    starts_item: Callable[[str], bool],
) -> bool:
    lower, prior = row.text.strip(), part[-1].text.rstrip()
    if prior.endswith(_END) and lower.lstrip("―—–−-").startswith(("「", "『")):
        return True
    if starts_item(lower) or lower.startswith(("――", "——", "--")):
        return True
    width = row.bounds.width
    if width <= min(0.62 * widest, 12 * row.bounds.height):
        a, b = styles.get(part[-1]), styles.get(row)
        if (
            a
            and b
            and not lower.endswith("。")
            and any(abs(x - y) >= 85 for x, y in zip(a.ink, b.ink, strict=True))
        ):
            return True
        if (
            len(part) >= 2
            and prior.endswith((*_END, "、", "，", ","))
            and (not lower.endswith("。") or prior.endswith(_TERMINAL))
        ):
            return True
    return (
        prior.endswith(_TERMINAL)
        and part[-1].bounds.width <= 0.78 * widest
        and width >= 0.95 * widest
    )


def dialogue_segments(
    rows: Sequence[TextTrack],
    owners: Mapping[TextTrack, tuple[TextTrack, ...]],
    styles: Mapping[TextTrack, Lettering],
    starts_item: Callable[[str], bool],
) -> Iterator[tuple[TextTrack, ...]]:
    """Yield disjoint overrides only when a proposal covers the existing blocks it touches."""
    for path in _paths(rows):
        members = set(path)
        if any(not members.issuperset(block) for block in {owners[r] for r in path}):
            continue
        part: list[TextTrack] = []
        widest = length = 0
        for row in path:
            text = row.text.strip()
            edge_chars = part[-1].text.rstrip()[-1:] + text[:1] if part else ""
            space = len(edge_chars) == 2 and edge_chars.isascii() and edge_chars.isalnum()
            if part and (
                length + len(text) + space > 512
                or _boundary(part, row, widest, styles, starts_item)
            ):
                if _admit(rows, part, styles, starts_item):
                    yield tuple(part)
                part = []
                widest = length = 0
                space = False
            part.append(row)
            widest = max(widest, row.bounds.width)
            length += len(text) + space
        if _admit(rows, part, styles, starts_item):
            yield tuple(part)
