"""PLaMo 3 Translate's native PFML3 prompt, independent of chat-model instructions."""

from dantejp.i18n import tr
from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.languages.target import ENGLISH, TargetLanguage
from dantejp.translation.backend import RequestRejected
from dantejp.translation.dialogue.context import DialogueTurn

STOPS = ("<|plamo:tag|>", "<|plamo:bos|>")
# PFML3 accepts the language codes from the pinned PLaMo 3 Translate model card.
# fmt: off
OUTPUT_CODES = frozenset({
    "ar", "az", "be", "bg", "bn", "ca", "ceb", "de", "en", "es", "et", "eu", "fa", "fr",
    "gu", "he", "hi", "hr", "hu", "hy", "id", "it", "ja", "jv", "ka", "kk", "km", "ko",
    "lt", "lv", "ml", "mr", "ms", "my", "ne", "nl", "pa", "pl", "ru", "si", "sk", "sl",
    "sr", "sw", "ta", "te", "th", "tl", "ur", "uz", "vi", "zh-hans", "zh-hant",
})
# fmt: on


def source_problem(language: SourceLanguage) -> str:
    if language.code.split("-")[0] in OUTPUT_CODES:
        return ""
    return tr(
        "PLaMo does not support {name} as a source. Choose a model such as Gemma.",
        name=language.name,
    )


def translation_prompt(
    text: str,
    context: tuple[DialogueTurn, ...],
    *,
    language: SourceLanguage = DEFAULT_SOURCE,
    target: TargetLanguage = ENGLISH,
) -> str:
    if problem := source_problem(language):
        raise RequestRejected(problem)
    if target.code not in OUTPUT_CODES:
        raise RequestRejected(
            tr(
                "PLaMo does not support {name}. Choose a multilingual model such as Gemma.",
                name=target.name,
            )
        )

    def escaped(value: str) -> str:
        return value.replace("<", "＜").replace(">", "＞")

    code = language.code.split("-")[0]
    source = f"<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>{code}<|plamo:msg|>"
    output = f"<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>{target.code}<|plamo:msg|>"
    history = "".join(source + escaped(t.source) + output + escaped(t.english) for t in context)
    # Explicit BOS exactly once; the caller tokenizes with add_bos=False, special=True.
    return (
        "<|plamo:bos|><|plamo:tag|>dataset<|plamo:msg|>translation"
        + history
        + source
        + escaped(text)
        + output
    )
