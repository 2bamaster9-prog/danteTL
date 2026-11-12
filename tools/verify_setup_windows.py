"""Native setup UX check using our demo, local models, and simulated consent clicks.

No downloads, game captures, or real preparation receipts. The model is actually
loaded and warmed on its worker. Saves only this application's widgets.
"""

import argparse
import json
import os
import time
import traceback
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from jp_overlay.app import create_recognizer, translation_backends
from jp_overlay.demo import DemoWindow
from jp_overlay.domain import WindowTarget
from jp_overlay.model_store import model_catalog
from jp_overlay.translation import BackendChoice, TranslationState
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--missing-runtime",
        action="store_true",
        help="Verify downloaded Gemma in a fresh CPU-only environment",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/setup"))
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow(dialogue=True)
    demo.show()
    bundles = model_catalog()
    missing = tuple(replace(b, directory=output / "not-installed" / b.key) for b in bundles)
    window = MainWindow(
        windows,
        create_recognizer,
        models=missing,
        backend_provider=translation_backends,
        cache_path=output / "cache.sqlite3",
    )
    window.show()
    target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
    window.windows_combo.addItem("Setup verification fixture", target)
    window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
    window.start_button.click()
    started, stage = time.monotonic(), 0
    preparation_ticks = 0
    receipts, loads = [], []
    evidence = {}
    failed = False

    def tick():
        nonlocal stage, preparation_ticks, failed
        try:
            assert time.monotonic() - started < 90, "Setup verification timed out"
            if stage == 0:
                if not window._session or not window._session.snapshot().frame:
                    return
                assert window._ocr is None and window._translation is None
                assert not window._overlay._translations
                window.grab().save(str(output / "capture-only.png"))
                evidence["capture_without_models"] = True
                window.start_button.click()
                stage = 1
            elif stage == 1:
                if window._session is not None:
                    return
                window._models = bundles
                window._refresh_models()
                assert window.backend_combo.currentData() is None
                window._manage_models()
                if args.missing_runtime:
                    assert window._model_manager
                    window._model_manager.choice.setCurrentIndex(
                        next(i for i, b in enumerate(bundles) if b.key == "gemma")
                    )
                stage = 2
            elif stage == 2:
                assert window._model_manager
                window._model_manager.grab().save(str(output / "model-manager.png"))
                window._model_manager.close()
                index = next(
                    i
                    for i in range(window.backend_combo.count())
                    if isinstance(b := window.backend_combo.itemData(i), BackendChoice)
                    and b.key.startswith("gemma")
                )
                original = window.backend_combo.itemData(index)
                if args.missing_runtime:
                    assert original.unavailable_reason
                    assert "Setup Gemma.cmd" in original.unavailable_reason
                    assert "not installed" in window._model_manager.status.text()
                    assert window.translate_check.isEnabled() and window.backend_combo.isEnabled()
                    with patch.object(QMessageBox, "information") as explanation:
                        window.backend_combo.setCurrentIndex(index)
                        explanation.assert_called_once()
                    assert window.backend_combo.currentData() is None
                    assert window._translation is None and window._preparing is None
                    evidence["downloaded_gemma_visible_without_runtime"] = True
                    evidence["missing_runtime_explained_without_loading"] = True
                    window.grab().save(str(output / "runtime-needed.png"))
                    stage = 5
                    return

                def load():
                    loads.append(time.monotonic())
                    return original.create()

                window.backend_combo.setItemData(
                    index,
                    replace(original, create=load, preparation_id=f"verification-{time.time_ns()}"),
                )
                with patch.object(
                    QMessageBox, "question", return_value=QMessageBox.StandardButton.No
                ):
                    window.backend_combo.setCurrentIndex(index)
                assert window.backend_combo.currentData() is None and not loads
                evidence["decline_returns_to_none_without_loading"] = True
                with patch.object(
                    QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes
                ):
                    window.backend_combo.setCurrentIndex(index)
                stage = 3
            elif stage == 3:
                if window._preparing:
                    preparation_ticks += 1
                    if preparation_ticks == 3:
                        assert window._progress_dialog
                        window._progress_dialog.grab().save(str(output / "preparation.png"))
                    return
                assert receipts and len(loads) == 1
                assert (
                    window._translation
                    and window._translation.snapshot().state == TranslationState.READY
                )
                evidence["responsive_preparation_ui_polls"] = preparation_ticks
                evidence["prepared_worker_reused"] = True
                window.start_button.click()
                stage = 4
            elif stage == 4:
                if not window._translation or not window._translation.snapshot().results:
                    return
                assert len(loads) == 1
                window.grab().save(str(output / "ready.png"))
                window.backend_combo.setCurrentIndex(window.backend_combo.count() - 1)
                stage = 5
            elif stage == 5:
                if window._translation:
                    return
                assert not window._overlay._translations
                evidence[
                    "no_unavailable_model_loaded"
                    if args.missing_runtime
                    else "none_unloads_model_and_removes_english"
                ] = True
                window.close()
                stage = 6
            elif stage == 6 and not window._timer.isActive():
                evidence["shutdown_finished"] = True
                demo.close()
                app.quit()
        except Exception:
            failed = True
            evidence["error"] = traceback.format_exc()
            window.close()
            demo.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    with patch("jp_overlay.ui.mark_prepared", receipts.append):
        app.exec()
    timer.stop()
    (output / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
