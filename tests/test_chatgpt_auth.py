import base64
import hashlib
import json
import socket
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from jp_overlay.chatgpt_auth import (
    ISSUER,
    PLAN_SCOPE,
    ChatGPTConnections,
    SessionExpired,
    authorization_callback,
    token_record,
    validate_identity,
)
from jp_overlay.protected_store import ProtectedStore


@pytest.fixture(scope="module")
def signing():
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    key = json.loads(RSAAlgorithm.to_jwk(private.public_key()))
    key["kid"] = "fixture"
    return private, {"keys": [key]}


def identity(private, *, headers=None, **changes):
    claims = {
        "iss": ISSUER,
        "aud": "oaiapp_fixture",
        "sub": "fixture-subject",
        "iat": int(time.time()),
        "exp": int(time.time()) + 600,
        "nonce": "expected",
        **changes,
    }
    return jwt.encode(
        claims, private, algorithm="RS256", headers={"kid": "fixture", **(headers or {})}
    )


@pytest.mark.parametrize("critical", [["x-policy"], "x-policy", [], [1], ["b64"]])
def test_identity_rejects_critical_extensions_even_with_a_valid_rsa_signature(signing, critical):
    private, jwks = signing
    token = identity(private, headers={"crit": critical, "x-policy": "unsupported"})
    with pytest.raises(ValueError, match="identity validation"):
        validate_identity(token, jwks, "oaiapp_fixture", "expected")


def test_identity_allows_ordinary_noncritical_headers(signing):
    private, jwks = signing
    token = identity(private, headers={"x-display-label": "ignored"})
    assert validate_identity(token, jwks, "oaiapp_fixture", "expected")["sub"] == "fixture-subject"


def test_identity_requires_real_signature_issuer_audience_nonce_and_expiry(signing):
    private, jwks = signing
    assert (
        validate_identity(identity(private), jwks, "oaiapp_fixture", "expected")["sub"]
        == "fixture-subject"
    )
    for changes in (
        {"iss": "https://untrusted.invalid"},
        {"aud": "another-client"},
        {"nonce": "wrong"},
        {"exp": int(time.time()) - 5},
        {"sub": ""},
        {"aud": ["oaiapp_fixture", "another"], "azp": "another"},
    ):
        with pytest.raises(ValueError, match="identity validation"):
            validate_identity(identity(private, **changes), jwks, "oaiapp_fixture", "expected")
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ValueError):
        validate_identity(identity(other), jwks, "oaiapp_fixture", "expected")
    with pytest.raises(ValueError):
        validate_identity(
            jwt.encode({"nonce": "expected"}, "fake", algorithm="HS256"),
            jwks,
            "oaiapp_fixture",
            "expected",
        )


@pytest.mark.parametrize(
    "path",
    [
        "/callback?state=expected",
        "/auth/callback?state=other",
        "/auth/callback?state=expected&state=expected",
        "/auth/callback?code=secret",
        "/auth/callback?state=expected&code=" + "x" * 17000,
    ],
)
def test_callback_rejects_wrong_state_path_duplicates_and_oversized_input(path):
    with pytest.raises(ValueError):
        authorization_callback(path, "expected")


