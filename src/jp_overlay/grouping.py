"""Bounded dialogue grouping over stable lines, independent of Qt and model runtimes."""

import re
from dataclasses import dataclass, field, replace
from statistics import median

from jp_overlay.domain import Rect, union_bounds
from jp_overlay.text_content import has_japanese
from jp_overlay.tracking import TextActivity, TextTrack

_END = tuple("。！？!?」』")
_CHOICE = re.compile(r"^(?:[・•●○◆◇▶▷→\-]|[0-9０-９①-⑳]+[.．、:：)）]|[A-Za-z][.．)）])")


def join_lines(lines: tuple[TextTrack, ...]) -> str:
    text = ""
    for line in lines:
        part = line.text.strip()
        if (
            text
            and part
            and text[-1].isascii()
            and text[-1].isalnum()
            and part[0].isascii()
            and part[0].isalnum()
        ):
            text += " "  # Keep Latin names/words separated across a Japanese line wrap.
        text += part
    return text


@dataclass(frozen=True, slots=True)
class TextBlock:
    lines: tuple[TextTrack, ...]
    dialogue: bool = field(default=False, compare=False)

    def __post_init__(self) -> None:
        if not self.lines:
            raise ValueError("A text block needs at least one line.")

    @property
    def text(self) -> str:
        return join_lines(self.lines)

    @property
    def bounds(self) -> Rect:
        return union_bounds(tuple(line.bounds for line in self.lines))

    @property
    def line_height(self) -> int:
        return round(median(line.bounds.height for line in self.lines))

    @property
    def key(self) -> tuple[tuple[int, int, str], ...]:
        return tuple((line.track_id, line.text_revision, line.text) for line in self.lines)


@dataclass(frozen=True, slots=True)
class GroupedText:
    blocks: tuple[TextBlock, ...]
    ready: tuple[TextBlock, ...]


def _can_follow(
    upper: TextTrack, lower: TextTrack, *, revealing: bool = False, paragraph: bool = False
) -> bool:
    a, b = upper.bounds, lower.bounds
    first, second = upper.text.strip(), lower.text.strip()
    if upper.vertical or lower.vertical or not has_japanese(first) or not has_japanese(second):
        return False
    if len(first) < 10 or len(second) < 1 or first.endswith((":", "：")):
        return False
    if _CHOICE.match(first) or _CHOICE.match(second) or second.startswith(("「", "『")):
        return False
    height = max(1, min(a.height, b.height))
    gap = b.y - a.y - a.height
    # A final kana plus punctuation can have shorter ink bounds than a full kanji line.
    # Relax height only for a narrow terminal fragment, never an ordinary smaller label.
    short_ending = (
        1 < len(second) <= 4
        and second.endswith(_END)
        and b.width <= min(a.width * 0.35, a.height * 4)
        and b.height < a.height
    )
    width_growth = (
        paragraph
        or revealing
        or _internal_prose(first)
        or first.endswith((*_END, "、", "，", ","))
        or first.startswith(("「", "『"))
    )
    return (
        max(a.height, b.height) <= height * (1.45 if short_ending else 1.3)
        # Wrapped rows can widen. A heading/name is substantially narrower than body
        # prose; measure that distinction in font units as well as relative width.
        and b.width
        <= (max(a.width * 1.5, a.width + height * 4) if width_growth else a.width * 1.25)
        and -height * 0.1 <= gap <= height * 0.95
        and (abs(a.x - b.x) <= max(6, height * 0.75) or _centered_wrap(upper, lower))
        and min(a.x + a.width, b.x + b.width) - max(a.x, b.x) >= min(a.width, b.width) * 0.8
        # A sentence boundary is weaker evidence of continuity, not a hard stop.
        # Require tightly spaced full prose rows; marked choices remain excluded.
        and (
            revealing
            or not first.endswith(_END)
            or (gap <= height * 0.55 and min(a.width, b.width) >= height * 8)
        )
    )


