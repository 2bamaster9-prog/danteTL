"""Install pinned runtimes in user state; publish only validated environments."""

import hashlib
import json
import os
import re
import shutil
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from jp_overlay.model_store import Cancelled, ModelProgress, Progress
from jp_overlay.paths import is_standalone, module_command, runtime_project, state_root
from jp_overlay.setup_process import run_setup_command


@dataclass(frozen=True, slots=True)
class RuntimeProfile:
    key: str
    name: str
    groups: tuple[str, ...]
    description: str


PROFILES = (
    RuntimeProfile(
        "nvidia",
        "NVIDIA GPU — CUDA",
        ("gpu", "gemma"),
        "Accelerates supported recognition and translation engines with CUDA 13. "
        "Downloads about 1.3 GB "
        "of NVIDIA/ONNX libraries, plus app dependencies. Model downloads are separate. "
        "An up-to-date NVIDIA driver is required; system drivers are not changed.",
    ),
    RuntimeProfile(
        "amd",
        "GPU — Vulkan",
        ("cpu", "gemma-vulkan"),
        "Accelerates supported translation engines with Vulkan; recognition stays on CPU. "
        "Requires a Vulkan-capable graphics driver. Radeon inference still needs testing "
        "on your card; experimental DirectML OCR is not installed by this option.",
    ),
    RuntimeProfile(
        "cpu",
        "CPU",
        ("cpu", "llm-cpu"),
        "Runs local recognition and translation without GPU dependencies. "
        "Larger language models may translate more slowly. CPU support is included in the "
        "standalone app. Your downloaded models are kept when switching.",
    ),
)


def project_root() -> Path:
    """Compatibility name for the writable installation/state root."""
    return state_root()


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256(b"runtime-setup-v1")
    for name in ("uv.lock", "pyproject.toml"):
        digest.update((runtime_project(root) / name).read_bytes())
    return digest.hexdigest()


