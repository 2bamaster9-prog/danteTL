import hashlib

import pytest

from jp_overlay import app, gemma, model_store, ocr_runtime
from jp_overlay.models import ModelAsset


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    asset = ModelAsset("fixture", "pinned", "weights", hashlib.sha256(b"good").hexdigest(), 4)
    bundles = tuple(
        model_store.ModelBundle(key, key, tmp_path / key, (asset,), "")
        for key in ("ocr", "sugoi", "gemma")
    )
    monkeypatch.setattr(model_store, "model_catalog", lambda: bundles)
    return {bundle.key: bundle for bundle in bundles}


def test_fresh_cpu_distribution_keeps_downloaded_gemma_visible_with_setup_reason(
    catalog, monkeypatch
):
    monkeypatch.setattr(gemma, "installed_device", lambda: None)
    assert not app.translation_backends()
    for key in ("ocr", "gemma"):
        catalog[key].directory.mkdir()
        (catalog[key].directory / "weights").write_bytes(b"good")
    choices = app.translation_backends()
    assert len(choices) == 1 and "Gemma" in choices[0].name
    assert "runtime setup needed" in choices[0].name
    assert "Setup Gemma.cmd" in choices[0].unavailable_reason
    assert "not installed" in model_store.model_status(catalog["gemma"])
    assert not choices[0].preparation_id


@pytest.mark.parametrize("device", ["cuda", "vulkan"])
def test_available_runtime_makes_existing_weights_usable_without_download(
    catalog, monkeypatch, device
):
    catalog["gemma"].directory.mkdir()
    (catalog["gemma"].directory / "weights").write_bytes(b"good")
    monkeypatch.setattr(gemma, "installed_device", lambda: device)
    choice = app.translation_backends()[0]
    assert choice.key == f"gemma-{device}" and choice.preparation_id
    assert not choice.unavailable_reason
    assert "Runtime available" in model_store.model_status(catalog["gemma"])


def test_sugoi_needs_no_gemma_runtime_and_incomplete_models_stay_absent(catalog, monkeypatch):
    monkeypatch.setattr(gemma, "installed_device", lambda: None)
    for key, data in (("sugoi", b"good"), ("gemma", b"bad")):
        catalog[key].directory.mkdir()
        (catalog[key].directory / "weights").write_bytes(data)
    choices = app.translation_backends()
    assert len(choices) == 2 and all(choice.key.startswith("sugoi") for choice in choices)
    assert all(not choice.unavailable_reason for choice in choices)


def test_automatic_ocr_depends_on_runtime_not_downloaded_meiki(catalog, monkeypatch):
    catalog["ocr"].directory.mkdir()
    (catalog["ocr"].directory / "weights").write_bytes(b"good")
    monkeypatch.setattr(app, "gpu_runtime_installed", lambda name="onnxruntime-gpu": False)
    monkeypatch.setattr(ocr_runtime, "gpu_runtime_installed", lambda name="onnxruntime-gpu": False)
    assert len(app.ocr_backends()) == 1 and app.ocr_backends()[0].name.startswith("CPU")
    assert "Setup GPU OCR.cmd" in model_store.model_status(catalog["ocr"])
    monkeypatch.setattr(
        app, "gpu_runtime_installed", lambda name="onnxruntime-gpu": name == "onnxruntime-gpu"
    )
    assert app.ocr_backends()[0].name.startswith("Automatic")
