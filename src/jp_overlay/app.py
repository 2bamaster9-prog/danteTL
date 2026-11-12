"""Application composition and startup diagnostics."""

import logging
import os
import sys
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

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
            OcrChoice("CPU · recommended with the AMD package", create_recognizer, 8),
            OcrChoice(
                "DirectML · experimental, checked CPU fallback",
                partial(create_recognizer, device="auto-directml"),
                8,
            ),
        )
    if gpu_runtime_installed():
        return (
            OcrChoice(
                "Automatic · GPU with CPU fallback", partial(create_recognizer, device="auto"), 8
            ),
            OcrChoice("CPU · low resource use", create_recognizer, 8),
        )
    return (OcrChoice("CPU · GPU setup optional", create_recognizer, 8),)


def create_translator(*, beam_size: int = 2) -> TranslationBackend:
    from jp_overlay.sugoi import SugoiBackend, model_directory

    return SugoiBackend(model_directory(), beam_size=beam_size)


def translation_backends() -> tuple[BackendChoice, ...]:
    from jp_overlay.gemma import installed_device
    from jp_overlay.model_store import GEMMA_RUNTIME_SETUP, model_catalog, preparation_id

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
    if bundles["gemma"].present():
        label = (
            "Vulkan GPU"
            if device == "vulkan"
            else "NVIDIA GPU"
            if device
            else "runtime setup needed"
        )
        choices.append(
            BackendChoice(
                f"Gemma 4 E2B · {label}",
                create_gemma_translator,
                f"gemma-{device or 'unavailable'}",
                preparation_id(bundles["gemma"], device) if device else "",
                GEMMA_RUNTIME_SETUP if device is None else "",
            )
        )
    return tuple(choices)


def create_gemma_translator() -> TranslationBackend:
    from jp_overlay.gemma import GemmaBackend, installed_device, model_directory

    return GemmaBackend(model_directory(), device=installed_device() or "cuda")


def configure_logging() -> None:
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "JPOverlay" / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "app.log", maxBytes=500_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit("JP Overlay currently requires Windows.")
    configure_logging()
    import shiboken6
    from PySide6.QtWidgets import QApplication, QMessageBox

    from jp_overlay.model_store import model_catalog
    from jp_overlay.ui import MainWindow
    from jp_overlay.windows import Windows

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName("JP Overlay")
    app.setOrganizationName("JPOverlay")

    def report_exception(
        kind: type[BaseException], error: BaseException, traceback: TracebackType | None
    ) -> None:
        logging.getLogger(__name__).error(
            "Unhandled application error", exc_info=(kind, error, traceback)
        )
        QMessageBox.critical(
            None,
            "JP Overlay",
            f"An unexpected error occurred:\n{error}\n\n"
            "Details are in %LOCALAPPDATA%/JPOverlay/logs/app.log.",
        )

    sys.excepthook = report_exception
    window = MainWindow(
        windows,
        create_recognizer,
        translation_backends(),
        ocr_backends=ocr_backends(),
        models=model_catalog(),
        backend_provider=translation_backends,
    )
    window.show()
    exit_code = app.exec()
    # Tear down Qt while its native dependencies are still loaded, before Python finalization.
    shiboken6.delete(app)
    sys.exit(exit_code)