def test_declined_callback_still_requires_state_and_tokens_rotate_together():
    assert (
        authorization_callback("/auth/callback?state=expected&error=access_denied", "expected")[
            "error"
        ]
        == "access_denied"
    )
    previous = {"client_id": "oaiapp_fixture", "scopes": [PLAN_SCOPE], "refresh_token": "old"}
    updated = token_record(
        previous,
        {
            "access_token": "access",
            "refresh_token": "new",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )
    assert updated["refresh_token"] == "new" and updated["scopes"] == [PLAN_SCOPE]
    assert previous["refresh_token"] == "old"
    identity_only = token_record(
        previous,
        {
            "access_token": "access",
            "token_type": "Bearer",
            "expires_in": 3600,
            "scope": "openid email",
        },
    )
    assert PLAN_SCOPE not in identity_only["scopes"]
    with pytest.raises(ValueError):
        token_record(previous, {"access_token": "", "expires_in": 3600})


class MemoryRecords:
    def __init__(self, records):
        self.records = records

    def read(self, key):
        return dict(self.records.get(key, {}))

    def write(self, key, value):
        self.records[key] = dict(value)

    def account_keys(self):
        return tuple(self.records)

    @contextmanager
    def lock(self, key, *, check=None):
        if check:
            check()
        yield


def test_scope_denial_never_sends_inference_or_refresh(monkeypatch):
    store = MemoryRecords({"account": {"access_token": "identity-only", "scopes": ["openid"]}})
    service = ChatGPTConnections(store)  # type: ignore[arg-type]

    def unexpected(*args, **kwargs):
        raise AssertionError("Identity-only grant cannot make requests")

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", unexpected)
    with pytest.raises(ValueError, match="Enable ChatGPT plan"):
        service.access_token("account")


def test_refresh_serializes_rotation_and_keeps_client_mapping_on_expiration(monkeypatch):
    store = MemoryRecords(
        {
            "account": {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "client_id": "oaiapp_fixture",
                "scopes": [PLAN_SCOPE],
                "subject": "subject",
                "expires_at": 0,
            }
        }
    )
    service = ChatGPTConnections(store)  # type: ignore[arg-type]
    calls = []

    def refresh(client, method, url, **kwargs):
        calls.append(kwargs["data"])
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", refresh)
    assert service.access_token("account") == service.access_token("account") == "new-access"
    assert len(calls) == 1 and calls[0]["client_id"] == "oaiapp_fixture"
    assert store.read("account")["refresh_token"] == "new-refresh"
    store.records["account"]["expires_at"] = 0

    def expired(*args, **kwargs):
        raise SessionExpired("expired")

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", expired)
    with pytest.raises(SessionExpired):
        service.access_token("account")
    assert "access_token" not in store.read("account")
    assert store.read("account")["client_id"] == "oaiapp_fixture"


def test_temporary_refresh_failure_keeps_credentials(monkeypatch):
    initial = {
        "access_token": "old",
        "refresh_token": "keep",
        "client_id": "oaiapp_fixture",
        "scopes": [PLAN_SCOPE],
    }
    store = MemoryRecords({"account": initial.copy()})
    service = ChatGPTConnections(store)  # type: ignore[arg-type]

    def failed(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", failed)
    with pytest.raises(OSError):
        service.access_token("account")
    assert store.read("account") == initial


def test_account_model_catalog_preserves_provider_order_and_filters_visibility(monkeypatch):
    store = MemoryRecords(
        {
            "account": {
                "access_token": "fixture",
                "expires_at": time.time() + 600,
                "scopes": [PLAN_SCOPE],
            }
        }
    )
    service = ChatGPTConnections(store)  # type: ignore[arg-type]

    def models(*args, **kwargs):
        return {
            "models": [
                {"slug": "gpt-6.1-sol", "display_name": "Sol", "visibility": "list"},
                {"slug": "hidden", "display_name": "Hidden", "visibility": "hidden"},
                {"slug": "gpt-6-luna", "display_name": "Luna", "visibility": "list"},
            ]
        }

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", models)
    assert service.refresh_models("account") == (("gpt-6.1-sol", "Sol"), ("gpt-6-luna", "Luna"))


def test_dpapi_records_round_trip_without_plaintext_and_reject_tampering(tmp_path):
    store = ProtectedStore(tmp_path)
    key = "account-" + "f" * 32
    value = {"access_token": "fixture-secret-never-plaintext", "email": "fixture@example.invalid"}
    with store.lock(key):
        store.write(key, value)
        assert store.read(key) == value
    data = (tmp_path / (key + ".dat")).read_bytes()
    assert b"fixture-secret" not in data
    (tmp_path / (key + ".dat")).write_bytes(data[:-5] + b"wrong")
    with pytest.raises(OSError):
        store.read(key)
    with pytest.raises(ValueError):
        store.read("../escape")


@pytest.mark.windows
def test_native_loopback_sign_in_reuses_registration_and_validates_pkce(
    tmp_path, monkeypatch, signing
):
    private, jwks = signing
    service = ChatGPTConnections(ProtectedStore(tmp_path))
    authorizations, exchanges, senders = [], [], []
    cancelled = threading.Event()

    def open_browser(url):
        params = parse_qs(urlparse(url).query)
        port = urlparse(params["redirect_uri"][0]).port
        assert port is not None
        with socket.socket() as competing:
            competing.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                competing.bind(("127.0.0.1", port))
        authorizations.append(params)
        callback = (
            params["redirect_uri"][0]
            + "?"
            + urlencode(
                {"state": params["state"][0], "code": "fixture-code", "client_id": "oaiapp_fixture"}
            )
        )
        assert callback.startswith("http://127.0.0.1:")

        def send():
            with urlopen(callback, timeout=3) as response:
                assert response.status == 200

        sender = threading.Thread(target=send)
        sender.start()
        senders.append(sender)

    def request(client, method, url, **kwargs):
        if url.endswith("/oauth/token"):
            params, data = authorizations[-1], kwargs["data"]
            exchanges.append(data)
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(data["code_verifier"].encode()).digest())
                .decode()
                .rstrip("=")
            )
            assert challenge == params["code_challenge"][0]
            assert data["client_id"] == "oaiapp_fixture"
            return {
                "access_token": "fixture-access",
                "refresh_token": "fixture-refresh",
                "token_type": "Bearer",
                "expires_in": 3600,
                "scope": PLAN_SCOPE,
                "id_token": identity(private, nonce=params["nonce"][0]),
            }
        if url.endswith("jwks.json"):
            return jwks
        assert url.endswith("/models")
        return {"models": [{"slug": "gpt-6-luna", "display_name": "Luna", "visibility": "list"}]}

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", request)
    key = service.sign_in("", open_browser, cancelled)
    assert service.accounts()[0].enabled
    assert service.access_token(key) == "fixture-access"
    assert service.sign_in(key, open_browser, cancelled) == key
    assert authorizations[0]["client_id"] == ["dynamic_agent_client"]
    assert authorizations[1]["client_id"] == ["oaiapp_fixture"]
    assert authorizations[0]["ext_agent_host_id"] == authorizations[1]["ext_agent_host_id"]
    assert "id_token_hint" in authorizations[1]
    assert len(exchanges) == 2
    for sender in senders:
        sender.join(3)
        assert not sender.is_alive()


