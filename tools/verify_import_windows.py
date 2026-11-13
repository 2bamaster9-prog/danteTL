"""Native import lifecycle with local GGUFs and our own demo; no downloads or game capture."""

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtWidgets import QApplication, QMessageBox

from jp_overlay import gguf_models
from jp_overlay.app import create_recognizer, ocr_backends, translation_backends
from jp_overlay.demo import DemoWindow
from jp_overlay.domain import WindowTarget
from jp_overlay.model_store import model_catalog
from jp_overlay.translation import TranslationState
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/import-native"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    registry = output / "imported-models.json"
    if registry.exists():
        raise ValueError("Use a fresh output directory.")
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)

    def wait(predicate, *, timeout=180):
        deadline = time.monotonic() + timeout
        while not predicate():
            app.processEvents()
            if time.monotonic() >= deadline:
                raise AssertionError("Native import check timed out")
            time.sleep(0.02)
        app.processEvents()

    with (
        patch.object(gguf_models, "registry_path", return_value=registry),
        patch("jp_overlay.ui.is_prepared", return_value=False),
        patch("jp_overlay.ui.mark_prepared"),
        patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes),
        patch.object(QMessageBox, "warning") as warning,
    ):
        demo = DemoWindow(dialogue=True)
        demo.show()
        window = MainWindow(
            windows,
            create_recognizer,
            translation_backends(),
            ocr_backends=ocr_backends(),
            models=model_catalog(),
            backend_provider=translation_backends,
            cache_path=output / "cache.sqlite3",
            preferences_path=output / "preferences.json",
        )
        window.show()
        manager = window._settings.models
        try:
            target = WindowTarget(int(demo.winId()), os.getpid(), demo.windowTitle())
            window.windows_combo.addItem("Import test fixture", target)
            window.windows_combo.setCurrentIndex(window.windows_combo.count() - 1)
            window.start_button.click()
            gemma_index = next(
                i
                for i in range(window.backend_combo.count())
                if getattr(window.backend_combo.itemData(i), "key", "").startswith("gemma-")
            )
            window.backend_combo.setCurrentIndex(gemma_index)
            wait(
                lambda: (
                    window._translation
                    and window._translation.snapshot().state == TranslationState.READY
                    and window._preparing is None
                )
            )
            old_choice, old_worker = window._selected_backend, window._translation
            assert old_worker is not None
            wait(lambda: window._overlay._translations)
            window._settings.show_models()
            manager._import()
            dialog = manager.import_dialog
            assert dialog
            dialog.file.setText(str(args.model.resolve()))
            dialog.start_test()
            wait(lambda: "Testing on" in dialog.status.text() or dialog.operation is None)
            assert dialog.operation, dialog.status.text()
            dialog.cancel()
            wait(lambda: dialog.operation is None)
            assert not dialog.add_button.isEnabled() and not registry.exists()
            assert window._selected_backend == old_choice
            dialog.start_test()
            wait(lambda: dialog.operation is None)
            assert dialog.add_button.isEnabled(), dialog.status.text()
            assert old_worker.finished and window._selected_backend == old_choice
            assert not registry.exists(), "Testing must not register or select the model"
            dialog.grab().save(str(output / "import-review.png"))
            assert dialog.test and dialog.test.result
            result = dialog.test.result
            dialog.add_button.click()
            wait(lambda: dialog.operation is None and registry.exists())
            assert window._selected_backend == old_choice
            model = gguf_models.read_registry()[0]
            index = next(
                i
                for i in range(window.backend_combo.count())
                if getattr(window.backend_combo.itemData(i), "key", "") == model.key
            )
            window.backend_combo.setCurrentIndex(index)
            wait(
                lambda: (
                    window._selected_backend
                    and window._selected_backend.key == model.key
                    and window._translation
                    and window._translation.snapshot().state == TranslationState.READY
                )
            )
            wait(lambda: window._overlay._translations)
            window.grab().save(str(output / "imported-active.png"))
            imported_worker = window._translation
            window.backend_combo.setCurrentIndex(gemma_index)
            wait(
                lambda: (
                    window._translation
                    and window._translation.snapshot().state == TranslationState.READY
                    and window._selected_backend == old_choice
                )
            )
            assert imported_worker is not None
            wait(lambda: window._overlay._translations)
            manager.refresh()
            item = next(
                i
                for i in range(manager.choice.count())
                if getattr(manager.choice.itemData(i), "key", "") == model.key
            )
            manager.choice.setCurrentIndex(item)
            app.processEvents()
            manager.grab().save(str(output / "registered-model.png"))
            manager._remove()
            wait(lambda: manager.operation is None and not gguf_models.read_registry())
            assert args.model.is_file() and window._selected_backend == old_choice
            assert not warning.called, warning.call_args
            (output / "results.json").write_text(
                json.dumps(
                    {
                        "model": model.name,
                        "device": result.device,
                        "gpu_layers": result.offloaded_layers,
                        "samples": result.samples,
                        "load_ms": result.load_ms,
                        "test_kept_selection": True,
                        "previous_unloaded_before_probe": old_worker.finished,
                        "import_and_switch_back": True,
                        "removal_kept_file": True,
                    },
                    indent=2,
                ),
                "utf-8",
            )
            print(
                "Native import, inference, selection, Gemma return and registration removal passed."
            )
        finally:
            window.close()
            wait(lambda: not window.isVisible(), timeout=60)
            demo.close()
    shiboken6.delete(app)


if __name__ == "__main__":
    main()
