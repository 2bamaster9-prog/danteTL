"""Build a Windows x64 ZIP with private CPython, CPU dependencies and a native GUI launcher.

Build tools (uv 0.13.8 and Zig 0.14.1) are needed only on the developer's PC.
Each build uses fresh staging; existing releases, runtimes and personal data are untouched.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from importlib.metadata import distributions
from pathlib import Path
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], environment: dict[str, str]) -> None:
    subprocess.run(args, cwd=ROOT, env=environment, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--zig", default="zig")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/DanteJP-windows-x64.zip")
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("Build on Windows x64.")
    uv = ROOT / ".bootstrap/Scripts/uv.exe"
    python = ROOT / ".python/cpython-3.12-windows-x86_64-none"
    if subprocess.check_output([str(uv), "--version"], text=True).split()[:2] != ["uv", "0.13.8"]:
        raise RuntimeError("Build requires uv 0.13.8.")
    if subprocess.check_output([args.zig, "version"], text=True).strip() != "0.14.1":
        raise RuntimeError("Build requires Zig 0.14.1.")
    version = subprocess.check_output([str(python / "python.exe"), "--version"], text=True).strip()
    if version != "Python 3.12.16":
        raise RuntimeError("Build requires the managed CPython 3.12.16 x64 distribution.")
    staging = ROOT / "build" / ("standalone-" + uuid4().hex)
    bundle = staging / "DanteJP"
    internal = bundle / "_internal"
    project = internal / "app"
    project.mkdir(parents=True)
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("UV_") and key not in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH")
    }
    environment.update(
        UV_PROJECT_ENVIRONMENT=str(staging / "dependencies"),
        UV_CACHE_DIR=str(ROOT / ".uv-cache"),
        UV_PYTHON_INSTALL_DIR=str(ROOT / ".python"),
        ZIG_GLOBAL_CACHE_DIR=str(ROOT / "build/zig-cache"),
        ZIG_LOCAL_CACHE_DIR=str(staging / "zig-cache"),
    )
    if args.offline:
        environment["UV_OFFLINE"] = "1"
    print("Installing locked CPU dependencies in fresh staging…", flush=True)
    run(
        [
            str(uv),
            "sync",
            "--locked",
            "--no-default-groups",
            "--group",
            "cpu",
            "--no-install-project",
            "--python",
            str(python / "python.exe"),
        ],
        environment,
    )
    print("Bundling private Python and native libraries…", flush=True)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
    shutil.copytree(
        python,
        internal / "python",
        ignore=shutil.ignore_patterns(
            "__pycache__", "*.pyc", "site-packages", "Scripts", "include", "libs"
        ),
    )
    packages = staging / "dependencies/Lib/site-packages"
    destination = internal / "python/Lib/site-packages"
    shutil.copytree(packages, destination, ignore=ignore)
    # App-local VC runtime supplied by PySide's wheel: native imports must not depend on
    # a globally installed Visual C++ redistributable or Qt having been imported first.
    for dll in (destination / "PySide6").glob("*140*.dll"):
        shutil.copy2(dll, internal / "python" / dll.name)
    shutil.copytree(ROOT / "src/jp_overlay", project / "src/jp_overlay", ignore=ignore)
    for name in ("pyproject.toml", "uv.lock", ".python-version", "README.md"):
        shutil.copy2(ROOT / name, project / name)
    shutil.copy2(ROOT / "tools/standalone/bootstrap.py", project / "bootstrap.py")
    (project / "standalone.json").write_text(json.dumps({"format": 1}), encoding="utf-8")
    shutil.copy2(uv, internal / "uv.exe")
    shutil.copytree(
        ROOT / ".bootstrap/Lib/site-packages/uv-0.13.8.dist-info", internal / "uv-notices"
    )
    shutil.copy2(ROOT / "tools/standalone/README.txt", bundle / "README.txt")
    shutil.copy2(ROOT / "tools/standalone/launcher.c", project / "launcher.c")
    print("Compiling DanteJP.exe…", flush=True)
    run(
        [
            args.zig,
            "cc",
            "-target",
            "x86_64-windows-gnu",
            "-municode",
            "-Wl,/subsystem:windows",
            "-Os",
            "-s",
            str(ROOT / "tools/standalone/launcher.c"),
            "-o",
            str(bundle / "DanteJP.exe"),
        ],
        environment,
    )
    installed = sorted(
        (
            {"name": d.metadata["Name"], "version": d.version}
            for d in distributions(path=[str(packages)])
        ),
        key=lambda d: d["name"].lower(),
    )
    (bundle / "THIRD-PARTY.txt").write_text(
        "DanteJP includes CPython (PSF license), uv (MIT/Apache-2.0) and the packages below.\n"
        "Licenses/notices are preserved in _internal/python/LICENSE.txt, DLLs, Lib/site-packages\n"
        "and _internal/uv-notices. See each package's .dist-info directory for its metadata.\n"
        "Qt/PySide are dynamically loaded and replaceable; no restriction on debugging changes.\n"
        "Qt/PySide sources and licenses: https://code.qt.io/cgit/pyside/pyside-setup.git/\n"
        "https://code.qt.io/cgit/qt/ and https://doc.qt.io/qtforpython-6/licenses.html\n"
        "No OCR or translation weights are included. Model downloads retain their own licenses.\n\n"
        + "\n".join(f"{d['name']} {d['version']}" for d in installed)
        + "\n",
        encoding="utf-8",
    )
    print("Checking bundled native CPU libraries…", flush=True)
    probe_env = environment | {"DANTEJP_DATA_DIR": str(staging / "probe-data")}
    run(
        [
            str(internal / "python/python.exe"),
            "-I",
            "-B",
            str(project / "bootstrap.py"),
            "--module",
            "jp_overlay.runtime_probe",
            "cpu",
        ],
        probe_env,
    )
    files = sorted(p for p in bundle.rglob("*") if p.is_file())
    manifest = {
        "built_utc": datetime.now(UTC).isoformat(),
        "python": version,
        "uv": "0.13.8",
        "packages": installed,
        "files": {
            p.relative_to(bundle).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in files
        },
    }
    (bundle / "MANIFEST.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_name(args.output.name + ".tmp")
    print("Compressing release ZIP…", flush=True)
    with ZipFile(temporary, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(p for p in bundle.rglob("*") if p.is_file()):
            archive.write(path, "DanteJP/" + path.relative_to(bundle).as_posix())
    temporary.replace(args.output)
    print(f"Created {args.output} ({args.output.stat().st_size / 1e6:.1f} MB)")
    print(f"Unpacked app: {bundle}")


if __name__ == "__main__":
    main()
