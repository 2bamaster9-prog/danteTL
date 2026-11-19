"""Selectable OCR sources, keyed by stable language codes."""

from typing import Final

from dantejp.i18n import mark
from dantejp.languages.japanese import Japanese
from dantejp.languages.paddle import PaddleOCRLanguage
from dantejp.languages.source import SourceLanguage

DEFAULT_SOURCE: Final[SourceLanguage] = Japanese("ja", mark("Japanese"), warmup_text="設定")

# Paddle's latin_PP-OCRv5_mobile_rec language table. Each entry shares the same weights.
LATIN_SOURCES = (
    PaddleOCRLanguage("af", mark("Afrikaans"), "Instellings"),
    PaddleOCRLanguage("sq", mark("Albanian"), "Cilësimet"),
    PaddleOCRLanguage("bs", mark("Bosnian (Latin)"), "Postavke"),
    PaddleOCRLanguage("hr", mark("Croatian"), "Postavke"),
    PaddleOCRLanguage("cs", mark("Czech"), "Nastavení"),
    PaddleOCRLanguage("da", mark("Danish"), "Indstillinger"),
    PaddleOCRLanguage("nl", mark("Dutch"), "Instellingen"),
    PaddleOCRLanguage("en", mark("English"), "Settings"),
    PaddleOCRLanguage("et", mark("Estonian"), "Seaded"),
    PaddleOCRLanguage("fr", mark("French"), "Paramètres"),
    PaddleOCRLanguage("de", mark("German"), "Einstellungen"),
    PaddleOCRLanguage("hu", mark("Hungarian"), "Beállítások"),
    PaddleOCRLanguage("is", mark("Icelandic"), "Stillingar"),
    PaddleOCRLanguage("id", mark("Indonesian"), "Pengaturan"),
    PaddleOCRLanguage("ga", mark("Irish"), "Socruithe"),
    PaddleOCRLanguage("it", mark("Italian"), "Impostazioni"),
    PaddleOCRLanguage("la", mark("Latin"), "Salve"),
    PaddleOCRLanguage("lt", mark("Lithuanian"), "Nustatymai"),
    PaddleOCRLanguage("ms", mark("Malay"), "Tetapan"),
    PaddleOCRLanguage("mi", mark("Māori"), "Tautuhinga"),
    PaddleOCRLanguage("no", mark("Norwegian"), "Innstillinger"),
    PaddleOCRLanguage("oc", mark("Occitan"), "Opcions"),
    PaddleOCRLanguage("pl", mark("Polish"), "Ustawienia"),
    PaddleOCRLanguage("pt", mark("Portuguese"), "Definições"),
    PaddleOCRLanguage("sr-Latn", mark("Serbian (Latin)"), "Podešavanja"),
    PaddleOCRLanguage("sk", mark("Slovak"), "Nastavenia"),
    PaddleOCRLanguage("sl", mark("Slovenian"), "Nastavitve"),
    PaddleOCRLanguage("es", mark("Spanish"), "Configuración"),
    PaddleOCRLanguage("sw", mark("Swahili"), "Mipangilio"),
    PaddleOCRLanguage("sv", mark("Swedish"), "Inställningar"),
    PaddleOCRLanguage("tl", mark("Tagalog"), "Mga setting"),
    PaddleOCRLanguage("tr", mark("Turkish"), "Ayarlar"),
    PaddleOCRLanguage("uz", mark("Uzbek (Latin)"), "Sozlamalar"),
    PaddleOCRLanguage("cy", mark("Welsh"), "Gosodiadau"),
)
SOURCE_LANGUAGES = {language.code: language for language in (DEFAULT_SOURCE, *LATIN_SOURCES)}


def source_language(code: str) -> SourceLanguage:
    return SOURCE_LANGUAGES[code]
