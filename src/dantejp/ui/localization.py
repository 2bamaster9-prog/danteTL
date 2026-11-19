"""Qt catalog lifetime and view-owned bindings for interface text."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import (
    SIGNAL,
    QCoreApplication,
    QLibraryInfo,
    QLocale,
    QObject,
    QTranslator,
    Signal,
)
from PySide6.QtWidgets import QApplication, QComboBox, QWidget

from dantejp.i18n import INTERFACE_LANGUAGES, install_lookup, mark, tr

CATALOGS = Path(__file__).with_name("locales")
QT_LOCALES = {"zh-hans": "zh_CN", "zh-hant": "zh_TW"}


class _Catalogs(QObject):
    changed = Signal()

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self.code: str | None = None
        self.translators: list[QTranslator] = []


def _catalogs() -> _Catalogs:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    catalogs = app.findChild(_Catalogs)
    return catalogs if catalogs is not None else _Catalogs(app)


def install_language(app: QApplication, code: str) -> None:
    catalogs = _catalogs()
    if code == catalogs.code:
        return
    locale = QLocale(QT_LOCALES.get(code, code))
    for translator in catalogs.translators:
        app.removeTranslator(translator)
        translator.deleteLater()
    catalogs.translators.clear()
    if code != "en":
        for directory, filename in (
            (str(CATALOGS), code + ".qm"),
            (
                QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath),
                "qtbase_" + locale.name(),
            ),
        ):
            translator = QTranslator(catalogs)
            if translator.load(filename, directory):
                app.installTranslator(translator)
                catalogs.translators.append(translator)
            else:
                translator.deleteLater()
    install_lookup(lambda source: QCoreApplication.translate("DanteJP", source))
    QLocale.setDefault(locale)
    app.setLayoutDirection(locale.textDirection())
    catalogs.code = code
    catalogs.changed.emit()


def on_language_change(owner: QObject, refresh: Callable[[], None]) -> None:
    # The Qt context disconnects the callback when its view is destroyed.
    catalogs = _catalogs()
    QObject.connect(catalogs, SIGNAL("changed()"), owner, refresh)


def localized[W: QWidget](widget: W, **messages: str | Callable[[], str]) -> W:
    """Bind static Qt text properties to English catalog entries for this widget's lifetime."""

    def refresh() -> None:
        for prop, source in messages.items():
            if not widget.setProperty(prop, source() if callable(source) else tr(source)):
                raise ValueError(f"Invalid text property {prop} on {type(widget).__name__}")

    refresh()
    on_language_change(widget, refresh)
    return widget


def localized_item(
    combo: QComboBox, source: str, data: object, *, capitalize: bool = False
) -> None:
    """Add a fixed option whose displayed name can change independently of its value."""
    index = combo.count()

    def label() -> str:
        text = tr(source)
        return text[:1].upper() + text[1:] if capitalize else text

    combo.addItem(label(), data)
    on_language_change(combo, lambda: combo.setItemText(index, label()))


class InterfaceLanguageCombo(QComboBox):
    def __init__(self, selected: str) -> None:
        super().__init__()
        localized(self, accessibleName=mark("App language"))
        for code in INTERFACE_LANGUAGES:
            locale = QLocale(QT_LOCALES.get(code, code))
            name = "English" if code == "en" else locale.nativeLanguageName()
            if code.startswith("pt-"):
                name = f"Português ({locale.nativeTerritoryName()})"
            self.addItem(name[:1].upper() + name[1:], code)
        self.setCurrentIndex(self.findData(selected))
