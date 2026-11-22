"""Local runtime recipes and model discovery; invoked by workers, never by views."""

from functools import partial

from dantetl.i18n import CatalogText
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.models import OcrModel, model_directory, ocr_model_for, paddle_directory
from dantetl.ocr.worker import OcrChoice, Recognizer
from dantetl.runtime.ocr import gpu_runtime_installed
from dantetl.translation.backend import TranslationBackend
from dantetl.translation.models.values import ImportedModel


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
