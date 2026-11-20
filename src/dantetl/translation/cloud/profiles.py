"""Explicit cloud configuration; only non-secret settings are stored in JSON."""

import json
import os
from contextlib import AbstractContextManager
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from dantetl.file_lock import file_lock
from dantetl.i18n import tr
from dantetl.paths import state_root
from dantetl.translation.cloud.values import (
    MAX_CLOUD_PROFILES,
    CloudProfile,
)


class CloudProfiles:
    """Small atomically replaced catalog. Read/write on a setup worker, never per frame."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_root() / "data/cloud-models.json"

    def transaction(self) -> AbstractContextManager[None]:
        """Serialize model, connection and vault changes using the same catalog identity."""
        return file_lock(self.path.with_suffix(".lock"))

    def update(self, profile: CloudProfile, *, remove: bool = False) -> None:
        with self.transaction():
            remaining = tuple(p for p in self.read() if p.key != profile.key)
            self.write(remaining if remove else (*remaining, profile))

    def read(self) -> tuple[CloudProfile, ...]:
        if not self.path.exists():
            return ()
        if self.path.stat().st_size > 32_768:
            raise ValueError(tr("Cloud model settings are too large."))
        data = json.loads(self.path.read_text("utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError(tr("Unsupported cloud model settings."))
        rows = data.get("profiles")
        if not isinstance(rows, list) or len(rows) > MAX_CLOUD_PROFILES:
            raise ValueError(tr("At most sixteen cloud model profiles are supported."))
        try:
            profiles = tuple(CloudProfile(**row) for row in rows)
        except TypeError as error:
            raise ValueError(tr("Invalid cloud model settings.")) from error
        if len({p.key for p in profiles}) != len(profiles):
            raise ValueError(tr("Duplicate cloud model IDs."))
        return profiles

    def write(self, profiles: tuple[CloudProfile, ...]) -> None:
        if len(profiles) > MAX_CLOUD_PROFILES or len({p.key for p in profiles}) != len(profiles):
            raise ValueError(tr("At most sixteen distinct cloud profiles are supported."))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}-{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps({"version": 1, "profiles": [asdict(p) for p in profiles]}, indent=2),
                "utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
