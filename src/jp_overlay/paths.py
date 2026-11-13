"""Read-only app resources and writable user state, without changing source-checkout paths."""

import os
from pathlib import Path


def resource_root() -> Path:
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
            raise ValueError("DANTEJP_DATA_DIR must be an absolute directory.")
        return path
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("Windows Local AppData is unavailable.")
    return Path(local) / "DanteJP"


def runtime_project(state: Path) -> Path:
    return resource_root() if is_standalone() else state


def module_command(python: Path, module: str, *args: str) -> list[str]:
    if is_standalone():
        # Load the current app's source, never an editable install pointing at an older ZIP.
        return [
            str(python),
            "-I",
            "-B",
            str(resource_root() / "bootstrap.py"),
            "--module",
            module,
            *args,
        ]
    return [str(python), "-m", module, *args]
