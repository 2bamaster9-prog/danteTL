import hashlib

import pytest

from jp_overlay import llama_runtime, model_store, ocr_runtime
from jp_overlay import model_factories as app
from jp_overlay.models import ModelAsset


def test_recommended_catalog_and_backend_order_do_not_mix_recognition(tmp_path, monkeypatch):
    from dataclasses import replace

    bundles = tuple(
        replace(b, directory=tmp_path / b.key, assets=(), bundled_directory=None)
        for b in model_store.model_catalog()
    )
    assert bundles[0].key == model_store.RECOMMENDED_TRANSLATION == "gemma"
    assert [b.key for b in bundles if b.category == "recognition"] == ["ocr"]
    monkeypatch.setattr(model_store, "model_catalog", lambda: bundles)
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: "cpu")
    monkeypatch.setattr(llama_runtime, "supports_plamo", lambda: True)
    choices = app.translation_backends()
    assert choices[0].preference_key == "gemma" and "Recommended" in choices[0].name
    assert all(c.preference_key != "ocr" for c in choices)
    assert {"gemma", "gemma-e4b", "qwen35-4b", "plamo-0.8b"} <= {c.preference_key for c in choices}
    assert not any("sugoi" in b.key for b in bundles)
    assert not any("sugoi" in c.preference_key for c in choices)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    asset = ModelAsset("fixture", "pinned", "weights", hashlib.sha256(b"good").hexdigest(), 4)
    bundles = tuple(
        model_store.ModelBundle(key, key, tmp_path / key, (asset,), "", language_model=key != "ocr")
        for key in ("ocr", "gemma", "gemma-e4b", "qwen35-4b")
    )
    monkeypatch.setattr(model_store, "model_catalog", lambda: bundles)
    return {bundle.key: bundle for bundle in bundles}


def test_missing_engine_keeps_downloaded_gemma_visible_with_setup_reason(catalog, monkeypatch):
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: None)
    assert not app.translation_backends()
    for key in ("ocr", "gemma"):
        catalog[key].directory.mkdir()
        (catalog[key].directory / "weights").write_bytes(b"good")
    choices = app.translation_backends()
    assert len(choices) == 1 and "Gemma" in choices[0].name
    assert "runtime setup needed" in choices[0].name
    assert "Acceleration" in choices[0].unavailable_reason
    assert "not installed" in model_store.model_status(catalog["gemma"])
    assert not choices[0].preparation_id


@pytest.mark.parametrize("device", ["cpu", "cuda", "vulkan"])
def test_available_runtime_makes_existing_weights_usable_without_download(
    catalog, monkeypatch, device
):
    catalog["gemma"].directory.mkdir()
    (catalog["gemma"].directory / "weights").write_bytes(b"good")
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: device)
    choice = app.translation_backends()[0]
    assert choice.key == f"gemma-{device}" and choice.preparation_id
    assert not choice.unavailable_reason
    assert bool(choice.performance_notice) == (device == "cpu")
    if device == "cpu":
        assert "CPU" in choice.name and "GPU" not in choice.name
    assert "Runtime available" in model_store.model_status(catalog["gemma"])


def test_incomplete_models_stay_absent(catalog, monkeypatch):
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: None)
    catalog["gemma"].directory.mkdir()
    (catalog["gemma"].directory / "weights").write_bytes(b"bad")
    assert not app.translation_backends()


def test_retired_files_are_preserved_but_never_discovered(tmp_path, monkeypatch):
    from jp_overlay import paths

    monkeypatch.setattr(paths, "state_root", lambda: tmp_path)
    legacy = tmp_path / "models" / "sugoi-v4"
    legacy.mkdir(parents=True)
    files = [legacy / name for name in ("model.bin", "config.json", "spm.ja.nopretok.model")]
    for file in files:
        file.write_bytes(b"user-owned model")
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: None)
    assert not any("sugoi" in b.key for b in model_store.model_catalog())
    assert not any("sugoi" in c.preference_key for c in app.translation_backends())
    assert all(file.read_bytes() == b"user-owned model" for file in files)


def test_automatic_ocr_depends_on_runtime_not_downloaded_meiki(catalog, monkeypatch):
    catalog["ocr"].directory.mkdir()
    (catalog["ocr"].directory / "weights").write_bytes(b"good")
    monkeypatch.setattr(app, "gpu_runtime_installed", lambda name="onnxruntime-gpu": False)
    monkeypatch.setattr(ocr_runtime, "gpu_runtime_installed", lambda name="onnxruntime-gpu": False)
    assert len(app.ocr_backends()) == 1 and app.ocr_backends()[0].name.startswith("CPU")
    assert "Acceleration" in model_store.model_status(catalog["ocr"])
    monkeypatch.setattr(
        app, "gpu_runtime_installed", lambda name="onnxruntime-gpu": name == "onnxruntime-gpu"
    )
    assert app.ocr_backends()[0].name.startswith("Automatic")


@pytest.mark.parametrize("device", [None, "cpu", "cuda", "vulkan"])
def test_curated_choices_keep_identity_across_runtime_changes(catalog, monkeypatch, device):
    from jp_overlay.preferences import decode_preferences

    monkeypatch.setattr(llama_runtime, "installed_device", lambda: device)
    for key in ("gemma", "gemma-e4b", "qwen35-4b"):
        catalog[key].directory.mkdir()
        (catalog[key].directory / "weights").write_bytes(b"good")
    choices = app.translation_backends()
    assert {b.preference_key for b in choices} == {"gemma", "gemma-e4b", "qwen35-4b"}
    for choice in choices:
        assert bool(choice.unavailable_reason) == (device is None)
        assert bool(choice.preparation_id) == (device is not None)
        saved = decode_preferences(
            {
                "version": 1,
                "model": choice.preference_key,
                "setup_model": choice.preference_key,
            }
        )
        assert saved.model == saved.setup_model == choice.preference_key


@pytest.mark.parametrize("supported", [False, True])
def test_downloaded_plamo_stays_visible_but_old_engine_needs_update(
    tmp_path, monkeypatch, supported
):
    from dataclasses import replace

    from jp_overlay.curated_models import MODELS

    models = []
    for definition in MODELS:
        if not definition.key.startswith("plamo-"):
            continue
        bundle = replace(
            definition.bundle(),
            directory=tmp_path / definition.key,
            assets=(ModelAsset("fixture", "pin", "weights", "hash", 4),),
        )
        bundle.directory.mkdir()
        (bundle.directory / "weights").write_bytes(b"good")
        models.append(bundle)
    monkeypatch.setattr(model_store, "model_catalog", lambda: tuple(models))
    monkeypatch.setattr(llama_runtime, "installed_device", lambda: "cpu")
    monkeypatch.setattr(llama_runtime, "supports_plamo", lambda: supported)
    choices = app.translation_backends()
    assert {c.selection_id for c in choices} == {"plamo-2b", "plamo-0.8b"}
    for choice in choices:
        assert bool(choice.preparation_id) is supported
        assert bool(choice.unavailable_reason) is not supported
        from jp_overlay.preferences import decode_preferences

        saved = decode_preferences(
            {"version": 1, "model": choice.preference_key, "setup_model": choice.preference_key}
        )
        assert saved.model == saved.setup_model == choice.preference_key
    for bundle in models:
        assert ("predates" in model_store.model_status(bundle)) is not supported
