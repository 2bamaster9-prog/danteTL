"""Written translation targets, independent of the selected OCR language."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TargetLanguage:
    code: str
    name: str


ENGLISH = TargetLanguage("en", "English")
TARGET_LANGUAGES = {
    target.code: target
    for target in (
        ENGLISH,
        TargetLanguage("bn", "Bengali"),
        TargetLanguage("nl", "Dutch"),
        TargetLanguage("fr", "French"),
        TargetLanguage("de", "German"),
        TargetLanguage("hi", "Hindi"),
        TargetLanguage("id", "Indonesian"),
        TargetLanguage("it", "Italian"),
        TargetLanguage("ko", "Korean"),
        TargetLanguage("ar", "Modern Standard Arabic"),
        TargetLanguage("pt-BR", "Portuguese (Brazil)"),
        TargetLanguage("pt-PT", "Portuguese (Portugal)"),
        TargetLanguage("ru", "Russian"),
        TargetLanguage("zh-hans", "Simplified Chinese"),
        TargetLanguage("es", "Spanish"),
        TargetLanguage("th", "Thai"),
        TargetLanguage("zh-hant", "Traditional Chinese"),
        TargetLanguage("vi", "Vietnamese"),
    )
}
