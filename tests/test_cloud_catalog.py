import json
import threading
from dataclasses import replace

import httpx2
import pytest

from dantejp.translation.cloud.catalog import CatalogCache, CatalogModel, fetch_models
from dantejp.translation.cloud.profiles import CloudProfile, CloudProfiles
from dantejp.translation.cloud.protocol import decoding_identity, request_body


@pytest.mark.parametrize("provider", ["openai", "deepseek", "gemini", "claude"])
def test_discovery_is_authenticated_metadata_only_and_accepts_new_models(provider):
    requests = []

    def handle(request):
        requests.append(request)
        row = {"id": "future-text-model"}
        if provider == "gemini":
            row = {
                "name": "models/future-text-model",
                "version": "002",
                "supportedGenerationMethods": ["generateContent"],
                "thinking": False,
            }
        return httpx2.Response(200, json={"models" if provider == "gemini" else "data": [row]})

    models = fetch_models(
        provider, "private-key", threading.Event(), transport=httpx2.MockTransport(handle)
    )
    assert len(models) == 1 and models[0].model == "future-text-model"
    profile = models[0].profile(provider)
    assert profile.decoding != "preset"
    assert len(requests) == 1 and requests[0].method == "GET" and not requests[0].content
    assert "private-key" in requests[0].headers.get(
        "authorization", requests[0].headers.get("x-goog-api-key", "")
    )
    assert "private-key" not in str(requests[0].url)
    body = request_body(profile, "Game", ("会心率", ()))
    if provider == "gemini":
        config = body["generationConfig"]
        assert isinstance(config, dict) and "thinkingConfig" not in config
        assert profile.model_revision == "002"
    elif provider == "claude":
        assert "thinking" not in body and "output_config" not in body
    else:
        assert "thinking" not in body and "reasoning_effort" not in body


@pytest.mark.parametrize("provider", ["gemini", "claude"])
def test_pagination_uses_fixed_origin_and_caps_repeated_tokens(provider):
    requests = []

    def handle(request):
        requests.append(request)
        row = {"id": "model-" + str(len(requests))}
        if provider == "gemini":
            row = {"name": "models/" + row["id"], "supportedGenerationMethods": ["generateContent"]}
        value: dict[str, object] = {"models" if provider == "gemini" else "data": [row]}
        if len(requests) == 1:
            value.update(
                {"nextPageToken": "https://evil.invalid/secret"}
                if provider == "gemini"
                else {"has_more": True, "last_id": "https://evil.invalid/secret"}
            )
        return httpx2.Response(200, json=value)

    result = fetch_models(
        provider, "fixture-key", threading.Event(), transport=httpx2.MockTransport(handle)
    )
    assert len(result) == 2
    assert requests[0].url.host == requests[1].url.host
    assert "evil.invalid" in str(requests[1].url.params)
    count = 0

    def repeat(request):
        nonlocal count
        count += 1
        return httpx2.Response(
            200,
            json={
                "models": [],
                "data": [],
                "has_more": True,
                "last_id": "again",
                "nextPageToken": "again",
            },
        )

    with pytest.raises(ValueError, match="pagination"):
        fetch_models(provider, "key", threading.Event(), transport=httpx2.MockTransport(repeat))
    assert count == 2


def test_filters_non_text_models_and_uses_claude_capabilities():
    def fetch(provider, rows):
        return fetch_models(
            provider,
            "key",
            threading.Event(),
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(
                    200, json={"models" if provider == "gemini" else "data": rows}
                )
            ),
        )

    assert [
        m.model for m in fetch("openai", [{"id": "text-embedding-3"}, {"id": "future-chat"}])
    ] == ["future-chat"]
    assert not fetch(
        "gemini", [{"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}]
    )
    assert not fetch("deepseek", [{"id": "image", "output_modalities": ["image"]}])
    model = fetch(
        "claude",
        [
            {
                "id": "future-claude",
                "lifecycle": "deprecated",
                "capabilities": {
                    "thinking": {"types": {"disabled": {"supported": True}}},
                    "effort": {"low": {"supported": True}},
                },
            }
        ],
    )[0]
    assert model.decoding == "claude-disabled-low" and model.lifecycle == "deprecated"
    body = request_body(model.profile("claude"), "", ("設定", ()))
    assert body["thinking"] == {"type": "disabled"}
    assert body["output_config"] == {"effort": "low"}


def test_refresh_errors_cancellation_bounds_and_secret_redaction(tmp_path):
    cache = CatalogCache(tmp_path)
    key = "api-" + "a" * 32
    old = (CatalogModel("old-model", "Old"),)
    cache.write("openai", key, old)

    def broken(_):
        raise ValueError("Authorization: PRIVATE-SECRET")

    for handle in (
        broken,
        lambda _: httpx2.Response(401, text="PRIVATE-SECRET"),
        lambda _: httpx2.Response(302, headers={"Location": "https://evil.invalid"}),
        lambda _: httpx2.Response(200, content=b"x" * 262145),
        lambda _: httpx2.Response(200, json={"data": [{"id": f"m{i}"} for i in range(513)]}),
    ):
        with pytest.raises(ValueError) as error:
            fetch_models(
                "openai",
                "PRIVATE-SECRET",
                threading.Event(),
                transport=httpx2.MockTransport(handle),
            )
        assert "PRIVATE-SECRET" not in str(error.value)
        assert cache.read("openai", key) == old
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(ValueError, match="cancelled"):
        fetch_models(
            "openai",
            "key",
            cancelled,
            transport=httpx2.MockTransport(lambda _: pytest.fail("network after cancel")),
        )
    assert cache.read("openai", key) == old


def test_catalog_and_saved_profile_survive_offline_without_leaking_or_crossing_accounts(tmp_path):
    cache = CatalogCache(tmp_path / "catalogs")
    a, b = "api-" + "a" * 32, "api-" + "b" * 32
    entry = CatalogModel("future-model", "Future model", revision="002")
    cache.write("gemini", a, (entry,))
    assert cache.read("gemini", a) == (entry,)
    assert cache.read("openai", a) is None and cache.read("gemini", b) is None
    cache.write("gemini", b, ())
    assert cache.read("gemini", b) == ()
    store = CloudProfiles(tmp_path / "profiles.json")
    profile = replace(entry.profile("gemini"), credential=a)
    store.write((profile,))
    assert store.read() == (profile,)
    assert decoding_identity(profile) != decoding_identity(replace(profile, model_revision="003"))
    assert "secret" not in json.dumps(json.loads(store.path.read_text()))
    (cache.root / (a + ".json")).write_text("broken", encoding="utf-8")
    assert cache.read("gemini", a) is None
    with pytest.raises(ValueError):
        cache.write("gemini", "../escape", ())
    # Existing saved presets keep their decoding contract and cache identity.
    preset = CloudProfile.new("openai")
    assert request_body(preset, "", ("設定", ()))["reasoning_effort"] == "none"
