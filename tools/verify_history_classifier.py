"""Offline classifier smoke evaluation using already installed instruction models."""

import argparse
import json
import socket
import threading
import time
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from dantetl.application.model_factories import translation_backends
from dantetl.domain import Rect
from dantetl.ocr.observation import TextTrack
from dantetl.runtime.llama import installed_device, load_runtime
from dantetl.translation.backend import RequestRejected
from dantetl.translation.dialogue.classifier import ClassificationInput, ClassifierBackend
from dantetl.translation.dialogue.history import DialogueHistory
from dantetl.translation.grouping import TextBlock

SAMPLES = (
    ("warning", "ここから先は危険です。私と一緒に進んでください。", "旅人", "dialogue", "yes"),
    ("anonymous", "待ってくれ！まだ中に人がいるんだ！", "", "dialogue", "no"),
    (
        "bubble",
        "も、申し訳ございません、ホロウ災害の発生により、捜査活動に影響が出ております。",
        "",
        "dialogue",
        "no",
    ),
    (
        "biography",
        "戦争に巻き込まれた調香師の少女。特殊な能力を持ち、軍のセラピストを務めていた。",
        "スクロール画面の切替",
        "description",
        "no",
    ),
    (
        "lore",
        "古い王国で作られた銀の指輪。表面には持ち主の名前が刻まれている。",
        "銀の指輪",
        "description",
        "no",
    ),
    (
        "skill",
        "敵全体に炎属性ダメージを与え、味方の攻撃力を35%上げる。",
        "火炎の力",
        "description",
        "no",
    ),
    ("control", "ボタンを長押しして画面を切り替えてください。", "操作方法", "ui", "no"),
    (
        "button_above_speech",
        "どうしてこんなところにいるんだ？早く帰ろう。",
        "画面の切り替え",
        "dialogue",
        "no",
    ),
    ("title_speaker", "市民の皆様、落ち着いて避難してください。", "警備隊長", "dialogue", "yes"),
    ("occupation_label", "「仮想訓練場」教官", "", "ui", "no"),
)


def panel_samples():
    """Same spoken wording in different UI roles, through the real candidate builder."""
    speech = "それなら私が手伝います。安心してください。"
    cases = (
        (
            "response_options",
            (speech, "いいえ、今は無理です。", "何があったのか教えてください。"),
            0,
            110,
            "choice",
        ),
        ("two_options", (speech, "今は手伝えません。また後で来ます。"), 0, 110, "choice"),
        ("spoken_same_words", (speech,), 0, 110, "dialogue"),
        (
            "loading_quote",
            ("ロード中・冒険のヒント", "危険を感じたら、すぐに逃げてください。"),
            1,
            80,
            "loading",
        ),
        ("ordinary_warning", ("危険を感じたら、すぐに逃げてください。",), 0, 80, "dialogue"),
        (
            "continuous_story_rows",
            (
                "昨日、私はあの村を訪ねました。",
                "そこで、ずっと探していた友人に会ったのです。",
                "彼は無事でした。本当によかった。",
            ),
            1,
            110,
            "dialogue",
        ),
        (
            "alternative_questions",
            ("あなたは誰ですか？", "ここはどこですか？", "出口はどこですか？"),
            0,
            100,
            "choice",
        ),
    )
    for name, texts, target, spacing, kind in cases:
        blocks = tuple(
            TextBlock((TextTrack(i, text, Rect(300, 300 + spacing * i, 600, 40)),))
            for i, text in enumerate(texts)
        )
        history = DialogueHistory()
        for now in (0, 1.3):
            history.observe(blocks, blocks, (1920, 1080), now, assisted=True)
        values = history.classification_requests()
        if kind == "choice":
            for i, value in enumerate(values):
                yield f"{name}_{i}", value, kind, "no"
        else:
            value = next(k for k in values if k.text == texts[target])
            yield name, value, kind, "no"


