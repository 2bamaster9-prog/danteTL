"""Bounded dialogue grouping over stable lines, independent of Qt and model runtimes."""

import re
from dataclasses import dataclass, field, replace
from statistics import median

from dantejp.domain import Rect, union_bounds
from dantejp.ocr.text_content import has_japanese
from dantejp.ocr.tracking import TextActivity, TextTrack

_END = tuple("。！？!?」』")
_CHOICE = re.compile(r"^(?:[・•●○◆◇▶▷→\-]|[0-9０-９①-⑳]+[.．、:：)）]|[A-Za-z][.．)）])")
# OCR can lose the bracket after a typographic dialogue dash (or read it as /).
# A single ASCII hyphen still marks a choice unless followed by a real bracket.
_QUOTE = re.compile(r"^(?:[―—–−]{1,3}|-{1,3}\s*[「『]|[「『])")
_DASHED_BRACKET = re.compile(r"^(?:-{2,}|[―—–]+)\s*(?=[「『/])")
_CLOSING_BRACKET = {"「": "」", "『": "』"}
# Short inline labels start items even when a leading icon is included or lost by OCR.
# Exclude sentence/quote punctuation so a colon inside prose does not create a label.
_LABEL = re.compile(r"^([^\s:：。、，！？!?「『]{1,10})[:：]\s*(?=\S)")
_PERCENT_NUMBER = r"[0-9０-９]+(?:[.．][0-9０-９]+)?[%％]"
_PERCENT = re.compile(rf"[tTｔＴ*＊]?[+＋\-−±:：]?{_PERCENT_NUMBER}[。.!！]?")
_PERCENT_OPERAND = re.compile(rf"[+＋\-−±]?{_PERCENT_NUMBER}(?:$|[。.!！])")
_PERCENT_CLAUSE = re.compile(
    rf"(?:[がはをもに]?(?:さらに|更に)|[がはをもに])[+＋\-−±:：]?\s*{_PERCENT_NUMBER}[。.!！]?"
)


def _is_choice(text: str) -> bool:
    return bool(_CHOICE.match(text)) and not _QUOTE.match(text)


def _labelled(text: str) -> bool:
    if marker := _CHOICE.match(text):
        text = text[marker.end() :].lstrip()
    return bool(_LABEL.match(text))


def _item_start(text: str) -> bool:
    return _is_choice(text) or _labelled(text)


def _continues_percentage(text: str, *, in_paragraph: bool) -> bool:
    """OCR can read the plus in a Japanese clause as a label separator."""
    if _PERCENT_CLAUSE.fullmatch(text):
        return True
    if not in_paragraph or _CHOICE.match(text):
        return False
    label = _LABEL.match(text)
    if not label or not ("による" in label[1] or "に対する" in label[1]):
        return False
    operand = _PERCENT_OPERAND.match(text, label.end())
    # A noun phrase can itself be a stat label. Require more prose after its value
    # before treating such a mid-row colon as a damaged operator.
    return operand is not None and has_japanese(text[operand.end() :])


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


def _on_column_pitch(previous: Rect, current: Rect, following: Rect) -> bool:
    """Predict the next row center from the last two, allowing for shorter glyphs."""
    pitch = current.y - previous.y + (current.height - previous.height) / 2
    step = following.y - current.y + (following.height - current.height) / 2
    unit = current.height
    return (
        unit * 0.9 <= pitch <= unit * 1.9
        and abs(step - pitch) <= unit * 0.25
        and abs(current.x - following.x) <= unit * 0.5
    )


