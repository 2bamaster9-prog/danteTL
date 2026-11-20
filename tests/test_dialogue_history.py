"""Explicit-time history replays; no inference, Qt, images or model context changes."""

from dataclasses import replace

import pytest

from dantejp.domain import Rect
from dantejp.languages.target import TARGET_LANGUAGES
from dantejp.ocr.tracking import TextTrack
from dantejp.translation.dialogue.history import DialogueHistory
from dantejp.translation.grouping import TextBlock
from dantejp.translation.values import TranslatedText, TranslationRequest

SIZE = (1920, 1080)


def body(text="ここから先は危険です。私と一緒に進んでください。", key=1, x=280, y=800):
    return TextBlock((TextTrack(key, text, Rect(x, y, 950, 36)),), dialogue=True)


def name(text="三月なのか", key=2, x=280, y=750):
    return TextBlock((TextTrack(key, text, Rect(x, y, 160, 28)),))


def result(block, english="Come with me."):
    return TranslatedText(TranslationRequest.from_block(block), english)


def accept(history, blocks, now=1.0, *, score=0.97, ready=None, english="Come with me."):
    ready = blocks if ready is None else ready
    scores = {line: score for b in blocks for line in b.lines}
    history.observe(blocks, ready, SIZE, now, scores=scores)
    history.observe(blocks, ready, SIZE, now + 1.3)
    history.published(tuple(result(b, english) for b in blocks))


def test_switch_preserves_visible_turn_and_only_pairs_same_target_speakers():
    history = DialogueHistory()
    first, second, speaker = body(), body("また明日会いましょう。", key=4), name()
    pt, br = TARGET_LANGUAGES["pt-PT"], TARGET_LANGUAGES["pt-BR"]
    for now, block, target in ((1, first, pt), (3, first, br), (5, second, br)):
        blocks = (block, speaker)
        history.observe(blocks, blocks, SIZE, now, scores={speaker.lines[0]: 0.99})
        history.observe(blocks, blocks, SIZE, now + 1)
        history.published(
            (
                replace(result(block, target.name), target=target),
                replace(result(speaker, "Viajante"), target=pt),
            )
        )
    assert [(t.source, t.target, t.english, t.speaker_english) for t in history.turns] == [
        (first.text, pt, pt.name, "Viajante"),
        (second.text, br, br.name, None),
    ]


def test_twenty_turns_named_and_unknown_with_session_boundaries():
    history = DialogueHistory()
    for number in range(25):
        b = body(f"今日は旅の話をしましょう。これは会話の第{number}話です。", key=number + 10)
        accept(history, (b, name(key=100 + number)), number * 2, score=0.97 if number % 2 else 0.7)
    assert len(history.turns) == 20
    assert history.turns[0].number == 6 and history.turns[-1].number == 25
    assert history.turns[-1].speaker is None and history.turns[-2].speaker == "三月なのか"
    history.reset_scene()
    assert len(history.turns) == 20
    history.start()
    assert history.turns == ()


@pytest.mark.parametrize(
    "blocks",
    [
        (body("秘技を使用した後、次の戦闘で攻撃力+35%を獲得する。"), name("騎士王の出陣")),
        (body("使うと味方全体の体力を回復する。"), name("使用効果")),
        (body("古い時代から大切にされてきた品物。"), name("アイテム")),
        (body(x=1460), name(x=1460)),  # Description on the right, including the user's skill panel.
        (body(y=350), name(y=300)),
        (body("・はい、出発しましょう。"), name()),
        (body(), name(), name("丹恒", key=3, x=480)),  # Ambiguous nearby names.
        (body(), body("ここに残って待ちましょう。", key=4, x=280, y=860), name()),
        (body(),),  # A grouped paragraph is not evidence of speech.
    ],
)
def test_descriptions_choices_and_ambiguous_panels_do_not_enter_history(blocks):
    history = DialogueHistory()
    accept(history, blocks)
    assert history.turns == ()


def test_single_line_dialogue_unknown_name_and_continuation_in_established_panel():
    history = DialogueHistory()
    b = replace(body("うん。"), dialogue=False)
    accept(history, (b, name()), score=0.7)
    assert history.turns[0].speaker is None and history.turns[0].source == "うん。"
    b = replace(body("それでは行きましょう。", key=3), dialogue=False)
    accept(history, (b,), 2.5)
    assert len(history.turns) == 2 and history.turns[1].speaker is None
    # Lose panel evidence after leaving it; anonymous descriptions cannot establish it.
    history.observe((), (), SIZE, 8)
    accept(history, (body("使うと味方全体の体力を回復する。"),), 9)
    assert len(history.turns) == 2


def test_partial_ocr_does_not_lose_name_confidence_but_different_name_must_earn_it():
    history = DialogueHistory()
    blocks = (body(), name())
    history.observe(blocks, blocks, SIZE, 1, scores={blocks[1].lines[0]: 0.98})
    history.observe(blocks, blocks, SIZE, 2, scores={blocks[0].lines[0]: 0.99})
    history.published((result(blocks[0]),))
    assert history.turns[-1].speaker == "三月なのか"
    accept(history, blocks, 2.1, score=0.65)
    assert history.turns[-1].speaker == "三月なのか"
    accept(history, (body("では私は先に行きます。", key=5), name("丹恒", key=6)), 3, score=0.65)
    assert history.turns[-1].speaker is None


def test_unknown_character_label_is_not_asserted_as_a_confident_name():
    history = DialogueHistory()
    accept(history, (body(), name("？？？")))
    assert len(history.turns) == 1 and history.turns[0].speaker is None


