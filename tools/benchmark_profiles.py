"""Experimental translation prompts; never imported by the application/catalog."""

import json
import os
from pathlib import Path
from typing import Any

from jp_overlay.dialogue_context import DialogueTurn
from jp_overlay.gguf_backend import completed_answer
from jp_overlay.llama_runtime import load_runtime
from jp_overlay.translation_backend import RequestRejected

CONTEXT = 2048
OUTPUT = 384


def bounded_history(context: tuple[DialogueTurn, ...]) -> tuple[DialogueTurn, ...]:
    context = context[-2:]
    while sum(len(t.source) + len(t.english) for t in context) > 512:
        context = context[1:]
    return context


def escaped(text: str) -> str:
    return text.replace("<", "＜").replace(">", "＞")


def specialist_prompt(profile: str, text: str, context: tuple[DialogueTurn, ...]) -> str:
    """Publisher's translation format; context extensions are recorded in the report."""
    if not text.strip() or len(text) > 512:
        raise RequestRejected("Source must contain 1–512 characters.")
    context = bounded_history(context)
    text = escaped(text)
    if profile == "plamo":
        start = "<|plamo:tag|>dataset<|plamo:msg|>translation"
        source = "<|plamo:tag|>input<|plamo:key|>lang<|plamo:val|>ja<|plamo:msg|>"
        target = "<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>en<|plamo:msg|>"
        history = "".join(source + escaped(t.source) + target + escaped(t.english) for t in context)
        return start + history + source + text + target
    reference = escaped(json.dumps([(t.source, t.english) for t in context], ensure_ascii=False))
    if profile == "cat":
        # CAT documents the source-only instruction, but no prescribed history interface.
        history = (
            "Reference dialogue (Japanese, English; do not translate again):\n"
            + reference
            + "\nTranslate only the new Japanese text below.\n"
            if context
            else ""
        )
        return history + "Translate the following Japanese text into English.\n\n" + text
    if profile == "index":
        if not context:
            return "请将以下日语文本翻译为英语，直接输出翻译结果，不要进行任何解释。\n\n" + text
        return (
            "请将以下日语文本翻译成英语，并且严格遵循所有约束要求。\n\n〖源文〗\n"
            + text
            + "\n\n〖约束要求〗\n1. 〖注意〗以下为之前的日英对话，仅供参考，保持姓名一致。"
            + "只翻译源文，不要重复翻译参考对话：\n"
            + reference
            + "\n\n只输出译文，不要有任何额外说明。"
        )
    raise ValueError("Unknown experimental prompt profile.")


class SpecialistBackend:
    """Bounded embedded inference using unmodified pinned llama.cpp libraries."""

    batch_size = 1

    def __init__(self, path: Path, profile: str, device: str) -> None:
        self.profile = profile
        self._model: Any = None
        self.last_prompt = ""
        self.last_usage: dict[str, int] = {}
        runtime = load_runtime(device)
        if device != "cpu" and not runtime.llama_supports_gpu_offload():
            raise RuntimeError("GPU offload is unavailable.")
        batch = 128 if device == "cpu" else 1
        try:
            self._model = runtime.Llama(
                model_path=str(path),
                n_ctx=CONTEXT,
                n_batch=batch,
                n_ubatch=batch,
                n_threads=min(4, max(1, (os.cpu_count() or 2) // 2)) if device == "cpu" else 2,
                n_gpu_layers=0 if device == "cpu" else -1,
                split_mode=0,
                main_gpu=0,
                flash_attn=device == "cuda",
                verbose=True,
            )
            from llama_cpp.llama_chat_format import Jinja2ChatFormatter

            def token_text(token: int) -> str:
                return self._model.detokenize([token], special=True).decode() if token >= 0 else ""

            eos, bos = token_text(self._model.token_eos()), token_text(self._model.token_bos())
            template = self._model.metadata.get("tokenizer.chat_template", "")
            if profile == "cat":
                # Text-only projection of CyberAgent's chat_template.jinja: user, EOS,
                # assistant generation prefix. The community GGUF omits this metadata.
                template = "{{ '<|user|>' + messages[0]['content'] + eos_token + '<|assistant|>' }}"
            if not template:
                raise ValueError("Candidate has no embedded chat template.")
            self._formatter = Jinja2ChatFormatter(template, eos, bos)
            self._formatter.strftime_now = lambda f: ""
            self._stops = (
                ["<|plamo:tag|>", "<|plamo:bos|>"]
                if profile == "plamo"
                else [s for s in (eos, "<|im_end|>") if s]
            )
            self.cache_identity = f"experiment-v1:{profile}:{runtime.__version__}:{device}"
        except BaseException:
            self.close()
            raise

    def translate(self, texts: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(self.translate_with_context(t, ()) for t in texts)

    def translate_with_context(self, text: str, context: tuple[DialogueTurn, ...]) -> str:
        context = bounded_history(context)
        while True:
            content = specialist_prompt(self.profile, text, context)
            prompt = (
                content
                if self.profile == "plamo"
                else self._formatter(
                    messages=[{"role": "user", "content": content}], enable_thinking=False
                ).prompt
            )
            tokens = self._model.tokenize(prompt.encode(), add_bos=False, special=True)
            if len(tokens) + OUTPUT <= CONTEXT:
                break
            if not context:
                raise RequestRejected("Source exceeds context; refusing truncation.")
            context = context[1:]
        self.last_prompt = prompt
        response = self._model.create_completion(
            prompt=tokens,
            max_tokens=OUTPUT,
            temperature=0,
            repeat_penalty=1.0,
            seed=42,
            stop=self._stops,
            stream=False,
        )
        self.last_usage = response.get("usage", {})
        return completed_answer(response)

    def close(self) -> None:
        if self._model is not None:
            self._model.close()
            self._model = None
