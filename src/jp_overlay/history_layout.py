"""Bounded spatial context for the reader; never changes OCR or translation grouping.

Four sorted edge indexes find local directional neighbours. Reciprocal vertical edges
form candidate lists; common alignment and consistent font-relative gaps constrain the
chains. This is a layout hypothesis, not proof that conversational text is a choice.
Only the latest scene is retained. Model identity uses relations, not pixel coordinates.
"""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from hashlib import blake2s
from statistics import median

from jp_overlay.domain import Rect, union_bounds
from jp_overlay.grouping import TextBlock

_MARKER = re.compile(r"^(?:[・•●○◆◇▶▷→]|[0-9０-９①-⑳]+[.．、:：)）]|[A-Za-z][.．)）])")


@dataclass(frozen=True, slots=True)
class PanelNeighbor:
    text: str
    relation: str
    alignment: str
    font: str
    multiline: bool
    digest: str = ""


@dataclass(frozen=True, slots=True)
class PanelContext:
    neighbors: tuple[PanelNeighbor, ...] = ()
    stacked_rows: int = 0
    detached_response: bool = False

    def payload(self) -> dict[str, object]:
        return {
            "layout": (
                "possible_response_options"
                if self.stacked_rows
                else "possible_single_response"
                if self.detached_response
                else "nearby_text"
            ),
            "stacked_rows": self.stacked_rows,
            "neighbors": [
                {
                    "text": n.text,
                    "relation": n.relation,
                    "alignment": n.alignment,
                    "font": n.font,
                    "multiline": n.multiline,
                }
                for n in self.neighbors
            ],
        }


@dataclass(frozen=True, slots=True)
class SpeakerHeader:
    """A compact two-line header, distinct from the utterance it labels.

    Primary is an existing translation block, never a synthetic translation source.
    The larger label is normally the name; equal sizes retain reading order.
    """

    primary: TextBlock
    parts: tuple[TextBlock, ...]


@dataclass(frozen=True, slots=True)
class _PanelAnchor:
    body: TextBlock
    header: SpeakerHeader
    column: Rect
    bounds: Rect
    reach: float


def _compact_label(block: TextBlock) -> bool:
    text = block.text.strip()
    return (
        1 <= len(text) <= 64
        and len(block.lines) <= 2
        and not any(t.vertical for t in block.lines)
        and not _MARKER.match(text)
        and (not any(c in text for c in "。！？!?、，") or not set(text) - set("?？"))
    )


def _alignments(a: TextBlock, b: TextBlock) -> tuple[str, ...]:
    unit = max(a.line_height, b.line_height, 1)
    first, second = a.bounds, b.bounds
    offsets = (
        (abs(first.x - second.x), "left"),
        (abs(first.x + first.width / 2 - second.x - second.width / 2), "center"),
        (abs(first.x + first.width - second.x - second.width), "right"),
    )
    return tuple(name for error, name in offsets if error <= unit * 0.75)


def _alignment(a: TextBlock, b: TextBlock) -> str:
    # Prefer left for full-width rows where both ends happen to align.
    return next(iter(_alignments(a, b)), "overlap")


def _font(a: TextBlock, b: TextBlock) -> str:
    ratio = b.line_height / max(1, a.line_height)
    return "smaller" if ratio < 0.75 else "larger" if ratio > 1.35 else "similar"


