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
from verification_isolation import app_owner
from verification_isolation import create_window as MainWindow

from dantetl.application.model_discovery import inspect_models, translation_backends
from dantetl.application.model_factories import create_recognizer
from dantetl.capture.windows import Windows
from dantetl.domain import WindowTarget
from dantetl.runtime.model_store import model_catalog
from dantetl.translation.selection import ModelOption
from dantetl.translation.values import TranslationState
from dantetl.ui.demo import DemoWindow


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--missing-runtime",
        action="store_true",
        help="Simulate an absent language-model engine with downloaded Gemma",
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/setup"))
    parser.add_argument(
        "--model",
        choices=("gemma", "gemma-e4b", "qwen35-4b", "plamo-2b", "plamo-0.8b"),
        default="gemma",
    )
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
    missing = tuple(
        replace(b, directory=output / "not-installed" / b.key, bundled_directory=None)
        for b in bundles
    )
    window = MainWindow(
        windows,
        create_recognizer,
        models=missing,
        backend_provider=translation_backends,
        cache_path=output / "cache.sqlite3",
    )
    application = app_owner(window)
    window.show()
    target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
    window.windows_combo.addItem("Setup verification fixture", target)
    window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
    window.start_button.click()
    started, stage = time.monotonic(), 0
    preparation_ticks = 0
    receipts, loads = [], []
    application.inventory._record = receipts.append
    evidence = {}
    failed = False

    def tick():
        nonlocal stage, preparation_ticks, failed
        try:
            assert time.monotonic() - started < 90, "Setup verification timed out"
            if stage == 0:
                if not application.live.capture or not application.live.capture.snapshot().frame:
                    return
                assert (
                    application.live.ocr is None
                    and application.translation.lifecycle.publication is None
                )
                assert not window._overlay._translations
                window.grab().save(str(output / "capture-only.png"))
                evidence["capture_without_models"] = True
                window.start_button.click()
                stage = 1
            elif stage == 1:
                if application.live.capture is not None:
                    return
                # The fixture changes its catalog paths to simulate files arriving.
                # Settings is now persistent, so update its test catalog too.
                assert window._model_manager
                application.inventory.set_inspector(lambda: inspect_models(bundles))
                application.setup.set_models(bundles)
                window._model_manager.refresh()
                window._refresh_models()
                assert window.backend_combo.currentData() is None
                window._manage_models()
                stage = 2
            elif stage == 2:
                assert window._model_manager
                if not any(f.key == args.model and f.present for f in application.setup.files):
                    return
                window._model_manager.refresh()
                if args.missing_runtime:
                    assert window._model_manager
                    window._model_manager.choice.setCurrentIndex(
                        next(
                            i
                            for i in range(window._model_manager.choice.count())
                            if window._model_manager.choice.itemData(i).key == args.model
                        )
                    )
                assert window._model_manager
                window._settings.grab().save(str(output / "model-manager.png"))
                window._settings.hide()
                index = next(
                    i
                    for i in range(window.backend_combo.count())
                    if isinstance(b := window.backend_combo.itemData(i), ModelOption)
                    and b.reference == "local:" + args.model
                )
                option = window.backend_combo.itemData(index)
                original = next(b for b in application.translation.choices if b.key == option.key)
                if original.key == f"{args.model}-cpu":
                    assert not original.unavailable_reason and original.performance_notice
                    window._model_manager.choice.setCurrentIndex(
                        next(
                            i
                            for i in range(window._model_manager.choice.count())
                            if window._model_manager.choice.itemData(i).key == args.model
                        )
                    )
                    assert "CPU ready" in window._model_manager.runtime_badge.text()
                    window._settings.grab().save(str(output / "cpu-ready.png"))
                    evidence["cpu_model_usable_without_gpu_setup"] = True
                if args.missing_runtime:
                    assert original.unavailable_reason
                    assert "Acceleration" in original.unavailable_reason
                    assert "not installed" in window._model_manager.status.text()
                    assert window.translate_check.isEnabled() and window.backend_combo.isEnabled()
                    window.backend_combo.setCurrentIndex(index)
                    assert window._runtime_dialog and window._runtime_dialog.isVisible()
                    window._runtime_dialog.grab().save(str(output / "runtime-setup.png"))
                    window._runtime_dialog.close()
                    assert window.backend_combo.currentData() is None
                    assert (
                        application.translation.lifecycle.publication is None
                        and not application.translation.lifecycle.snapshot().preparing
                    )
                    evidence["downloaded_gemma_visible_without_runtime"] = True
                    evidence["missing_runtime_explained_without_loading"] = True
                    window.grab().save(str(output / "runtime-needed.png"))
                    stage = 5
                    return

                def load():
                    loads.append(time.monotonic())
                    return original.create()

                candidate = replace(
                    original, create=load, preparation_id=f"verification-{time.time_ns()}"
                )
                inventory = application.inventory
                data = replace(
                    inventory.snapshot().data,
                    backends=tuple(
                        candidate if b.key == original.key else b
                        for b in application.translation.choices
                    ),
                )
                inventory._inspect = lambda: data
                inventory.invalidate()
                inventory._snapshot = replace(
                    inventory.snapshot(), data=data, revision=inventory.snapshot().revision + 1
                )
                window.routing.set_models(
                    application.translation.options(), application.translation.plan
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
                if application.translation.lifecycle.snapshot().preparing:
                    preparation_ticks += 1
                    if preparation_ticks == 3:
                        assert window._progress_dialog
                        window._progress_dialog.grab().save(str(output / "preparation.png"))
                    return
                assert len(loads) == 1
                assert (
                    application.translation.lifecycle.publication
                    and application.translation.lifecycle.publication.snapshot().state
                    == TranslationState.READY
                )
                # Preparation commits immediately; inventory persists its receipt on
                # the background worker. Readiness does not wait for that disk write.
                if not receipts:
                    return
                evidence["responsive_preparation_ui_polls"] = preparation_ticks
                evidence["prepared_worker_reused"] = True
                if (
                    selected := application.translation.lifecycle.snapshot().selected
                ) and selected.key == "gemma-cpu":
                    window._update_notice()
                    assert "CPU translation" in window.notice.text()
                    evidence["cpu_performance_notice"] = True
                window.start_button.click()
                stage = 4
            elif stage == 4:
                if (
                    not application.translation.lifecycle.publication
                    or not application.translation.lifecycle.publication.snapshot().results
                ):
                    return
                assert len(loads) == 1
                window.grab().save(str(output / "ready.png"))
                window.translate_check.setChecked(False)
                stage = 5
            elif stage == 5:
                if application.translation.lifecycle.publication:
                    return
                assert not window._overlay._translations
                evidence[
                    "no_unavailable_model_loaded"
                    if args.missing_runtime
                    else "translation_off_unloads_model_and_removes_english"
                ] = True
                window.close()
                stage = 6
            elif stage == 6 and not window.driver.timer.isActive():
                evidence["shutdown_finished"] = True
                demo.close()
                app.quit()
        except Exception:
            failed = True
            evidence["stage"] = stage
            evidence["status"] = window.status.text()
            evidence["ocr"] = window.ocr_status.text()
            evidence["translation"] = window.translation_status.text()
            evidence["assignment"] = repr(window.routing.selection)
            evidence["model_lifecycle"] = str(application.translation.lifecycle.snapshot().phase)
            evidence["worker_state"] = (
                str(application.translation.lifecycle.publication.snapshot().state)
                if application.translation.lifecycle.publication
                else None
            )
            evidence["error"] = traceback.format_exc()
            window.close()
            demo.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    from contextlib import nullcontext

    runtime_check = (
        patch("dantetl.runtime.llama.installed_device", return_value=None)
        if args.missing_runtime
        else nullcontext()
    )
    with patch("dantetl.runtime.model_store.mark_prepared", receipts.append), runtime_check:
        app.exec()
    timer.stop()
    (output / "result.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    from verification_isolation import run_isolated

    run_isolated(main)
