"""Cached model metadata for views. Availability is sampled by the inventory worker."""

from dataclasses import dataclass

from jp_overlay.import_values import ImportedModel


@dataclass(frozen=True)
class ModelFile:
    key: str
    name: str
    description: str
    category: str
    size: int
    present: bool
    included: bool
    language_model: bool
    needs_plamo: bool
    directory: str
    bundled_directory: str
    local_directory: str
    status: str
    device: str | None
    upgrade: bool
    imported: ImportedModel | None = None
