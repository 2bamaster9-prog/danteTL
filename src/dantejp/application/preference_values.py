from dataclasses import dataclass

from dantejp.application.hotkeys import DEFAULT_CAPTURE, DEFAULT_ORIGINAL, DEFAULT_OVERLAY


@dataclass(frozen=True, slots=True)
class Preferences:
    show_overlay: bool = True
    show_border: bool = True
    include_overlay_in_capture: bool = True
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
    setup_seen: bool = False
    setup_model: str = ""
    translation_route: str = "local"
    cloud_model: str = ""
    game_hint: str = ""
    advanced_routing: bool = False
    short_model: str = "legacy"
    long_model: str = "legacy"
    translate_short: bool = True
    translate_long: bool = True
    game_from_window: bool = True
    history_enabled: bool = False
    history_model: str = ""
    backdrop_blur: bool = False
