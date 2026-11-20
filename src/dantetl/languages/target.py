"""Written translation targets, independent of the selected OCR language."""

from dataclasses import dataclass

from dantetl.i18n import mark


@dataclass(frozen=True, slots=True)
class TargetLanguage:
    code: str
    name: str


ENGLISH = TargetLanguage("en", mark("English"))
TARGET_LANGUAGES = {
    target.code: target
    for target in (
        ENGLISH,
        TargetLanguage("bn", mark("Bengali")),
        TargetLanguage("nl", mark("Dutch")),
        TargetLanguage("fr", mark("French")),
        TargetLanguage("de", mark("German")),
        TargetLanguage("hi", mark("Hindi")),
        TargetLanguage("id", mark("Indonesian")),
        TargetLanguage("it", mark("Italian")),
        TargetLanguage("ja", mark("Japanese")),
        TargetLanguage("ko", mark("Korean")),
        TargetLanguage("ar", mark("Modern Standard Arabic")),
        TargetLanguage("pt-BR", mark("Portuguese (Brazil)")),
        TargetLanguage("pt-PT", mark("Portuguese (Portugal)")),
        TargetLanguage("ru", mark("Russian")),
        TargetLanguage("zh-hans", mark("Simplified Chinese")),
        TargetLanguage("es", mark("Spanish")),
        TargetLanguage("th", mark("Thai")),
        TargetLanguage("zh-hant", mark("Traditional Chinese")),
        TargetLanguage("vi", mark("Vietnamese")),
    )
}
