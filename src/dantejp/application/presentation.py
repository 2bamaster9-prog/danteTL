"""Pure status projection. Formatting cannot start, stop or advance a worker."""

from dataclasses import replace

from dantejp.application.translation_activity import (
    InactiveReason,
    TranslationActivity,
    TranslationMode,
)
from dantejp.application.values import ApplicationView, ProcessingProgress, Scene
from dantejp.domain import CaptureState
from dantejp.ocr.values import OcrSnapshot, OcrState
from dantejp.translation.values import TranslationSnapshot, TranslationState


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
    if activity.mode == TranslationMode.SWITCHING:
        return "Waiting for the previous translation model to unload…"
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
        f"Translating · oldest active call {now - snapshot.processing_since:.1f} s"
        if snapshot.processing_since is not None
        else f"Ready · {len(snapshot.results)} English blocks"
    )


def processing_progress(view: ApplicationView, *, translation_enabled: bool) -> ProcessingProgress:
    """Visible startup stages, including partially ready routes; no invented percentage."""
    capture = view.capture
    if capture is None or capture.state not in (CaptureState.STARTING, CaptureState.RUNNING):
        return ProcessingProgress()
    if capture.state == CaptureState.STARTING or capture.frame is None:
        return ProcessingProgress("Waiting for the first captured frame…", busy=True)
    if view.frame is None:  # Minimized or waiting for matching geometry.
        return ProcessingProgress()
    messages: list[str] = []
    busy = False
    tone = "info"
    ocr = view.ocr
    if ocr and ocr.state == OcrState.LOADING:
        messages.append("Loading MeikiOCR… First GPU initialization can take longer.")
        busy = True
    elif ocr and ocr.state == OcrState.FAILED:
        messages.append(view.ocr_status)
        tone = "error"
    elif ocr and ocr.result is None and ocr.state == OcrState.READY:
        messages.append("Reading the first frame…")
        busy = True
    if translation_enabled:
        translation = view.translation
        if view.translation_mode in (
            TranslationMode.PREPARING,
            TranslationMode.SWITCHING,
            TranslationMode.PROBING,
        ):
            messages.append(view.translation_status)
            busy = True
        elif translation and view.translation_mode == TranslationMode.ACTIVE:
            for lane in translation.lanes:
                if lane.state in (TranslationState.LOADING, TranslationState.STOPPING):
                    messages.append(f"Loading {lane.name}… {lane.message}".strip())
                    busy = True
                elif lane.state == TranslationState.FAILED:
                    messages.append(f"{lane.name} unavailable: {lane.message}")
                    tone = "error"
            if not translation.lanes and translation.state in (
                TranslationState.LOADING,
                TranslationState.STOPPING,
                TranslationState.FAILED,
            ):
                messages.append(view.translation_status)
                busy |= translation.state != TranslationState.FAILED
                if translation.state == TranslationState.FAILED:
                    tone = "error"
            if (
                not messages
                and not view.english
                and (translation.pending or translation.processing_since is not None)
            ):
                messages.append("Translating recognized text…")
                busy = True
        if not messages and view.scene.waiting_blocks and not view.english:
            messages.append("Waiting for text to finish appearing…")
            busy = True
    return ProcessingProgress("\n".join(messages), busy, tone)
