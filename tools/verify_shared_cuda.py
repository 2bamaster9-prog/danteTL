"""Verify real OCR/Gemma coexistence and loaded CUDA DLLs in both initialization orders.

Uses local weights, synthetic Japanese pixels and blocked Python sockets; never captures a game.
"""

import argparse
import ctypes
import json
import socket
from importlib.metadata import distributions
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from verify_ocr import EXPECTED, fixture

from jp_overlay.gemma import GemmaBackend
from jp_overlay.gemma import model_directory as gemma_directory
from jp_overlay.meiki import MeikiRecognizer
from jp_overlay.models import model_directory
from jp_overlay.ocr_runtime import CUDA


def loaded_libraries() -> dict[str, str]:
    api = ctypes.WinDLL("psapi", use_last_error=True)
    api.EnumProcessModules.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    )
    api.GetModuleFileNameExW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
    )
    modules = (ctypes.c_void_p * 2048)()
    needed = ctypes.c_ulong()
    process = ctypes.c_void_p(-1)  # Only our own process.
    if not api.EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    assert needed.value <= ctypes.sizeof(modules)
    paths = {}
    for module in modules[: needed.value // ctypes.sizeof(ctypes.c_void_p)]:
        buffer = ctypes.create_unicode_buffer(32768)
        if not api.GetModuleFileNameExW(process, module, buffer, len(buffer)):
            raise ctypes.WinError(ctypes.get_last_error())
        name = Path(buffer.value).name.lower()
        if name.startswith(
            ("cublas", "cudart", "cudnn", "ggml-cuda", "onnxruntime_providers_cuda")
        ):
            paths[name] = buffer.value
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order", choices=("ocr-first", "gemma-first"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packages = {d.metadata["Name"].lower(): d.version for d in distributions()}
    assert not any(name.startswith("nvidia-") and name.endswith("-cu12") for name in packages)
    assert "onnxruntime" not in packages and packages["onnxruntime-gpu"] == "1.30.0"
    app = QApplication([])
    frame = fixture()
    ocr = None
    translator = None
    answer = ""
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        try:
            for component in ("ocr", "gemma") if args.order == "ocr-first" else ("gemma", "ocr"):
                if component == "ocr":
                    ocr = MeikiRecognizer(model_directory(), device="cuda")
                    ocr.recognize(frame)
                else:
                    translator = GemmaBackend(gemma_directory(), device="cuda")
                    answer = translator.translate((EXPECTED[0],))[0]
            assert ocr and translator and ocr.provider == CUDA
            assert any("冒険" in region.text for region in ocr.recognize(frame))
            assert "adventure" in answer.lower()
            assert translator.translate(("設定",))[0].strip()
            libraries = loaded_libraries()
            assert "cublas64_13.dll" in libraries and "cudart64_13.dll" in libraries
            assert "cublas64_12.dll" not in libraries and "cudart64_12.dll" not in libraries
            result = {
                "order": args.order,
                "ocr_provider": ocr.provider,
                "translation": answer,
                "cuda12_packages": False,
                "libraries": libraries,
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result | {"libraries": sorted(libraries)}, indent=2))
        finally:
            if translator:
                translator.close()
            ocr = None  # ONNX sessions are owned by the adapter and released with it.
    app.quit()


if __name__ == "__main__":
    main()
