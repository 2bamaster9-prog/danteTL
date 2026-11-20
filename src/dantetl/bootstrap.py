"""Application composition and startup diagnostics."""

import logging
import os
import sys
from functools import partial
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from dantetl.application.model_factories import (
    create_recognizer,
    ocr_backends,
    translation_backends,
)
from dantetl.application.preferences import PreferenceStore
from dantetl.i18n import tr
from dantetl.languages.selection import source_language
from dantetl.paths import is_standalone, state_root


def configure_logging() -> None:
    directory = (
        state_root()
        if is_standalone()
        else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DanteTL"
    ) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        directory / "app.log", maxBytes=500_000, backupCount=2, encoding="utf-8"
    )
    # Cloud adapters supply sanitized diagnostics. Transport debug logs may contain
    # headers/token request bodies and must never enter the application log.
    handler.addFilter(
        lambda record: (
            record.name.split(".", 1)[0] not in ("httpx", "httpx2", "httpcore", "httpcore2")
        )
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[handler],
    )


def main() -> None:
    if sys.platform != "win32":
        raise SystemExit(tr("DanteTL currently requires Windows."))
    configure_logging()
    import shiboken6
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from dantetl.application.hotkeys import Hotkeys
    from dantetl.application.model_inventory import inspect_models
    from dantetl.capture.windows import Windows
    from dantetl.composition import (
        application_session,
        cloud_services,
        model_inventory,
        setup_coordinator,
    )
    from dantetl.languages.source import SourceLanguage
    from dantetl.ocr.worker import OcrChoice
    from dantetl.runtime.hardware import HardwareCheck
    from dantetl.runtime.model_store import model_catalog
    from dantetl.runtime.restart import acknowledge_startup
    from dantetl.runtime.setup import project_root
    from dantetl.ui.desktop_driver import DesktopDriver
    from dantetl.ui.hotkeys_windows import WindowsHotkeyEvents, WindowsHotkeyRegistrar
    from dantetl.ui.icons import APP_ICON
    from dantetl.ui.localization import install_language
    from dantetl.ui.main_window import MainWindow

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName("DanteTL")
    app.setWindowIcon(QIcon(str(APP_ICON)))
    app.setOrganizationName("DanteTL")
    preferences = PreferenceStore(project_root() / "data/preferences.json")
    install_language(app, preferences.current.interface_language)

    def report_exception(
        kind: type[BaseException], error: BaseException, traceback: TracebackType | None
    ) -> None:
        logging.getLogger(__name__).error(
            tr("Unhandled application error"), exc_info=(kind, error, traceback)
        )
        QMessageBox.critical(
            None,
            "DanteTL",
            tr(
                "An unexpected error occurred:\n{error}\n\nDetails are in "
                "%LOCALAPPDATA%/DanteTL/logs/app.log.",
                error=error,
            ),
        )

    sys.excepthook = report_exception
    hardware = HardwareCheck()
    hardware.start()
    hotkeys = Hotkeys(WindowsHotkeyRegistrar())
    hotkey_events = WindowsHotkeyEvents(app, hotkeys)

    driver = DesktopDriver()
    language = source_language(preferences.current.source_language)
    models = model_catalog(language)
    inventory = model_inventory(models, partial(translation_backends, language=language))
    setup = setup_coordinator(inventory, models, project_root())

    def source_models(selected: SourceLanguage) -> tuple[OcrChoice, ...]:
        bundles = model_catalog(selected)
        setup.set_models(bundles)
        inventory.set_inspector(
            partial(inspect_models, bundles, partial(translation_backends, language=selected))
        )
        return ocr_backends(selected)

    application = application_session(
        windows,
        partial(create_recognizer, language=language),
        cloud=cloud_services(language=language),
        language=language,
        inventory=inventory,
        setup=setup,
        ocr_backends=ocr_backends(language),
        source_models=source_models,
        notify=driver.notify,
        preferences=preferences,
        hardware=hardware,
        hotkeys=hotkeys,
    )
    window = MainWindow(application, windows, driver, hardware=hardware, hotkeys=hotkeys)
    window.show()
    QTimer.singleShot(0, window.offer_first_run)
    if notice := os.environ.pop("DANTETL_STARTUP_NOTICE", ""):
        window.status.setText(notice)
    QTimer.singleShot(0, acknowledge_startup)
    exit_code = app.exec()
    hotkey_events.close()
    # Tear down Qt while its native dependencies are still loaded, before Python finalization.
    shiboken6.delete(app)
    sys.exit(exit_code)
