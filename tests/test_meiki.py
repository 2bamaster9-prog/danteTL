import hashlib
from dataclasses import replace

import pytest

from jp_overlay.domain import Rect
from jp_overlay.meiki import MeikiRecognizer, convert_regions
from jp_overlay.models import ModelAsset, validate_asset


def test_detection_boxes_remain_in_original_frame_pixels_and_empty_detections_survive() -> None:
    regions = convert_regions(
        [{"bbox": [100, 200, 500, 240]}, {"bbox": [-10, -10, 80, 100]}],
        [
            {
                "text": "日本",
                "is_vertical": False,
                "chars": [
                    {"char": "日", "bbox": [102, 201, 130, 239], "conf": 0.8},
                    {"char": "本", "bbox": [135, 201, 165, 239], "conf": 0.6},
                ],
            },
            {"text": "", "is_vertical": True, "chars": []},
        ],
        1920,
        1080,
    )
    assert regions[0].bounds == Rect(100, 200, 400, 40)
    assert regions[0].characters[1].bounds == Rect(135, 201, 30, 38)
    assert regions[0].confidence == pytest.approx(0.7)
    assert regions[1].bounds == Rect(0, 0, 80, 100)
    assert regions[1].confidence is None
    assert regions[1].vertical


def test_model_validation_detects_missing_incomplete_and_same_size_corruption(tmp_path) -> None:
    path = tmp_path / "test.onnx"
    asset = ModelAsset("repo", "revision", path.name, hashlib.sha256(b"good").hexdigest(), 4)
    with pytest.raises(RuntimeError, match="Missing or incomplete"):
        validate_asset(path, asset)
    path.write_bytes(b"bad")
    with pytest.raises(RuntimeError, match="Missing or incomplete"):
        validate_asset(path, asset)
    path.write_bytes(b"evil")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        validate_asset(path, asset)
    path.write_bytes(b"good")
    validate_asset(path, asset)
    with pytest.raises(RuntimeError):
        validate_asset(path, replace(asset, size=5))


def test_missing_models_never_invoke_upstream_downloader(tmp_path, monkeypatch) -> None:
    def unexpected_download(*args, **kwargs):
        pytest.fail("Runtime attempted a model download")

    monkeypatch.setattr("meikiocr.ocr.hf_hub_download", unexpected_download)
    with pytest.raises(RuntimeError, match="Setup OCR.cmd"):
        MeikiRecognizer(tmp_path)
