from dataclasses import replace

from jp_overlay.dialogue_context import DialogueMemory, DialogueTurn
from jp_overlay.domain import Rect
from jp_overlay.grouping import TextBlock
from jp_overlay.tracking import TextTrack


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
