"""Build picker recipes and setup status from one model inventory scan."""

from collections.abc import Callable
from functools import partial
from pathlib import Path

from dantetl.application.model_factories import (
    create_curated_translator,
    create_gemma_translator,
    create_imported_translator,
)
from dantetl.application.model_inventory import InventoryData
from dantetl.application.model_values import ModelFile
from dantetl.i18n import CatalogText, tr
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.runtime.model_store import (
    LANGUAGE_RUNTIME_SETUP,
    PLAMO_RUNTIME_SETUP,
    ModelBundle,
    ModelLocation,
)
from dantetl.translation.backend import BackendChoice
from dantetl.translation.backends.plamo import OUTPUT_CODES as PLAMO_OUTPUT_CODES
from dantetl.translation.backends.plamo import source_problem
from dantetl.translation.models.gguf import available
from dantetl.translation.models.values import ImportedModel


def inspect_models(
    bundles: tuple[ModelBundle, ...],
    backends: Callable[[], tuple[BackendChoice, ...]] | None = None,
    *,
    language: SourceLanguage = DEFAULT_SOURCE,
    include_imports: bool = True,
) -> InventoryData:
    """Worker-side filesystem/runtime boundary, shared by startup and explicit refresh."""
    from dantetl.runtime.llama import installed_device, supports_plamo
    from dantetl.runtime.model_store import is_prepared
    from dantetl.runtime.ocr import gpu_runtime_installed
    from dantetl.translation.models.gguf import read_registry

    device = installed_device()
    plamo = supports_plamo()
    gpu_ocr = gpu_runtime_installed() or gpu_runtime_installed("onnxruntime-directml")
    files = []
    for b in bundles:
        location = b.inspect_location()
        files.append(
            ModelFile(
                b.key,
                b.name,
                b.description,
                b.category,
                b.size,
                location.present,
                location.included,
                b.language_model,
                b.needs_plamo,
                str(b.directory),
                str(b.bundled_directory or ""),
                str(location.directory),
                _model_status(b, location, device, plamo, gpu_ocr),
                device,
                b.needs_plamo and not plamo,
            )
        )
    import_problem = ""
    try:
        imported = read_registry() if include_imports else ()
    except (OSError, ValueError) as error:
        imported = ()
        import_problem = tr("Cannot read imported models: {error}", error=error)
    for model in imported:
        present = available(model)
        files.append(
            ModelFile(
                model.key,
                model.name,
                tr(
                    "Imported · {architecture} · {value:.2f} GiB on disk. Local "
                    "translation. Quality depends on the model.",
                    architecture=model.architecture,
                    value=model.size / 2**30,
                ),
                "translation",
                model.size,
                present,
                False,
                True,
                model.profile == "plamo3",
                model.path,
                "",
                model.path,
                tr("File is missing or changed size. Use Locate file to check its new location.")
                if not present
                else tr("Language-model engine missing. Open Acceleration to set up CPU or GPU.")
                if device is None
                else tr(
                    "Local model registered. Select it on the main screen to prepare and use it."
                ),
                device,
                model.profile == "plamo3" and not plamo,
                model,
            )
        )
    discovered = tuple(files)
    choices = (
        backends() if backends is not None else _backend_choices(bundles, discovered, language)
    )
    return InventoryData(
        choices,
        discovered,
        frozenset(c.preparation_id for c in choices if is_prepared(c.preparation_id)),
        device,
        import_problem,
    )


def _model_status(
    bundle: ModelBundle, location: ModelLocation, device: str | None, plamo: bool, gpu_ocr: bool
) -> str:
    """Distinguish downloaded weights from the runtime available to this process."""
    if not location.present:
        return CatalogText("Not downloaded. Choose Download to install this model's files.")
    origin = CatalogText("Included with app.") if location.included else CatalogText("Downloaded.")
    if bundle.language_model:
        if device is None:
            return CatalogText(LANGUAGE_RUNTIME_SETUP)
        if bundle.needs_plamo and not plamo:
            return CatalogText(PLAMO_RUNTIME_SETUP)
        if device == "cpu":
            return CatalogText(
                "Downloaded. Runtime available on CPU; translations may be slower. "
                "GPU acceleration is optional. Integrity is checked before use."
            )
    if bundle.key == "ocr" and not gpu_ocr:
        return CatalogText(
            "{origin} CPU OCR is ready. The Automatic NVIDIA OCR option needs a "
            "separate runtime: open Acceleration, install NVIDIA support, then "
            "restart. OCR model files do not install GPU support.",
            origin=origin,
        )
    return CatalogText(
        "{origin} Runtime available; integrity is checked before use.", origin=origin
    )


def _backend_choices(
    bundles: tuple[ModelBundle, ...], files: tuple[ModelFile, ...], language: SourceLanguage
) -> tuple[BackendChoice, ...]:
    from dantetl.application.model_advice import RECOMMENDED_TRANSLATION
    from dantetl.runtime.model_store import preparation_id
    from dantetl.translation.models.curated import MODELS

    catalog = {bundle.key: bundle for bundle in bundles}
    choices = []
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
    for file in files:
        key, device = file.key, file.device
        if key not in factories or not file.present or file.imported is not None:
            continue
        name, factory = factories[key]
        bundle = catalog[key]
        label = {
            "vulkan": CatalogText("Vulkan GPU"),
            "cuda": CatalogText("NVIDIA GPU"),
            "cpu": CatalogText("CPU · slower"),
        }.get(device or "", CatalogText("runtime setup needed"))
        reason = (
            CatalogText(LANGUAGE_RUNTIME_SETUP)
            if device is None
            else (CatalogText(PLAMO_RUNTIME_SETUP) if file.upgrade else "")
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
    for file in files:
        model, device = file.imported, file.device
        if model is None:
            continue
        reason = (
            CatalogText(
                "Imported model file is missing or changed size. Open Models → Locate file."
            )
            if not file.present
            else CatalogText("Language-model engine is missing. Open Settings → Acceleration.")
            if not device
            else CatalogText(PLAMO_RUNTIME_SETUP)
            if file.upgrade
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
                _imported_preparation_id(model, device) if device and not reason else "",
                reason,
                CatalogText("CPU translation may be slower; GPU acceleration is optional.")
                if device == "cpu"
                else "",
                classifies=model.profile != "plamo3",
                output_codes=PLAMO_OUTPUT_CODES if model.profile == "plamo3" else None,
            )
        )
    return tuple(choices)


def _imported_preparation_id(model: ImportedModel, device: str) -> str:
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


def translation_backends() -> tuple[BackendChoice, ...]:
    """Discover the installed choices for standalone local verification tools."""
    from dantetl.runtime.model_store import model_catalog

    return inspect_models(model_catalog()).backends