def _excerpt(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit // 2] + "…" + text[-(limit // 2 - 1) :]


class PanelLayout:
    """One bounded neighbour graph, reused during unchanged observation/UI polls.

    Index construction is O(n log n); queries inspect only nearby axis strips. Dense
    overlapping layouts remain O(n²), bounded to 128 blocks, without a distance matrix.
    Context uses a local neighbourhood, not transitive connected-component expansion:
    one bridging label cannot pull the entire HUD into a dialogue prompt.
    """

    def __init__(self) -> None:
        self._input: tuple[TextBlock, ...] = ()
        self._blocks: tuple[TextBlock, ...] = ()
        self._neighbors: dict[TextBlock, tuple[tuple[str, TextBlock], ...]] = {}
        self._peers: dict[TextBlock, tuple[TextBlock, ...]] = {}
        self._headers: dict[TextBlock, SpeakerHeader] = {}
        self._labels: set[TextBlock] = set()
        self._side_panels: dict[TextBlock, _PanelAnchor] = {}

    def update(self, blocks: tuple[TextBlock, ...]) -> None:
        blocks = blocks[:128]
        if blocks == self._input:
            return
        self._input = blocks
        ordered = tuple(sorted(blocks[:128], key=lambda b: (b.bounds.y, b.bounds.x, b.key)))
        if ordered == self._blocks:
            return
        self._blocks = ordered
        self._neighbors, self._peers, self._headers, self._labels = {}, {}, {}, set()
        self._side_panels = {}
        boxes = tuple(b.bounds for b in ordered)
        heights = tuple(max(1, b.line_height) for b in ordered)
        vertical = tuple(any(t.vertical for t in b.lines) for b in ordered)
        # Index the edge facing the query, not centers (long paragraphs have large boxes).
        edges = {
            "above": tuple(b.y + b.height for b in boxes),
            "below": tuple(b.y for b in boxes),
            "left": tuple(b.x + b.width for b in boxes),
            "right": tuple(b.x for b in boxes),
        }
        indexes = {
            direction: sorted((edge, i) for i, edge in enumerate(values))
            for direction, values in edges.items()
        }
        coordinates = {direction: [v for v, _ in values] for direction, values in indexes.items()}
        for block_index, block in enumerate(ordered):
            box, unit = boxes[block_index], heights[block_index]
            limits = {
                "above": (box.y - unit * 6, box.y),
                "below": (box.y + box.height, box.y + box.height + unit * 6),
                "left": (box.x - unit * 3, box.x),
                "right": (box.x + box.width, box.x + box.width + unit * 3),
            }
            neighbors = []
            for direction, (low, high) in limits.items():
                coords = coordinates[direction]
                possible = indexes[direction][bisect_left(coords, low) : bisect_right(coords, high)]
                candidates = []
                for edge, index in possible:
                    if index == block_index or vertical[index]:
                        continue
                    ob = boxes[index]
                    if direction in ("above", "below"):
                        overlap = min(box.x + box.width, ob.x + ob.width) - max(box.x, ob.x)
                        extent = min(box.width, ob.width)
                        gap = box.y - edge if direction == "above" else edge - box.y - box.height
                    else:
                        overlap = min(box.y + box.height, ob.y + ob.height) - max(box.y, ob.y)
                        extent = min(box.height, ob.height)
                        gap = box.x - edge if direction == "left" else edge - box.x - box.width
                    if overlap < max(1, extent) * 0.6 or not 0.45 <= heights[index] / unit <= 1.8:
                        continue
                    candidates.append((gap / unit, index))
                candidates.sort()
                # Ambiguous/overlapping detections are not reliable context anchors.
                if candidates and (
                    len(candidates) == 1 or candidates[1][0] - candidates[0][0] > 0.35
                ):
                    neighbors.append((direction, ordered[candidates[0][1]]))
            self._neighbors[block] = tuple(neighbors)
        self._find_headers()
        self._find_lists()
        self._find_side_panels()

    def _find_headers(self) -> None:
        # Follow at most two reciprocal above edges. This is a local hierarchy,
        # not a connected component that can swallow adjacent UI panels.
        proposals: dict[TextBlock, SpeakerHeader] = {}
        for body in self._blocks:
            lower = next((b for d, b in self._neighbors[body] if d == "above"), None)
            if lower is None or ("below", body) not in self._neighbors[lower]:
                continue
            unit = max(1, body.line_height)
            gap = body.bounds.y - lower.bounds.y - lower.bounds.height
            if (
                len(body.text) < 2
                or any(t.vertical for t in body.lines)
                or not 0.8 * unit <= gap <= 2.4 * unit
            ):
                continue
            parts = (lower,)
            if len(lower.lines) == 1:
                upper = next((b for d, b in self._neighbors[lower] if d == "above"), None)
                if upper is None or ("below", lower) not in self._neighbors[upper]:
                    continue
                parts = (upper, lower)
            lines = tuple(t for b in parts for t in b.lines)
            if len(lines) != 2 or not all(_compact_label(b) for b in parts):
                continue
            first, second = (TextBlock((t,)) for t in sorted(lines, key=lambda t: t.bounds.y))
            separation = second.bounds.y - first.bounds.y - first.bounds.height
            # A greeting may be narrower than the name. In that case require
            # sentence evidence plus compact labels, not a minimum utterance length.
            wide_body = all(b.bounds.width <= body.bounds.width * 0.55 for b in (first, second))
            short_speech = (
                len(body.text) <= 24
                and body.text.rstrip().endswith(tuple("。！？!?…"))
                and body.bounds.width >= unit * 2
            )
            if (
                not 0 <= separation <= max(first.line_height, second.line_height) * 0.65
                or not set(_alignments(first, second)).intersection(_alignments(body, first))
                or any(
                    b.bounds.width > b.line_height * 18 or not 0.45 <= b.line_height / unit <= 1.8
                    for b in (first, second)
                )
                or not (wide_body or short_speech)
            ):
                continue
            proposals[body] = SpeakerHeader(max(parts, key=lambda b: b.line_height), parts)
        # An overlapping hierarchy is ambiguous; never turn one candidate body
        # into another's metadata. A future observation can resolve it.
        self._headers = {
            b: header
            for b, header in proposals.items()
            if not any(p in proposals for p in header.parts)
        }
        self._labels = {p for header in self._headers.values() for p in header.parts}

    def header(self, block: TextBlock) -> SpeakerHeader | None:
        return self._headers.get(block)

    def is_header_label(self, block: TextBlock) -> bool:
        return block in self._labels

    def _find_side_panels(self) -> None:
        """Offer a detached row its nearby named panel, even without sibling options.

        Vertical range queries use expanded header envelopes; horizontal gaps are
        measured from the header column, not a long subtitle's variable width.
        This is only model context, never a choice verdict or a grouping edge.
        """
        anchors = []
        for body, header in self._headers.items():
            column = union_bounds(tuple(b.bounds for b in header.parts))
            unit = max(1, body.line_height)
            reach = min(unit * 16, max(unit * 8, column.width))
            bounds = union_bounds((column, body.bounds))
            anchors.append(_PanelAnchor(body, header, column, bounds, reach))
        index = sorted((a.bounds.y - a.reach, i) for i, a in enumerate(anchors))
        tops = [top for top, _ in index]
        for block in self._blocks:
            if (
                block in self._headers
                or block in self._labels
                or any(t.vertical for t in block.lines)
            ):
                continue
            box = block.bounds
            matches = []
            for _, i in index[: bisect_right(tops, box.y + box.height)]:
                anchor = anchors[i]
                if box.y > anchor.bounds.y + anchor.bounds.height + anchor.reach:
                    continue
                unit = max(1, anchor.body.line_height)
                dx = max(
                    anchor.column.x - box.x - box.width,
                    box.x - anchor.column.x - anchor.column.width,
                )
                dy = max(
                    0,
                    anchor.bounds.y - box.y - box.height,
                    box.y - anchor.bounds.y - anchor.bounds.height,
                )
                if (
                    unit * 0.5 <= dx <= anchor.reach * 1.75
                    and dy <= anchor.reach
                    and 0.65 <= block.line_height / unit <= 1.35
                    and unit * 2 <= box.width <= unit * 20
                ):
                    matches.append(((dx + dy) / anchor.reach, i))
            matches.sort()
            if matches and (len(matches) == 1 or matches[1][0] - matches[0][0] > 0.5):
                self._side_panels[block] = anchors[matches[0][1]]

    def _find_lists(self) -> None:
        following: dict[TextBlock, TextBlock] = {}
        for block, neighbors in self._neighbors.items():
            below = next((b for direction, b in neighbors if direction == "below"), None)
            if below is None or ("above", block) not in self._neighbors[below]:
                continue
            if any(b in self._labels or b in self._headers for b in (block, below)):
                continue  # Header/body edges are hierarchical, not alternative rows.
            a, b = block.bounds, below.bounds
            unit = max(1, block.line_height, below.line_height)
            gap = (b.y - a.y - a.height) / unit
            if (
                0.8 <= gap <= 4
                and max(block.line_height, below.line_height)
                <= min(block.line_height, below.line_height) * 1.3
                and _alignment(block, below) != "overlap"
                and min(a.width, b.width) >= unit * 2
                and (
                    min(a.width, b.width) >= max(a.width, b.width) * 0.3
                    or max(a.width, b.width) <= unit * 8
                )
                and 2 <= len(block.text) <= 512
                and 2 <= len(below.text) <= 512
            ):
                following[block] = below
        for root in self._blocks:
            if root not in following or root in self._peers:
                continue
            chain = [root]
            gaps: list[float] = []
            alignments = {"left", "center", "right"}
            while chain[-1] in following and len(chain) < 8:
                prev, next_block = chain[-1], following[chain[-1]]
                gap = (next_block.bounds.y - prev.bounds.y - prev.bounds.height) / max(
                    1, prev.line_height, next_block.line_height
                )
                # Reject drifting columns and changing paragraph/list spacing.
                common = alignments.intersection(_alignments(root, next_block))
                if not common:
                    break
                if gaps and abs(gap - median(gaps)) > max(0.4, median(gaps) * 0.3):
                    break
                chain.append(next_block)
                gaps.append(gap)
                alignments = common
            if len(chain) >= 2:
                for block in chain:
                    self._peers[block] = tuple(chain)

    def peers(self, block: TextBlock) -> tuple[TextBlock, ...]:
        return self._peers.get(block, ())

    def marked_choice(self, block: TextBlock) -> bool:
        return bool(_MARKER.match(block.text.strip())) or any(
            _MARKER.match(peer.text.strip()) for peer in self.peers(block)
        )

    def context(self, block: TextBlock, speaker: TextBlock | None = None) -> PanelContext:
        peers = self.peers(block)
        header = self.header(block)
        selected = [("speaker_detail", b) for b in header.parts if b != speaker] if header else []
        side = self._side_panels.get(block) if speaker is None else None
        if side:
            selected.extend((("headed_text", side.body), ("panel_speaker", side.header.primary)))
            selected.extend(
                ("panel_speaker_detail", b) for b in side.header.parts if b != side.header.primary
            )
        # Peers take priority over incidental controls; at most four excerpts/192 chars.
        selected.extend(("sibling", b) for b in peers if b != block and b != speaker)
        used = {b for _, b in selected} | {block, speaker}
        selected.extend(
            ("headed_text" if b in self._headers else direction, b)
            for direction, b in self._neighbors.get(block, ())
            if b not in used
        )
        selected = selected[:4]
        limit = 192 // max(1, len(selected))
        return PanelContext(
            tuple(
                PanelNeighbor(
                    _excerpt(b.text, limit),
                    direction,
                    next(iter(_alignments(block, b)), "none") if side else _alignment(block, b),
                    _font(block, b),
                    len(b.lines) > 1,
                    blake2s(b.text.encode(), digest_size=8).hexdigest(),
                )
                for direction, b in selected
            ),
            len(peers),
            side is not None,
        )