def _internal_prose(text: str) -> bool:
    # Japanese sentence punctuation inside a long unfinished row is also wrap evidence.
    return len(text) >= 14 and any(mark in text[:-1] for mark in "、，。")


def _centered_wrap(upper: TextTrack, lower: TextTrack) -> bool:
    """A centered continuation under prose, not generally centered menu rows.

    Similar-width rows use the ordinary alignment tolerance. A narrow final row gets
    extra leeway: missing edge glyphs on its much longer predecessor can shift the center.
    Font, gap, choice and unambiguous-successor checks still belong to _can_follow.
    """
    a, b = upper.bounds, lower.bounds
    unit = max(1, min(a.height, b.height))
    tolerance = 1.25 if b.width <= a.width * 0.7 else 0.75
    text = upper.text.strip()
    return abs((a.x + a.width / 2) - (b.x + b.width / 2)) <= unit * tolerance and (
        _internal_prose(text) or text.endswith(("、", "，", ",")) or text.startswith(("「", "『"))
    )


def _wrapped_prose(lines: tuple[TextTrack, ...]) -> bool:
    if len(lines) < 2:
        return False
    first, second = lines[:2]
    return (
        _internal_prose(first.text.strip())
        and not first.text.rstrip().endswith(_END)
        and (
            _centered_wrap(first, second)
            or (
                len(second.text.strip()) >= 10
                and min(first.bounds.width, second.bounds.width)
                >= max(first.bounds.width, second.bounds.width) * 0.8
            )
        )
    )


def _dialogue_evidence(lines: tuple[TextTrack, ...]) -> bool:
    return (
        lines[-1].text.rstrip().endswith(_END)
        or lines[0].text.lstrip().startswith(("「", "『"))
        or any(line.text.rstrip().endswith(("、", "，", ",")) for line in lines[:-1])
        or _wrapped_prose(lines)
    )


def _row_fragments(
    first: TextTrack, available: tuple[TextTrack, ...], column: Rect, limit: int
) -> tuple[TextTrack, ...]:
    """Join split detections only inside a column established by earlier prose rows."""
    row = (first,)
    while len(row) < limit:
        a = row[-1].bounds
        candidates = []
        for next_line in available:
            b = next_line.bounds
            height = max(1, min(a.height, b.height))
            if (
                next_line not in row
                and not next_line.vertical
                and has_japanese(next_line.text)
                and not _CHOICE.match(next_line.text.lstrip())
                and 0 <= b.x - a.x - a.width <= height * 2
                and max(a.height, b.height) <= height * 1.3
                and abs((a.y + a.height / 2) - (b.y + b.height / 2)) <= height * 0.25
                and b.x + b.width <= column.x + column.width + height * 0.75
            ):
                candidates.append(next_line)
        if len(candidates) != 1:
            break
        row = (*row, candidates[0])
    return row


