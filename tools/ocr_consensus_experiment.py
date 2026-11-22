"""Replay-only OCR evidence experiment. Never imported by the live application.

Align bounded observations to one committed revision, vote on edit locations, and
propose an actual observed reading (never a synthesized sentence). Repeated samples
from one OCR engine are correlated: unknown visual evidence cannot establish truth.
"""

from collections import Counter, deque
from dataclasses import dataclass
from math import ceil
from typing import Literal

from dantetl.domain import Rect
from dantetl.ocr.observation import TextTrack

Edit = tuple[int, int, str]


def _edits(old: str, new: str) -> tuple[Edit, ...] | None:
    """Unit-cost banded DP with traceback, capped at eight code-point edits."""
    limit = 8
    if max(len(old), len(new)) > 512 or abs(len(old) - len(new)) > limit:
        return None
    costs = {(0, j): j for j in range(min(limit, len(new)) + 1)}
    for i in range(1, len(old) + 1):
        for j in range(max(0, i - limit), min(len(new), i + limit) + 1):
            value = min(
                costs.get((i - 1, j), limit + 1) + 1,
                costs.get((i, j - 1), limit + 1) + 1,
                costs.get((i - 1, j - 1), limit + 1) + (old[i - 1] != new[j - 1])
                if j
                else limit + 1,
            )
            if value <= limit:
                costs[i, j] = value
    if (len(old), len(new)) not in costs:
        return None
    i, j = len(old), len(new)
    edits: list[Edit] = []
    while i or j:
        value = costs[i, j]
        if i and j and value == costs.get((i - 1, j - 1), limit + 1) + (old[i - 1] != new[j - 1]):
            if old[i - 1] != new[j - 1]:
                edits.append((i - 1, i, new[j - 1]))
            i, j = i - 1, j - 1
        elif i and value == costs.get((i - 1, j), limit + 1) + 1:
            edits.append((i - 1, i, ""))
            i -= 1
        else:
            edits.append((i, i, new[j - 1]))
            j -= 1
    # Coalesce insertions at the same anchor, retaining order after traceback.
    result: list[Edit] = []
    for start, end, text in reversed(edits):
        if result and start == end == result[-1][0] == result[-1][1]:
            result[-1] = start, end, result[-1][2] + text
        else:
            result.append((start, end, text))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Reading:
    sequence: int
    captured_at: float
    text: str
    bounds: Rect
    confidence: float


@dataclass(frozen=True, slots=True)
class Proposal:
    reading: Reading
    supported_edits: tuple[Edit, ...]
    unresolved_edits: int


class EvidenceWindow:
    """At most eight completed readings; explicit revision/geometry and observation time.

    Five distinct observations spanning 1.25 s and two-thirds edit support are needed.
    Same-pixel proof vetoes proposals; misses/reset/incompatible layouts clear evidence.
    Unscanned lines and repeated polls add no evidence. This is deliberately NOT a
    replacement for live confidence reviews, typewriter readiness or absence policy.
    """

    def __init__(self) -> None:
        self._track: TextTrack | None = None
        self._last_sequence = -1
        self._last_time = float("-inf")
        self._samples: deque[tuple[Reading, tuple[Edit, ...]]] = deque(maxlen=8)

    def reset(self) -> None:
        self.__init__()

    def observe(
        self,
        accepted: TextTrack,
        reading: Reading | None,
        *,
        visual: Literal["same", "changed", "unknown"] = "unknown",
        covered: bool = True,
    ) -> Proposal | None:
        if accepted != self._track:
            self.reset()
            self._track = accepted
        if not covered:
            return None
        if reading is None:
            self._samples.clear()
            return None
        if reading.sequence <= self._last_sequence or reading.captured_at < self._last_time:
            return None
        self._last_sequence, self._last_time = reading.sequence, reading.captured_at
        if visual == "same" or reading.bounds != accepted.bounds:
            self._samples.clear()
            return None
        edits = _edits(accepted.text, reading.text)
        if edits is None or (
            reading.text != accepted.text
            and (reading.text.startswith(accepted.text) or accepted.text.startswith(reading.text))
        ):
            self._samples.clear()  # Leave growth/contraction to ordinary confirmation.
            return None
        if not edits:
            self._samples.clear()  # Returning to the committed reading breaks a change run.
            return None
        self._samples.append((reading, edits))
        if len(self._samples) < 5:
            return None
        votes = Counter(edit for _, edits in self._samples for edit in edits)
        supported = tuple(
            sorted(
                edit for edit, count in votes.items() if count >= ceil(len(self._samples) * 2 / 3)
            )
        )
        if not supported or not all(edit in edits for edit in supported):
            return None
        # Each proposed change needs sustained support, not merely an old window.
        for edit in supported:
            times = [sample.captured_at for sample, edits in self._samples if edit in edits]
            if times[-1] - times[0] < 1.25:
                return None
        candidates = [
            (sample, edits)
            for sample, edits in self._samples
            if all(edit in edits for edit in supported)
        ]
        if not candidates:
            return None  # Do not manufacture a consensus sentence never seen by OCR.
        sample, edits = max(
            candidates,
            key=lambda item: (
                sum(votes[e] - len(self._samples) / 2 for e in item[1]),
                -len(set(item[1]) - set(supported)),
                item[0].confidence,
                item[0].sequence,
            ),
        )
        return Proposal(sample, supported, len(set(edits) - set(supported)))
