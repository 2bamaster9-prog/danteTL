from unittest.mock import Mock

import pytest

from dantejp.application.hotkeys import (
    DEFAULT_CAPTURE,
    DEFAULT_OVERLAY,
    HotkeyAction,
    Hotkeys,
    parse_shortcut,
)


class Registrar:
    def __init__(self):
        self.active = {}
        self.conflicts = set()

    def register(self, identifier, modifiers, key):
        chord = (modifiers, key)
        if chord in self.conflicts or chord in self.active.values():
            raise OSError("Shortcut is already in use")
        self.active[identifier] = chord

    def unregister(self, identifier):
        del self.active[identifier]


@pytest.mark.parametrize(
    "value", ["F8", "Win+F9", "Ctrl+F12", "Ctrl++", "Ctrl+Alt+é", "Ctrl+F8,F9"]
)
def test_reserved_or_ambiguous_shortcuts_are_rejected(value):
    with pytest.raises(ValueError):
        parse_shortcut(value)


def test_defaults_and_disabled_have_unambiguous_native_keys():
    assert parse_shortcut(DEFAULT_OVERLAY) == (3, 0x77)
    assert parse_shortcut(DEFAULT_CAPTURE) == (3, 0x78)
    assert parse_shortcut("") is None


def test_conflict_preserves_working_binding_and_duplicate_action_is_rejected():
    native = Registrar()
    hotkeys = Hotkeys(native)
    hotkeys.activated = Mock()
    hotkeys.bind(HotkeyAction.OVERLAY, DEFAULT_OVERLAY)
    identifier = next(iter(native.active))
    native.conflicts.add(parse_shortcut("Ctrl+Shift+F7"))
    with pytest.raises(OSError):
        hotkeys.bind(HotkeyAction.OVERLAY, "Ctrl+Shift+F7")
    with pytest.raises(ValueError, match="other action"):
        hotkeys.bind(HotkeyAction.CAPTURE, DEFAULT_OVERLAY)
    assert hotkeys.shortcut(HotkeyAction.OVERLAY) == DEFAULT_OVERLAY
    assert hotkeys.dispatch(identifier, 3, 0x77)
    hotkeys.activated.assert_called_once_with(HotkeyAction.OVERLAY)


def test_rebind_disable_and_release_reject_queued_old_events():
    native = Registrar()
    hotkeys = Hotkeys(native)
    hotkeys.activated = Mock()
    hotkeys.bind(HotkeyAction.CAPTURE, DEFAULT_CAPTURE)
    identifier = next(iter(native.active))
    hotkeys.bind(HotkeyAction.CAPTURE, "Ctrl+Shift+F7")
    assert not hotkeys.dispatch(identifier, 3, 0x78)
    current = next(iter(native.active))
    assert not hotkeys.dispatch(current, 3, 0x78)  # Wrong key cannot trigger the current action.
    assert hotkeys.dispatch(current, 6, 0x76)
    hotkeys.bind(HotkeyAction.CAPTURE, "")
    assert not native.active and not hotkeys.dispatch(current, 6, 0x76)
    hotkeys.bind(HotkeyAction.CAPTURE, DEFAULT_CAPTURE)
    hotkeys.bind(HotkeyAction.OVERLAY, DEFAULT_OVERLAY)
    hotkeys.release()
    hotkeys.release()
    assert not native.active
    assert not hotkeys.dispatch(identifier, 3, 0x78)
    hotkeys.activated.assert_called_once_with(HotkeyAction.CAPTURE)


def test_failed_old_registration_release_rolls_back_new_shortcut():
    native = Registrar()
    hotkeys = Hotkeys(native)
    hotkeys.bind(HotkeyAction.OVERLAY, DEFAULT_OVERLAY)
    old_identifier = next(iter(native.active))
    unregister = native.unregister

    def fail_old(identifier):
        if identifier == old_identifier:
            raise OSError("Could not release")
        unregister(identifier)

    native.unregister = fail_old
    with pytest.raises(OSError, match="release"):
        hotkeys.bind(HotkeyAction.OVERLAY, "Ctrl+Shift+F7")
    assert hotkeys.shortcut(HotkeyAction.OVERLAY) == DEFAULT_OVERLAY
    assert native.active == {old_identifier: (3, 0x77)}


def test_hold_release_rebind_disable_and_shutdown_cannot_leave_a_stuck_hold():
    native = Registrar()
    hotkeys = Hotkeys(native)
    hotkeys.hold_changed = Mock()
    hotkeys.activated = Mock()
    hotkeys.bind(HotkeyAction.ORIGINAL, "Ctrl+Alt+F10")
    identifier = next(iter(native.active))
    down = {17, 18, 0x79}
    key_down = lambda key: key in down  # noqa: E731
    hotkeys.dispatch(identifier, 3, 0x79, key_down=key_down)
    hotkeys.dispatch(identifier, 3, 0x79, key_down=key_down)
    hotkeys.check_release(key_down)
    hotkeys.hold_changed.assert_called_once_with(True)
    native.conflicts.add(parse_shortcut("Ctrl+Shift+F7"))
    with pytest.raises(OSError):
        hotkeys.bind(HotkeyAction.ORIGINAL, "Ctrl+Shift+F7")
    assert hotkeys.holding_original  # Failed edit preserves the still-held working binding.
    hotkeys.bind(HotkeyAction.ORIGINAL, "Ctrl+Alt+F11")
    assert not hotkeys.holding_original
    assert not hotkeys.dispatch(identifier, 3, 0x79)
    identifier = next(iter(native.active))
    hotkeys.dispatch(identifier, 3, 0x7A)
    hotkeys.bind(HotkeyAction.ORIGINAL, "")
    assert not hotkeys.holding_original
    hotkeys.bind(HotkeyAction.ORIGINAL, "Ctrl+Alt+F10")
    identifier = next(iter(native.active))
    hotkeys.dispatch(identifier, 3, 0x79)
    hotkeys.release()
    assert not hotkeys.holding_original and not native.active
    assert [call.args for call in hotkeys.hold_changed.call_args_list] == [
        (True,),
        (False,),
        (True,),
        (False,),
        (True,),
        (False,),
    ]
    hotkeys.activated.assert_not_called()
