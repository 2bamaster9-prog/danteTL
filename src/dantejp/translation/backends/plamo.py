"""PLaMo 3 Translate's native PFML3 prompt, independent of chat-model instructions."""

from dantejp.translation.dialogue.context import DialogueTurn

STOPS = ("<|plamo:tag|>", "<|plamo:bos|>")


def translation_prompt(text: str, context: tuple[DialogueTurn, ...]) -> str:
    def escaped(value: str) -> str:
        return value.replace("<", "＜").replace(">", "＞")

    source = "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"
    target = "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>"
    history = "".join(source + escaped(t.source) + target + escaped(t.english) for t in context)
    # Explicit BOS exactly once; the caller tokenizes with add_bos=False, special=True.
    return (
        "<|plamo:bos|><|plamo:tag|>dataset<|plamo:msg|>translation"
        + history
        + source
        + escaped(text)
        + target
    )
