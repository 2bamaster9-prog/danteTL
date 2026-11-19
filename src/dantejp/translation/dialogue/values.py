"""Published reading history values, independent of classification workers."""

from dataclasses import dataclass

from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.languages.target import ENGLISH, TargetLanguage


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    number: int
    source: str
    english: str
    speaker: str | None = None
    speaker_english: str | None = None
    target: TargetLanguage = ENGLISH
    language: SourceLanguage = DEFAULT_SOURCE
