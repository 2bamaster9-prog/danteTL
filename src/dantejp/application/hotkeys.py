"""Global actions with atomic rebinding and a transient show-original hold."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class HotkeyAction(StrEnum):
    OVERLAY = "overlay"
    CAPTURE = "capture"
    ORIGINAL = "original"


DEFAULT_OVERLAY = "Ctrl+Alt+F8"
DEFAULT_CAPTURE = "Ctrl+Alt+F9"
DEFAULT_ORIGINAL = "Ctrl+Alt+F10"
MODIFIERS = {
    "Ctrl+Alt": 0x0003,
    "Ctrl+Shift": 0x0006,
    "Alt+Shift": 0x0005,
    "Ctrl+Alt+Shift": 0x0007,
    "Ctrl": 0x0002,
    "Alt": 0x0001,
}
# Deliberately exclude Windows shortcuts, unmodified keys, F12 and layout-dependent punctuation.
KEYS = {f"F{n}": 0x6F + n for n in range(1, 12)} | {
    key: ord(key) for key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
}


def parse_shortcut(value: str) -> tuple[int, int] | None:
    """Return Windows modifier/key codes; an empty string explicitly disables the action."""
    if not value:
        return None
    modifiers, _, key = value.rpartition("+")
    if modifiers not in MODIFIERS or key not in KEYS:
        raise ValueError("Choose Ctrl/Alt modifiers and a letter, number, or F1–F11.")
    return MODIFIERS[modifiers], KEYS[key]


def chord_down(modifiers: int, key: int, key_down: Callable[[int], bool]) -> bool:
    return key_down(key) and all(
        key_down(vk) for bit, vk in ((1, 18), (2, 17), (4, 16)) if modifiers & bit
    )


class HotkeyRegistrar(Protocol):
    def register(self, identifier: int, modifiers: int, key: int) -> None: ...

    def unregister(self, identifier: int) -> None: ...


@dataclass(frozen=True)
class _Registration:
    identifier: int
    shortcut: str
    modifiers: int
    key: int


class Hotkeys:
    """GUI-thread service. Register a replacement before releasing the working shortcut."""

    def __init__(self, registrar: HotkeyRegistrar) -> None:
        self._registrar = registrar
        self._active: dict[HotkeyAction, _Registration] = {}
        self._next_id = 0x2000
        self.activated: Callable[[HotkeyAction], None] = lambda _: None
        self.hold_changed: Callable[[bool], None] = lambda _: None
        self._held: _Registration | None = None

    @property
    def holding_original(self) -> bool:
        return self._held is not None

    def end_hold(self) -> None:
        if self._held is not None:
            self._held = None
            self.hold_changed(False)

    def check_release(self, key_down: Callable[[int], bool]) -> None:
        if self._held and not chord_down(self._held.modifiers, self._held.key, key_down):
            self.end_hold()

    def shortcut(self, action: HotkeyAction) -> str:
        registration = self._active.get(action)
        return registration.shortcut if registration else ""

    def bind(self, action: HotkeyAction, shortcut: str) -> None:
        parsed = parse_shortcut(shortcut)
        old = self._active.get(action)
        if shortcut and shortcut == self.shortcut(action):
            return
        if shortcut and any(item.shortcut == shortcut for item in self._active.values()):
            raise ValueError("The other action already uses this shortcut. Choose a different one.")
        new = None
        if parsed:
            # Never reuse IDs: an already queued WM_HOTKEY must not operate a new binding.
            if self._next_id > 0xBFFF:
                raise ValueError("Restart DanteJP before changing more shortcuts.")
            identifier = self._next_id
            self._next_id += 1
            self._registrar.register(identifier, *parsed)
            new = _Registration(identifier, shortcut, *parsed)
        try:
            if old:
                self._registrar.unregister(old.identifier)
        except OSError:
            if new:
                self._registrar.unregister(new.identifier)
            raise
        if new:
            self._active[action] = new
        else:
            self._active.pop(action, None)
        if action == HotkeyAction.ORIGINAL:
            self.end_hold()

    def dispatch(
        self,
        identifier: int,
        modifiers: int,
        key: int,
        *,
        key_down: Callable[[int], bool] | None = None,
    ) -> bool:
        for action, registration in self._active.items():
            if (identifier, modifiers, key) == (
                registration.identifier,
                registration.modifiers,
                registration.key,
            ):
                if action == HotkeyAction.ORIGINAL:
                    # A queued key-down may arrive after release; do not flash the overlay.
                    if not self._held and (
                        key_down is None or chord_down(modifiers, key, key_down)
                    ):
                        self._held = registration
                        self.hold_changed(True)
                else:
                    self.activated(action)
                return True
        return False

    def release(self) -> None:
        """Release every owned registration, including before starting a replacement process."""
        self.end_hold()
        for action, registration in tuple(self._active.items()):
            self._registrar.unregister(registration.identifier)
            del self._active[action]
