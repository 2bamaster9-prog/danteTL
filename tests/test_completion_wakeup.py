import os
import threading
import time
from dataclasses import replace
from unittest.mock import Mock

from ui_fixtures import app_owner

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from ui_fixtures import create_window as MainWindow  # noqa: E402

from dantetl.completion_wakeup import CompletionWakeup  # noqa: E402
from dantetl.domain import CapturedFrame, Rect, WindowGeometry  # noqa: E402
from dantetl.ocr.values import OcrResult, TextRegion  # noqa: E402
from dantetl.translation.values import TranslatedText, TranslationRequest  # noqa: E402


def pump(app, predicate):
    end = time.monotonic() + 3
    while not predicate():
        app.processEvents()
        assert time.monotonic() < end
        time.sleep(0.001)


def test_worker_bursts_coalesce_on_ui_thread_and_wakes_during_delivery_survive(app):
    deliveries = []
    owner = threading.get_ident()

    def delivered():
        deliveries.append(threading.get_ident())
        if len(deliveries) == 1:
            wake.notify()  # New publication during delivery must get a later pass.

    wake = CompletionWakeup(delivered)
    threads = [
        threading.Thread(target=lambda: [wake.notify() for _ in range(1000)]) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert deliveries == []  # Never run receiver inline on a worker.
    pump(app, lambda: len(deliveries) == 2)
    app.processEvents()
    assert deliveries == [owner, owner]
    wake.close()
    shiboken6.delete(wake)


def test_close_revokes_queued_and_late_wakes(app):
    callback = Mock()
    wake = CompletionWakeup(callback)
    wake.notify()
    wake.close()
    app.processEvents()
    shiboken6.delete(wake)
    thread = threading.Thread(target=wake.notify)
    thread.start()
    thread.join(2)
    assert not thread.is_alive()
    callback.assert_not_called()


def test_completion_during_nested_ui_processing_never_reenters_session(app, tmp_path):
    windows = Mock()
    windows.list_targets.return_value = []
    window = MainWindow(windows, Mock(), preferences_path=tmp_path / "preferences.json")
    application = app_owner(window)
    window.driver.timer.stop()
    calls, depths = [], []
    depth = 0

    def advance(now):
        nonlocal depth
        depth += 1
        depths.append(depth)
        calls.append(1)
        if len(calls) == 1:
            window.driver.wakeup.notify()
            app.processEvents()  # Like a nested Qt modal loop.
            window._tick()  # The fallback timer may also fire during that loop.
            assert len(calls) == 1
        depth -= 1
        return application.view

    application.advance = advance
    window._tick()
    pump(app, lambda: len(calls) == 2)
    app.processEvents()
    assert depths == [1, 1]
    window.close()
    window.deleteLater()


def test_completion_advances_without_polling_but_defers_inspector_rendering(app, tmp_path):
    windows = Mock()
    windows.list_targets.return_value = []
    window = MainWindow(windows, Mock(), preferences_path=tmp_path / "preferences.json")
    application = app_owner(window)
    window.driver.timer.stop()
    window.advanced.setChecked(True)
    bounds = Rect(0, 0, 200, 100)
    frame = CapturedFrame(1, 0, WindowGeometry(bounds, bounds, bounds, 96), bytes(200 * 100 * 4))
    result = OcrResult(frame, (TextRegion("設定", Rect(10, 10, 40, 20)),), 1, 0)
    english = (TranslatedText(TranslationRequest(1, 1, "設定"), "Settings"),)
    current_result, current_english = result, english
    calls = []

    def advance(now):
        application.view = replace(
            application.view,
            observation=current_result,
            assignments=(1,),
            results=current_english,
        )
        calls.append(1)

        return application.view

    application.advance = advance
    window.driver.wakeup.notify()
    pump(app, lambda: bool(calls))
    assert window.inspector.result is None
    assert window.inspector._latest_result is result
    window._tick()
    assert window.inspector.result is result
    assert (cell := window.inspector.table.item(0, 3)) and cell.text() == "Settings"
    window.inspector.pause.setChecked(True)
    second = OcrResult(frame, (TextRegion("戻る", Rect(10, 10, 40, 20)),), 1, 0)
    current_result = second
    current_english = (TranslatedText(TranslationRequest(1, 2, "戻る"), "Back"),)
    window.driver.wakeup.notify()
    pump(app, lambda: len(calls) == 3)
    assert window.inspector.result is result
    window._tick()
    assert window.inspector.result is result
    assert (cell := window.inspector.table.item(0, 3)) and cell.text() == "Settings"
    window.inspector.pause.setChecked(False)
    assert window.inspector.result is second
    assert (cell := window.inspector.table.item(0, 3)) and cell.text() == "Back"
    window.close()
    window.deleteLater()
