"""Run the pinned interpreter's bundled pip inside the new, empty Windows runtime."""

import ctypes
import ensurepip
import os
import runpy
import sys
from pathlib import Path


def install(requirements: str) -> None:
    # Only the installing process can enter Windows background processing mode.
    # This gives its CPU, memory and file I/O lower priority for the whole extraction.
    kernel = ctypes.WinDLL("kernel32")
    kernel.GetCurrentProcess.restype = ctypes.c_void_p
    kernel.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.SetPriorityClass(kernel.GetCurrentProcess(), 0x00100000)  # PROCESS_MODE_BACKGROUND_BEGIN

    # -I isolates Python. Isolate pip from machine config and inherited install destinations too.
    for key in list(os.environ):
        if key.startswith("PIP_"):
            del os.environ[key]
    os.environ["PIP_CONFIG_FILE"] = os.devnull
    bundled = Path(ensurepip.__file__).parent / "_bundled"
    pip = bundled / f"pip-{ensurepip.version()}-py3-none-any.whl" / "pip"
    sys.argv = [
        str(pip),
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "install",
        "--no-index",
        "--no-deps",
        "--only-binary=:all:",
        "--no-cache-dir",
        "--no-compile",
        "--require-hashes",
        "--requirement",
        requirements,
    ]
    runpy.run_path(str(pip), run_name="__main__")


if __name__ == "__main__":
    install(sys.argv[1])
