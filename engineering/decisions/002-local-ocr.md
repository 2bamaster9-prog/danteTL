# 002 — Local MeikiOCR and frame-matched inspection

Status: accepted, 2026-11-13.

The user requested MeikiOCR and a way to inspect Japanese recognition before translation.
Use MeikiOCR 0.3.5 with ONNX Runtime CPU by default. No CUDA toolkit, GPU runtime, server, or
translation model is needed. This keeps installation simple and leaves the game GPU available.
GPU acceleration and more OCR backends require evidence from real workloads.

Meiki's constructor automatically downloads models and has no path/session-options injection.
The adapter initializes its three known session attributes explicitly in a small subclass, then
uses the upstream recognition pipeline. This is version-coupled: pin Meiki and verify the adapter
with actual models when upgrading. Capture detector boxes through its public `run_detection`
override, preserving even boxes whose text is empty. Do not globally monkeypatch third-party code.

The three models total 45,970,040 bytes (43.84 MiB). Pin repository revisions and SHA-256 hashes in
`models.py`, validate on loading, and keep network downloads in the explicit setup tool. That tool
uses temporary files and only replaces a destination after validation. Repeated setup verifies
existing assets. Runtime neither calls the upstream constructor nor queries Hugging Face.

Meiki requests `opencv-python-headless`; Windows Capture requests `opencv-python`. Both install
the same `cv2` package. Use the latter once and exclude the former with uv, recording this exception
in pyproject.toml. Use the documented uv setup; a generic `pip install .` does not apply uv exclusions.

Display completed OCR on its source frame, with matching numbered rows, character boxes, zoom,
copying, and pause. Keep raw recognized text, including punctuation mistakes. On-game boxes are
diagnostics with bounded lag, not persistent tracks. Confidence is a character-score summary,
not a calibrated sentence-correctness probability. This exposes errors before adding translation.

References:
- [Pinned Meiki package](https://pypi.org/project/meikiocr/0.3.5/)
- [Meiki implementation](https://github.com/rtr46/meikiocr/blob/main/meikiocr/ocr.py)
- [Detection model revision](https://huggingface.co/rtr46/meiki.text.detect.v0/tree/a9cffa4f60cbf72ddb87edf19c6f98a01cd042e6)
- [Recognition model revision](https://huggingface.co/rtr46/meiki.txt.recognition.v0/tree/a28cf5874dc2438ebb1c86336be26bcec51e3375)
- [uv dependency exclusion](https://docs.astral.sh/uv/reference/settings/#exclude-dependencies)
