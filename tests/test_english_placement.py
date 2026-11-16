import os
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dantejp.domain import Rect  # noqa: E402
from dantejp.ocr.regions import intersects  # noqa: E402
from dantejp.ui.english_placement import EnglishLabel, EnglishPlacement  # noqa: E402
from dantejp.ui.text_layout import layout_english  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def label(i, x=100, y=100, text="This is a longer English translation for the small label."):
    return EnglishLabel(((i, 1, "日本語"),), text, Rect(x, y, 150, 24), 24)


def test_neighboring_expansions_avoid_collision_without_losing_english():
    labels = (label(1), label(2, y=130))
    independent = tuple(layout_english(item.text, item.source, (800, 600)) for item in labels)
    assert intersects(*(layout.bounds for layout in independent))
    placed = EnglishPlacement().arrange(labels, (800, 600), tuple(item.source for item in labels))
    assert not intersects(*(layout.bounds for layout in placed))
    for item, layout in zip(labels, placed, strict=True):
        assert layout.bounds.contains(item.source)
        assert not layout.truncated
        assert " ".join(layout.lines) == item.text
        assert layout.pixel_size >= 12


def test_scene_reordering_repaints_and_unrelated_arrivals_do_not_move_labels():
    owner = EnglishPlacement()
    labels = (label(1), label(2, y=130))
    sources = tuple(item.source for item in labels)
    first = owner.arrange(labels, (1200, 800), sources)
    for _ in range(20):
        assert owner.arrange(labels[::-1], (1200, 800), sources[::-1]) == first[::-1]
    extra = label(3, x=900, y=600)
    assert owner.arrange((*labels, extra), (1200, 800), (*sources, extra.source))[:2] == first
    assert owner.arrange(labels, (1200, 800), sources) == first


def test_untranslated_sources_are_reserved_and_manual_size_is_preserved():
    item = label(1, y=200)
    obstacle = Rect(100, 230, 150, 24)
    (layout,) = EnglishPlacement().arrange(
        (item,), (800, 600), (item.source, obstacle), automatic=False, pixels=24
    )
    assert not intersects(layout.bounds, obstacle)
    assert layout.pixel_size == 24


def test_crowded_edge_layout_is_bounded_and_revisions_resize_and_reset_are_fresh():
    labels = tuple(label(i, x=(i % 4) * 35, y=(i // 4) * 8) for i in range(128))
    owner = EnglishPlacement()
    placed = owner.arrange(labels, (300, 280))
    assert len(placed) == 128  # Impossible crowding never hides or drops translations.
    assert all(Rect(0, 0, 300, 280).contains(p.bounds) for p in placed)
    changed = (replace(labels[0], key=((0, 2, "新しい文章"),), text="Changed."),)
    assert owner.arrange(changed, (240, 180)) == EnglishPlacement().arrange(changed, (240, 180))
    owner.clear()
    assert owner.arrange(labels[:2], (600, 400)) == EnglishPlacement().arrange(
        labels[:2], (600, 400)
    )


def test_group_and_vertical_use_line_metrics_and_full_overflow_source_is_preserved():
    group = EnglishLabel(
        ((1, 1, "一"), (2, 1, "二")), "A complete sentence.", Rect(20, 20, 500, 150), 32
    )
    vertical = replace(label(3, x=600), source=Rect(600, 100, 24, 150), vertical=True)
    overflowing = label(4, y=300, text="Long translation " * 100)
    layouts = EnglishPlacement().arrange((group, vertical, overflowing), (900, 600))
    assert layouts[0].pixel_size == round(32 * 0.72)
    assert all(Rect(0, 0, 900, 600).contains(p.bounds) for p in layouts)
    assert layouts[-1].truncated and layouts[-1].lines[-1].endswith("…")
    assert overflowing.text == "Long translation " * 100