def _can_follow(
    upper: TextTrack,
    lower: TextTrack,
    *,
    revealing: bool = False,
    previous_row: Rect | None = None,
    opening_quote: bool = False,
) -> bool:
    a, b = upper.bounds, lower.bounds
    height = max(1, min(a.height, b.height))
    gap = b.y - a.y - a.height
    if not -height * 0.1 <= gap <= height * 0.95:
        return False  # Distant rows need no text/quote analysis in dense layouts.
    first, second = upper.text.strip(), lower.text.strip()
    introduces_value = first.endswith(("さらに", "更に", "最大で", "上限は"))
    paragraph = previous_row is not None
    percentage = (
        _PERCENT.fullmatch(second)
        if (paragraph or introduces_value) and len(second) <= 16
        else None
    )
    on_pitch = bool(percentage and previous_row and _on_column_pitch(previous_row, a, b))
    numeric_tail = (
        percentage is not None
        and not first.endswith(_END)
        and (not second.startswith(("*", "＊")) or on_pitch)
        and b.width <= min(a.width * 0.35, a.height * 4)
    )
    if (
        upper.vertical
        or lower.vertical
        or not has_japanese(first)
        or not (has_japanese(second) or numeric_tail)
    ):
        return False
    labelled = _labelled(first)
    if (
        (len(first) < 10 and not (introduces_value and numeric_tail))
        or not second
        or (first.endswith((":", "：")) and not labelled)
    ):
        return False
    quoted = opening_quote or bool(_QUOTE.match(first))
    if _is_choice(first) and not (labelled or opening_quote):
        return False  # Bare menu choices stay independent; labelled descriptions can wrap.
    if not numeric_tail and _QUOTE.match(second):
        return False
    if (
        not numeric_tail
        and _item_start(second)
        and (
            first.endswith(_END)
            or not _continues_percentage(second, in_paragraph=paragraph or labelled)
        )
    ):
        return False
    item = not opening_quote and _item_start(first)
    # A final kana plus punctuation can have shorter ink bounds than a full kanji line.
    # Relax height only for a narrow terminal fragment, never an ordinary smaller label.
    short_ending = numeric_tail or (
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
        or quoted
    )
    height_ratio = 1.45 if short_ending else 1.3
    if numeric_tail and on_pitch:
        height_ratio = 1.65  # Digits may occupy much less of the same physical row.
    return (
        max(a.height, b.height) <= height * height_ratio
        # Wrapped rows can widen. A heading/name is substantially narrower than body
        # prose; measure that distinction in font units as well as relative width.
        and b.width
        <= (max(a.width * 1.5, a.width + height * 4) if width_growth else a.width * 1.25)
        and (
            abs(a.x - b.x) <= max(6, height * 0.75)
            or (not item and _centered_wrap(upper, lower))
            # Ink extents include or omit the leading dash/bracket depending on the
            # scan. Allow a hanging mark or indent; overlap/gap/font checks still apply.
            or (quoted and abs(a.x - b.x) <= height * 2)
            # A list marker/inline label may hang to the left of wrapped body text.
            or (item and 0 <= b.x - a.x <= height * 2)
        )
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
        _internal_prose(text) or text.endswith(("、", "，", ",")) or bool(_QUOTE.match(text))
    )


def _wrapped_prose(lines: tuple[TextTrack, ...]) -> bool:
    if len(lines) < 2:
        return False
    first, second = lines[:2]
    if first.text.rstrip().endswith(_END) or not any(
        _internal_prose(line.text.strip()) for line in lines[:-1]
    ):
        return False
    return (
        _centered_wrap(first, second)
        or (
            len(second.text.strip()) >= 10
            and min(first.bounds.width, second.bounds.width)
            >= max(first.bounds.width, second.bounds.width) * 0.8
        )
        # A hanging marker can make the opening much wider than the next row.
        # Two body rows at the predicted spacing independently support that opening.
        or (
            len(lines) >= 3
            and _labelled(first.text.lstrip())
            and first.bounds.x + second.bounds.height * 0.5 < second.bounds.x
            and _on_column_pitch(first.bounds, second.bounds, lines[2].bounds)
        )
    )


def _dialogue_evidence(lines: tuple[TextTrack, ...]) -> bool:
    first, last = lines[0].text.lstrip(), lines[-1].text.strip()
    return (
        last.endswith(_END)
        or bool(_QUOTE.match(first))
        or (len(lines) > 1 and bool(_PERCENT.fullmatch(last) or _PERCENT_CLAUSE.fullmatch(last)))
        or any(line.text.rstrip().endswith(("、", "，", ",")) for line in lines[:-1])
        or _wrapped_prose(lines)
    )


