"""Reusable provider credentials, separate from model entries. Worker-only operations."""

import json
import os
from dataclasses import asdict, replace
from uuid import uuid4

from dantejp.i18n import tr
from dantejp.translation.cloud.credentials import Secrets
from dantejp.translation.cloud.profiles import CloudProfiles
from dantejp.translation.cloud.values import MAX_CLOUD_PROFILES, ApiConnection, CloudProfile


class ApiConnections:
    def __init__(self, catalog: CloudProfiles) -> None:
        self.catalog = catalog
        self.path = catalog.path.with_name(catalog.path.stem + "-connections.json")

    def read(
        self, profiles: tuple[CloudProfile, ...], secrets: Secrets
    ) -> tuple[ApiConnection, ...]:
        connections: tuple[ApiConnection, ...] = ()
        if self.path.exists():
            if self.path.stat().st_size > 16_384:
                raise ValueError(tr("API connection settings are too large."))
            value = json.loads(self.path.read_text("utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1:
                raise ValueError(tr("Unsupported API connection settings."))
            rows = value.get("connections")
            if not isinstance(rows, list) or len(rows) > 16:
                raise ValueError(tr("Invalid API connection settings."))
            try:
                connections = tuple(ApiConnection(**row) for row in rows)
            except TypeError:
                raise ValueError(tr("Invalid API connection settings.")) from None
            if len({c.key for c in connections}) != len(connections):
                raise ValueError(tr("Duplicate API connection IDs."))
        # Adopt previous model-owned credentials in place, without copying secret material.
        legacy = tuple(
            ApiConnection(p.key, p.provider, p.name + " key")
            for p in profiles
            if p.provider != "chatgpt"
            and not p.credential
            and not any(c.key == p.key for c in connections)
            and secrets.read(p.key)
        )
        if legacy:
            connections += legacy
            self._write(connections)
        return connections

    def _write(self, connections: tuple[ApiConnection, ...]) -> None:
        if len(connections) > 16:
            raise ValueError(tr("Remove an unused API connection first (limit: sixteen)."))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}-{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(
                    {"version": 1, "connections": [asdict(c) for c in connections]}, indent=2
                ),
                "utf-8",
            )
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def secret(self, profile: CloudProfile, secrets: Secrets) -> str:
        connections = self.read(self.catalog.read(), secrets)
        if not any(
            c.key == profile.credential_key and c.provider == profile.provider for c in connections
        ):
            return ""
        return secrets.read(profile.credential_key) or ""

    def save_model(
        self, profile: CloudProfile, connection: str, secret: str, secrets: Secrets
    ) -> CloudProfile:
        profiles = self.catalog.read()
        connections = self.read(profiles, secrets)
        existing = next(
            (c for c in connections if c.key == connection and c.provider == profile.provider), None
        )
        if connection and existing is None:
            raise ValueError(
                tr("Choose a saved connection for this provider, or add a new API key.")
            )
        selected = existing or ApiConnection(
            "api-" + uuid4().hex, profile.provider, profile.name + " key"
        )
        previous = secrets.read(selected.key)
        if not secret and not previous:
            raise ValueError(tr("Enter an API key or choose a saved connection."))
        saved = replace(profile, credential=selected.key)
        updated = tuple(p for p in profiles if p.key != profile.key) + (saved,)
        if len(updated) > MAX_CLOUD_PROFILES or (existing is None and len(connections) >= 16):
            raise ValueError(tr("Remove an unused model or connection before adding another."))
        try:
            if secret:
                secrets.write(selected.key, secret)
            if existing is None:
                self._write(connections + (selected,))
            self.catalog.write(updated)
        except Exception:
            if secret:
                if previous:
                    secrets.write(selected.key, previous)
                else:
                    secrets.delete(selected.key)
            if existing is None:
                self._write(connections)
            raise
        return saved

    def forget(self, key: str, secrets: Secrets) -> None:
        connections = self.read(self.catalog.read(), secrets)
        if not any(c.key == key for c in connections):
            raise ValueError(tr("This connection is no longer available."))
        secrets.delete(key)
        self._write(tuple(c for c in connections if c.key != key))
