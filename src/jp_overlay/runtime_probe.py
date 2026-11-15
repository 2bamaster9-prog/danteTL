"""Fresh-process library check, without model downloads or first-use model preparation."""

import argparse
import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def verify(profile: str) -> None:
    if profile not in ("cpu", "nvidia", "amd"):
        raise ValueError("Unknown runtime profile.")
    installed = []
    for name in ("onnxruntime", "onnxruntime-gpu", "onnxruntime-directml"):
        try:
            version(name)
            installed.append(name)
        except PackageNotFoundError:
            pass
    expected = "onnxruntime-gpu" if profile == "nvidia" else "onnxruntime"
    if installed != [expected]:
        raise RuntimeError(f"Expected only {expected}; found {installed}.")
    # Verify the same native imports used at app startup, in this throwaway process.
    import ctranslate2  # noqa: F401
    import meikiocr  # noqa: F401
    import onnxruntime as ort
    import windows_capture  # noqa: F401
    from PySide6 import QtWidgets  # noqa: F401

    if profile == "nvidia":
        from jp_overlay.ocr_runtime import CUDA, prepare_cuda

        prepare_cuda(ort)
        if CUDA not in ort.get_available_providers():
            raise RuntimeError("The installed OCR runtime does not provide CUDA.")
    from jp_overlay.llama_runtime import installed_device, load_runtime

    device = {"nvidia": "cuda", "amd": "vulkan", "cpu": "cpu"}[profile]
    if installed_device() != device:
        raise RuntimeError(f"The installed language-model engine does not provide {device}.")
    runtime = load_runtime(device)
    runtime.llama_backend_init()
    try:
        if device != "cpu" and not runtime.llama_supports_gpu_offload():
            raise RuntimeError(
                "GPU offload is unavailable. Update your graphics driver or use CPU."
            )
    finally:
        runtime.llama_backend_free()
    print("Library checks passed. Model preparation happens after restart.", flush=True)


def verify_ocr(image_path: Path) -> dict[str, object]:
    """Offline diagnostic against an explicit synthetic fixture, with no font dependency."""
    from unittest.mock import patch

    from PySide6.QtGui import QImage

    from jp_overlay.domain import CapturedFrame, Rect, WindowGeometry
    from jp_overlay.meiki import MeikiRecognizer
    from jp_overlay.models import model_directory

    image = QImage(str(image_path)).convertToFormat(QImage.Format.Format_RGB32)
    if image.isNull() or image.width() != 1920 or image.height() != 1080:
        raise ValueError("Expected the 1920x1080 OCR verification fixture")
    expected = "新しい冒険が、ここから始まる。"
    bounds = Rect(0, 0, image.width(), image.height())
    frame = CapturedFrame(
        1, 0.0, WindowGeometry(bounds, bounds, bounds, 96), bytes(image.constBits())
    )
    with patch("socket.socket", side_effect=RuntimeError("Diagnostic must remain offline")):
        recognizer = MeikiRecognizer(model_directory(), device="cpu")
        rows = recognizer.recognize(frame)
        provider = recognizer.provider
        recognizer.close()
    text = "".join(row.text for row in rows)
    if expected not in text:
        raise RuntimeError(f"OCR diagnostic did not recognize the fixture: {text}")
    return {"provider": provider, "text": text, "models": str(model_directory())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", choices=("cpu", "nvidia", "amd"))
    parser.add_argument("--application-only", action="store_true", help="Check app import only")
    parser.add_argument(
        "--ocr-image", type=Path, help="Check CPU OCR against the synthetic fixture"
    )
    parser.add_argument("--report", type=Path, help="Write results for a windowed executable")
    args = parser.parse_args()
    if not args.application_only:
        verify(args.profile)
    result: dict[str, object] = {"profile": args.profile}
    if not args.application_only:
        result["libraries"] = "passed"
    from jp_overlay.paths import resource_root, state_root

    result["application"] = {
        "module": __file__,
        "version": version("jp-overlay"),
        "resources": str(resource_root()),
        "state": str(state_root()),
    }
    if args.ocr_image:
        result["ocr"] = verify_ocr(args.ocr_image)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
