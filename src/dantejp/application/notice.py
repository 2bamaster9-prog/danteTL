"""Pure, cached presentation policy. Inputs are values, never widgets or workers."""

from dataclasses import dataclass
from functools import lru_cache

from dantejp.application.setup_status import SetupAdvice, acceleration_advice
from dantejp.runtime.hardware_values import HardwareStatus
from dantejp.translation.plan import TranslationPlan
from dantejp.translation.selection import ModelOption


@dataclass(frozen=True)
class NoticeInput:
    options: tuple[ModelOption, ...]
    plan: TranslationPlan
    ocr_ready: bool
    saving_error: str = ""
    setup_error: str = ""
    setup_busy: bool = False
    preparing: bool = False
    ocr_state: str = ""
    ocr_message: str = ""
    translation_state: str = ""
    translation_message: str = ""
    rejected: bool = False
    hardware: HardwareStatus | None = None
    ocr_device: str = "cpu"
    requested_device: str = "cpu"
    provider: str = ""
    fallback: str = ""
    capturing: bool = False


@dataclass(frozen=True)
class Notices:
    message: str = ""
    action: str = "Open settings"
    tone: str = "warning"
    destination: str = "models"
    model_warning: str = ""
    model_action: str = "Models"
    save_note: str = "Most settings save automatically. Save model edits; apply hotkeys."
    acceleration: SetupAdvice = SetupAdvice()
    model_destination: str = "models"


@lru_cache(maxsize=1)
def project_notices(value: NoticeInput) -> Notices:
    options = {c.reference: c for c in value.options}
    active = tuple(options[k] for k in value.plan.active_models if k in options)
    cloud = tuple(c for c in active if not c.local)
    cloud_ready = any(c.prepared for c in cloud)
    missing = []
    if not value.ocr_ready:
        missing.append("MeikiOCR is not downloaded")
    for label, key, enabled in (
        ("short labels", value.plan.short, value.plan.short_enabled),
        ("long text", value.plan.long, value.plan.long_enabled),
    ):
        if not enabled:
            continue
        choice = options.get(key)
        if not key:
            missing.append(f"No translation model is selected for {label}")
        elif choice is None:
            missing.append(f"The model for {label} is unavailable")
        elif not choice.local and not choice.prepared:
            missing.append(f"Connect the cloud model for {label} in Models")
        elif choice.local and not choice.prepared:
            missing.append(f"Select the model for {label} to prepare it")
    if not options:
        missing.append("No translation model is downloaded or configured")
    warning = ". ".join(missing)
    if warning:
        warning += ". Capture can continue, but translation needs setup."
    message, action, tone, destination = "", "Open settings", "warning", "models"
    if value.saving_error:
        message, tone, destination = value.saving_error, "error", "settings"
    elif value.setup_error:
        message, tone = "Setup needs attention: " + value.setup_error, "error"
    elif value.setup_busy:
        message = "Setup is running in the background. Open Settings for progress."
        action, tone = "View setup", "info"
    elif cloud and not cloud_ready:
        message, action, destination = warning, "Cloud models", "cloud"
    elif not value.ocr_ready or not options:
        message, action = warning, "Download models"
    elif value.preparing:
        message, action, tone = "Preparing the translation model. Capture can continue.", "", "info"
    elif value.ocr_state in ("failed", "loading"):
        message, action = value.ocr_message, ""
        tone = "error" if value.ocr_state == "failed" else "info"
    elif value.translation_state in ("failed", "loading"):
        message, action = value.translation_message, ""
        tone = "error" if value.translation_state == "failed" else "info"
    elif missing:
        message, action, destination = warning, "Choose model", "selection"
    elif value.rejected:
        message, action = value.translation_message, ""
        if any(p.provider == "chatgpt" for p in cloud):
            action, destination = "Manage usage", "usage"
    elif notice := next(
        (c.performance_notice for c in active if c.local and c.performance_notice), ""
    ):
        message, action, destination = notice, "Acceleration options", "runtime"
    advice = acceleration_advice(
        value.hardware, value.ocr_device, actual_provider=value.provider, fallback=value.fallback
    )
    if (
        value.capturing
        and advice.destination == "recognition"
        and value.requested_device != value.ocr_device
    ):
        advice = SetupAdvice(
            "CPU OCR is still active. Your new OCR device applies after restarting capture.",
            "recognition",
            "OCR settings",
        )
    return Notices(
        message,
        action,
        tone,
        destination,
        warning,
        "Choose model" if value.ocr_ready and any(c.local for c in value.options) else "Models",
        "Settings could not be saved. Changes still apply to this session. " + value.saving_error
        if value.saving_error
        else Notices.save_note,
        advice,
        "cloud"
        if cloud and not cloud_ready
        else "selection"
        if value.ocr_ready and options
        else "models",
    )
