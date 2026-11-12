"""Bounded dialogue grouping over stable lines, independent of Qt and model runtimes."""

import re
from dataclasses import dataclass, field
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


def _can_follow(upper: TextTrack, lower: TextTrack, *, revealing: bool = False) -> bool:
    a, b = upper.bounds, lower.bounds
    first, second = upper.text.strip(), lower.text.strip()
    if upper.vertical or lower.vertical or not has_japanese(first) or not has_japanese(second):
        return False
    if (
        len(first) < 10
        or len(second) < 1
        or first.endswith((":", "："))
        or (first.endswith(_END) and not revealing)
    ):
        return False
    if _CHOICE.match(first) or _CHOICE.match(second) or second.startswith(("「", "『")):
        return False
    height = max(1, min(a.height, b.height))
    gap = b.y - a.y - a.height
    return (
        max(a.height, b.height) <= height * 1.3
        and b.width <= a.width * 1.25  # A short heading/name above wide dialogue is separate.
        and -height * 0.1 <= gap <= height * 0.95
        and abs(a.x - b.x) <= max(6, height * 0.75)
        and min(a.x + a.width, b.x + b.width) - max(a.x, b.x) >= min(a.width, b.width) * 0.8
    )


def _dialogue_evidence(lines: tuple[TextTrack, ...]) -> bool:
    return (
        lines[-1].text.rstrip().endswith(_END)
        or lines[0].text.lstrip().startswith(("「", "『"))
        or any(line.text.rstrip().endswith(("、", "，", ",")) for line in lines[:-1])
    )


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
        if enabled:
            while len(lines) < 6:
                candidates = [
                    line
                    for line in ordered
                    if line.track_id not in used
                    and line not in lines
                    and _can_follow(
                        lines[-1],
                        line,
                        revealing=any(member.track_id in growing for member in (*lines, line)),
                    )
                ]
                if len(candidates) != 1:
                    break  # Ambiguous columns/layouts stay separate.
                proposed = (*lines, candidates[0])
                if len(join_lines(proposed)) > 512:
                    break
                lines = proposed
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

    def reset(self) -> None:
        self._since.clear()

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
        blocks = tuple(
            TextBlock(tuple(displayed[t.track_id] for t in b.lines), dialogue=b.dialogue)
            for b in _blocks(layout, enabled, growing)
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
        quiet = 0.18 if complete else 0.55 if revealing or len(block.lines) > 1 else 0.35
        return now - max(t.changed_at for t in members) >= quiet
