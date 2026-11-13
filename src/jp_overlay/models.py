"""Pinned OCR assets. Runtime validates local files and never downloads anything."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from jp_overlay.paths import is_standalone, state_root


@dataclass(frozen=True, slots=True)
class ModelAsset:
    repo: str
    revision: str
    filename: str
    sha256: str
    size: int

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{self.filename}"


ASSETS = (
    ModelAsset(
        "rtr46/meiki.text.detect.v0",
        "a9cffa4f60cbf72ddb87edf19c6f98a01cd042e6",
        "meiki.text.detect.v0.1.960x544.onnx",
        "40b6a016667745cae7d3055929ae3b8b1e7716aac795f5904cd3c2c7c3b8404b",
        14_503_825,
    ),
    ModelAsset(
        "rtr46/meiki.txt.recognition.v0",
        "a28cf5874dc2438ebb1c86336be26bcec51e3375",
        "meiki.text.rec.v0.960x32.onnx",
        "3e96bc772fbee9717e536a6353032bb944c3382dd2f6960ef4890decda43b000",
        18_593_254,
    ),
    ModelAsset(
        "rtr46/meiki.txt.recognition.v0",
        "a28cf5874dc2438ebb1c86336be26bcec51e3375",
        "meiki.text.rec.v0.vertical.32x480.onnx",
        "2c2a83a23bc3b7e6c63962175f507ecc6c5e85cc174f17bdec37d9bbd0bf895a",
        12_872_961,
    ),
)


def model_directory() -> Path:
    override = os.environ.get("JP_OVERLAY_MODEL_DIR")
    return Path(override) if override else state_root() / "models" / "meiki"


def validate_asset(path: Path, asset: ModelAsset, setup: str | None = "Setup OCR.cmd") -> None:
    recovery = "Open Models and choose Download or Verify / repair."
    if setup and not is_standalone():
        recovery += f" You can also run {setup}."
    if not path.is_file() or path.stat().st_size != asset.size:
        raise RuntimeError(f"Missing or incomplete model asset: {asset.filename}. {recovery}")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != asset.sha256:
        raise RuntimeError(f"Model checksum mismatch: {asset.filename}. {recovery}")


def local_model_paths(directory: Path) -> tuple[Path, ...]:
    paths = tuple(directory / asset.filename for asset in ASSETS)
    for path, asset in zip(paths, ASSETS, strict=True):
        validate_asset(path, asset)
    return paths
