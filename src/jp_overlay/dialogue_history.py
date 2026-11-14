"""Bounded reading history; never supplies transcript context to translation."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass

from jp_overlay.dialogue_classifier import Classification, ClassificationInput
from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.history_layout import PanelLayout
from jp_overlay.history_values import HistoryTurn as HistoryTurn
from jp_overlay.text_content import has_japanese
from jp_overlay.tracking import TextTrack
from jp_overlay.translation_values import TranslatedText, TranslationRequest

_END = tuple("。！？!?」』…")
_MENU = frozenset(
    (
        "詳細",
        "説明",
        "効果",
        "スキル",
        "秘技",
        "天賦",
        "アイテム",
        "装備",
        "能力",
        "所持",
        "確認",
        "戻る",
        "キャンセル",
        "おすすめ",
        "強化",
        "消費",
        "使用効果",
        "基本情報",
    )
)
_STAT = re.compile(r"(?:[+＋]\s*[0-9０-９]|[0-9０-９]\s*[%％]|[Ll][Vv][.．]?\s*[0-9０-９])")
_CHOICE = re.compile(r"^[・•●○◆◇▶▷→]|^[0-9０-９]+[.．、:：)）]")
_NAME_PUNCTUATION = frozenset("。！？!?、，:：%％+＋/／[]【】（）()")
_READING = re.compile(r"(?:\([ぁ-ゖァ-ヺー・ ]+\)|（[ぁ-ゖァ-ヺー・ ]+）)$")


@dataclass(slots=True)
class _Candidate:
    block: TextBlock
    speaker: str | None
    name_source: str
    name_request: TranslationRequest | None
    since: float
    seen: float
    entry: int | None = None
    peers: tuple[TextBlock, ...] = ()


@dataclass(frozen=True, slots=True)
class _ChoiceEvidence:
    block: TextBlock
    header: tuple[str, ...]


def _same_panel(a: TextBlock, b: TextBlock) -> bool:
    unit = max(a.line_height, b.line_height, 12)
    aligned = abs(a.bounds.x - b.bounds.x) <= unit * 2 or _centered(a, b, unit * 2)
    return aligned and abs(a.bounds.y - b.bounds.y) <= unit * 2


def _centered(a: TextBlock, b: TextBlock, tolerance: float) -> bool:
    return abs((a.bounds.x + a.bounds.width / 2) - (b.bounds.x + b.bounds.width / 2)) <= tolerance


class _SpeakerIndex:
    """One scene's bottom-edge index; query only the narrow speaker band above a body."""

    def __init__(self, blocks: tuple[TextBlock, ...]) -> None:
        self._rows: list[tuple[TextBlock, Rect]] = sorted(
            ((block, block.bounds) for block in blocks), key=lambda row: row[1].y + row[1].height
        )
        self._bottoms = [bounds.y + bounds.height for _, bounds in self._rows]

    def above(self, block: TextBlock) -> list[TextBlock]:
        b, unit = block.bounds, block.line_height
        start = bisect_left(self._bottoms, b.y - unit * 2.4)
        end = bisect_right(self._bottoms, b.y + unit * 0.15)
        return [
            other
            for other, bounds in self._rows[start:end]
            if other != block
            and (
                b.x - unit * 1.5 <= bounds.x <= b.x + max(unit * 2, b.width * 0.5)
                or abs((b.x + b.width / 2) - (bounds.x + bounds.width / 2)) <= unit * 0.75
            )
        ]


