import hashlib
from dataclasses import replace

import pytest

from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
from jp_overlay.meiki import MeikiRecognizer, convert_regions
from jp_overlay.models import ModelAsset, validate_asset
from jp_overlay.ocr_runtime import CPU, CUDA


@pytest.mark.parametrize("provider", [CPU, CUDA])
@pytest.mark.parametrize("vertical", [False, True])
def test_partial_gpu_batches_keep_a_fixed_shape_and_never_emit_padded_detections(
    monkeypatch, provider, vertical
):
    import numpy as np
    from meikiocr import MeikiOCR

    from jp_overlay.meiki import _LocalMeiki

    seen = []

    def run(self, batch, is_vertical):
        seen.append((batch.shape, is_vertical))
        return [np.arange(len(batch)), np.ones((len(batch), 2, 4)), np.ones((len(batch), 2))]

    monkeypatch.setattr(MeikiOCR, "_run_recognition_inference", run)
    engine = object.__new__(_LocalMeiki)
    engine.active_provider, engine.max_batch_size = provider, 4
    h, w = (480, 32) if vertical else (32, 960)
    for count in (4, 1, 3, 4, 1):
        outputs = engine._run_recognition_inference(np.ones((count, 3, h, w), np.float32), vertical)
        assert all(len(output) == count for output in outputs)
        assert outputs[0].tolist() == list(range(count))
    assert [shape[0] for shape, _ in seen] == ([4] * 5 if provider == CUDA else [4, 1, 3, 4, 1])
    assert all(flag == vertical for _, flag in seen)


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


@pytest.mark.parametrize("fail_on_run", [False, True])
def test_auto_gpu_failure_falls_back_once_and_reports_the_actual_provider(
    tmp_path, monkeypatch, fail_on_run
) -> None:
    monkeypatch.setattr("jp_overlay.meiki.local_model_paths", lambda path: ())
    created = []

    class Engine:
        def __init__(self, paths, threads, provider):
            created.append(provider)
            if provider == CUDA and not fail_on_run:
                raise RuntimeError("GPU unavailable")
            self.active_provider, self.detected = provider, []

        def run_ocr(self, image, **kwargs):
            if self.active_provider == CUDA:
                raise RuntimeError()  # Even an exception with no message must fall back.
            return []

    monkeypatch.setattr("jp_overlay.meiki._LocalMeiki", Engine)
    recognizer = MeikiRecognizer(tmp_path, device="auto")
    box = Rect(0, 0, 2, 2)
    frame = CapturedFrame(1, 0, WindowGeometry(box, box, box, 96), bytes(16))
    assert recognizer.recognize(frame) == ()
    assert recognizer.recognize(frame) == ()
    assert created == [CUDA, CPU]
    assert recognizer.provider == CPU and "using CPU" in recognizer.message


def test_explicit_cpu_never_initializes_gpu_and_strict_cuda_never_silently_falls_back(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr("jp_overlay.meiki.local_model_paths", lambda path: ())
    created = []

    class Engine:
        def __init__(self, paths, threads, provider):
            created.append(provider)
            self.active_provider = provider
            if provider == CUDA:
                raise RuntimeError("GPU unavailable")

    monkeypatch.setattr("jp_overlay.meiki._LocalMeiki", Engine)
    assert MeikiRecognizer(tmp_path, device="cpu").provider == CPU
    with pytest.raises(RuntimeError, match="GPU unavailable"):
        MeikiRecognizer(tmp_path, device="cuda")
    assert created == [CPU, CUDA]
