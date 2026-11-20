import os
from unittest.mock import Mock

import pytest

from dantetl.capture.windows import Windows, WindowUnavailable
from dantetl.domain import Rect, WindowGeometry


@pytest.fixture
def windows():
    value = Windows.__new__(Windows)
    value.user = Mock()
    value.user.GetDesktopWindow.return_value = 1
    value.user.GetShellWindow.return_value = 2
    value.user.GetForegroundWindow.return_value = 10
    value.user.IsWindowVisible.return_value = True
    value.user.GetWindowLongPtrW.return_value = 0
    value.dwm = Mock()
    value.dwm.DwmGetWindowAttribute.return_value = 0
    value.process_id = Mock(return_value=os.getpid() + 100)
    value.title = Mock(return_value="Our game fixture")
    rect = Rect(0, 0, 800, 600)
    value.geometry = Mock(return_value=WindowGeometry(rect, rect, rect, 96))
    return value


def test_focused_target_has_exact_identity_and_rejects_focus_races(windows):
    target = windows.foreground_target()
    assert target.hwnd == 10 and target.process_id == os.getpid() + 100
    windows.user.GetForegroundWindow.side_effect = [10, 11]
    with pytest.raises(WindowUnavailable, match="changed"):
        windows.foreground_target()
    windows.user.GetForegroundWindow.side_effect = None
    windows.process_id.side_effect = [os.getpid() + 100, os.getpid() + 101]
    with pytest.raises(WindowUnavailable, match="changed"):
        windows.foreground_target()


@pytest.mark.parametrize("hwnd", [0, 1, 2])
def test_no_focus_desktop_and_shell_are_not_capture_targets(windows, hwnd):
    windows.user.GetForegroundWindow.return_value = hwnd
    with pytest.raises(WindowUnavailable, match="Focus the game"):
        windows.foreground_target()


def test_own_windows_tool_windows_and_unreadable_windows_are_rejected(windows):
    windows.process_id.return_value = os.getpid()
    with pytest.raises(WindowUnavailable):
        windows.foreground_target()
    windows.process_id.return_value += 100
    windows.user.GetWindowLongPtrW.return_value = 0x80
    with pytest.raises(WindowUnavailable):
        windows.foreground_target()
    windows.user.GetWindowLongPtrW.return_value = 0
    windows.dwm.DwmGetWindowAttribute.return_value = -1
    with pytest.raises(WindowUnavailable):
        windows.foreground_target()
    windows.dwm.DwmGetWindowAttribute.return_value = 0
    windows.geometry.side_effect = WindowUnavailable("Closed")
    with pytest.raises(WindowUnavailable):
        windows.foreground_target()
