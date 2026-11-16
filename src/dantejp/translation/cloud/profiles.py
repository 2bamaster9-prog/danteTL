"""Explicit cloud configuration; only non-secret settings are stored in JSON."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from dantejp.paths import state_root
from dantejp.translation.cloud.values import ENDPOINTS as ENDPOINTS
from dantejp.translation.cloud.values import MAX_CLOUD_PROFILES as MAX_CLOUD_PROFILES
from dantejp.translation.cloud.values import MODELS as MODELS
from dantejp.translation.cloud.values import PROVIDERS as PROVIDERS
from dantejp.translation.cloud.values import CloudProfile as CloudProfile


class CloudProfiles:
    """Small atomically replaced catalog. Read/write on a setup worker, never per frame."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or state_root() / "data/cloud-models.json"

    def read(self) -> tuple[CloudProfile, ...]:
        if not self.path.exists():
            return ()
        if self.path.stat().st_size > 32_768:
            raise ValueError("Cloud model settings are too large.")
        data = json.loads(self.path.read_text("utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1:
            raise ValueError("Unsupported cloud model settings.")
        rows = data.get("profiles")
        if not isinstance(rows, list) or len(rows) > MAX_CLOUD_PROFILES:
            raise ValueError("At most sixteen cloud model profiles are supported.")
        try:
            profiles = tuple(CloudProfile(**row) for row in rows)
        except TypeError as error:
            raise ValueError("Invalid cloud model settings.") from error
        if len({p.key for p in profiles}) != len(profiles):
            raise ValueError("Duplicate cloud model IDs.")
        return profiles

    def write(self, profiles: tuple[CloudProfile, ...]) -> None:
        if len(profiles) > MAX_CLOUD_PROFILES or len({p.key for p in profiles}) != len(profiles):
            raise ValueError("At most sixteen distinct cloud profiles are supported.")
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
