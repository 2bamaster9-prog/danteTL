"""Local runtime recipes and model discovery; invoked by workers, never by views."""

import logging
from functools import partial
from pathlib import Path

from dantetl.i18n import CatalogText
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.models import OcrModel, model_directory, ocr_model_for, paddle_directory
from dantetl.ocr.worker import OcrChoice, Recognizer
from dantetl.runtime.ocr import gpu_runtime_installed
from dantetl.translation.backend import TranslationBackend
from dantetl.translation.backends.plamo import OUTPUT_CODES as PLAMO_OUTPUT_CODES
from dantetl.translation.backends.plamo import source_problem
from dantetl.translation.models.gguf import available
from dantetl.translation.models.values import ImportedModel
from dantetl.translation.worker import BackendChoice


def create_recognizer(
    *, device: str = "cpu", language: SourceLanguage = DEFAULT_SOURCE
) -> Recognizer:
    # Import native inference dependencies on the OCR worker, keeping GUI startup light.
    if ocr_model_for(language) == OcrModel.PADDLE_LATIN:
        from dantetl.ocr.paddle import PaddleRecognizer

        return PaddleRecognizer(paddle_directory(), device=device)
    from dantetl.ocr.meiki import MeikiRecognizer

    return MeikiRecognizer(model_directory(), device=device)


def ocr_backends(language: SourceLanguage = DEFAULT_SOURCE) -> tuple[OcrChoice, ...]:
    create = partial(create_recognizer, language=language)
    if gpu_runtime_installed("onnxruntime-directml"):
        if ocr_model_for(language) == OcrModel.PADDLE_LATIN:
            return (OcrChoice(CatalogText("CPU · AMD package"), create, 8, "cpu"),)
        return (
            OcrChoice(CatalogText("CPU · recommended with the AMD package"), create, 8, "cpu"),
            OcrChoice(
                CatalogText("DirectML · experimental, checked CPU fallback"),
                partial(create, device="auto-directml"),
                8,
                "auto-directml",
            ),
        )
    if gpu_runtime_installed():
        return (
            OcrChoice(
                CatalogText("Automatic · GPU with CPU fallback"),
                partial(create, device="auto"),
                8,
                "auto",
            ),
            OcrChoice(CatalogText("CPU · low resource use"), create, 8, "cpu"),
        )
    return (OcrChoice(CatalogText("CPU · GPU setup optional"), create, 8, "cpu"),)


