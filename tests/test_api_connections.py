import json
from dataclasses import replace
from uuid import uuid4

import pytest

from dantejp.translation.cloud.api_connections import ApiConnections
from dantejp.translation.cloud.credentials import WindowsSecrets
from dantejp.translation.cloud.profiles import (
    MAX_CLOUD_PROFILES,
    MODELS,
    CloudProfile,
    CloudProfiles,
)


class SecretsFixture:
    def __init__(self):
        self.values = {}

    def read(self, key):
        return self.values.get(key)

    def write(self, key, secret):
        self.values[key] = secret

    def delete(self, key):
        self.values.pop(key, None)


def test_mixed_catalog_can_edit_at_full_capacity_without_mutating_keys_on_overflow(tmp_path):
    catalog = CloudProfiles(tmp_path / "models.json")
    connections, secrets = ApiConnections(catalog), SecretsFixture()
    first = connections.save_model(CloudProfile.new("openai"), "", "old-key", secrets)
    mixed = tuple(
        CloudProfile(
            "cloud-" + uuid4().hex,
            "Plan model",
            "chatgpt",
            "gpt-6-luna",
            account="account-" + "a" * 32,
        )
        for _ in range(MAX_CLOUD_PROFILES - 1)
    )
    catalog.write((first, *mixed))
    edited = connections.save_model(
        replace(first, name="Edited API model"), first.credential, "new-key", secrets
    )
    assert len(catalog.read()) == MAX_CLOUD_PROFILES
    assert edited in catalog.read() and connections.secret(edited, secrets) == "new-key"
    before = catalog.read()
    with pytest.raises(ValueError):
        connections.save_model(
            CloudProfile.new("openai"), first.credential, "must-not-save", secrets
        )
    assert catalog.read() == before and connections.secret(edited, secrets) == "new-key"


@pytest.mark.parametrize("provider", ["openai", "gemini", "claude"])
def test_connection_is_reused_after_restart_model_removal_and_new_model(tmp_path, provider):
    catalog = CloudProfiles(tmp_path / "models.json")
    connections = ApiConnections(catalog)
    secrets = SecretsFixture()
    first = connections.save_model(CloudProfile.new(provider), "", "fixture-key", secrets)
    second = connections.save_model(
        replace(CloudProfile.new(provider), model=MODELS[provider][1][0]),
        first.credential,
        "",
        secrets,
    )
    assert first.credential == second.credential
    assert len(secrets.values) == 1
    # New service instances, no model entries: the connection still exists.
    catalog.write(())
    reloaded = ApiConnections(CloudProfiles(catalog.path))
    assert len(reloaded.read((), secrets)) == 1
    third = reloaded.save_model(CloudProfile.new(provider), first.credential, "", secrets)
    assert reloaded.secret(third, secrets) == "fixture-key"
    assert "fixture-key" not in connections.path.read_text()
    assert "fixture-key" not in catalog.path.read_text()
    reloaded.forget(first.credential, secrets)
    assert reloaded.secret(third, secrets) == "" and not secrets.values


@pytest.mark.parametrize("other", ["deepseek", "gemini", "claude"])
def test_connection_never_crosses_provider_and_key_replacement_rolls_back(
    tmp_path, monkeypatch, other
):
    catalog = CloudProfiles(tmp_path / "models.json")
    connections, secrets = ApiConnections(catalog), SecretsFixture()
    first = connections.save_model(CloudProfile.new("openai"), "", "original-secret", secrets)
    with pytest.raises(ValueError, match="this provider"):
        connections.save_model(CloudProfile.new(other), first.credential, "", secrets)
    forged = replace(CloudProfile.new(other), credential=first.credential)
    assert connections.secret(forged, secrets) == ""
    before = catalog.read()

    def disk_error(*args):
        raise OSError("fixture disk full")

    monkeypatch.setattr(catalog, "write", disk_error)
    with pytest.raises(OSError):
        connections.save_model(first, first.credential, "new-secret", secrets)
    assert connections.secret(first, secrets) == "original-secret"
    with pytest.raises(OSError):
        connections.save_model(CloudProfile.new("openai"), "", "abandoned-secret", secrets)
    assert list(secrets.values.values()) == ["original-secret"]
    assert len(connections.read(before, secrets)) == 1


def test_legacy_keys_are_adopted_without_moving_or_merging_accounts(tmp_path):
    catalog = CloudProfiles(tmp_path / "models.json")
    first, second = CloudProfile.new("openai"), CloudProfile.new("openai")
    catalog.write((first, second))
    secrets = SecretsFixture()
    secrets.write(first.key, "first-account")
    secrets.write(second.key, "second-account")
    connections = ApiConnections(catalog)
    assert len(connections.read(catalog.read(), secrets)) == 2
    assert connections.secret(first, secrets) == "first-account"
    assert connections.secret(second, secrets) == "second-account"
    connections.forget(first.key, secrets)
    assert len(connections.read(catalog.read(), secrets)) == 1
    assert connections.secret(first, secrets) == ""
    assert connections.secret(second, secrets) == "second-account"
    assert json.loads(catalog.path.read_text())["version"] == 1


@pytest.mark.windows
def test_native_vault_round_trip_does_not_modify_stored_key_when_wiping_read_buffer():
    secrets = WindowsSecrets("DanteJP/verification/" + uuid4().hex)
    try:
        assert secrets.read("fixture") is None
        secrets.write("fixture", "fake-owned-test-key")
        assert secrets.read("fixture") == secrets.read("fixture") == "fake-owned-test-key"
        secrets.delete("fixture")
        assert secrets.read("fixture") is None
    finally:
        secrets.delete("fixture")
