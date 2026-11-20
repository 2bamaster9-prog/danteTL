"""Pinned model assets, cheap presence checks and worker-owned hash validation."""

import hashlib
from dataclasses import dataclass
from pathlib import Path

from dantetl.i18n import tr
from dantetl.paths import is_standalone


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
    recovery = tr("Open Models and choose Download or Verify / repair.")
    if setup and not is_standalone():
        recovery += tr(" You can also run {setup}.", setup=setup)
    if not path.is_file() or path.stat().st_size != asset.size:
        raise RuntimeError(
            tr(
                "Missing or incomplete model asset: {filename}. {recovery}",
                filename=asset.filename,
                recovery=recovery,
            )
        )
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != asset.sha256:
        raise RuntimeError(
            tr(
                "Model checksum mismatch: {filename}. {recovery}",
                filename=asset.filename,
                recovery=recovery,
            )
        )
