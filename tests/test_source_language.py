import pytest
from test_live_session import Replay, frame
from test_translation import Backend, until

from dantejp.domain import Rect
from dantejp.languages.selection import DEFAULT_SOURCE, source_language
from dantejp.languages.source import SourceLanguage
from dantejp.languages.target import TARGET_LANGUAGES
from dantejp.ocr.tracking import TextTrack, TextTracker, prepare_matching
from dantejp.ocr.values import OcrResult, TextRegion
from dantejp.translation.backend import RequestRejected
from dantejp.translation.backends import gemma, gguf, plamo
from dantejp.translation.cache import TranslationCache, translation_key
from dantejp.translation.cloud.protocol import request_body
from dantejp.translation.cloud.values import CloudProfile
from dantejp.translation.dialogue.layout import PanelLayout
from dantejp.translation.grouping import DialogueGrouper, TextBlock
from dantejp.translation.worker import TranslationSession

# Exercise the generic policy without registering another supported OCR language.
PORTUGUESE = SourceLanguage("pt", "Portuguese", warmup_text="Mapa")


def grouped_rows(language, *texts):
    rows = tuple(
        TextTrack(i + 1, text, Rect(100, 100 + 45 * i, 380, 35)) for i, text in enumerate(texts)
    )
    grouped = DialogueGrouper(language=language).update(rows, rows, 0)
    return [[row.text for row in block.lines] for block in grouped.blocks]


def test_new_quoted_speech_starts_a_block_without_ocr_dash_recovery():
    first, second = "Chegou, viu a casa.", "Ficou para jantar."
    assert grouped_rows(PORTUGUESE, first, second, "Vai para casa.") == [
        [first, second, "Vai para casa."]
    ]
    assert grouped_rows(PORTUGUESE, first, second, "“Vai para casa.”") == [
        [first, second],
        ["“Vai para casa.”"],
    ]


def test_percentage_label_needs_established_prose_and_text_after_the_value():
    class EffectLanguage(SourceLanguage):
        percentage_label_terms = ("bônus",)

    language = EffectLanguage("pt", "Portuguese", "Mapa")
    lead, tail = "Efeito: Quando chega", "bônus:25%. Outra frase."
    assert grouped_rows(language, lead, tail) == [[lead, tail]]
    for first, second in [
        ("Quando chega aqui", tail),
        (lead, "bônus:25%."),
        (lead, "•bônus:25%. Outra frase."),
    ]:
        assert grouped_rows(language, first, second) == [[first], [second]]
    assert grouped_rows(PORTUGUESE, lead, tail) == [[lead], [tail]]


@pytest.mark.parametrize(
    ("marker", "generic", "japanese"),
    [
        ("A)", True, True),
        ("•", True, True),
        ("-", False, False),
        ("・", False, True),
        ("１、", False, True),
    ],
)
def test_panel_uses_the_selected_list_notation(marker, generic, japanese):
    for language, expected in [(PORTUGUESE, generic), (DEFAULT_SOURCE, japanese)]:
        row = TextTrack(1, marker + " Item", Rect(100, 100, 180, 35))
        block = TextBlock((row,), language=language)
        layout = PanelLayout()
        layout.update((block,))
        assert layout.marked_choice(block) is expected


def test_generic_language_groups_and_publishes_through_the_live_pipeline(tmp_path):
    replay = Replay(language=PORTUGUESE)
    rows = (
        TextRegion("Mapa", Rect(50, 40, 100, 30)),
        TextRegion("O caminho leva até", Rect(100, 650, 380, 35)),
        TextRegion("à praça da vila.", Rect(100, 695, 360, 35)),
    )
    replay.observe(frame(1), rows)
    scene = replay.observe(frame(2, 1.5), rows)
    phrase = "O caminho leva até à praça da vila."
    assert [b.text for b in scene.requests] == ["Mapa", phrase]
    assert [line.text for line in scene.requests[1].lines] == [r.text for r in rows[1:]]

    backend = Backend()
    path = tmp_path / "cache.sqlite3"
    cache = TranslationCache(path)
    cache.put(translation_key(backend.cache_identity, "Mapa"), "Wrong language")
    cache.close()
    session = TranslationSession(lambda: backend, path, language=PORTUGUESE)
    session.start()
    try:
        replay.live.publish(session, scene.requests, scene.blocks)
        until(lambda: len(session.snapshot().results) == 2)
        english = replay.live.publish(session, scene.requests, scene.blocks)
        assert english.blocks == scene.blocks
        assert [t.english for t in english.translations] == [
            f"{backend.cache_identity}: Mapa",
            f"{backend.cache_identity}: {phrase}",
        ]
    finally:
        session.request_stop()
        until(lambda: session.finished)


