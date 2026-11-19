import pytest
from test_live_session import frame

from dantejp.domain import Rect
from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.ocr.tracking import TextTrack, TextTracker, prepare_matching
from dantejp.ocr.values import OcrResult, TextRegion
from dantejp.translation.dialogue.layout import PanelLayout
from dantejp.translation.grouping import DialogueGrouper, TextBlock

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
