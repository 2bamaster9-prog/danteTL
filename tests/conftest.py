"""One QApplication owns Qt objects throughout a model-free test process."""

import gc
import os

import pytest
import shiboken6
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qt_application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    existing = QApplication.instance()
    application = existing or QApplication([])
    yield application
    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if existing is None:
        shiboken6.delete(application)


@pytest.fixture
def app(qt_application):
    existing = set(qt_application.topLevelWidgets())
    yield qt_application
    # A closed top-level widget can still own timers or native resources.
    # Leave shared windows alone and release only this test's independent roots.
    for widget in qt_application.topLevelWidgets():
        if widget not in existing and widget.parent() is None:
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
