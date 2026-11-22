import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from dantetl.application.cache_management import CacheManagement  # noqa: E402
from dantetl.translation.cache import TranslationCache  # noqa: E402
from dantetl.ui.cache_settings import CacheSettings  # noqa: E402


def test_cache_controls_confirm_named_game_and_full_clear(app, tmp_path):
    path = tmp_path / "disposable.sqlite3"
    cache = TranslationCache(path)
    for game in ("First", "Second"):
        cache.lookup_pending((game,), reset=False, game=game)
        cache.put(game, "Answer", scope=cache.scope)
    cache.close()
    commands = CacheManagement(path, lambda: None)
    page = CacheSettings(commands)

    def settled():
        end = time.monotonic() + 3
        while commands.snapshot().busy:
            QTest.qWait(5)
            assert time.monotonic() < end
        page.refresh_view()
        return page.games.count()

    def click(button, response):
        prompts = []

        def respond():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                prompts.append(dialog.text())
                dialog.done(response)

        QTimer.singleShot(0, respond)
        button.click()
        assert len(prompts) == 1
        return prompts[0]

    page.show()
    app.processEvents()
    try:
        assert settled() == 2
        page.games.setCurrentRow(0)
        for answer, count in (
            (QMessageBox.StandardButton.Cancel, 2),
            (QMessageBox.StandardButton.Yes, 1),
        ):
            assert "First" in click(page.clear_game, answer)
            assert settled() == count
        assert page.games.item(0).data(Qt.ItemDataRole.UserRole) == "Second"
        for answer, count in (
            (QMessageBox.StandardButton.Cancel, 1),
            (QMessageBox.StandardButton.Yes, 0),
        ):
            click(page.clear_all, answer)
            assert settled() == count
        assert not page.clear_game.isEnabled() and not page.clear_all.isEnabled()
    finally:
        page.close()
