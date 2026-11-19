"""Pinned OCR assets. Runtime validates local files and never downloads anything."""

import os
from enum import StrEnum
from pathlib import Path

from dantejp import paths
from dantejp.languages.selection import DEFAULT_SOURCE, LATIN_SOURCES
from dantejp.languages.source import SourceLanguage
from dantejp.paths import is_standalone, state_root
from dantejp.runtime.assets import ModelAsset, asset_directory, validate_asset

ASSETS = (
    ModelAsset(
        "rtr46/meiki.text.detect.v0",
        "a9cffa4f60cbf72ddb87edf19c6f98a01cd042e6",
        "meiki.text.detect.v0.1.960x544.onnx",
        "40b6a016667745cae7d3055929ae3b8b1e7716aac795f5904cd3c2c7c3b8404b",
        14_503_825,
    ),
    ModelAsset(
        "rtr46/meiki.txt.recognition.v0",
        "a28cf5874dc2438ebb1c86336be26bcec51e3375",
        "meiki.text.rec.v0.960x32.onnx",
        "3e96bc772fbee9717e536a6353032bb944c3382dd2f6960ef4890decda43b000",
        18_593_254,
    ),
    ModelAsset(
        "rtr46/meiki.txt.recognition.v0",
        "a28cf5874dc2438ebb1c86336be26bcec51e3375",
        "meiki.text.rec.v0.vertical.32x480.onnx",
        "2c2a83a23bc3b7e6c63962175f507ecc6c5e85cc174f17bdec37d9bbd0bf895a",
        12_872_961,
    ),
)


def download_directory() -> Path:
    override = os.environ.get("DANTEJP_MODEL_DIR")
    return Path(override) if override else state_root() / "models" / "meiki"


def bundled_model_directory() -> Path | None:
    if is_standalone() and not os.environ.get("DANTEJP_MODEL_DIR"):
        return paths.resource_root() / "models" / "meiki"
    return None


def model_directory() -> Path:
    return asset_directory(download_directory(), ASSETS, bundled_model_directory())


def local_model_paths(directory: Path) -> tuple[Path, ...]:
    paths = tuple(directory / asset.filename for asset in ASSETS)
    for path, asset in zip(paths, ASSETS, strict=True):
        validate_asset(path, asset)
    return paths


class OcrModel(StrEnum):
    MEIKI = "MeikiOCR"
    PADDLE_LATIN = "PaddleOCR Latin"


_SOURCE_MODELS = {
    DEFAULT_SOURCE.code: OcrModel.MEIKI,
    **{source.code: OcrModel.PADDLE_LATIN for source in LATIN_SOURCES},
}


def ocr_model_for(language: SourceLanguage) -> OcrModel:
    return _SOURCE_MODELS[language.code]


PADDLE_ASSETS = (
    ModelAsset(
        "PaddlePaddle/PP-OCRv5_mobile_det_onnx",
        "e6f4fa85f00e168c862bc462aebca69eef9b3d3d",
        "det.onnx",
        "a431985659dc921974177a95adcfbb90fd9e51989a5e04d70d0b75f597b6e61d",
        4_826_518,
        "inference.onnx",
    ),
    ModelAsset(
        "PaddlePaddle/latin_PP-OCRv5_mobile_rec_onnx",
        "89d3a50e2c27e2e7cceeab0e944c25c807d5db4f",
        "rec.onnx",
        "7888113072263cb471b93f66dd5e2ad70548dc526fa1ace760d0d973dd121498",
        8_042_023,
        "inference.onnx",
    ),
)


def paddle_download_directory() -> Path:
    override = os.environ.get("DANTEJP_PADDLE_MODEL_DIR")
    return Path(override) if override else state_root() / "models" / "paddle-latin-v5"


def bundled_paddle_directory() -> Path | None:
    if is_standalone() and not os.environ.get("DANTEJP_PADDLE_MODEL_DIR"):
        return paths.resource_root() / "models" / "paddle-latin-v5"
    return None


def paddle_directory() -> Path:
    return asset_directory(paddle_download_directory(), PADDLE_ASSETS, bundled_paddle_directory())
