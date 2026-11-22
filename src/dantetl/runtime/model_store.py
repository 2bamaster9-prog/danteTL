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
from typing import Literal

from dantetl import paths
from dantetl.i18n import CatalogText, mark, tr
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.paths import is_standalone, state_root
from dantetl.runtime.assets import ModelAsset, asset_directory, assets_present
from dantetl.runtime.download_transport import download_file
from dantetl.runtime.setup_values import Cancelled, DownloadProgress, ModelProgress, Progress

LANGUAGE_RUNTIME_SETUP = mark(
    "The model is downloaded, but its language-model engine is not installed in this environment. "
    "Open Settings → Acceleration and choose CPU or GPU, then restart. "
    "Your model files are already present; no model download is needed."
)
PLAMO_RUNTIME_SETUP = mark(
    "PLaMo is downloaded, but this engine predates its tokenizer. "
    "Open Settings → Acceleration, install an updated CPU or GPU runtime, then restart. "
    "Your downloaded models are kept."
)


@dataclass(frozen=True, slots=True)
class ModelLocation:
    directory: Path
    present: bool
    included: bool


@dataclass(frozen=True, slots=True)
class ModelBundle:
    key: str
    name: str
    directory: Path
    assets: tuple[ModelAsset, ...]
    description: str
    bundled_directory: Path | None = None
    language_model: bool = False
    needs_plamo: bool = False
    category: Literal["translation", "recognition"] = "translation"

    @property
    def selection_id(self) -> str:
        return self.key

    @property
    def size(self) -> int:
        return sum(a.size for a in self.assets)

    def inspect_location(self) -> ModelLocation:
        primary = assets_present(self.directory, self.assets)
        included = self.included
        directory = self.directory
        if not primary and included and self.bundled_directory is not None:
            directory = self.bundled_directory
        return ModelLocation(directory, primary or included, included)

    def present(self) -> bool:
        return self.inspect_location().present

    @property
    def local_directory(self) -> Path:
        return asset_directory(self.directory, self.assets, self.bundled_directory)

    @property
    def included(self) -> bool:
        return bool(self.bundled_directory and assets_present(self.bundled_directory, self.assets))


def model_catalog(language: SourceLanguage = DEFAULT_SOURCE) -> tuple[ModelBundle, ...]:
    from dantetl.ocr import models
    from dantetl.translation.backends import gemma
    from dantetl.translation.models.curated import MODELS

    return (
        ModelBundle(
            "gemma",
            CatalogText("Gemma 4 E2B · Recommended"),
            gemma.model_directory(),
            gemma.ASSETS,
            CatalogText("Recommended balance of game terminology, quality and speed."),
            language_model=True,
        ),
        *(model.bundle() for model in MODELS),
        ModelBundle(
            "ocr",
            CatalogText("MeikiOCR · Japanese text recognition"),
            models.download_directory(),
            models.ASSETS,
            CatalogText(
                "Reads Japanese text from the game image; it does not translate it. "
                "Included in the standalone app."
            ),
            models.bundled_model_directory(),
            category="recognition",
        )
        if models.ocr_model_for(language) == models.OcrModel.MEIKI
        else ModelBundle(
            "ocr",
            CatalogText("PaddleOCR Latin · PP-OCRv5 mobile"),
            models.paddle_download_directory(),
            models.PADDLE_ASSETS,
            CatalogText(
                "Reads {name} game text. All Latin-script sources share these files.",
                name=CatalogText(language.name),
            ),
            models.bundled_paddle_directory(),
            category="recognition",
        ),
    )


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
    _check_cancel(cancel)
    if bundle.bundled_directory and bundle.local_directory == bundle.bundled_directory:
        progress(ModelProgress(tr("Checking included OCR files…"), 0, bundle.size))
        if all(_valid(bundle.bundled_directory / a.filename, a, cancel) for a in bundle.assets):
            progress(ModelProgress(tr("Included OCR files verified."), bundle.size, bundle.size))
            return
    if is_standalone() and bundle.directory.resolve().is_relative_to(
        paths.resource_root().resolve()
    ):
        raise RuntimeError(
            tr("App resources are read-only. Repair models in AppData or a user folder.")
        )
    bundle.directory.mkdir(parents=True, exist_ok=True)
    completed = 0
    for asset in bundle.assets:
        _check_cancel(cancel)
        destination = bundle.directory / asset.filename
        progress(
            ModelProgress(
                tr("Checking {filename}…", filename=asset.filename), completed, bundle.size
            )
        )
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
                local = (
                    bundle.bundled_directory / asset.filename if bundle.bundled_directory else None
                )
                if local and not _valid(local, asset, cancel):
                    local = None

                def report(
                    received: int,
                    _total: int,
                    *,
                    asset: ModelAsset = asset,
                    local: Path | None = local,
                    completed: int = completed,
                ) -> None:
                    progress(
                        ModelProgress(
                            tr("Restoring {filename}", filename=asset.filename)
                            if local
                            else tr("Downloading {filename}", filename=asset.filename),
                            completed + received,
                            bundle.size,
                            download=DownloadProgress(asset.filename, received, asset.size),
                        )
                    )

                if local:
                    with local.open("rb") as response:
                        while chunk := response.read(1024 * 1024):
                            _check_cancel(cancel)
                            received += len(chunk)
                            out.write(chunk)
                            report(received, asset.size)
            if not local:
                download_file(asset.url, temporary, asset.size, report, cancel)
            _check_cancel(cancel)
            if not _valid(temporary, asset, cancel):
                raise RuntimeError(
                    tr(
                        "Checksum/size mismatch for {filename}. Retry the download.",
                        filename=asset.filename,
                    )
                )
            _check_cancel(cancel)
            os.replace(temporary, destination)
            completed += asset.size
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    progress(ModelProgress(tr("Model files ready and verified."), bundle.size, bundle.size))


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
                    tr("Cancelled. Verified files were kept for retry."), done=True, cancelled=True
                )
            )
        except Exception as error:
            self._progress(ModelProgress(tr("Setup failed."), done=True, error=str(error)))


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