def header_samples():
    """Two header labels, one spoken question, and two aligned selectable replies."""
    blocks = tuple(
        TextBlock((TextTrack(i, text, Rect(x, y, width, height)),))
        for i, (text, x, y, width, height) in enumerate(
            (
                ("アルト", 300, 100, 140, 50),
                ("訓練施設の教官", 300, 160, 260, 35),
                ("新人よ、少し体を動かさないか？今日は私が訓練に付き合おう。", 300, 260, 800, 40),
                ("はい、一緒に行きましょう。", 300, 370, 600, 40),
                ("いいえ、今は遠慮します。", 300, 480, 600, 40),
            )
        )
    )
    history = DialogueHistory()
    for now in (0, 1.3):
        history.observe(blocks, blocks, (1920, 1080), now, assisted=True)
    values = history.classification_requests()
    assert len(values) == 3 and values[0].speaker == blocks[0].text
    yield "stacked_header_speech", values[0], "dialogue", "yes"
    for i, value in enumerate(values[1:]):
        yield f"headed_panel_option_{i}", value, "choice", "no"


def single_response_samples():
    """Supplied screenshot's OCR text/geometry; no image is sent to the model."""
    blocks = tuple(
        TextBlock((TextTrack(i, text, Rect(x, y, width, height)),))
        for i, (text, x, y, width, height) in enumerate(
            (
                ("厳彦(ゴンゲン)", 1613, 1535, 559, 79),
                ("仮想訓練場」教官", 1722, 1624, 429, 56),
                ("来たか、新人。", 1705, 1770, 382, 64),
                ("ここで何を学べる?", 2572, 1367, 462, 51),
            )
        )
    )
    history = DialogueHistory()
    for now in (0, 1.3):
        history.observe(blocks, blocks, (3840, 2160), now, assisted=True)
    values = history.classification_requests()
    assert len(values) == 2
    for value in values:
        option = value.text == blocks[3].text
        yield (
            "single_detached_option" if option else "short_named_greeting",
            value,
            "choice" if option else "dialogue",
            "no" if option else "yes",
        )
    yield "same_question_without_panel", ClassificationInput(blocks[3].text), "dialogue", "no"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma")
    parser.add_argument("--device", choices=("cpu", "cuda", "vulkan"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    choice = next(c for c in translation_backends() if c.preference_key == args.model)
    assert choice.classifies and not choice.unavailable_reason
    assert installed_device() == args.device, "Strict device verification; no fallback"
    runtime = load_runtime(args.device)
    original = runtime.Llama

    def load(*a, **kw):
        kw["verbose"] = True
        return original(*a, **kw)

    evidence = {"model": args.model, "device": args.device, "samples": []}
    with (
        patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")),
        patch.object(runtime, "Llama", load),
    ):
        started = time.monotonic()
        engine = choice.create()
        evidence["load_seconds"] = time.monotonic() - started
        assert isinstance(engine, ClassifierBackend)
        try:
            samples = (
                [
                    (name, ClassificationInput(text, speaker), kind, label)
                    for name, text, speaker, kind, label in SAMPLES
                ]
                + list(panel_samples())
                + list(header_samples())
                + list(single_response_samples())
            )
            for name, value, kind, label in samples:
                started = time.monotonic()
                try:
                    answer = engine.classify(value, threading.Event())
                    record = {
                        "id": name,
                        "answer": asdict(answer),
                        "matches_expected": (answer.kind, answer.speaker) == (kind, label),
                    }
                except RequestRejected as error:
                    record = {"id": name, "rejected": str(error), "matches_expected": False}
                record["seconds"] = round(time.monotonic() - started, 3)
                record["panel_neighbors"] = len(value.panel.neighbors)
                evidence["samples"].append(record)
                print(json.dumps(record), flush=True)
        finally:
            engine.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2), "utf-8")


if __name__ == "__main__":
    main()