def translation_backends(*, language: SourceLanguage = DEFAULT_SOURCE) -> tuple[BackendChoice, ...]:
    from dantetl.application.model_advice import RECOMMENDED_TRANSLATION
    from dantetl.runtime.llama import installed_device, supports_plamo
    from dantetl.runtime.model_store import (
        LANGUAGE_RUNTIME_SETUP,
        PLAMO_RUNTIME_SETUP,
        model_catalog,
        preparation_id,
    )
    from dantetl.translation.models.curated import MODELS

    bundles = {bundle.key: bundle for bundle in model_catalog()}
    choices = []
    device = installed_device()
    factories = {
        "gemma": ("Gemma 4 E2B", partial(create_gemma_translator, language=language)),
        **{
            model.key: (
                model.name.split(" · ")[0],
                partial(create_curated_translator, model.key, language=language),
            )
            for model in MODELS
        },
    }
    for key, (name, factory) in factories.items():
        bundle = bundles.get(key)
        if bundle is None or not bundle.present():
            continue
        label = {
            "vulkan": CatalogText("Vulkan GPU"),
            "cuda": CatalogText("NVIDIA GPU"),
            "cpu": CatalogText("CPU · slower"),
        }.get(device or "", CatalogText("runtime setup needed"))
        reason = (
            CatalogText(LANGUAGE_RUNTIME_SETUP)
            if device is None
            else (
                CatalogText(PLAMO_RUNTIME_SETUP)
                if bundle.needs_plamo and not supports_plamo()
                else ""
            )
        )
        if reason:
            label = CatalogText("runtime setup needed")
        elif bundle.needs_plamo and (reason := source_problem(language)):
            label = CatalogText("source language unsupported")
        choices.append(
            BackendChoice(
                CatalogText(
                    "{name} · {label}",
                    name=name,
                    label=label,
                    suffix=CatalogText(" · Recommended") if key == RECOMMENDED_TRANSLATION else "",
                ),
                factory,
                f"{key}-{device or 'unavailable'}",
                preparation_id(bundle, device) if device and not reason else "",
                reason,
                CatalogText(
                    "CPU translation is available. It may be slower, especially on busy screens. "
                    "GPU acceleration is optional."
                )
                if device == "cpu"
                else "",
                selection_id=key,
                classifies=not bundle.needs_plamo,
                output_codes=PLAMO_OUTPUT_CODES if bundle.needs_plamo else None,
            )
        )
    from dantetl.translation.models.gguf import read_registry

    try:
        imported = read_registry()
    except (OSError, ValueError) as error:
        logging.getLogger(__name__).warning("Cannot read imported models: %s", error)
        imported = ()
    for model in imported:
        reason = (
            CatalogText(
                "Imported model file is missing or changed size. Open Models → Locate file."
            )
            if not available(model)
            else CatalogText("Language-model engine is missing. Open Settings → Acceleration.")
            if not device
            else CatalogText(PLAMO_RUNTIME_SETUP)
            if model.profile == "plamo3" and not supports_plamo()
            else ""
        )
        if model.profile == "plamo3":
            reason = reason or source_problem(language)
        choices.append(
            BackendChoice(
                CatalogText(
                    "{name} · Imported · {value}", name=model.name, value=device or "engine needed"
                ),
                partial(create_imported_translator, model, language=language),
                model.key,
                imported_preparation_id(model, device) if device and not reason else "",
                reason,
                CatalogText("CPU translation may be slower; GPU acceleration is optional.")
                if device == "cpu"
                else "",
                classifies=model.profile != "plamo3",
                output_codes=PLAMO_OUTPUT_CODES if model.profile == "plamo3" else None,
            )
        )
    rank = {bundle.selection_id: i for i, bundle in enumerate(bundles.values())}
    return tuple(sorted(choices, key=lambda choice: rank.get(choice.preference_key, len(rank))))


def imported_preparation_id(model: ImportedModel, device: str) -> str:
    from dantetl.runtime.assets import ModelAsset
    from dantetl.runtime.model_store import ModelBundle, preparation_id

    asset = ModelAsset("", "", model.key, model.sha256, model.size)
    return (
        preparation_id(
            ModelBundle(model.key, model.name, Path(model.path).parent, (asset,), ""), device
        )
        + "-"
        + model.key
    )


def create_imported_translator(
    model: ImportedModel, *, language: SourceLanguage = DEFAULT_SOURCE
) -> TranslationBackend:
    from dantetl.runtime.llama import installed_device
    from dantetl.translation.backends.gguf import GgufBackend

    device = installed_device()
    if device is None:
        raise RuntimeError(CatalogText("Language-model engine is missing. Open Acceleration."))
    return GgufBackend(model, device=device, language=language)


def create_curated_translator(
    key: str, *, language: SourceLanguage = DEFAULT_SOURCE
) -> TranslationBackend:
    from dantetl.runtime.llama import installed_device
    from dantetl.translation.models.curated import MODELS

    device = installed_device()
    if device is None:
        raise RuntimeError(CatalogText("Language-model engine is missing. Open Acceleration."))
    model = next(model for model in MODELS if model.key == key)
    return model.load(device, language=language)


def create_gemma_translator(*, language: SourceLanguage = DEFAULT_SOURCE) -> TranslationBackend:
    from dantetl.runtime.llama import installed_device
    from dantetl.translation.backends.gemma import GemmaBackend, model_directory

    device = installed_device()
    if device is None:
        raise RuntimeError(
            CatalogText("Local language-model engine is not installed. Open runtime setup.")
        )
    return GemmaBackend(model_directory(), device=device, language=language)
