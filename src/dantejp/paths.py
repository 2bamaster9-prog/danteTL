"""Read-only app resources and writable user state, without changing source-checkout paths."""

import os
import sys
from pathlib import Path

from dantejp.i18n import tr


def resource_root() -> Path:
    if frozen := getattr(sys, "_MEIPASS", None):
        return Path(frozen) / "app"
    if resources := os.environ.get("DANTEJP_RESOURCE_DIR"):
        # Managed Python imports its installed wheel. Only read-only assets belong to the ZIP.
        root = Path(resources)
        if not root.is_absolute() or not (root / "standalone.json").is_file():
            raise ValueError(tr("DANTEJP_RESOURCE_DIR must identify a complete standalone app."))
        return root
    return Path(__file__).resolve().parents[2]


def is_standalone() -> bool:
    return (resource_root() / "standalone.json").is_file()


def state_root() -> Path:
    if not is_standalone():
        return resource_root()
    # An explicit override supports isolated acceptance tests and managed installations.
    if override := os.environ.get("DANTEJP_DATA_DIR"):
        path = Path(override)
        if not path.is_absolute():
            raise ValueError(tr("DANTEJP_DATA_DIR must be an absolute directory."))
        return path
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError(tr("Windows Local AppData is unavailable."))
    return Path(local) / "DanteJP"


def runtime_project(state: Path) -> Path:
    return resource_root() if is_standalone() else state


def module_command(python: Path, module: str, *args: str) -> list[str]:
    if getattr(sys, "frozen", False) and python.resolve() == Path(sys.executable).resolve():
        return [str(python), "--module", module, *args]
    if is_standalone():
        # Only our launch-scoped PYTHONPATH is admitted; exclude cwd and the user site.
        return [str(python), "-P", "-s", "-B", "-m", module, *args]
    return [str(python), "-m", module, *args]


def gui_executable() -> Path:
    python = Path(sys.executable)
    return python if getattr(sys, "frozen", False) else python.with_name("pythonw.exe")
