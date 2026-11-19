"""Text evidence shared by the Latin-script sources supported by PaddleOCR."""

from typing import ClassVar

from dantejp.languages.source import SourceLanguage


class PaddleOCRLanguage(SourceLanguage):
    """Override individual cues in a subclass for a particular source language."""

    __slots__ = ()
    inline_quotes: ClassVar[tuple[tuple[str, str], ...]] = (('"', '"'), ("“", "”"), ("‘", "’"))

    def quoted_term_with_suffix(self, text: str) -> bool:
        """A quoted name followed by more words on the same physical row."""
        for opener, closer in self.inline_quotes:
            if text.startswith(opener):
                term, mark, suffix = text[1:].partition(closer)
                return bool(
                    mark
                    and self.contains_text(term)
                    and not term.endswith(self.terminal)
                    and suffix[:1].isspace()
                    and suffix.lstrip()[:1].isalpha()
                )
        return False

    def closes_wrapped_quote(self, first: str, tail: str) -> bool:
        """A centered final word can finish a quotation embedded in a longer label."""
        for opener, closer in self.inline_quotes:
            # Small closing double quotes are sometimes recognized as an apostrophe.
            if not tail.endswith((closer, "'")) or not self.contains_text(tail[:-1]):
                continue
            prefix, mark, term = first.rpartition(opener)
            if (
                mark
                and prefix.endswith(" ")
                and term
                and not term[0].isspace()
                and closer not in term
                and closer not in tail[:-1]
            ):
                return True
        return False