def _paragraph_boundary(lines: tuple[TextTrack, ...], upper: TextTrack, lower: TextTrack) -> bool:
    """A ragged terminal row followed by a full row starts a new paragraph.

    Establish the column from earlier rows, so a sentence ending on a full-width
    row stays joined. A trailing dash is continuation, not terminal punctuation.
    """
    if len(lines) < 2 or not upper.text.rstrip().endswith(_END):
        return False
    width = max(line.bounds.width for line in lines)
    unit = max(1, min(upper.bounds.height, lower.bounds.height))
    return (
        upper.bounds.width <= width * 0.85
        and width - upper.bounds.width >= unit * 2
        and lower.bounds.width >= width * 0.9
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
                and not _is_choice(next_line.text.lstrip())
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


def _quote_openings(
    rows: list[TextTrack], dash_edges: dict[TextTrack, int]
) -> dict[int, tuple[TextTrack, int]]:
    """Geometry for a supported opening and the only row it may newly join."""
    openings = {}
    for row in rows:
        text = row.text.strip()
        edge = dash_edges.get(row)
        if row.vertical or not text:
            continue
        if edge is None:
            if not (dash := _DASHED_BRACKET.match(text)):
                continue
            body = text[dash.end() :]
        else:
            body = text
        if (
            not body.startswith(("「", "『", "/"))
            or not has_japanese(body)
            or (_labelled(body) or "%" in body or "％" in body)
        ):
            continue
        if closer := _CLOSING_BRACKET.get(body[0]):
            if body.count(closer) >= body.count(body[0]):
                continue  # A complete quoted label cannot open a wrapped quotation.
        elif body.endswith(("」", "』", "/")):
            continue
        a = row.bounds
        if edge is not None:
            a = replace(a, x=edge, width=a.width + a.x - edge)
        above, below = [], []
        for other in rows:
            b = other.bounds
            h = min(a.height, b.height)
            if other.vertical or abs(a.x - b.x) > h * 1.2 or max(a.height, b.height) > h * 1.32:
                continue
            step = b.y - a.y + (b.height - a.height) / 2
            if h * 0.9 <= abs(step) <= h * 1.95:
                (above if step < 0 else below).append(other)
        if len(above) > 1 or len(below) != 1:
            continue
        if above and (not above[0].text.rstrip().endswith(_END) or _item_start(above[0].text)):
            continue
        next_text = below[0].text.strip()
        if _item_start(next_text) or not (
            next_text.endswith(("」", "』", "、", "，", ",", "/")) or _internal_prose(next_text)
        ):
            continue
        opening = replace(row, bounds=a)
        if _can_follow(opening, below[0], opening_quote=True):
            openings[row.track_id] = (opening, below[0].track_id)
    return openings


def _blocks(
    tracks: tuple[TextTrack, ...],
    enabled: bool,
    growing: frozenset[int],
    dash_edges: dict[TextTrack, int],
) -> tuple[TextBlock, ...]:
    ordered = sorted(tracks[:128], key=lambda t: (t.bounds.y, t.bounds.x, t.track_id))
    openings = _quote_openings(ordered, dash_edges) if enabled else {}
    used: set[int] = set()
    blocks: list[TextBlock] = []
    for first in ordered:
        if first.track_id in used:
            continue
        lines = (first,)
        members = {first.track_id}
        revealing = first.track_id in growing
        last_row, continuation = openings.get(first.track_id, (first, None))
        previous_row = None
        if enabled:
            while len(lines) < len(ordered):
                candidates = [
                    line
                    for line in ordered
                    if line.track_id not in used
                    and line.track_id not in members
                    and line.track_id not in openings
                    and _can_follow(
                        last_row,
                        line,
                        revealing=revealing or line.track_id in growing,
                        previous_row=previous_row,
                        opening_quote=line.track_id == continuation,
                    )
                ]
                if len(candidates) != 1:
                    break  # Ambiguous columns/layouts stay separate.
                if (
                    len(lines) == 1
                    and continuation is not None
                    and candidates[0].track_id != continuation
                ):
                    break
                if _paragraph_boundary(lines, last_row, candidates[0]):
                    break
                row = (candidates[0],)
                if len(lines) >= 2 and _dialogue_evidence(lines):
                    row = _row_fragments(
                        candidates[0],
                        tuple(
                            t
                            for t in ordered
                            if t.track_id not in used and t.track_id not in members
                        ),
                        union_bounds(tuple(t.bounds for t in lines)),
                        len(ordered) - len(lines),
                    )
                proposed = (*lines, *row)
                source = join_lines(proposed)
                if len(source) > 512:
                    break
                lines = proposed
                members.update(t.track_id for t in row)
                revealing = revealing or any(t.track_id in growing for t in row)
                # Aggregate geometry is private to adjacency; requests retain every raw member.
                previous_row = last_row.bounds
                last_row = replace(
                    row[0], text=join_lines(row), bounds=union_bounds(tuple(t.bounds for t in row))
                )
                # An unmarked button can share the column width and pitch immediately
                # below the closing quote. Its proximity adds no continuation evidence.
                if continuation is not None and last_row.text.rstrip().endswith(("」", "』", "/")):
                    opener = _DASHED_BRACKET.sub("", first.text.strip())[0]
                    closer = _CLOSING_BRACKET.get(opener)
                    if (
                        closer is None
                        or source.endswith("/")
                        or source.count(closer) >= source.count(opener)
                    ):
                        break
        if len(lines) > 1 and not (
            first.track_id in openings
            or _dialogue_evidence(lines)
            or any(line.track_id in growing for line in lines)
        ):
            lines = (first,)  # Nearby menu labels alone are not evidence of a dialogue box.
        used.update(line.track_id for line in lines)
        dialogue = enabled and (
            len(lines) > 1
            or (
                len(join_lines(lines)) >= 10
                and _dialogue_evidence(lines)
                and (first.track_id in growing or bool(_QUOTE.match(first.text.lstrip())))
            )
        )
        blocks.append(TextBlock(lines, dialogue=dialogue))
    return tuple(blocks)


class DialogueGrouper:
    """Wait briefly for a whole group to settle; never queue partial old paragraphs."""

    def __init__(self, settle_seconds: float = 0.35) -> None:
        self._settle_seconds = settle_seconds
        self._since: dict[tuple[tuple[int, int, str], ...], float] = {}
        self._layout_key: (
            tuple[
                tuple[TextTrack, ...],
                bool,
                frozenset[int],
                tuple[tuple[TextTrack, int], ...],
            ]
            | None
        ) = None
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
        dash_edges: dict[TextTrack, int] | None = None,
    ) -> GroupedText:
        observed = {value.observation.track_id: value for value in activity or ()}
        growing = frozenset(key for key, value in observed.items() if value.growing)
        # Only reveal growth can reserve a different layout before commitment. Ordinary
        # candidate readings must not split/merge accepted groups and revoke their English.
        layout = tuple(
            value.observation
            if (value := observed.get(t.track_id)) and value.pending and value.growing
            else t
            for t in visible
        )
        displayed = {t.track_id: t for t in visible}
        dash_edges = dash_edges or {}
        layout_key = (layout, enabled, growing, tuple(dash_edges.items()))
        if layout_key != self._layout_key:
            self._layout = _blocks(layout[:128], enabled, growing, dash_edges)
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
            len(block.lines) > 1 or (len(block.text) >= 10 and not _is_choice(block.text))
        )
        if not revealing and not dialogue:
            return True  # Ordinary short menu labels need no extra debounce.
        complete = block.text.rstrip().endswith(_END)
        unfinished_prose = revealing or len(block.lines) > 1 or _internal_prose(block.text)
        quiet = 0.18 if complete else 0.55 if unfinished_prose else 0.35
        return now - max(t.changed_at for t in members) >= quiet
