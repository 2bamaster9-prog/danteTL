"""Pinned model assets, cheap presence checks and worker-owned hash validation."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from dantejp.paths import is_standalone


@dataclass(frozen=True, slots=True)
class ModelAsset:
    repo: str
    revision: str
    filename: str
    sha256: str
    size: int
    remote_filename: str = ""

    @property
    def url(self) -> str:
        remote = self.remote_filename or self.filename
        return f"https://huggingface.co/{self.repo}/resolve/{self.revision}/{remote}"


def assets_present(directory: Path, assets: tuple[ModelAsset, ...]) -> bool:
    """Cheap availability only; workers verify hashes before loading or repairing."""
    try:
        return all((directory / asset.filename).stat().st_size == asset.size for asset in assets)
    except OSError:
        return False


def asset_directory(primary: Path, assets: tuple[ModelAsset, ...], bundled: Path | None) -> Path:
    if not assets_present(primary, assets) and bundled and assets_present(bundled, assets):
        return bundled
    return primary


def validate_asset(path: Path, asset: ModelAsset, setup: str | None = None) -> None:
    recovery = "Open Models and choose Download or Verify / repair."
    if setup and not is_standalone():
        recovery += f" You can also run {setup}."
    if not path.is_file() or path.stat().st_size != asset.size:
        raise RuntimeError(f"Missing or incomplete model asset: {asset.filename}. {recovery}")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != asset.sha256:
        raise RuntimeError(f"Model checksum mismatch: {asset.filename}. {recovery}")
