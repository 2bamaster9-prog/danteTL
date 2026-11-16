"""Published reading history values, independent of classification workers."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    number: int
    source: str
    english: str
    speaker: str | None = None
    speaker_english: str | None = None
