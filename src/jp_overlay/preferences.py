"""Validated user preferences and coalesced atomic writes; no window handles or model paths."""

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import uuid4

from jp_overlay.hotkeys import DEFAULT_CAPTURE, DEFAULT_ORIGINAL, DEFAULT_OVERLAY, parse_shortcut


@dataclass(frozen=True, slots=True)
class Preferences:
    show_overlay: bool = True
    translation: bool = True
    stabilize: bool = True
    opacity: int = 85
    automatic_size: bool = True
    text_size: int = 20
    group_dialogue: bool = True
    ocr_device: str = "auto"
    capture_rate: int = 8
    model: str = "auto"
    overlay_hotkey: str = DEFAULT_OVERLAY
    capture_hotkey: str = DEFAULT_CAPTURE
    original_hotkey: str = DEFAULT_ORIGINAL
    capture_focused_window: bool = True


def decode_preferences(value: object) -> Preferences:
    if not isinstance(value, dict) or value.get("version") != 1:
        raise ValueError("Unsupported settings format; defaults are being used.")
    defaults = asdict(Preferences())
    ranges = {"opacity": (20, 100), "text_size": (10, 60), "capture_rate": (2, 12)}
    choices = {
        "ocr_device": {"auto", "cpu", "auto-directml"},
        "model": {"auto", "none", "sugoi-fast", "sugoi-wide", "gemma"},
    }
    for key, default in defaults.items():
        candidate = value.get(key, default)
        if type(candidate) is not type(default):
            continue
        if key in ranges and not ranges[key][0] <= candidate <= ranges[key][1]:
            continue
        if key in choices and candidate not in choices[key]:
            continue
        if key in ("overlay_hotkey", "capture_hotkey", "original_hotkey"):
            try:
                parse_shortcut(candidate)
            except ValueError:
                continue
        defaults[key] = candidate
    return Preferences(**defaults)


class PreferenceStore:
    """One pending value replaces older writes; shutdown can poll idle without blocking Qt."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self.initial = Preferences()
        self.load_warning = ""
        self._error = ""
        self._lock = threading.Lock()
        self._pending: Preferences | None = None
        self._thread: threading.Thread | None = None
        self._last: Preferences | None = None
        self._read_only = False
        if path and path.exists():
            try:
                if path.stat().st_size > 16_384:
                    raise ValueError("Settings file is too large; defaults are being used.")
                self.initial = decode_preferences(json.loads(path.read_text("utf-8")))
            except (OSError, ValueError, TypeError) as error:
                # Never silently overwrite corrupt or newer settings on startup.
                self.load_warning = str(error)
                self._read_only = True

    @property
    def idle(self) -> bool:
        with self._lock:
            return self._thread is None

    @property
    def error(self) -> str:
        with self._lock:
            return self._error or self.load_warning

    def save(self, value: Preferences) -> None:
        if self.path is None or self._read_only:
            return
        with self._lock:
            if value == self._last and not self._error:
                return
            self._last = self._pending = value
            if self._thread is None:
                self._thread = threading.Thread(
                    target=self._write_pending, daemon=True, name="settings"
                )
                self._thread.start()

    def _write_pending(self) -> None:
        while True:
            with self._lock:
                value, self._pending = self._pending, None
                if value is None:
                    self._thread = None
                    return
            try:
                self._write(value)
                error = ""
            except OSError as failure:
                error = f"Could not save settings: {failure}"
            with self._lock:
                self._error = error

    def _write(self, value: Preferences) -> None:
        assert self.path is not None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}-{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps({"version": 1, **asdict(value)}, indent=2), "utf-8")
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