@pytest.mark.windows
def test_native_cancelled_sign_in_preserves_existing_connection(tmp_path):
    service = ChatGPTConnections(ProtectedStore(tmp_path))
    key = "account-" + "a" * 32
    previous = {"client_id": "oaiapp_fixture", "access_token": "fixture", "scopes": [PLAN_SCOPE]}
    service.store.write(key, previous)
    cancelled = threading.Event()
    with pytest.raises(ValueError, match="cancelled"):
        service.sign_in(key, lambda _: cancelled.set(), cancelled)
    assert service.store.read(key) == previous


def test_missing_auth_dependency_does_not_activate_account(monkeypatch):
    import builtins

    from jp_overlay.chatgpt_auth import require_sign_in_dependencies

    original = builtins.__import__

    def missing(name, *args, **kwargs):
        if name == "jwt":
            raise ImportError("missing optional auth in old runtime")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", missing)
    with pytest.raises(ValueError, match="Repair it"):
        require_sign_in_dependencies()


@pytest.mark.parametrize(
    "path",
    [
        "/auth/callback?state=%E6%97%A5",
        "/auth/callback?state=expected&iss=https://untrusted.invalid",
        "http://untrusted.invalid/auth/callback?state=expected",
        "/auth/callback?state=expected#fragment",
    ],
)
def test_callback_rejects_non_ascii_state_and_issuer_mixups(path):
    with pytest.raises(ValueError):
        authorization_callback(path, "expected")


@pytest.mark.parametrize(
    "changes",
    [
        {"access_token": "secret\r\nInjected: value"},
        {"access_token": "secret日"},
        {"token_type": 123},
        {"refresh_token": "secret with whitespace"},
    ],
)
def test_malformed_token_responses_fail_without_echoing_secret(changes):
    with pytest.raises(ValueError) as failure:
        token_record(
            {}, {"access_token": "good", "token_type": "Bearer", "expires_in": 100, **changes}
        )
    assert "secret" not in str(failure.value)


def test_sign_out_always_removes_tokens_even_when_revocation_breaks(monkeypatch):
    store = MemoryRecords(
        {
            "account": {
                "client_id": "oaiapp_fixture",
                "access_token": "secret-access",
                "refresh_token": "secret-refresh",
                "id_token": "secret-identity",
                "scopes": [PLAN_SCOPE],
            }
        }
    )
    service = ChatGPTConnections(store)  # type: ignore[arg-type]

    def broken(*args, **kwargs):
        raise TypeError("secret must never reach UI")

    monkeypatch.setattr("jp_overlay.chatgpt_auth._json_request", broken)
    message = service.sign_out("account")
    assert "locally" in message and "secret" not in message
    assert store.read("account") == {"client_id": "oaiapp_fixture"}


def test_protected_records_cannot_be_swapped_between_accounts_and_legacy_still_reads(tmp_path):
    from jp_overlay.protected_store import _protect

    store = ProtectedStore(tmp_path)
    a, b = "account-" + "a" * 32, "account-" + "b" * 32
    store.write(a, {"access_token": "fixture"})
    (tmp_path / (b + ".dat")).write_bytes((tmp_path / (a + ".dat")).read_bytes())
    with pytest.raises(ValueError, match="match this account"):
        store.read(b)
    (tmp_path / (b + ".dat")).write_bytes(_protect(b'{"access_token":"legacy"}'))
    assert store.read(b)["access_token"] == "legacy"
