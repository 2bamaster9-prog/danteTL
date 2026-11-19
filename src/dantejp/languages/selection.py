"""Installed source-language policies. Production currently uses Japanese for every session."""

from typing import Final

from dantejp.languages.japanese import Japanese
from dantejp.languages.source import SourceLanguage

_JAPANESE = Japanese("ja", "Japanese", warmup_text="設定")
_SOURCE_LANGUAGES: dict[str, SourceLanguage] = {_JAPANESE.code: _JAPANESE}


def source_language(code: str) -> SourceLanguage:
    return _SOURCE_LANGUAGES[code]


DEFAULT_SOURCE: Final = source_language("ja")
