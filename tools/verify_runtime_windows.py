"""Exercise actual in-app setup/restart in an extracted, disposable distribution (no games)."""

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

import shiboken6
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from jp_overlay import runtime_setup, ui
from jp_overlay.app import create_recognizer, ocr_backends, translation_backends
from jp_overlay.hotkeys import HotkeyAction, Hotkeys
from jp_overlay.hotkeys_windows import WindowsHotkeyEvents, WindowsHotkeyRegistrar
from jp_overlay.model_store import model_catalog
from jp_overlay.preferences import Preferences, PreferenceStore
from jp_overlay.runtime_restart import RuntimeRestart
from jp_overlay.ui import MainWindow
from jp_overlay.windows import Windows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("nvidia", "amd", "cpu"), required=True)
    parser.add_argument(
        "--offline", action="store_true", help="Use already cached dependencies only"
    )
    parser.add_argument("--output", type=Path, default=Path("artifacts/runtime-setup"))
    parser.add_argument(
        "--cache-root", type=Path, help="Reuse a development project's uv/Python cache"
    )
    args = parser.parse_args()
    root = runtime_setup.project_root()
    if "artifacts" not in root.parts:
        raise SystemExit(
            "Run this installer check from a disposable extracted copy under artifacts."
        )
    args.output.mkdir(parents=True, exist_ok=True)
    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    preferences = root / "data/preferences.json"
    preferences.parent.mkdir(exist_ok=True)
    PreferenceStore(preferences)._write(
        Preferences(overlay_hotkey="Ctrl+Alt+Shift+F6", capture_hotkey="Ctrl+Alt+Shift+F7")
    )
    hotkeys = Hotkeys(WindowsHotkeyRegistrar())
    native = WindowsHotkeyEvents(app, hotkeys)
    window = MainWindow(
        windows,
        create_recognizer,
        translation_backends(),
        ocr_backends=ocr_backends(),
        models=model_catalog(),
        backend_provider=translation_backends,
        preferences_path=preferences,
        hotkeys=hotkeys,
    )
    assert not window._settings.hotkeys.problem, window._settings.hotkeys.problem
    window.show()
    window._manage_models()
    assert window._model_manager
    window._model_manager.runtime_button.click()
    dialog = window._runtime_dialog
    assert dialog
    stage, ticks, busy_ticks = 0, 0, 0
    started = time.monotonic()
    child: RuntimeRestart | None = None
    evidence = {"profile": args.profile, "initial_environment": sys.prefix}
    failed = False
    original_command = runtime_setup.run_setup_command

    def command(argv, *a, **kw):
        if args.cache_root:
            a[1]["UV_CACHE_DIR"] = str(args.cache_root / ".uv-cache")
            a[1]["UV_PYTHON_INSTALL_DIR"] = str(args.cache_root / ".python")
        if args.offline and "sync" in argv:
            argv = [*argv, "--offline"]
        return original_command(argv, *a, **kw)

    def restart(*a, **kw):
        nonlocal child
        assert not any(hotkeys.shortcut(action) for action in HotkeyAction)
        evidence["hotkeys_released_before_restart"] = True
        child = RuntimeRestart(*a, **kw)
        return child

    def tick():
        nonlocal stage, ticks, busy_ticks, failed
        ticks += 1
        try:
            assert time.monotonic() - started < 600, "Runtime verification timed out"
            if stage == 0:
                if dialog.operation:
                    return
                evidence["hardware"] = dialog.hardware.text()
                index = next(
                    i
                    for i in range(dialog.choice.count())
                    if dialog.choice.itemData(i).key == args.profile
                )
                dialog.choice.setCurrentIndex(index)
                dialog.grab().save(str(args.output / "offer.png"))
                assert dialog.install.isEnabled()
                dialog.install.click()
                assert dialog.operation
                stage = 1
            elif stage == 1:
                if dialog.operation:
                    busy_ticks += 1
                    if busy_ticks == 5:
                        dialog.grab().save(str(args.output / "progress.png"))
                    assert not dialog.restart.isEnabled()
                    return
                assert dialog.restart.isEnabled(), dialog.status.text()
                ready = runtime_setup.ready_runtime(root, args.profile)
                assert ready
                evidence["installed_environment"] = str(ready)
                evidence["responsive_polls"] = busy_ticks
                dialog.grab().save(str(args.output / "installed.png"))
                dialog.restart.click()
                stage = 2
            elif stage == 2:
                if window.isVisible():
                    assert window._closing, window.status.text()
                    return
                assert child and child.process.poll() is None
                assert runtime_setup.selected_runtime(root) == child.target
                evidence["restarted_pid"] = child.started_pid
                evidence["selected_environment"] = str(runtime_setup.selected_runtime(root))
                probe = WindowsHotkeyRegistrar()
                for key in (0x75, 0x76):
                    try:
                        probe.register(0x1500, 7, key)
                    except OSError as error:
                        assert "already uses" in str(error)
                    else:
                        probe.unregister(0x1500)
                        raise AssertionError("Replacement app did not register its saved hotkeys")
                evidence["replacement_owns_saved_hotkeys"] = True
                # Close only the child app started by this verification, through its window.
                targets = [t for t in windows.list_targets() if t.process_id == child.started_pid]
                if not targets:
                    return
                post = ctypes.WinDLL("user32").PostMessageW
                post.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
                for target in targets:
                    post(target.hwnd, 0x0010, 0, 0)  # WM_CLOSE
                stage = 3
            elif stage == 3:
                assert child
                if child.process.poll() is None:
                    return
                assert child.process.returncode == 0
                evidence["clean_child_exit"] = True
                probe = WindowsHotkeyRegistrar()
                for key in (0x75, 0x76):
                    probe.register(0x1500, 7, key)
                    probe.unregister(0x1500)
                evidence["child_exit_released_hotkeys"] = True
                evidence["seconds"] = round(time.monotonic() - started, 2)
                (args.output / "results.json").write_text(json.dumps(evidence, indent=2), "utf-8")
                print(json.dumps(evidence), flush=True)
                timer.stop()
                app.quit()
        except Exception as error:
            failed = True
            print(f"FAIL: {error}", flush=True)
            timer.stop()
            if child and child.process.poll() is None:
                child._tree.close()
            window.close()
            app.quit()

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    with (
        patch.object(runtime_setup, "run_setup_command", command),
        patch.object(ui, "RuntimeRestart", restart),
    ):
        app.exec()
    native.close()
    shiboken6.delete(app)
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
