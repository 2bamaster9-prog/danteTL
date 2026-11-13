"""Relocate the release ZIP and test its EXE with no Python/tools on PATH.

Only the owned app window is closed. No games are captured and no models are downloaded.
Run subsequent native fixtures with the extracted private interpreter and source paths.
"""

import argparse
import ctypes
import hashlib
import json
import os
import struct
import subprocess
import time
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

from jp_overlay.windows import Windows

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=ROOT / "dist/DanteJP-windows-x64.zip")
    parser.add_argument("--bundle", type=Path, help="Verify an already extracted bundle")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts") or output.exists():
        raise ValueError("Use a new directory under this project's artifacts folder.")
    output.mkdir(parents=True)
    if args.bundle:
        bundle = args.bundle.resolve()
        if not bundle.is_relative_to(ROOT / "artifacts"):
            raise ValueError("Use an extracted test bundle under artifacts.")
    else:
        relocated = output / "Moved app 日本語"
        with ZipFile(args.zip) as archive:
            for name in archive.namelist():
                if not (relocated / name).resolve().is_relative_to(relocated):
                    raise ValueError("ZIP path escapes extraction.")
            archive.extractall(relocated)
        bundle = relocated / "DanteJP"
    manifest = json.loads((bundle / "MANIFEST.json").read_text("utf-8"))
    for relative, digest in manifest["files"].items():
        assert hashlib.sha256((bundle / relative).read_bytes()).hexdigest() == digest, relative
    image = (bundle / "DanteJP.exe").read_bytes()
    pe = struct.unpack_from("<I", image, 0x3C)[0]
    assert struct.unpack_from("<H", image, pe + 24 + 68)[0] == 2, "Must be a GUI executable"
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("UV_", "JP_OVERLAY_", "DANTEJP_"))
        and key not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV")
    }
    environment.update(
        PATH=str(Path(os.environ["SYSTEMROOT"]) / "System32"),
        LOCALAPPDATA=str(output / "AppData"),
    )
    state = output / "AppData/DanteJP"
    python = bundle / "_internal/python/python.exe"
    bootstrap = bundle / "_internal/app/bootstrap.py"
    subprocess.run(
        [str(python), "-I", "-B", str(bootstrap), "--module", "jp_overlay.runtime_probe", "cpu"],
        env=environment,
        cwd=output,
        check=True,
        timeout=60,
    )
    token = uuid4().hex
    environment["JP_OVERLAY_RESTART_TOKEN"] = token
    subprocess.run(
        [str(bundle / "DanteJP.exe")], env=environment, cwd=output, check=True, timeout=10
    )
    receipt = state / "data/restarts" / token
    deadline = time.monotonic() + 40
    while not receipt.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert receipt.is_file(), "Native EXE did not acknowledge Qt startup"
    pid = int(receipt.read_text("ascii"))
    windows = Windows()
    targets = [t for t in windows.list_targets() if t.process_id == pid]
    assert len(targets) == 1 and targets[0].title == "DanteJP", targets
    user = ctypes.WinDLL("user32")
    user.PostMessageW.argtypes = (ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t)
    kernel = ctypes.WinDLL("kernel32")
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x100000, False, pid)
    assert handle
    try:
        user.PostMessageW(targets[0].hwnd, 0x0010, 0, 0)
        assert kernel.WaitForSingleObject(handle, 15000) == 0, "App did not drain on close"
    finally:
        kernel.CloseHandle(handle)
    assert not (state / "models").exists(), "First launch must not download models"
    assert not (state / ".runtimes").exists(), "First launch must not install a runtime"
    # Untouched defaults need not write a preferences file. The startup receipt and log
    # establish where state goes; UI fixtures separately exercise edited preferences.
    assert (state / "logs/app.log").is_file()
    before = set(manifest["files"]) | {"MANIFEST.json"}
    assert {p.relative_to(bundle).as_posix() for p in bundle.rglob("*") if p.is_file()} == before
    result = {
        "bundle": str(bundle),
        "state": str(state),
        "private_python": str(python),
        "no_python_on_path": True,
        "relocated_exe_started": True,
        "unicode_path": any(ord(char) > 127 for char in str(bundle)),
        "appdata_receipt_and_logs": True,
        "no_implicit_downloads": True,
        "no_files_written_in_app_folder": True,
        "clean_shutdown": True,
        "verified_files": len(manifest["files"]),
    }
    (output / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