def _blocks(
    tracks: tuple[TextTrack, ...], enabled: bool, growing: frozenset[int] = frozenset()
) -> tuple[TextBlock, ...]:
    ordered = sorted(tracks[:128], key=lambda t: (t.bounds.y, t.bounds.x, t.track_id))
    used: set[int] = set()
    blocks: list[TextBlock] = []
    for first in ordered:
        if first.track_id in used:
            continue
        lines = (first,)
        last_row = first
        if enabled:
            while len(lines) < 6:
                candidates = [
                    line
                    for line in ordered
                    if line.track_id not in used
                    and line not in lines
                    and _can_follow(
                        last_row,
                        line,
                        revealing=any(member.track_id in growing for member in (*lines, line)),
                        paragraph=len(lines) >= 2,
                    )
                ]
                if len(candidates) != 1:
                    break  # Ambiguous columns/layouts stay separate.
                row = (candidates[0],)
                if len(lines) >= 2 and _dialogue_evidence(lines):
                    row = _row_fragments(
                        candidates[0],
                        tuple(t for t in ordered if t.track_id not in used and t not in lines),
                        union_bounds(tuple(t.bounds for t in lines)),
                        6 - len(lines),
                    )
                proposed = (*lines, *row)
                if len(join_lines(proposed)) > 512:
                    break
                lines = proposed
                # Aggregate geometry is private to adjacency; requests retain every raw member.
                last_row = replace(
                    row[0], text=join_lines(row), bounds=union_bounds(tuple(t.bounds for t in row))
                )
        if len(lines) > 1 and not (
            _dialogue_evidence(lines) or any(line.track_id in growing for line in lines)
        ):
            lines = (first,)  # Nearby menu labels alone are not evidence of a dialogue box.
        used.update(line.track_id for line in lines)
        dialogue = enabled and (
            len(lines) > 1
            or (
                len(join_lines(lines)) >= 10
                and _dialogue_evidence(lines)
                and (first.track_id in growing or first.text.startswith(("「", "『")))
            )
        )
        blocks.append(TextBlock(lines, dialogue=dialogue))
    return tuple(blocks)


class DialogueGrouper:
    """Wait briefly for a whole group to settle; never queue partial old paragraphs."""

    def __init__(self, settle_seconds: float = 0.35) -> None:
        self._settle_seconds = settle_seconds
        self._since: dict[tuple[tuple[int, int, str], ...], float] = {}
        self._layout_key: tuple[tuple[TextTrack, ...], bool, frozenset[int]] | None = None
        self._layout: tuple[TextBlock, ...] = ()

    def reset(self) -> None:
        self._since.clear()
        self._layout_key, self._layout = None, ()

    def update(
        self,
        visible: tuple[TextTrack, ...],
        confirmed: tuple[TextTrack, ...],
        now: float,
        *,
        enabled: bool = True,
        activity: tuple[TextActivity, ...] | None = None,
    ) -> GroupedText:
        observed = {value.observation.track_id: value for value in activity or ()}
        growing = frozenset(key for key, value in observed.items() if value.growing)
        layout = tuple(
            observed[t.track_id].observation if t.track_id in observed else t for t in visible
        )
        displayed = {t.track_id: t for t in visible}
        layout_key = (layout, enabled, growing)
        if layout_key != self._layout_key:
            self._layout = _blocks(layout, enabled, growing)
            self._layout_key = layout_key
        blocks = tuple(
            TextBlock(tuple(displayed[t.track_id] for t in b.lines), dialogue=b.dialogue)
            for b in self._layout
        )
        ready_keys = {(line.track_id, line.text_revision, line.text) for line in confirmed}
        since = {block.key: self._since.get(block.key, now) for block in blocks}
        ready = tuple(
            block
            for block in blocks
            if all(key in ready_keys for key in block.key)
            and (
                self._activity_ready(block, observed, now, enabled)
                if activity is not None
                else len(block.lines) == 1 or now - since[block.key] >= self._settle_seconds
            )
        )
        self._since = since
        return GroupedText(blocks, ready)

    def _activity_ready(
        self, block: TextBlock, activity: dict[int, TextActivity], now: float, enabled: bool
    ) -> bool:
        members = [activity[t.track_id] for t in block.lines if t.track_id in activity]
        if len(members) != len(block.lines) or any(t.pending for t in members):
            return False
        revealing = any(t.growing for t in members)
        dialogue = enabled and (
            len(block.lines) > 1 or (len(block.text) >= 10 and not _CHOICE.match(block.text))
        )
        if not revealing and not dialogue:
            return True  # Ordinary short menu labels need no extra debounce.
        complete = block.text.rstrip().endswith(_END)
        unfinished_prose = revealing or len(block.lines) > 1 or _internal_prose(block.text)
        quiet = 0.18 if complete else 0.55 if unfinished_prose else 0.35
        return now - max(t.changed_at for t in members) >= quiet
