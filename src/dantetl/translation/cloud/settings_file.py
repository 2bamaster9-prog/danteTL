"""Bounded, atomically replaced JSON for non-secret cloud settings."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from dantetl.i18n import tr


@dataclass(frozen=True, slots=True)
class SettingsFile:
    max_bytes: int
    size_error: str

    def _checked(self, data: bytes) -> bytes:
        if len(data) > self.max_bytes:
            raise ValueError(tr(self.size_error))
        return data

    def read(self, path: Path) -> object:
        with path.open("rb") as stream:
            data = self._checked(stream.read(self.max_bytes + 1))
        return json.loads(data.decode("utf-8"))

    def write(self, path: Path, value: dict[str, object]) -> None:
        data = self._checked(json.dumps(value, indent=2).encode("ascii"))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