class DialogueHistory:
    """Twenty completed turns, bounded candidates, no images or I/O.

    Model mode admits exact current publications only after a semantic verdict. Explicit
    layout-only mode retains conservative lower-screen heuristics. Neither mode supplies
    translation context or invents speakers; names additionally need exact OCR confidence.
    """

    def __init__(self) -> None:
        self._turns: tuple[HistoryTurn, ...] = ()
        self._candidate: _Candidate | None = None
        self._resume: _Candidate | None = None
        self._scores: dict[TextTrack, float] = {}
        self._ready: set[TranslationRequest] = set()
        self._eligible = False
        self._number = 0
        self._now = 0.0
        self._scene_key: tuple[object, ...] | None = None
        self._assisted = False
        self._candidates: dict[ClassificationInput, _Candidate] = {}
        self._resume_candidates: tuple[_Candidate, ...] = ()
        self._verdicts: dict[ClassificationInput, Classification] = {}
        self._layout = PanelLayout()
        self._choice_blocks: dict[tuple[tuple[int, int, str], ...], _ChoiceEvidence] = {}

    @property
    def turns(self) -> tuple[HistoryTurn, ...]:
        return self._turns

    def clear(self) -> None:
        """Clear the reader without immediately re-adding the currently visible turn."""
        self._turns = ()
        # Leave its entry token in place: a correction after Clear is not a new turn.

    def start(self) -> None:
        self._turns = ()
        self._number = 0
        self.reset_scene()
        self._resume = None
        self._resume_candidates = ()

    def reset_scene(self) -> None:
        """Forget panel evidence on resets, but retain the completed transcript."""
        self._resume = self._candidate or self._resume
        self._candidate = None
        self._scores.clear()
        self._ready.clear()
        self._eligible = False
        self._scene_key = None
        self._resume_candidates = tuple(self._candidates.values()) or self._resume_candidates
        self._candidates.clear()
        self._verdicts.clear()
        self._layout = PanelLayout()
        self._choice_blocks.clear()

    def observe(
        self,
        blocks: tuple[TextBlock, ...],
        ready: tuple[TextBlock, ...],
        size: tuple[int, int],
        now: float,
        *,
        scores: Mapping[TextTrack, float] | None = None,
        corrections: tuple[tuple[TextTrack, TextTrack], ...] = (),
        assisted: bool = False,
    ) -> None:
        self._now = now
        blocks = blocks[:128]
        visible = {line for block in blocks for line in block.lines}
        self._scores = {t: score for t, score in self._scores.items() if t in visible}
        for track, score in (scores or {}).items():
            if track in visible:
                self._scores[track] = max(score, self._scores.get(track, 0))
        self._ready = {TranslationRequest.from_block(b) for b in ready[:128]}
        current_keys = {b.key for b in blocks}
        self._choice_blocks = {k: b for k, b in self._choice_blocks.items() if k in current_keys}
        self._assisted = assisted
        # Scene evidence is independent of readiness, settling time and model replies.
        # Detector order is irrelevant; confidence/corrections and new choice evidence
        # must still invalidate the analysis even when the visible strings are unchanged.
        scene_key = (
            frozenset((block, block.dialogue) for block in blocks),
            size,
            frozenset(self._scores.items()),
            frozenset(corrections),
            frozenset(self._choice_blocks.items()),
            assisted,
        )
        if assisted:
            for candidate in self._candidates.values():
                candidate.seen = now
            if scene_key == self._scene_key:
                return
            self._scene_key = scene_key
            self._observe_assisted(blocks, now, corrections)
            return
        # Changing grouping or waiting for a model does not end an utterance whose
        # accepted lines are still present. Repeated polling is not new evidence.
        if self._candidate and all(t in visible for t in self._candidate.block.lines):
            self._candidate.seen = now
        previous = self._candidate
        if previous and now - previous.seen > 2:
            self._candidate = previous = None
        # UI/completion polls often have the same accepted scene. Reclassify only
        # changed layout/text/name evidence, but keep time and readiness current.
        if scene_key == self._scene_key:
            return
        self._scene_key, self._eligible = scene_key, False
        choices = []
        speakers = _SpeakerIndex(blocks)
        for block in blocks:
            if not self._body(block, size):
                continue
            neighbours = speakers.above(block)
            if any(b.text.strip() in _MENU or _STAT.search(b.text) for b in neighbours):
                continue
            names = [b for b in neighbours if self._name(b, block)]
            if len(names) > 1:
                continue
            established = previous is not None and _same_panel(previous.block, block)
            if (
                not names
                and not established
                and not (not neighbours and self._anonymous_subtitle(block, size))
            ):
                continue
            name = names[0].text.strip() if names else ""
            speaker = (
                name
                if names
                and set(name) - set("?？")
                and self._scores.get(names[0].lines[0], 0) >= 0.90
                else None
            )
            # Two prose blocks in the same dialogue band are usually choices or menus.
            competitors = [
                other
                for other in blocks
                if other != block
                and other not in names
                and len(other.text) >= 8
                and abs(other.bounds.y - block.bounds.y) < block.line_height * 3
                and (
                    other.dialogue
                    or other.text.endswith(_END)
                    or abs(other.bounds.x - block.bounds.x) < block.line_height
                    or _centered(other, block, block.line_height * 1.25)
                )
            ]
            if not competitors:
                choices.append((block, speaker, name, names[0] if names else None))
        if len(choices) != 1:
            return
        block, speaker, name, name_block = choices[0]
        previous = previous or self._resume
        self._resume = None  # Reset evidence may deduplicate, never establish a new panel.
        same = previous is not None and _same_panel(previous.block, block)
        if same and previous:
            # An absent/uncertain label must not inherit another character's name.
            same_name = not (previous.speaker and speaker and previous.speaker != speaker)
            predecessors = dict(corrections)
            corrected = len(block.lines) == len(previous.block.lines) and all(
                current == old or predecessors.get(current) == old
                for current, old in zip(block.lines, previous.block.lines, strict=True)
            )
            growth = block.text.startswith(previous.block.text) and any(
                t.track_id == old.track_id for t in block.lines for old in previous.block.lines
            )
            same = (same_name or not name or not previous.name_source) and (
                block.text == previous.block.text or corrected or growth
            )
        entry = previous.entry if previous and same else None
        since = previous.since if previous and previous.block.key == block.key else now
        name_request = TranslationRequest.from_block(name_block) if name_block else None
        self._candidate = _Candidate(block, speaker, name, name_request, since, now, entry)
        self._eligible = True

    def published(self, results: tuple[TranslatedText, ...]) -> None:
        if self._assisted:
            by_block = {c.block: self._verdicts.get(k) for k, c in self._candidates.items()}
            for key, candidate in self._candidates.items():
                verdict = self._verdicts.get(key)
                peers = [by_block[b] for b in candidate.peers if b in by_block]
                # Resolve possible alternatives together before recording any member.
                # A slow or failed sibling check affects only history, never translation.
                if (verdict and verdict.kind == "choice") or any(
                    v and v.kind == "choice" for v in peers
                ):
                    for b in candidate.peers or (candidate.block,):
                        self._choice_blocks[b.key] = _ChoiceEvidence(b, self._header_source(b))
                    # A slowly revealed list can initially resemble one spoken line.
                    # Correct only this still-live entry, never unrelated past turns.
                    self._turns = tuple(t for t in self._turns if t.number != candidate.entry)
                    candidate.entry = None
                    continue
                if any(v is None for v in peers):
                    continue
                if verdict and verdict.kind == "dialogue":
                    self._choice_blocks.pop(candidate.block.key, None)
                    self._publish_candidate(candidate, results, named=verdict.speaker == "yes")
            return
        candidate = self._candidate
        if not self._eligible or candidate is None:
            return
        self._publish_candidate(candidate, results)

    def _header_source(self, block: TextBlock) -> tuple[str, ...]:
        header = self._layout.header(block)
        return tuple(b.text for b in header.parts) if header else ()

    def _publish_candidate(
        self, candidate: _Candidate, results: tuple[TranslatedText, ...], *, named: bool = True
    ) -> None:
        block = candidate.block
        speaker = candidate.speaker if named else None
        request = TranslationRequest.from_block(block)
        # Extra reader settling never delays inference or the overlay. Retained English
        # for an older revision/group is not a completed source for this transcript.
        settle = 0.45 if block.text.endswith(_END) else 1.2
        if request not in self._ready or self._now - candidate.since < settle:
            return
        result = next((r for r in results if r.request == request), None)
        if result is None or not result.english.strip() or len(result.english) > 8192:
            return
        # Reuse only a current, ready speaker translation supplied by the live owner.
        # Do not guess names, reuse a previous character/model's reply, or request
        # extra inference when the user's routing excludes short labels.
        speaker_english = next(
            (
                r.english.strip()
                for r in results
                if speaker
                and candidate.name_request in self._ready
                and r.request == candidate.name_request
                and 0 < len(r.english.strip()) <= 160
            ),
            None,
        )
        if candidate.entry is None:
            self._number += 1
            candidate.entry = self._number
            self._turns = (
                *self._turns,
                HistoryTurn(self._number, block.text, result.english, speaker, speaker_english),
            )[-20:]
        else:
            self._turns = tuple(
                HistoryTurn(t.number, block.text, result.english, speaker, speaker_english)
                if t.number == candidate.entry
                else t
                for t in self._turns
            )

    def _observe_assisted(
        self,
        blocks: tuple[TextBlock, ...],
        now: float,
        corrections: tuple[tuple[TextTrack, TextTrack], ...],
    ) -> None:
        """Geometry proposes bounded candidates; semantics decides admission, never grouping."""
        resuming = not self._candidates
        previous = tuple(self._candidates.values()) or self._resume_candidates
        if blocks:
            self._resume_candidates = ()
        visible = {line for block in blocks for line in block.lines}
        # A grouping toggle is not a new utterance. Keep the whole candidate while
        # its exact accepted members remain, without classifying retained-only work.
        reserved = {
            k: c
            for k, c in self._candidates.items()
            if c.block not in blocks and all(t in visible for t in c.block.lines)
        }
        # Preserve the same context while a whole paragraph is temporarily split by
        # the grouping toggle. Fragment translations never become history sources.
        effective = tuple(
            b
            for b in blocks
            if not any(set(b.lines) < set(c.block.lines) for c in reserved.values())
        ) + tuple(c.block for c in reserved.values())
        self._layout.update(effective)
        # A title may arrive before its name/body. Retract only a still-visible
        # entry whose exact source now belongs to a compact speaker header.
        labels = {b.key: b for b in effective if self._layout.is_header_label(b)}
        label_entries = {
            c.entry
            for c in previous
            if c.block.key in labels and _same_panel(labels[c.block.key], c.block)
        }
        self._turns = tuple(t for t in self._turns if t.number not in label_entries)
        current: dict[ClassificationInput, _Candidate] = {
            k: c for k, c in reserved.items() if not self._layout.is_header_label(c.block)
        }
        predecessors = dict(corrections)
        exact = {c.block.key: c for c in previous}
        by_track: dict[int, dict[int, _Candidate]] = {}
        by_text: dict[str, dict[int, _Candidate]] = {}
        for index, candidate in enumerate(previous):
            for line in candidate.block.lines:
                by_track.setdefault(line.track_id, {})[index] = candidate
            if resuming:
                by_text.setdefault(candidate.block.text, {})[index] = candidate
        speakers = _SpeakerIndex(blocks)
        for block in sorted(blocks, key=lambda b: (b.bounds.y, b.bounds.x)):
            if any(set(block.lines) < set(c.block.lines) for c in reserved.values()):
                continue
            if len(current) >= 128:
                break
            text = block.text.strip()
            known_choice = self._choice_blocks.get(block.key)
            header_source = self._header_source(block)
            if (
                not 2 <= len(text) <= 512
                or not has_japanese(text)
                or any(t.vertical for t in block.lines)
                or self._layout.is_header_label(block)
                or self._layout.marked_choice(block)
                or (
                    known_choice is not None
                    and _same_panel(known_choice.block, block)
                    # A newly discovered name/title is new role evidence. Merely
                    # hiding sibling options still cannot turn a choice into speech.
                    and not (header_source and header_source != known_choice.header)
                )
                or (len(text) >= 8 and block.bounds.width < block.line_height * 4)
            ):
                continue
            neighbours = speakers.above(block)
            names = [
                b
                for b in neighbours
                if len(b.lines) == 1
                and b not in self._layout.peers(block)
                and self._layout.header(b) is None
                and 1 <= len(b.text) <= 64
                and b.bounds.width <= block.line_height * 20
                and 0.45 <= b.line_height / max(1, block.line_height) <= 1.5
            ]
            header = self._layout.header(block)
            name_block = header.primary if header else names[0] if len(names) == 1 else None
            if len(text) < 8 and name_block is None and not self._layout.peers(block):
                continue
            name = name_block.text if name_block else ""
            # Canonical relations/exact relevant text enter cache identity, not track IDs,
            # pixel jitter, unrelated HUD labels, observation order or timestamps.
            key = ClassificationInput(text, name, self._layout.context(block, name_block))
            old = exact.get(block.key)
            if old and not _same_panel(old.block, block):
                old = None
            related = dict(by_text.get(text, {})) if resuming else {}
            if old is None:
                for line in block.lines:
                    related.update(by_track.get(line.track_id, {}))
            old = old or next(
                (
                    c
                    for _, c in sorted(related.items())
                    if _same_panel(c.block, block)
                    and (
                        c.block.key == block.key
                        or (resuming and c.block.text == text)
                        or (
                            any(
                                t.track_id == o.track_id for t in block.lines for o in c.block.lines
                            )
                            and (
                                text.startswith(c.block.text)
                                or (
                                    len(block.lines) == len(c.block.lines)
                                    and all(
                                        t == o or predecessors.get(t) == o
                                        for t, o in zip(block.lines, c.block.lines, strict=True)
                                    )
                                )
                            )
                        )
                    )
                ),
                None,
            )
            speaker = (
                name
                if name_block
                and all(self._scores.get(line, 0) >= 0.90 for line in name_block.lines)
                and set(name) - set("?？")
                else None
            )
            current[key] = _Candidate(
                block,
                speaker,
                name,
                TranslationRequest.from_block(name_block) if name_block else None,
                old.since
                if old
                and old.block.key == block.key
                and old.name_source == name
                and self._candidates.get(key) is old
                else now,
                now,
                old.entry if old else None,
                self._layout.peers(block),
            )
        self._candidates = current
        self._verdicts = {k: v for k, v in self._verdicts.items() if k in current}

    def classification_requests(self) -> tuple[ClassificationInput, ...]:
        return tuple(
            k
            for k, c in self._candidates.items()
            if TranslationRequest.from_block(c.block) in self._ready
            and self._now - c.since >= (0.45 if c.block.text.endswith(_END) else 1.2)
        )

    def accept_classifications(
        self, results: tuple[tuple[ClassificationInput, Classification], ...]
    ) -> None:
        self._verdicts = {k: v for k, v in results if k in self._candidates}

    @staticmethod
    def _body(block: TextBlock, size: tuple[int, int]) -> bool:
        w, h = size
        b = block.bounds
        return (
            w > 0
            and h > 0
            and 2 <= len(block.text) <= 2048
            and has_japanese(block.text)
            and not any(t.vertical for t in block.lines)
            and not _CHOICE.match(block.text)
            and not _STAT.search(block.text)
            and 0.06 * w <= b.x <= 0.55 * w
            and b.x + b.width <= 0.95 * w
            and 0.53 * h <= b.y
            and b.y + b.height <= 0.98 * h
            and b.height <= 0.28 * h
            and 0.01 * h <= block.line_height <= 0.08 * h
            and (block.dialogue or block.text.endswith(_END) or len(block.text) >= 24)
        )

    @staticmethod
    def _anonymous_subtitle(block: TextBlock, size: tuple[int, int]) -> bool:
        """Strong subtitle geometry can establish speech without inventing a speaker.

        This is intentionally narrower than the named-panel path. Description/menu,
        competitor and source-readiness checks still apply; no semantic certainty is implied.
        """
        width, height = size
        bounds, unit = block.bounds, block.line_height
        return (
            len(block.lines) <= 3
            and len(block.text) >= 12
            and block.text.endswith(_END)
            and bounds.y >= height * 0.68
            and bounds.height <= height * 0.16
            and bounds.width >= width * 0.3
            and all(
                abs(line.bounds.x + line.bounds.width / 2 - width / 2) <= unit * 1.5
                for line in block.lines
            )
        )

    @staticmethod
    def _name(name: TextBlock, body: TextBlock) -> bool:
        text = name.text.strip()
        # A parenthesized kana reading is part of a name, not a menu annotation.
        # Validate its base normally; retain the exact full source for identity/confidence.
        base = _READING.sub("", text).strip()
        # Some subtitle UIs center a larger speaker label above the body. Keep the
        # ordinary small-label limit elsewhere; a large nearby heading is not a name.
        maximum_height = 1.5 if _centered(name, body, body.line_height) else 1.15
        return (
            len(name.lines) == 1
            and not name.lines[0].vertical
            and 1 <= len(text) <= 18
            and (any(c.isalpha() for c in text) or not set(text) - set("?？"))
            and not text.isnumeric()
            and bool(base)
            and (not any(c in _NAME_PUNCTUATION for c in base) or not set(base) - set("?？"))
            and base not in _MENU
            and name.bounds.width <= body.line_height * 18
            and body.line_height * 0.45 <= name.line_height <= body.line_height * maximum_height
        )