def _atomic_json(path: Path, value: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(value), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def runtime_path(root: Path, name: str) -> Path:
    """Receipts may select only generated environments inside this project."""
    if not re.fullmatch(r"(?:nvidia|amd|cpu)-[a-f0-9]{32}", name):
        raise ValueError("Invalid runtime environment name.")
    base = (root / ".runtimes").resolve()
    candidate = base / name
    target = candidate.resolve()
    if (
        base.parent != root.resolve()
        or target.parent != base
        or candidate.is_symlink()
        or candidate.is_junction()
    ):
        raise ValueError("Runtime environment escapes this project.")
    return target


def ready_runtime(root: Path, key: str) -> Path | None:
    if key not in {p.key for p in PROFILES}:
        return None
    try:
        receipt = json.loads((root / "data/runtimes" / f"{key}.json").read_text("utf-8"))
        target = runtime_path(root, receipt["environment"])
        if (
            target.name.startswith(key + "-")
            and receipt["fingerprint"] == _fingerprint(root)
            and (target / "Scripts/pythonw.exe").is_file()
            and (target / "ready.json").read_text("utf-8") == json.dumps(receipt)
        ):
            return target
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def selected_runtime(root: Path) -> Path | None:
    try:
        value = json.loads((root / "data/runtime.json").read_text("utf-8"))
        target = ready_runtime(root, value["profile"])
        return target if target and target.name == value["environment"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def select_runtime(root: Path, target: Path) -> None:
    key = target.name.split("-", 1)[0]
    if ready_runtime(root, key) != target.resolve():
        raise ValueError("Only a verified runtime can be selected.")
    _atomic_json(root / "data/runtime.json", {"profile": key, "environment": target.name})


def install_runtime(
    root: Path, profile: RuntimeProfile, progress: Progress, cancel: threading.Event
) -> None:
    """Explicit action only. Reuse completed installs; never mutate a loaded environment."""
    if profile not in PROFILES:
        raise ValueError("Unknown runtime profile.")
    root = root.resolve()
    # Exclusive across app copies sharing this project. A crash releases the OS lock.
    import msvcrt

    (root / "data").mkdir(parents=True, exist_ok=True)
    with (root / "data/runtime-install.lock").open("a+b") as lock:
        lock.seek(0)
        if not lock.read(1):
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError(
                "Another DanteJP instance is already installing a runtime."
            ) from error
        try:
            _install(root, profile, progress, cancel)
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def _install(
    root: Path, profile: RuntimeProfile, progress: Progress, cancel: threading.Event
) -> None:
    environment = os.environ.copy()
    # Do not inherit uv run's environment selection or an activated developer venv.
    for key in tuple(environment):
        if key.startswith("UV_") or key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
            environment.pop(key)
    target = runtime_path(root, f"{profile.key}-{uuid4().hex}")
    environment.update(
        UV_PROJECT_ENVIRONMENT=str(target),
        UV_CACHE_DIR=str(root / ".uv-cache"),
        UV_PYTHON_INSTALL_DIR=str(root / ".python"),
        PYTHONUTF8="1",
        UV_NO_PROGRESS="1",
    )
    project = runtime_project(root)
    if is_standalone():
        # Never bind an AppData runtime to an app folder which may be moved or replaced.
        environment["UV_PYTHON_PREFERENCE"] = "only-managed"
        environment["DANTEJP_DATA_DIR"] = str(root)

    def command(args: list[str], stage: str, timeout: float = 1800) -> None:
        progress(ModelProgress(stage))
        run_setup_command(
            args,
            project,
            environment,
            cancel,
            lambda detail: progress(ModelProgress(f"{stage}\n{detail}")),
            timeout=timeout,
        )

    if ready := ready_runtime(root, profile.key):
        try:
            command(
                module_command(
                    ready / "Scripts/python.exe", "jp_overlay.runtime_probe", profile.key
                ),
                "Checking the installed runtime…",
                timeout=180,
            )
        except (OSError, RuntimeError):
            progress(
                ModelProgress("Existing runtime needs repair. Building a separate replacement…")
            )
        else:
            progress(ModelProgress("Installed runtime checks passed. Restart to use it."))
            return

    uv = project.parent / "uv.exe" if is_standalone() else root / ".bootstrap/Scripts/uv.exe"
    if is_standalone() and not uv.is_file():
        raise RuntimeError("The bundled installer is missing. Extract the complete DanteJP ZIP.")
    if not uv.is_file():
        located = shutil.which("uv")
        if located:
            uv = Path(located)
        else:
            bootstrap = root / ".runtime-bootstrap"
            command(
                [sys.executable, "-m", "venv", str(bootstrap)], "1/3 · Preparing the installer…"
            )
            command(
                [str(bootstrap / "Scripts/python.exe"), "-m", "pip", "install", "uv==0.13.8"],
                "1/3 · Downloading the installer…",
            )
            uv = bootstrap / "Scripts/uv.exe"
    args = [str(uv), "sync", "--locked", "--no-default-groups", "--python", "3.12"]
    if is_standalone():
        args.append("--no-install-project")
    for group in profile.groups:
        args.extend(("--group", group))
    # Keep the final path: Windows venv entry points must not be renamed after installation.
    try:
        command(args, "2/3 · Downloading and installing dependencies…")
        command(
            module_command(target / "Scripts/python.exe", "jp_overlay.runtime_probe", profile.key),
            "3/3 · Checking installed libraries and GPU support…",
            timeout=180,
        )
        if cancel.is_set():
            raise Cancelled()
        receipt = {"environment": target.name, "fingerprint": _fingerprint(root)}
        _atomic_json(target / "ready.json", receipt)
        _atomic_json(root / "data/runtimes" / f"{profile.key}.json", receipt)
    except BaseException:
        # Only remove the fresh environment owned by this call, after subprocesses have exited.
        checked = runtime_path(root, target.name)
        if checked.exists() and checked != Path(sys.prefix).resolve():
            shutil.rmtree(checked)
        raise
    progress(
        ModelProgress("Runtime installed and checked. Restart to use it. Model files were kept.")
    )
