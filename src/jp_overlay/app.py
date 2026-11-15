"""Application composition and startup diagnostics."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from jp_overlay.model_factories import create_recognizer, ocr_backends, translation_backends
from jp_overlay.paths import is_standalone, state_root


def configure_logging() -> None:
    directory = (
        state_root()
        if is_standalone()
        else Path(os.environ.get("LOCALAPPDATA", Path.home())) / "DanteJP"
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
        raise SystemExit("DanteJP currently requires Windows.")
    configure_logging()
    import shiboken6
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox

    from jp_overlay.composition import (
        application_session,
        cloud_services,
        model_inventory,
        setup_coordinator,
    )
    from jp_overlay.desktop_driver import DesktopDriver
    from jp_overlay.hardware import HardwareCheck
    from jp_overlay.hotkeys import Hotkeys
    from jp_overlay.hotkeys_windows import WindowsHotkeyEvents, WindowsHotkeyRegistrar
    from jp_overlay.model_store import model_catalog
    from jp_overlay.runtime_setup import project_root
    from jp_overlay.ui import MainWindow
    from jp_overlay.windows import Windows

    windows = Windows()
    windows.enable_dpi_awareness()
    app = QApplication(sys.argv)
    app.setApplicationName("DanteJP")
    app.setOrganizationName("DanteJP")

    def report_exception(
        kind: type[BaseException], error: BaseException, traceback: TracebackType | None
    ) -> None:
        logging.getLogger(__name__).error(
            "Unhandled application error", exc_info=(kind, error, traceback)
        )
        QMessageBox.critical(
            None,
            "DanteJP",
            f"An unexpected error occurred:\n{error}\n\n"
            "Details are in %LOCALAPPDATA%/DanteJP/logs/app.log.",
        )

    sys.excepthook = report_exception
    hardware = HardwareCheck()
    hardware.start()
    hotkeys = Hotkeys(WindowsHotkeyRegistrar())
    hotkey_events = WindowsHotkeyEvents(app, hotkeys)
    models = model_catalog()
    inventory = model_inventory(models, translation_backends)
    driver = DesktopDriver()
    application = application_session(
        windows,
        create_recognizer,
        cloud=cloud_services(),
        inventory=inventory,
        setup=setup_coordinator(inventory, models, project_root()),
        ocr_backends=ocr_backends(),
        notify=driver.notify,
        preferences_path=project_root() / "data/preferences.json",
        hardware=hardware,
        hotkeys=hotkeys,
    )
    window = MainWindow(application, windows, driver, hardware=hardware, hotkeys=hotkeys)
    window.show()
    from jp_overlay.runtime_restart import acknowledge_startup

    QTimer.singleShot(0, acknowledge_startup)
    QTimer.singleShot(0, window.offer_first_run)
    notice = os.environ.pop("JP_OVERLAY_STARTUP_NOTICE", "")
    if notice:
        window.status.setText(notice)
    exit_code = app.exec()
    hotkey_events.close()
    # Tear down Qt while its native dependencies are still loaded, before Python finalization.
    shiboken6.delete(app)
    sys.exit(exit_code)
