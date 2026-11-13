"""Explicit model installation and preparation, independent of Qt and inference runtimes."""

import hashlib
import json
import os
import platform
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.request import urlopen

from jp_overlay.models import ModelAsset
from jp_overlay.paths import state_root

GEMMA_RUNTIME_SETUP = (
    "Gemma is downloaded, but its language-model engine is not installed in this app environment. "
    "Open Settings → Acceleration and choose CPU or GPU, then restart. "
    "Your model files are already present; no model download is needed."
)


@dataclass(frozen=True, slots=True)
class ModelBundle:
    key: str
    name: str
    directory: Path
    assets: tuple[ModelAsset, ...]
    description: str

    @property
    def size(self) -> int:
        return sum(a.size for a in self.assets)

    def present(self) -> bool:
        # Availability only. Integrity checks run on workers before model use.
        try:
            return all((self.directory / a.filename).stat().st_size == a.size for a in self.assets)
        except OSError:
            return False


def model_catalog() -> tuple[ModelBundle, ...]:
    from jp_overlay import gemma, models, sugoi

    return (
        ModelBundle(
            "ocr",
            "MeikiOCR · Japanese text recognition",
            models.model_directory(),
            models.ASSETS,
            "Required for text recognition; download once for any OCR device.",
        ),
        ModelBundle(
            "sugoi",
            "Sugoi V4 · compact CPU translation",
            sugoi.model_directory(),
            sugoi.ASSETS,
            "Fast Japanese → English. Review the upstream Sugoi license before redistribution.",
        ),
        ModelBundle(
            "gemma",
            "Gemma 4 E2B · local translation",
            gemma.model_directory(),
            gemma.ASSETS,
            "Google QAT Q4_0 · Apache-2.0. Runs on CPU; optional GPU acceleration is faster. "
            "Select the downloaded model to prepare it for this PC.",
        ),
    )


def model_status(bundle: ModelBundle) -> str:
    """Distinguish downloaded weights from the runtime available to this process."""
    if not bundle.present():
        return "Not downloaded. Choose Download to install this model's files."
    if bundle.key == "gemma":
        from jp_overlay.llama_runtime import installed_device

        if installed_device() is None:
            return GEMMA_RUNTIME_SETUP
        if installed_device() == "cpu":
            return (
                "Downloaded. Runtime available on CPU; translations may be slower. "
                "GPU acceleration is optional. Integrity is checked before use."
            )
    if bundle.key == "ocr":
        from jp_overlay.ocr_runtime import gpu_runtime_installed

        if not (gpu_runtime_installed() or gpu_runtime_installed("onnxruntime-directml")):
            return (
                "Downloaded. CPU OCR is ready. The Automatic NVIDIA OCR option needs a separate "
                "runtime: open Acceleration, install NVIDIA support, then restart. "
                "Downloading Meiki does not install GPU support."
            )
    return "Downloaded. Runtime available; integrity is checked before use."


class Cancelled(Exception):
    pass


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    name: str
    received: int = 0
    total: int = 0


@dataclass(frozen=True, slots=True)
class ModelProgress:
    message: str = "Starting…"
    received: int = 0
    total: int = 0
    done: bool = False
    cancelled: bool = False
    error: str = ""
    download: DownloadProgress | None = None
    stage: int = 0
    stages: int = 0


Progress = Callable[[ModelProgress], None]


def _check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def _valid(path: Path, asset: ModelAsset, cancel: threading.Event) -> bool:
    if not path.is_file() or path.stat().st_size != asset.size:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_cancel(cancel)
            digest.update(chunk)
    return digest.hexdigest() == asset.sha256


def install_model(bundle: ModelBundle, progress: Progress, cancel: threading.Event) -> None:
    """Called only by an explicit UI/CLI download action. Atomic verified files."""
    bundle.directory.mkdir(parents=True, exist_ok=True)
    completed = 0
    for asset in bundle.assets:
        _check_cancel(cancel)
        destination = bundle.directory / asset.filename
        progress(ModelProgress(f"Checking {asset.filename}…", completed, bundle.size))
        if _valid(destination, asset, cancel):
            completed += asset.size
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, suffix=".part", delete=False
            ) as out:
                temporary = Path(out.name)
                received = 0
                digest = hashlib.sha256()
                with urlopen(asset.url, timeout=15) as response:
                    while chunk := response.read(1024 * 1024):
                        _check_cancel(cancel)
                        received += len(chunk)
                        if received > asset.size:
                            raise RuntimeError("Download exceeded the pinned model size.")
                        digest.update(chunk)
                        out.write(chunk)
                        progress(
                            ModelProgress(
                                f"Downloading {asset.filename}",
                                completed + received,
                                bundle.size,
                                download=DownloadProgress(asset.filename, received, asset.size),
                            )
                        )
            _check_cancel(cancel)
            if received != asset.size or digest.hexdigest() != asset.sha256:
                raise RuntimeError(
                    f"Checksum/size mismatch for {asset.filename}. Retry the download."
                )
            os.replace(temporary, destination)
            completed += asset.size
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    progress(ModelProgress("Model files downloaded and verified.", bundle.size, bundle.size))


class ModelOperation:
    """One bounded background operation and immutable progress; no GUI callbacks."""

    def __init__(self, action: Callable[[Progress, threading.Event], None]) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._snapshot = ModelProgress()
        self._thread = threading.Thread(
            target=self._run, args=(action,), daemon=True, name="model-setup"
        )

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def snapshot(self) -> ModelProgress:
        with self._lock:
            return self._snapshot

    def _progress(self, value: ModelProgress) -> None:
        with self._lock:
            self._snapshot = value

    def _run(self, action: Callable[[Progress, threading.Event], None]) -> None:
        try:
            action(self._progress, self._cancel)
            value = self.snapshot()
            self._progress(replace(value, done=True))
        except Cancelled:
            self._progress(
                ModelProgress(
                    "Cancelled. Verified files were kept for retry.", done=True, cancelled=True
                )
            )
        except Exception as error:
            self._progress(ModelProgress("Setup failed.", done=True, error=str(error)))


def preparation_id(bundle: ModelBundle, device: str) -> str:
    try:
        runtime = version("llama-cpp-python")
    except PackageNotFoundError:
        runtime = "missing"
    payload = [
        "prepare-v1",
        [a.sha256 for a in bundle.assets],
        runtime,
        device,
        platform.node(),
        platform.version(),
    ]
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()


def preparation_file(key: str) -> Path:
    return state_root() / "data/prepared" / f"{key}.json"


def is_prepared(key: str) -> bool:
    return not key or preparation_file(key).is_file()


def mark_prepared(key: str) -> None:
    destination = preparation_file(key)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps({"prepared": True, "id": key}), encoding="utf-8")
    os.replace(temporary, destination)
