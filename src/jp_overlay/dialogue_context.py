"""Small, explicitly scoped conversation memory; never a screen-wide transcript."""

from dataclasses import dataclass
from difflib import SequenceMatcher

from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock


@dataclass(frozen=True, slots=True)
class DialogueTurn:
    source: str
    english: str


def _same_panel(a: Rect, b: Rect) -> bool:
    height = max(20, min(a.height, b.height))
    return abs(a.x - b.x) <= height and abs(a.y - b.y) <= height


def _same_utterance(a: str, b: str) -> bool:
    return a.startswith(b) or b.startswith(a) or SequenceMatcher(None, a, b).ratio() >= 0.82


class DialogueMemory:
    """At most two complete published turns / 512 characters, expiring after 30s.

    Only one unambiguous dialogue panel may own history. Short menu labels never
    qualify. Revisions of a revealing/corrected utterance replace its history entry.
    """

    def __init__(self) -> None:
        self._history: tuple[DialogueTurn, ...] = ()
        self._bounds: Rect | None = None
        self._current: TextBlock | None = None
        self._last_seen = float("-inf")
        self._last_published = float("-inf")

    def reset(self) -> None:
        self.__init__()

    def observe(self, blocks: tuple[TextBlock, ...], now: float) -> None:
        if now - self._last_seen > 3 or (self._history and now - self._last_published > 30):
            self._history = ()
            self._bounds = None
        candidates = tuple(
            b
            for b in blocks
            if b.dialogue
            or (
                self._bounds is not None
                and _same_panel(self._bounds, b.bounds)
                and b.text.endswith(tuple("。！？!?」』"))
                and len(b.text) >= 2
                and not b.text.startswith(tuple("・•●○◆◇▶▷→0123456789０１２３４５６７８９"))
            )
        )
        if len(candidates) != 1:
            self._current = None
            if candidates:
                self.reset()  # Ambiguous panels/choices do not share a conversation.
            return
        current = candidates[0]
        if self._bounds is not None and not _same_panel(self._bounds, current.bounds):
            self._history = ()
        self._current, self._bounds, self._last_seen = current, current.bounds, now

    def context_for(self, block: TextBlock) -> tuple[DialogueTurn, ...]:
        if self._current is None or block.key != self._current.key:
            return ()
        return tuple(t for t in self._history if not _same_utterance(t.source, block.text))

    def published(self, block: TextBlock, english: str, now: float) -> None:
        if self._current is None or self._current.key != block.key:
            return
        history = tuple(t for t in self._history if not _same_utterance(t.source, block.text))
        turn = DialogueTurn(block.text, english)
        if len(turn.source) + len(turn.english) > 512:
            return
        history = (*history, turn)[-2:]
        while sum(len(t.source) + len(t.english) for t in history) > 512:
            history = history[1:]
        self._history, self._last_published = history, now
