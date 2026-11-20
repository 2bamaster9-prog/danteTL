"""Published reading history values, independent of classification workers."""

from dataclasses import dataclass

from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.languages.target import ENGLISH, TargetLanguage


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    number: int
    source: str
    english: str
    speaker: str | None = None
    speaker_english: str | None = None
    target: TargetLanguage = ENGLISH
    language: SourceLanguage = DEFAULT_SOURCE
