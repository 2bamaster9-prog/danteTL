"""Exercise real global shortcuts with a foreground fixture in another owned process.

Only the fixture receives synthetic key input; abort if its HWND/PID loses foreground.
No models, downloads, game inputs or game screenshots. Run on an unlocked desktop.
"""

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from ctypes import wintypes as wt
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

import shiboken6
from PySide6.QtCore import QByteArray, QTimer
from PySide6.QtWidgets import QApplication
from verification_isolation import app_owner
from verification_isolation import create_window as MainWindow

from dantetl.application.hotkeys import HotkeyAction, Hotkeys
from dantetl.application.preference_values import Preferences
from dantetl.capture.windows import Windows
from dantetl.domain import WindowTarget
from dantetl.ui.demo import DemoWindow
from dantetl.ui.hotkeys_windows import WindowsHotkeyEvents, WindowsHotkeyRegistrar


class _Keyboard(ctypes.Structure):
    _fields_ = [
        ("vk", wt.WORD),
        ("scan", wt.WORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class _Mouse(ctypes.Structure):
    _fields_ = [
        ("x", wt.LONG),
        ("y", wt.LONG),
        ("data", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class _Payload(ctypes.Union):
    _fields_ = [("keyboard", _Keyboard), ("mouse", _Mouse)]


class _Input(ctypes.Structure):
    _fields_ = [("kind", wt.DWORD), ("payload", _Payload)]


class ObservedEvents(WindowsHotkeyEvents):
    def nativeEventFilter(
        self, eventType: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        if eventType in (b"windows_dispatcher_MSG", b"windows_generic_MSG"):
            event = wt.MSG.from_address(int(message))
            if event.message == 0x0312:
                print(
                    f"WM_HOTKEY id={event.wParam} modifiers={event.lParam & 0xFFFF} "
                    f"key={(event.lParam >> 16) & 0xFFFF}",
                    flush=True,
                )
        return super().nativeEventFilter(eventType, message)


def fixture(identity: Path) -> int:
    Windows().enable_dpi_awareness()
    app = QApplication([])
    demo = DemoWindow()
    registrar = WindowsHotkeyRegistrar()
    registrar.register(0x1000, 7, 0x79)  # Reserve Ctrl+Alt+Shift+F10 for the conflict test.
    demo.show()
    identity.write_text(json.dumps({"hwnd": int(demo.winId()), "pid": os.getpid()}))
    result = app.exec()
    registrar.unregister(0x1000)
    shiboken6.delete(app)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--output", type=Path, default=Path("artifacts/hotkeys"))
    args = parser.parse_args()
    if args.fixture:
        return fixture(args.fixture)
    args.output.mkdir(parents=True, exist_ok=True)
    identity = (args.output / f"fixture-{uuid4().hex}.json").resolve()
    preferences = args.output / f"preferences-{uuid4().hex}.json"
    preferences.write_text(
        json.dumps(
            {
                "version": 1,
                **asdict(
                    Preferences(
                        overlay_hotkey="Ctrl+Alt+Shift+F8",
                        capture_hotkey="Ctrl+Alt+Shift+F9",
                        original_hotkey="Ctrl+Alt+Shift+F7",
                    )
                ),
            }
        )
    )
    windows = Windows()
    windows.enable_dpi_awareness()
    windows.user.SendInput.argtypes = [wt.UINT, ctypes.POINTER(_Input), ctypes.c_int]
    windows.user.SendInput.restype = wt.UINT
    windows.user.SetForegroundWindow.argtypes = [wt.HWND]
    windows.user.SetForegroundWindow.restype = wt.BOOL
    windows.user.GetAsyncKeyState.argtypes = [ctypes.c_int]
    windows.user.GetAsyncKeyState.restype = wt.SHORT
    windows.user.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    windows.user.PostMessageW.restype = wt.BOOL
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    hotkeys = Hotkeys(WindowsHotkeyRegistrar())
    native = ObservedEvents(app, hotkeys)

    def no_recognizer():
        raise AssertionError("This capture/hotkey fixture must not load OCR models")

    window = MainWindow(windows, no_recognizer, hotkeys=hotkeys, preferences_path=preferences)
    application = app_owner(window)
    from dataclasses import replace

    from dantetl.application.model_discovery import inspect_models
    from dantetl.runtime.model_store import model_catalog

    missing = tuple(
        replace(b, directory=args.output / "absent-ocr", bundled_directory=None)
        for b in model_catalog()
        if b.key == "ocr"
    )
    inventory = application.inventory
    data = inspect_models(missing, lambda: (), include_imports=False)
    inventory._inspect = lambda: data
    inventory._snapshot = replace(
        inventory.snapshot(), data=data, revision=inventory.snapshot().revision + 1
    )
    window.showMinimized()
    child = subprocess.Popen(
        [sys.executable, __file__, "--fixture", str(identity)],
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    target = None
    started, stage_at = time.monotonic(), time.monotonic()
    stage = 0
    failure = ""
    evidence = {}
    session = None
    frame_sequence = 0
    held_keys: list[int] = []

    def send_keys(values: list[tuple[int, int]]) -> None:
        inputs = (_Input * len(values))(
            *[_Input(1, _Payload(keyboard=_Keyboard(k, 0, flags, 0, 0))) for k, flags in values]
        )
        sent = windows.user.SendInput(len(inputs), inputs, ctypes.sizeof(_Input))
        assert sent == len(inputs), f"SendInput accepted only {sent}/{len(inputs)} events"

    def begin_hold() -> None:
        assert target and windows.is_foreground(target), "Fixture lost focus; input was not sent"
        assert not any(windows.user.GetAsyncKeyState(k) & 0x8000 for k in (16, 17, 18, 91, 92))
        held_keys[:] = [17, 18, 16, 0x76]
        send_keys([(key, 0) for key in held_keys])

    def end_hold() -> None:
        if held_keys:
            # Release only keys pressed by this fixture, even after focus loss or test failure.
            send_keys([(key, 2) for key in reversed(held_keys)])
            held_keys.clear()

    def chord(key: int, repeats: int = 1) -> None:
        assert target and windows.is_foreground(target), "Fixture lost focus; input was not sent"
        assert not any(windows.user.GetAsyncKeyState(k) & 0x8000 for k in (16, 17, 18, 91, 92)), (
            "A physical modifier is held; input was not sent"
        )
        # One contiguous batch: modifiers down, repeated key-down, then every key up.
        values = [(k, 0) for k in (17, 18, 16)] + [(key, 0)] * repeats
        values += [(k, 2) for k in (key, 16, 18, 17)]
        send_keys(values)

    def advance() -> None:
        nonlocal stage, stage_at
        stage += 1
        stage_at = time.monotonic()

    def tick() -> None:
        nonlocal target, stage, failure, session, frame_sequence
        try:
            if stage == 99:
                if time.monotonic() - started > 35:
                    timer.stop()
                    app.exit(1)
                    return
                if window.driver.timer.isActive():
                    window.close()
                    return
                timer.stop()
                app.quit()
                return
            assert time.monotonic() - started < 25, f"Timed out at stage {stage}"
            if stage == 0:
                if not identity.exists():
                    return
                data = json.loads(identity.read_text())
                target = WindowTarget(data["hwnd"], data["pid"], "DanteTL Demo")
                assert windows.is_target(target)
                window.windows_combo.clear()
                window.start_button.setEnabled(False)
                assert not window._settings.hotkeys.problem
                windows.user.SetForegroundWindow(target.hwnd)
                advance()
            elif stage == 1:
                assert target
                if not windows.is_foreground(target):
                    return
                chord(0x78)
                advance()
            elif stage == 2:
                session = application.live.capture
                if not session or not session.snapshot().frame:
                    return
                assert session.target == target and window.isMinimized()
                assert window.windows_combo.currentData() == target
                evidence["focused_window_selected_from_empty_picker"] = True
                evidence["background_start_received_frame"] = True
                chord(0x77, repeats=4)
                advance()
            elif stage == 3:
                assert session
                if time.monotonic() - stage_at < 0.3:
                    return
                assert not window.overlay_check.isChecked(), (
                    "Repeat key-down toggled more than once"
                )
                assert application.live.capture is session
                frame = session.snapshot().frame
                assert frame
                frame_sequence = frame.sequence
                evidence["repeat_suppressed"] = True
                chord(0x77)
                advance()
            elif stage == 4:
                assert session and target
                frame = session.snapshot().frame
                if not frame or frame.sequence <= frame_sequence:
                    return
                assert window.overlay_check.isChecked() and application.live.capture is session
                assert windows.is_foreground(target), "Hotkey stole focus"
                evidence["hide_show_preserves_capture_and_focus"] = True
                row = window._settings.hotkeys.rows[HotkeyAction.OVERLAY]
                row.key.setCurrentIndex(row.key.findData("F10"))
                row.apply.click()
                assert "already uses" in row.status.label.text()
                assert hotkeys.shortcut(HotkeyAction.OVERLAY) == "Ctrl+Alt+Shift+F8"
                evidence["other_process_conflict_preserves_shortcut"] = True
                row.key.setCurrentIndex(row.key.findData("F11"))
                row.apply.click()
                assert hotkeys.shortcut(HotkeyAction.OVERLAY) == "Ctrl+Alt+Shift+F11"
                chord(0x77)  # The old key must no longer toggle.
                advance()
            elif stage == 5:
                if time.monotonic() - stage_at < 0.2:
                    return
                assert window.overlay_check.isChecked()
                chord(0x7A)
                advance()
            elif stage == 6:
                if window.overlay_check.isChecked():
                    return
                evidence["rebind_releases_old_and_activates_new"] = True
                chord(0x78, repeats=3)
                advance()
            elif stage == 7:
                assert session
                if application.live.capture is not None:
                    return
                assert session.finished and window.start_button.isEnabled()
                evidence["stop_drained_capture"] = True
                chord(0x78)
                advance()
            elif stage == 8:
                if not application.live.capture or not application.live.capture.snapshot().frame:
                    return
                assert (
                    application.live.capture is not session
                    and application.live.capture.target == target
                )
                evidence["restart_same_selected_source"] = True
                session = application.live.capture
                frame = session.snapshot().frame
                assert frame
                frame_sequence = frame.sequence
                window.overlay_check.setChecked(True)
                begin_hold()
                advance()
            elif stage == 9:
                assert session
                if time.monotonic() - stage_at < 0.3:
                    return
                frame = session.snapshot().frame
                assert frame and frame.sequence > frame_sequence
                assert hotkeys.holding_original and application.original
                assert application.live.capture is session and window.overlay_check.isChecked()
                assert not window._overlay.isVisible()
                evidence["hold_keeps_capture_running"] = True
                send_keys([(17, 2)])  # Release a modifier before the main key.
                held_keys.remove(17)
                advance()
            elif stage == 10:
                if hotkeys.holding_original or application.original:
                    return
                evidence["modifier_release_seconds"] = round(time.monotonic() - stage_at, 3)
                assert application.live.capture is session and window.overlay_check.isChecked()
                end_hold()
                begin_hold()
                advance()
            elif stage == 11:
                if not application.original:
                    return
                end_hold()
                advance()
            elif stage == 12:
                if application.original:
                    return
                assert not native._release_timer.isActive()
                evidence["key_up_restores_without_capture_restart"] = (
                    application.live.capture is session
                )
                assert application.live.capture is session
                begin_hold()
                advance()
            elif stage == 13:
                if not application.original:
                    return
                window.showNormal()
                window.activateWindow()
                windows.user.SetForegroundWindow(int(window.winId()))
                advance()
            elif stage == 14:
                if application.original:
                    return
                assert not hotkeys.holding_original
                end_hold()
                evidence["focus_loss_cancels_hold"] = True
                window._settings.resize(680, 780)
                window._settings.show_hotkeys()
                advance()
            elif stage == 15:
                window._settings.grab().save(str(args.output / "settings.png"))
                window.close()
                stage = 99
        except Exception as error:
            failure = f"Stage {stage}: {error}"
            evidence["last_status"] = window.status.text()
            evidence["capture_exists"] = application.live.capture is not None
            print(f"FAIL: {failure}", flush=True)
            stage = 99
            window.close()

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    try:
        app.exec()
        assert not hotkeys.shortcut(HotkeyAction.OVERLAY)
        assert not hotkeys.shortcut(HotkeyAction.CAPTURE)
        # A fresh native owner can acquire the released shortcut after shutdown.
        probe = WindowsHotkeyRegistrar()
        probe.register(0x1500, 7, 0x7A)
        probe.unregister(0x1500)
        evidence["shutdown_released_shortcuts"] = True
    finally:
        end_hold()
        native.close()
        if target and windows.is_target(target):
            windows.user.PostMessageW(target.hwnd, 0x0010, 0, 0)  # WM_CLOSE to our child only.
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=3)
        shiboken6.delete(app)
    evidence["failure"] = failure
    (args.output / "report.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2))
    return 1 if failure else 0


if __name__ == "__main__":
    from verification_isolation import run_isolated

    run_isolated(main)
