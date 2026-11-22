from dataclasses import replace

import pytest

from dantetl.domain import Rect
from dantetl.ocr.observation import TextTrack
from dantetl.translation.dialogue.context import DialogueMemory, DialogueTurn
from dantetl.translation.grouping import TextBlock


def block(text="私の名前はリナです。", key=1, *, dialogue=True, x=100, y=600):
    return TextBlock((TextTrack(key, text, Rect(x, y, 500, 40)),), dialogue=dialogue)


def test_only_the_same_unambiguous_panel_receives_recent_published_turns():
    memory = DialogueMemory()
    first, second = block(), block("明日は一緒に行きましょう。", 2)
    menu = block("設定", 3, dialogue=False, y=100)
    memory.observe((first, menu), 0)
    memory.published(first, "My name is Rina.", 0)
    memory.observe((second, menu), 1)
    assert memory.context_for(second) == (DialogueTurn(first.text, "My name is Rina."),)
    assert not memory.context_for(menu)
    memory.observe((second, block("別の会話です。", 4, x=800)), 2)
    assert not memory.context_for(second)


def test_short_reply_can_follow_dialogue_but_a_menu_label_cannot():
    memory = DialogueMemory()
    first = block()
    memory.observe((first,), 0)
    memory.published(first, "Rina.", 0)
    reply = block("はい。", 2, dialogue=False)
    memory.observe((reply,), 1)
    assert memory.context_for(reply)
    menu = block("設定", 3, dialogue=False)
    memory.observe((menu,), 2)
    assert not memory.context_for(menu)


def test_reveal_evidence_survives_until_single_line_is_ready_to_publish():
    memory = DialogueMemory()
    growing = block()
    memory.observe((growing,), 0)
    settled = replace(growing, dialogue=False)
    memory.observe((settled,), 0.5)
    memory.published(settled, "Rina.", 0.5)
    next_turn = block("明日は一緒に行きましょう。", 2)
    memory.observe((next_turn,), 1)
    assert memory.context_for(next_turn) == (DialogueTurn(growing.text, "Rina."),)


def test_history_expires_on_absence_age_panel_change_and_explicit_reset():
    for kind in ("absence", "age", "panel", "reset"):
        memory = DialogueMemory()
        first, second = block(), block("明日は一緒に行きましょう。", 2)
        memory.observe((first,), 0)
        memory.published(first, "Rina.", 0)
        if kind == "age":
            for t in range(1, 32):
                memory.observe((first,), t)
        elif kind == "panel":
            second = block(second.text, 2, x=900)
        elif kind == "reset":
            memory.reset()
        memory.observe((second,), 32 if kind == "age" else 4 if kind == "absence" else 1)
        assert not memory.context_for(second), kind


def test_revisions_replace_history_and_never_feed_themselves_back():
    memory = DialogueMemory()
    first = block()
    memory.observe((first,), 0)
    memory.published(first, "My name is Rina.", 0)
    correction = replace(first, lines=(replace(first.lines[0], text_revision=2),))
    memory.observe((correction,), 1)
    assert not memory.context_for(correction)
    memory.published(correction, "I'm Rina.", 1)
    second = block("明日は一緒に行きましょう。", 2)
    memory.observe((second,), 2)
    assert memory.context_for(second) == (DialogueTurn(first.text, "I'm Rina."),)


def test_bounded_history_and_stale_results_do_not_seed_memory():
    memory = DialogueMemory()
    for key, text in enumerate(
        ("今日は冒険に出かけよう。", "敵を倒したぞ！", "また会えるといいですね。")
    ):
        current = block(text, key)
        memory.observe((current,), key)
        memory.published(current, "English " + str(key), key)
    next_block = block("村へ戻りましょう。", 10)
    memory.observe((next_block,), 3)
    assert len(memory.context_for(next_block)) == 2
    memory.published(block("古い結果", 99), "stale", 3)
    assert all(t.english != "stale" for t in memory.context_for(next_block))
    memory.published(next_block, "x" * 513, 3)
    assert sum(len(t.source) + len(t.english) for t in memory.context_for(next_block)) <= 512


@pytest.mark.parametrize("key", (1, 2))
def test_negation_is_a_new_turn_even_when_tracking_reuses_the_box(key):
    memory = DialogueMemory()
    first = block("私は彼を信じている。")
    second = block("私は彼を信じていない。", key)
    second = replace(second, lines=(replace(second.lines[0], text_revision=2),))
    memory.observe((first,), 0)
    memory.published(first, "I trust him.", 0)
    memory.observe((second,), 1)
    assert memory.context_for(second) == (DialogueTurn(first.text, "I trust him."),)
    memory.published(second, "I do not trust him.", 1)
    following = block("そうですか。", 3)
    memory.observe((following,), 2)
    assert memory.context_for(following) == (
        DialogueTurn(first.text, "I trust him."),
        DialogueTurn(second.text, "I do not trust him."),
    )


def test_identical_or_prefixed_words_on_new_tracks_are_distinct_turns():
    for source in ("はい。", "はい。行きましょう。"):
        memory = DialogueMemory()
        first, second = block("はい。"), block(source, 2)
        memory.observe((first,), 0)
        memory.published(first, "Yes.", 0)
        memory.observe((second,), 1)
        assert memory.context_for(second) == (DialogueTurn(first.text, "Yes."),)


def test_tracked_growth_and_explicit_correction_replace_only_their_own_turn():
    memory = DialogueMemory()
    first = block("私の名前はリナ")
    memory.observe((first,), 0)
    memory.published(first, "My name is Rina", 0)
    grown = replace(
        first, lines=(replace(first.lines[0], text="私の名前はリナです。", text_revision=2),)
    )
    memory.observe((grown,), 1)
    assert not memory.context_for(grown)
    memory.published(grown, "My name is Rina.", 1)
    corrected = replace(
        grown, lines=(replace(grown.lines[0], text="私の名前はリノです。", text_revision=3),)
    )
    memory.observe((corrected,), 2, corrections=((corrected.lines[0], grown.lines[0]),))
    assert not memory.context_for(corrected)
    memory.published(grown, "Stale Rina", 2)
    memory.published(corrected, "My name is Rino.", 2)
    following = block("よろしくね。", 2)
    memory.observe((following,), 3)
    assert memory.context_for(following) == (DialogueTurn(corrected.text, "My name is Rino."),)


def test_new_continuation_line_keeps_turn_but_an_edit_to_existing_members_does_not():
    memory = DialogueMemory()
    first = block()
    memory.observe((first,), 0)
    memory.published(first, "Rina.", 0)
    grown = replace(first, lines=(*first.lines, block("よろしくね。", 2, y=650).lines[0]))
    memory.observe((grown,), 1)
    assert not memory.context_for(grown)
    memory.published(grown, "Rina. Nice to meet you.", 1)
    changed = replace(
        grown,
        lines=(
            replace(grown.lines[0], text="私の名前はリノです。", text_revision=2),
            grown.lines[1],
        ),
    )
    memory.observe((changed,), 2)
    assert memory.context_for(changed) == (DialogueTurn(grown.text, "Rina. Nice to meet you."),)