def test_uncertain_name_variant_does_not_duplicate_unchanged_dialogue():
    history = DialogueHistory()
    b = body()
    accept(history, (b, name("旅人")))
    accept(history, (b, name("旅入", key=3)), 2.5, score=0.65)
    assert len(history.turns) == 1 and history.turns[0].speaker is None
    accept(history, (b, name("旅人")), 4)
    assert len(history.turns) == 1 and history.turns[0].speaker == "旅人"


def test_grouping_disabled_and_reenabled_does_not_duplicate_unchanged_dialogue():
    history = DialogueHistory()
    a = body("ここから先は危険だから、")
    line = TextTrack(5, "私と一緒に進んでください。", Rect(280, 848, 500, 36))
    grouped = TextBlock((*a.lines, line), dialogue=True)
    accept(history, (grouped, name()))
    separate = (replace(a, dialogue=False), TextBlock((line,)), name())
    for now in range(3, 15):
        history.observe(separate, separate, SIZE, now)
        history.published((result(a), result(separate[1])))
    accept(history, (grouped, name()), 15)
    assert len(history.turns) == 1


def test_group_growth_and_explicit_correction_replace_turn_without_logging_stale_english():
    history = DialogueHistory()
    first = body("私と一緒に進んでください。")
    accept(history, (first, name()))
    second = TextTrack(3, "もうすぐ町に着きます。", Rect(280, 848, 500, 36))
    grown = TextBlock((*first.lines, second), dialogue=True)
    history.observe((grown, name()), (), SIZE, 3)
    history.published((result(first),))
    assert len(history.turns) == 1 and history.turns[0].source == first.text
    accept(history, (grown, name()), 3.5, english="Come with me. We are nearly there.")
    assert len(history.turns) == 1 and history.turns[0].source == grown.text
    changed = replace(second, text="もうすぐ街に着きます。", text_revision=2)
    fixed = TextBlock((first.lines[0], changed), dialogue=True)
    history.observe((fixed, name()), (fixed,), SIZE, 5, corrections=((changed, second),))
    history.observe((fixed, name()), (fixed,), SIZE, 6)
    history.published((result(grown, "STALE"),))
    assert history.turns[0].source == grown.text
    history.published((result(fixed, "Come with me. The town is close."),))
    assert len(history.turns) == 1 and history.turns[0].source == fixed.text
    # A real content edit, even in the same track, is another turn, not a fuzzy match.
    edit = body("私と一緒には進まないでください。")
    accept(history, (edit, name()), 7)
    assert len(history.turns) == 2


def test_pending_retained_only_and_stale_replies_cannot_add_turns():
    history = DialogueHistory()
    b, n = body(), name()
    accept(history, (b, n), ready=())
    assert history.turns == ()
    history.observe((b, n), (b,), SIZE, 3)
    history.published((result(body("全く別の文章です。")),))
    assert history.turns == ()
    history.published((result(b),))
    assert len(history.turns) == 1
    for _ in range(100):
        history.observe((b, n), (b,), SIZE, 3)
        history.published((result(b),))
    assert len(history.turns) == 1
    history.clear()
    accept(history, (b, n), 3.1)
    assert history.turns == ()
    accept(history, (body("次の冒険に向かいましょう。", key=4), n), 5)
    assert len(history.turns) == 1


def test_brief_mask_resize_and_model_retranslation_do_not_duplicate_visible_turn():
    history = DialogueHistory()
    blocks = (body(), name())
    accept(history, blocks)
    history.observe((), (), SIZE, 2.4)
    history.published((result(blocks[0]),))
    accept(history, blocks, 2.5)
    assert len(history.turns) == 1
    history.reset_scene()
    accept(history, blocks, 3.9, english="A new model's translation.")
    assert len(history.turns) == 1 and history.turns[0].english == "A new model's translation."
    history.observe((), (), SIZE, 10)
    accept(history, blocks, 11)
    assert len(history.turns) == 2  # A genuinely repeated later utterance is allowed.


def test_speaker_translation_arriving_after_body_updates_the_same_turn():
    history = DialogueHistory()
    b, n = body(), name()
    accept(history, (b, n), ready=(b,))
    assert history.turns[0].speaker_english is None
    # A name reply cannot bypass source readiness.
    history.published((result(b), result(n, "March 7th")))
    assert history.turns[0].speaker_english is None
    history.observe((b, n), (b, n), SIZE, 3)
    history.published((result(b), result(n, "March 7th")))
    assert len(history.turns) == 1
    assert history.turns[0].speaker == "三月なのか"
    assert history.turns[0].speaker_english == "March 7th"
    # The active owner may republish this source using another model.
    history.published((result(b, "New body"),))
    assert history.turns[0].speaker_english is None
    history.published((result(b, "New body"), result(n, "March")))
    assert history.turns[0].speaker_english == "March"


def test_speaker_translation_requires_exact_identity_revision_and_confident_name():
    b, n = body(), name()
    stale = (
        replace(n, lines=(replace(n.lines[0], track_id=8),)),
        replace(n, lines=(replace(n.lines[0], text_revision=2),)),
        name("丹恒"),
    )
    history = DialogueHistory()
    accept(history, (b, n), ready=(b,))
    history.observe((b, n), (b, n), SIZE, 3)
    for wrong in stale:
        history.published((result(b), result(wrong, "Wrong name")))
        assert history.turns[0].speaker_english is None
    history.published((result(b), result(n, "x" * 161)))
    assert history.turns[0].speaker_english is None
    uncertain = DialogueHistory()
    accept(uncertain, (b, n), score=0.7)
    uncertain.published((result(b), result(n, "March 7th")))
    assert uncertain.turns[0].speaker is None
    assert uncertain.turns[0].speaker_english is None
