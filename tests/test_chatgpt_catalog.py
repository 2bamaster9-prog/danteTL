"""Catalog HTTP limits, recovery and cancellation with synthetic responses only."""

import asyncio
import gzip
import json
import time

import httpx2
import pytest

from dantejp.translation.cloud.auth_work import AUTH_RESPONSE_LIMIT, AuthInterrupted, AuthWork
from dantejp.translation.cloud.chatgpt_auth import (
    MODEL_CATALOG_RESPONSE_LIMIT,
    PLAN_SCOPE,
    ChatGPTConnections,
)
from dantejp.translation.cloud.protected_store import ProtectedStore


class Body(httpx2.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.closed = False

    async def __aiter__(self):
        for start in range(0, len(self.data), 8192):
            yield self.data[start : start + 8192]

    async def aclose(self):
        self.closed = True


@pytest.fixture
def saved(tmp_path):
    service = ChatGPTConnections(ProtectedStore(tmp_path / "accounts"))
    key = "account-" + "a" * 32
    service.store.write(
        key,
        {
            "access_token": "fixture-access",
            "refresh_token": "fixture-refresh",
            "client_id": "oaiapp_fixture",
            "expires_at": time.time() + 600,
            "scopes": [PLAN_SCOPE],
            "models": [["previous", "Previous"]],
        },
    )
    return service, key


@pytest.mark.parametrize("compressed", [False, True])
def test_large_catalog_keeps_visible_models_in_order_and_persists_only_picker_fields(
    saved, compressed
):
    service, key = saved
    before = service.store.read(key)
    rows = [
        {"slug": "fixture-fast", "display_name": "Fast", "visibility": "list"},
        {"slug": "fixture-hidden", "display_name": "Hidden", "visibility": "hidden"},
        {"slug": "fixture-quality", "display_name": "Quality", "visibility": "list"},
    ]
    for row in rows:
        row["metadata"] = "catalog metadata " * 32_768
    payload = json.dumps({"models": rows}).encode()
    assert AUTH_RESPONSE_LIMIT < len(payload) < MODEL_CATALOG_RESPONSE_LIMIT
    body = Body(gzip.compress(payload) if compressed else payload)

    def respond(request):
        assert request.url.path == "/v1/models"
        return httpx2.Response(
            200, stream=body, headers={"Content-Encoding": "gzip"} if compressed else {}
        )

    result = service.refresh_models(key, AuthWork(transport=httpx2.MockTransport(respond)))
    assert result == (("fixture-fast", "Fast"), ("fixture-quality", "Quality"))
    assert body.closed
    after = service.store.read(key)
    assert {k: v for k, v in after.items() if k != "models"} == {
        k: v for k, v in before.items() if k != "models"
    }
    assert after["models"] == [list(row) for row in result]
    assert "metadata" not in json.dumps(after)


@pytest.mark.parametrize("compressed", [False, True])
def test_oversized_catalog_still_fails_without_replacing_account_or_saved_models(saved, compressed):
    service, key = saved
    before = service.store.read(key)
    payload = b" " * (MODEL_CATALOG_RESPONSE_LIMIT + 1)
    body = Body(gzip.compress(payload) if compressed else payload)
    transport = httpx2.MockTransport(
        lambda _: httpx2.Response(
            200, stream=body, headers={"Content-Encoding": "gzip"} if compressed else {}
        )
    )
    with pytest.raises(AuthInterrupted, match="4,096 KiB"):
        service.refresh_models(key, AuthWork(transport=transport))
    assert body.closed and service.store.read(key) == before


def test_token_refresh_keeps_smaller_limit_even_when_called_by_catalog_refresh(saved):
    service, key = saved
    record = service.store.read(key)
    record["expires_at"] = 0
    service.store.write(key, record)
    body = Body(b" " * (AUTH_RESPONSE_LIMIT + 1))

    def respond(request):
        assert request.url.path == "/api/accounts/oauth/token"  # No catalog request follows.
        return httpx2.Response(200, stream=body)

    with pytest.raises(AuthInterrupted, match="128 KiB"):
        service.refresh_models(key, AuthWork(transport=httpx2.MockTransport(respond)))
    assert body.closed and service.store.read(key) == record


@pytest.mark.parametrize("cancel", [False, True])
def test_larger_catalog_budget_does_not_weaken_deadline_or_cancellation(saved, cancel):
    service, key = saved
    before = service.store.read(key)
    work = AuthWork(deadline=time.monotonic() + (3 if cancel else 0.15))
    closed = []

    class SlowBody(httpx2.AsyncByteStream):
        async def __aiter__(self):
            yield b" "
            if cancel:
                work.cancelled.set()
            while True:
                await asyncio.sleep(0.01)
                yield b" "  # Below per-chunk timeout; total deadline must still stop this.

        async def aclose(self):
            closed.append(True)

    work.transport = httpx2.MockTransport(lambda _: httpx2.Response(200, stream=SlowBody()))
    with pytest.raises(AuthInterrupted, match="cancelled" if cancel else "timed out"):
        service.refresh_models(key, work)
    assert closed and service.store.read(key) == before
