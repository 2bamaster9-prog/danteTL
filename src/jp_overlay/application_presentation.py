"""Pure status projection. Formatting cannot start, stop or advance a worker."""

from dataclasses import replace

from jp_overlay.application_values import ApplicationView, Scene
from jp_overlay.ocr_values import OcrSnapshot, OcrState
from jp_overlay.translation_activity import InactiveReason, TranslationActivity, TranslationMode
from jp_overlay.translation_values import TranslationSnapshot, TranslationState


def reset_scene(view: ApplicationView) -> ApplicationView:
    return replace(
        view,
        scene=Scene(),
        blocks=(),
        english=(),
        results=(),
        observation=None,
        frame=None,
        assignments=(),
        overlay_bounds=None,
        reset=view.reset + 1,
    )


def ocr_status(snapshot: OcrSnapshot, visual_message: str, now: float) -> str:
    if snapshot.state == OcrState.FAILED:
        return f"OCR unavailable: {snapshot.message} Stop and restart to retry."
    if snapshot.state == OcrState.LOADING:
        return "Loading local MeikiOCR models… GPU initialization can take longer."
    if snapshot.result is not None:
        busy = (
            f"Reading · {now - snapshot.processing_since:.1f} s"
            if snapshot.processing_since is not None
            else f"Last scan · {len(snapshot.result.regions)} regions"
        )
        return snapshot.message or visual_message or busy
    elapsed = (
        f" {now - snapshot.processing_since:.0f} s."
        if snapshot.processing_since is not None
        else ""
    )
    return f"Reading the first frame…{elapsed}" + (
        " First GPU use may compile kernels; later launches reuse the local cache."
        if snapshot.provider == "CUDAExecutionProvider"
        else ""
    )


def translation_status(
    activity: TranslationActivity,
    snapshot: TranslationSnapshot | None,
    now: float,
) -> str:
    if activity.mode == TranslationMode.PROBING:
        return "Testing imported model; previous translation selection resumes afterward."
    if activity.mode == TranslationMode.PREPARING:
        return "Preparing translation model for this PC…"
    if activity.mode == TranslationMode.INACTIVE:
        return {
            InactiveReason.UNLOADING: "Unloading translation model…",
            InactiveReason.NEEDS_RUNTIME: (
                "Translation needs runtime setup. Select a model for instructions."
            ),
            InactiveReason.OFF: "English translation is off.",
            InactiveReason.NO_MODEL: (
                "No translation model selected. Open Settings to download one."
            ),
            InactiveReason.STOPPED: "Translation stopped.",
        }[activity.reason]
    assert snapshot is not None
    if activity.mode == TranslationMode.STANDBY:
        return (
            "Model ready. Start capture to translate."
            if snapshot.state == TranslationState.READY
            else "Loading the local model…"
        )
    if snapshot.state == TranslationState.FAILED:
        return (
            f"Translation unavailable: {snapshot.message} "
            "Toggle Translation overlay off/on to retry."
        )
    if snapshot.state == TranslationState.LOADING:
        return f"Loading/preparing {activity.model_name}… First use can take longer."
    if snapshot.state == TranslationState.STOPPING:
        return "Waiting for translation to finish unloading…"
    return snapshot.message or (
        f"Translating · {now - snapshot.processing_since:.1f} s"
        if snapshot.processing_since is not None
        else f"Ready · {len(snapshot.results)} English blocks"
    )
