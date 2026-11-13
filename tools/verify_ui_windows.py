"""Native layout/settings check with our own demo; no game capture or model downloads."""

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import shiboken6
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jp_overlay.app import create_recognizer, ocr_backends, translation_backends
from jp_overlay.controls import InfoButton
from jp_overlay.demo import DemoWindow
from jp_overlay.hardware import HardwareCheck
from jp_overlay.model_store import model_catalog
from jp_overlay.preferences import PreferenceStore
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/ui"))
    parser.add_argument("--missing-models", action="store_true", help="Show first-run warnings")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    demo = DemoWindow(dialogue=True)
    preferences_path = args.output / f"preferences-{time.time_ns()}.json"
    hardware = HardwareCheck()
    hardware.start()
    models = model_catalog()
    if args.missing_models:
        models = tuple(replace(b, directory=args.output / "not-installed" / b.key) for b in models)
    window = MainWindow(
        windows,
        create_recognizer,
        () if args.missing_models else translation_backends(),
        models=models,
        ocr_backends=ocr_backends(),
        preferences_path=preferences_path,
        hardware=hardware,
    )
    # Show only our fixture name in screenshots, never another application's title.
    window.windows_combo.clear()
    window.windows_combo.addItem("DanteJP Demo · 日本語のテスト")
    window.show()
    started, stage = time.monotonic(), 0
    failed = False
    evidence = {}

    def tick():
        nonlocal stage, failed
        try:
            assert time.monotonic() - started < 20, "UI verification timed out"
            settings = window._settings
            if stage == 0:
                if not hardware.finished:
                    return
                assert not window.advanced.isChecked() and not window.advanced_panel.isVisible()
                assert window.translate_check.text() == "Translation overlay"
                QTest.keyClick(window.overlay_check, Qt.Key.Key_Space)
                assert not window.overlay_check.isChecked()
                QTest.keyClick(window.overlay_check, Qt.Key.Key_Space)
                assert window.overlay_check.isChecked()
                evidence["keyboard_switch_toggle"] = True
                evidence["compact_size"] = [window.width(), window.height()]
                window.grab().save(str(args.output / "main.png"))
                if args.missing_models:
                    assert (
                        window.onboarding.isVisible() and "not downloaded" in window.notice.text()
                    )
                    assert window.onboarding.property("tone") == "warning"
                window.settings_button.click()
                stage = 1
            elif stage == 1:
                assert settings.isVisible() and not settings.isModal()
                assert [settings.tabs.tabText(i) for i in range(settings.tabs.count())] == [
                    "Appearance",
                    "Recognition",
                    "Models",
                    "Acceleration",
                    "Hotkeys",
                ]
                assert settings.runtime is None  # Merely opening Settings does not start setup.
                assert window.stabilize_check.isChecked() and window.automatic_font.isChecked()
                settings.grab().save(str(args.output / "appearance.png"))
                settings.opacity.setValue(62)
                window.automatic_font.setChecked(False)
                window.font_size.setValue(24)
                settings.tabs.setCurrentIndex(1)
                stage = 2
            elif stage == 2:
                settings.set_capture_active(True)
                assert settings.ocr_device.isEnabled() and settings.capture_rate.isEnabled()
                assert "next time" in settings.capture_note.text()
                settings.grab().save(str(args.output / "recognition.png"))
                window._manage_models()
                stage = 3
            elif stage == 3:
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Models"
                assert ("Download required" if args.missing_models else "Downloaded") in (
                    settings.models.download_badge.text()
                )
                settings.grab().save(str(args.output / "models.png"))
                gemma = next(
                    (
                        i
                        for i in range(settings.models.choice.count())
                        if settings.models.choice.itemData(i).key == "gemma"
                    ),
                    None,
                )
                if gemma is not None:
                    settings.models.choice.setCurrentIndex(gemma)
                stage = 31
            elif stage == 31:
                description = settings.models.description
                assert description.height() >= description.heightForWidth(description.width()), (
                    "Model description is clipped after changing selection"
                )
                settings.grab().save(str(args.output / "gemma-status.png"))
                settings.models.runtime_button.click()
                stage = 4
            elif stage == 4:
                if settings.busy:
                    return
                assert window._runtime_dialog and window._runtime_dialog.isVisible()
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Acceleration"
                assert not window._translation and not window._ocr
                settings.grab().save(str(args.output / "runtime.png"))
                runtime = settings.runtime
                settings.show_hotkeys()
                assert settings.tabs.tabText(settings.tabs.currentIndex()) == "Hotkeys"
                settings.show_models()
                settings.show_runtime()
                assert (
                    settings.runtime is runtime
                )  # Navigating never replaces an active setup view.
                evidence["separate_setup_tabs_and_navigation"] = True
                settings.resize(550, 470)
                stage = 5
            elif stage == 5:
                assert settings.width() <= 550, "Settings minimum width broke the compact layout"
                settings.grab().save(str(args.output / "settings-small.png"))
                assert all(
                    b.accessibleName() and b.toolTip() for b in settings.findChildren(InfoButton)
                )
                settings.close()
                # Background setup notices may have enlarged the main window since startup.
                evidence["before_expansion_height"] = window.height()
                window.advanced.setChecked(True)
                stage = 6
            elif stage == 6:
                assert window.advanced_panel.isVisible()
                window.grab().save(str(args.output / "advanced.png"))
                window.advanced.setChecked(False)
                if not window._preferences.idle:
                    return
                saved = PreferenceStore(preferences_path).initial
                assert saved.opacity == 62 and saved.text_size == 24 and not saved.automatic_size
                evidence.update(
                    settings_saved=True, info_controls=len(settings.findChildren(InfoButton))
                )
                window.showMaximized()
                stage = 8
            elif stage == 8:
                assert window.isMaximized()
                assert window.control_panel.width() <= 760 and window.control_panel.height() < 850
                assert window.control_panel.mapTo(window, QPoint()).y() <= 24
                assert window.translate_check.mapTo(window, QPoint()).x() < 450
                assert window.windows_combo.mapTo(window, QPoint()).y() < 200
                window.grab().save(str(args.output / "maximized.png"))
                window.advanced.setChecked(True)
                stage = 9
            elif stage == 9:
                assert window.isMaximized() and window.advanced_panel.isVisible()
                window.grab().save(str(args.output / "maximized-advanced.png"))
                window.advanced.setChecked(False)
                stage = 10
            elif stage == 10:
                assert window.isMaximized() and not window.advanced_panel.isVisible()
                evidence["maximized_controls_stay_compact_and_left"] = True
                evidence["advanced_preserves_maximized_state"] = True
                window.showNormal()
                stage = 11
            elif stage == 11:
                window.close()
                stage = 7
            elif stage == 7:
                if window.isVisible():
                    return
                assert window.height() <= evidence["before_expansion_height"], (
                    "Collapsing Advanced did not restore its previous compact height"
                )
                evidence["shutdown_finished"] = True
                (args.output / "results.json").write_text(json.dumps(evidence, indent=2), "utf-8")
                print(json.dumps(evidence), flush=True)
                timer.stop()
                app.quit()
        except Exception as error:
            failed = True
            print(f"FAIL at stage {stage}: {error!r}", flush=True)
            timer.stop()
            window._settings.cancel_operations()
            window.hide()
            app.quit()

    timer = QTimer()
    timer.setInterval(180)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    demo.close()
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
