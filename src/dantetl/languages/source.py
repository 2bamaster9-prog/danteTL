"""Text evidence for a known source language. Layout and timing belong to their consumers."""

import re
import unicodedata
from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ListSyntax:
    """Read the same list notation at the evidence strength each consumer requires."""

    possible_prefix: tuple[str, ...]
    numbered_or_bullet: re.Pattern[str]
    panel_marker: re.Pattern[str]
    line_marker: re.Pattern[str]
    inline_label: re.Pattern[str]

    @classmethod
    def from_punctuation(
        cls, *, label_stops: str, extra_bullets: str = "", extra_number_stops: str = ""
    ) -> "ListSyntax":
        bullets = "•●○◆◇▶▷→" + extra_bullets
        number_stop = f"[.．:：)）{re.escape(extra_number_stops)}]"
        bullet = f"[{re.escape(bullets)}]"
        panel = rf"(?:{bullet}|[0-9０-９①-⑳]+{number_stop}|[A-Za-z][.．)）])"
        return cls(
            possible_prefix=tuple(bullets + "0123456789０１２３４５６７８９"),
            numbered_or_bullet=re.compile(rf"(?:{bullet}|[0-9０-９]+{number_stop})"),
            panel_marker=re.compile(panel),
            line_marker=re.compile(rf"(?:-|{panel})"),
            inline_label=re.compile(rf"^([^\s:：{re.escape(label_stops)}]{{1,10}})[:：]\s*(?=\S)"),
        )

    def has_inline_label(self, text: str) -> bool:
        if marker := self.line_marker.match(text):
            text = text[marker.end() :].lstrip()
        return bool(self.inline_label.match(text))


@dataclass(frozen=True, slots=True)
class DashQuotes:
    """Paired quotation marks for which OCR can drop a preceding dash or read a bracket as '/'."""

    pairs: tuple[tuple[str, str], ...]
    prefix: re.Pattern[str]

    def missing_dash_candidate(self, text: str) -> bool:
        return text.startswith((*self.openers, "/")) and not text.endswith(self.closers)

    @property
    def openers(self) -> tuple[str, ...]:
        return tuple(a for a, _ in self.pairs)

    @property
    def closers(self) -> tuple[str, ...]:
        return tuple(b for _, b in self.pairs)

    def opening(self, text: str, *, recovered: bool) -> str:
        if not recovered:
            dash = self.prefix.match(text)
            if dash is None:
                return ""
            text = text[dash.end() :]
        if not text.startswith((*self.openers, "/")):
            return ""
        for opener, closer in self.pairs:
            if text[0] == opener:
                return text if text.count(closer) < text.count(opener) else ""
        return "" if text.endswith((*self.closers, "/")) else text

    def complete(self, opening: str, source: str) -> bool:
        opener = self.prefix.sub("", opening)[0]
        for left, right in self.pairs:
            if left == opener:
                return source.endswith("/") or source.count(right) >= source.count(left)
        return True  # OCR read the opening bracket as a slash.


@dataclass(frozen=True, slots=True)
class SourceLanguage:
    """Defaults for space-separated prose. The player already knows the source language."""

    code: str
    name: str
    warmup_text: str
    trim_edge_icons: ClassVar = False
    extra_edge_marks: ClassVar[frozenset[str]] = frozenset()
    tracking_brackets: ClassVar = "()[]"
    word_separator: ClassVar[str] = " "
    reveal_marks: ClassVar[str] = ".,!?”’"
    terminal: ClassVar[tuple[str, ...]] = tuple(".!?")
    endings: ClassVar[tuple[str, ...]] = (*terminal, "”", "’")
    commas: ClassVar[tuple[str, ...]] = (",",)
    label_punctuation: ClassVar[str] = ".,!?"
    speaker_delimiters: ClassVar = ":：%％+＋/／[]（）()"
    lists: ClassVar = ListSyntax.from_punctuation(label_stops=label_punctuation + '"“‘')
    period: ClassVar = "."
    prose_punctuation: ClassVar = ",."
    opening_punctuation: ClassVar = ".,!?…"
    prose_script: ClassVar[re.Pattern[str] | None] = None
    quote_start: ClassVar = re.compile(r"""^["“‘]""")
    dash_quotes: ClassVar[DashQuotes | None] = None
    menu_labels: ClassVar[frozenset[str]] = frozenset()
    value_introductions: ClassVar[tuple[str, ...]] = ()
    percentage_lead: ClassVar[re.Pattern[str] | None] = None
    percentage_label_terms: ClassVar[tuple[str, ...]] = ()
    short_row_cue: ClassVar = re.compile(r"[.!?]$")
    ellipsis_clause_mark: ClassVar[str | None] = None

    def contains_text(self, text: str) -> bool:
        """Is this OCR text eligible under the selected source language?"""
        return any(c.isalpha() for c in text)

    def matching_text(self, text: str) -> str:
        return self.word_separator.join(unicodedata.normalize("NFKC", text).split())

    def needs_space(self, left: str, right: str) -> bool:
        """Whether the two edge characters need a word space at an OCR line wrap."""
        return bool(left and right and left not in "([“‘-'" and right not in ".,:;!?)]”’'")

    def is_choice(self, text: str) -> bool:
        return bool(self.lists.line_marker.match(text)) and not self.quote_start.match(text)

    def has_speaker_punctuation(self, text: str) -> bool:
        return any(c in self.label_punctuation or c in self.speaker_delimiters for c in text)

    def starts_item(self, text: str) -> bool:
        return self.is_choice(text) or self.lists.has_inline_label(text)

    def internal_prose(self, text: str) -> bool:
        return len(text) >= 14 and any(mark in text[:-1] for mark in self.prose_punctuation)

    def prose_opening(self, text: str) -> bool:
        return any(c in self.opening_punctuation for c in text) and (
            bool(self.prose_script.search(text)) if self.prose_script else self.contains_text(text)
        )

    def short_continuation(self, text: str) -> bool:
        text = text.rstrip()
        return bool(self.short_row_cue.search(text)) or (
            text.endswith("…")
            and (self.ellipsis_clause_mark is None or self.ellipsis_clause_mark in text)
        )

    def subtitle_continuation(self, first: str, tail: str) -> bool:
        """Strong linguistic evidence for joining an otherwise ambiguous centered tail."""
        return False

    def quoted_term_with_suffix(self, text: str) -> bool:
        """Does the row continue past an inline quoted term?"""
        return False

    def closes_wrapped_quote(self, first: str, tail: str) -> bool:
        """Does the final row close a quoted term from the preceding row?"""
        return False

    def section_heading(self, text: str) -> bool:
        return False

    def sample_effect_lettering(self, text: str) -> bool:
        return False

    def separate_effects(self, first: str, second: str) -> bool:
        return False

    def speaker_base(self, text: str) -> str:
        return text
