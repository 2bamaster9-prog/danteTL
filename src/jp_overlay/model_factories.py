"""Local runtime recipes and model discovery; invoked by workers, never by views."""

import logging
from functools import partial
from pathlib import Path

from jp_overlay.gguf_models import available
from jp_overlay.import_values import ImportedModel
from jp_overlay.models import model_directory
from jp_overlay.ocr_runtime import gpu_runtime_installed
from jp_overlay.recognition import OcrChoice, Recognizer
from jp_overlay.translation import BackendChoice, TranslationBackend


def create_recognizer(*, device: str = "cpu") -> Recognizer:
    # Import native inference dependencies on the OCR worker, keeping GUI startup light.
    from jp_overlay.meiki import MeikiRecognizer

    return MeikiRecognizer(model_directory(), device=device)


def ocr_backends() -> tuple[OcrChoice, ...]:
    if gpu_runtime_installed("onnxruntime-directml"):
        return (
            OcrChoice("CPU · recommended with the AMD package", create_recognizer, 8, "cpu"),
            OcrChoice(
                "DirectML · experimental, checked CPU fallback",
                partial(create_recognizer, device="auto-directml"),
                8,
                "auto-directml",
            ),
        )
    if gpu_runtime_installed():
        return (
            OcrChoice(
                "Automatic · GPU with CPU fallback",
                partial(create_recognizer, device="auto"),
                8,
                "auto",
            ),
            OcrChoice("CPU · low resource use", create_recognizer, 8, "cpu"),
        )
    return (OcrChoice("CPU · GPU setup optional", create_recognizer, 8, "cpu"),)


def create_translator(*, beam_size: int = 2) -> TranslationBackend:
    from jp_overlay.sugoi import SugoiBackend, model_directory

    return SugoiBackend(model_directory(), beam_size=beam_size)


def translation_backends() -> tuple[BackendChoice, ...]:
    from jp_overlay.curated_models import MODELS
    from jp_overlay.llama_runtime import installed_device, supports_plamo
    from jp_overlay.model_store import (
        LANGUAGE_RUNTIME_SETUP,
        PLAMO_RUNTIME_SETUP,
        RECOMMENDED_TRANSLATION,
        model_catalog,
        preparation_id,
    )

    bundles = {bundle.key: bundle for bundle in model_catalog()}
    choices = []
    if bundles["sugoi"].present():
        choices.extend(
            (
                BackendChoice("Sugoi V4 · Fast CPU", create_translator, "sugoi-fast"),
                BackendChoice(
                    "Sugoi V4 · Wider search", partial(create_translator, beam_size=5), "sugoi-wide"
                ),
            )
        )
    device = installed_device()
    factories = {
        "gemma": ("Gemma 4 E2B", create_gemma_translator),
        **{
            model.key: (model.name.split(" · ")[0], partial(create_curated_translator, model.key))
            for model in MODELS
        },
    }
    for key, (name, factory) in factories.items():
        bundle = bundles.get(key)
        if bundle is None or not bundle.present():
            continue
        label = {"vulkan": "Vulkan GPU", "cuda": "NVIDIA GPU", "cpu": "CPU · slower"}.get(
            device or "", "runtime setup needed"
        )
        reason = (
            LANGUAGE_RUNTIME_SETUP
            if device is None
            else (PLAMO_RUNTIME_SETUP if bundle.needs_plamo and not supports_plamo() else "")
        )
        if reason:
            label = "runtime setup needed"
        choices.append(
            BackendChoice(
                f"{name} · {label}" + (" · Recommended" if key == RECOMMENDED_TRANSLATION else ""),
                factory,
                f"{key}-{device or 'unavailable'}",
                preparation_id(bundle, device) if device and not reason else "",
                reason,
                "CPU translation is available. It may be slower, especially on busy screens. "
                "GPU acceleration is optional."
                if device == "cpu"
                else "",
                selection_id=key,
                classifies=not bundle.needs_plamo,
            )
        )
    from jp_overlay.gguf_models import read_registry

    try:
        imported = read_registry()
    except (OSError, ValueError) as error:
        logging.getLogger(__name__).warning("Cannot read imported models: %s", error)
        imported = ()
    for model in imported:
        reason = (
            "Imported model file is missing or changed size. Open Models → Locate file."
            if not available(model)
            else "Language-model engine is missing. Open Settings → Acceleration."
            if not device
            else PLAMO_RUNTIME_SETUP
            if model.profile == "plamo3" and not supports_plamo()
            else ""
        )
        choices.append(
            BackendChoice(
                f"{model.name} · Imported · {device or 'engine needed'}",
                partial(create_imported_translator, model),
                model.key,
                imported_preparation_id(model, device) if device and not reason else "",
                reason,
                "CPU translation may be slower; GPU acceleration is optional."
                if device == "cpu"
                else "",
                classifies=model.profile != "plamo3",
            )
        )
    rank = {bundle.selection_id: i for i, bundle in enumerate(bundles.values())}
    rank["sugoi-wide"] = rank["sugoi-fast"]
    return tuple(sorted(choices, key=lambda choice: rank.get(choice.preference_key, len(rank))))


def imported_preparation_id(model: ImportedModel, device: str) -> str:
    from jp_overlay.model_store import ModelBundle, preparation_id
    from jp_overlay.models import ModelAsset

    asset = ModelAsset("", "", model.key, model.sha256, model.size)
    return (
        preparation_id(
            ModelBundle(model.key, model.name, Path(model.path).parent, (asset,), ""), device
        )
        + "-"
        + model.key
    )


def create_imported_translator(model: ImportedModel) -> TranslationBackend:
    from jp_overlay.gguf_backend import GgufBackend
    from jp_overlay.llama_runtime import installed_device

    device = installed_device()
    if device is None:
        raise RuntimeError("Language-model engine is missing. Open Acceleration.")
    return GgufBackend(model, device=device)


def create_curated_translator(key: str) -> TranslationBackend:
    from jp_overlay.curated_models import MODELS
    from jp_overlay.llama_runtime import installed_device

    device = installed_device()
    if device is None:
        raise RuntimeError("Language-model engine is missing. Open Acceleration.")
    model = next(model for model in MODELS if model.key == key)
    return model.load(device)


def create_gemma_translator() -> TranslationBackend:
    from jp_overlay.gemma import GemmaBackend, model_directory
    from jp_overlay.llama_runtime import installed_device

    device = installed_device()
    if device is None:
        raise RuntimeError("Local language-model engine is not installed. Open runtime setup.")
    return GemmaBackend(model_directory(), device=device)
