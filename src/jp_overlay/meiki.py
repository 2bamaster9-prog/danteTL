"""The single compatibility boundary for pinned MeikiOCR 0.3.5.

Its constructor downloads models and exposes neither paths nor thread settings. We
initialize its three sessions explicitly, preserving its OCR algorithms. No global
monkeypatches, hub lookups, automatic downloads, or GPU dependency are needed.
"""

import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
from meikiocr import MeikiOCR

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.models import local_model_paths
from jp_overlay.recognition import TextCharacter, TextRegion


class _LocalMeiki(MeikiOCR):
    def __init__(self, paths: tuple[Path, ...], threads: int) -> None:
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        options.log_severity_level = 3
        sessions = [
            ort.InferenceSession(
                str(path), sess_options=options, providers=["CPUExecutionProvider"]
            )
            for path in paths
        ]
        self.det_session, self.rec_session, self.vrec_session = sessions
        self.active_provider = "CPUExecutionProvider"
        self.max_batch_size = 4
        self.detected: list[dict[str, Any]] = []

    def run_detection(self, image: Any, conf_threshold: float = 0.5) -> list[dict[str, Any]]:
        # Public run_ocr omits line bounds, including detections with no recognized chars.
        # Retain the detector's original boxes, in its original ordering.
        self.detected = super().run_detection(image, conf_threshold)
        return self.detected


def clipped_box(values: list[int], width: int, height: int) -> Rect:
    x1, y1, x2, y2 = values
    x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
    y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
    return Rect(x1, y1, max(0, x2 - x1), max(0, y2 - y1))


def convert_regions(
    detections: list[dict[str, Any]], results: list[dict[str, Any]], width: int, height: int
) -> tuple[TextRegion, ...]:
    regions = []
    for detected, result in zip(detections, results, strict=True):
        bounds = clipped_box(detected["bbox"], width, height)
        if min(bounds.size) <= 0:
            continue
        characters = []
        for char in result["chars"]:
            confidence = float(char["conf"])
            box = clipped_box(char["bbox"], width, height)
            if math.isfinite(confidence) and min(box.size) > 0:
                characters.append(TextCharacter(char["char"], box, min(1.0, max(0.0, confidence))))
        regions.append(
            TextRegion(result["text"], bounds, tuple(characters), bool(result["is_vertical"]))
        )
    return tuple(regions)


class MeikiRecognizer:
    def __init__(self, directory: Path, *, threads: int = 2) -> None:
        paths = local_model_paths(directory)  # Validate before initializing model sessions.
        if not 1 <= threads <= 8:
            raise ValueError("OCR CPU threads must be between 1 and 8.")
        cv2.setNumThreads(1)
        self._engine = _LocalMeiki(paths, threads)

    def recognize(self, frame: CapturedFrame) -> tuple[TextRegion, ...]:
        bgra = np.frombuffer(frame.bgra, dtype=np.uint8).reshape(frame.height, frame.width, 4)
        bgr = cv2.cvtColor(bgra, cv2.COLOR_BGRA2BGR)
        # Meiki scales detection internally and maps both box types back to this image.
        results = self._engine.run_ocr(bgr, det_threshold=0.5, rec_threshold=0.1)
        return convert_regions(self._engine.detected, results, frame.width, frame.height)
