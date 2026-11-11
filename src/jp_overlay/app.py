"""Application composition and startup diagnostics."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType


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
    from PySide6.QtWidgets import QApplication, QMessageBox

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
    window = MainWindow(windows)
    window.show()
    sys.exit(app.exec())