def test_japanese_remains_selected_and_rejects_latin_only_ocr(tmp_path):
    assert source_language("ja") is DEFAULT_SOURCE
    with pytest.raises(KeyError):
        source_language("unregistered")
    regions = (
        TextRegion("Mapa", Rect(50, 40, 100, 30)),
        TextRegion("マップ", Rect(50, 300, 100, 30)),
    )
    replay = Replay()
    replay.observe(frame(1), regions)
    scene = replay.observe(frame(2, 1.5), regions)
    assert len(scene.blocks) == 2
    backend = Backend()
    session = TranslationSession(lambda: backend, tmp_path / "cache.sqlite3")
    session.start()
    try:
        replay.live.publish(session, scene.requests, scene.blocks)
        until(lambda: session.snapshot().results)
        english = replay.live.publish(session, scene.requests, scene.blocks)
        assert [b.text for b in english.blocks] == ["マップ"]
        assert backend.calls == [("マップ",)]
    finally:
        session.request_stop()
        until(lambda: session.finished)


@pytest.mark.parametrize("lower_length, expected_blocks", [(255, 1), (256, 2)])
def test_shared_request_budget_counts_the_language_specific_word_space(
    lower_length, expected_blocks
):
    lines = (
        TextTrack(1, "a" * 255 + "é", Rect(100, 650, 380, 35)),
        TextTrack(2, "é" * (lower_length - 1) + ".", Rect(100, 695, 360, 35)),
    )
    grouped = DialogueGrouper(language=PORTUGUESE).update(lines, lines, 0)
    assert len(grouped.blocks) == expected_blocks
    assert all(len(block.text) <= 512 for block in grouped.blocks)


def test_matching_evidence_is_scoped_to_its_source_language():
    source = frame(1)
    result = OcrResult(source, (TextRegion("por que", Rect(10, 10, 100, 25)),), 25, 1.0)
    tracker = TextTracker(language=PORTUGUESE)
    with pytest.raises(ValueError, match="evidence"):
        tracker.observe(result, matching=prepare_matching(result, ()))
    assert tracker.observe(result, matching=prepare_matching(result, (), language=PORTUGUESE)) == (
        1,
    )


def test_backends_use_the_selected_language_in_their_native_prompt():
    language = PORTUGUESE
    assert "Translate Portuguese video game text" in gemma.translation_prompt(
        "Mapa", language=language
    )
    assert "Translate Portuguese video game text" in gguf.user_prompt("Mapa", (), language=language)
    prompt = plamo.translation_prompt("Mapa", (), language=language)
    assert "<|plamo:val|>pt<|plamo:msg|>Mapa" in prompt
    assert prompt.endswith("<|plamo:val|>en<|plamo:msg|>")
    profile = CloudProfile.new("claude")
    body = request_body(profile, "", ("Mapa", ()), language=language)
    assert "Translate CURRENT from Portuguese" in str(body["system"])


@pytest.mark.parametrize("target", TARGET_LANGUAGES.values(), ids=TARGET_LANGUAGES.keys())
def test_backends_request_the_same_output_language(target):
    from dantejp.translation.dialogue.context import DialogueTurn

    history = (DialogueTurn("先に行って。", "…"),)
    for prompt in (
        gemma.translation_prompt("設定", history, target=target),
        gguf.user_prompt("設定", history, target=target),
        str(
            request_body(CloudProfile.new("claude"), "", ("設定", history), target=target)["system"]
        ),
    ):
        assert target.name in prompt
        if target.code != "en":
            assert "English" not in prompt
    if target.code in ("pt-PT", "pt-BR"):
        with pytest.raises(RequestRejected, match="PLaMo does not support Portuguese"):
            plamo.translation_prompt("設定", history, target=target)
        return
    output = f"<|plamo:tag|>output<|plamo:key|>lang<|plamo:val|>{target.code}<|plamo:msg|>"
    prompt = plamo.translation_prompt("設定", history, target=target)
    assert prompt.count(output) == 2 and prompt.endswith(output)
