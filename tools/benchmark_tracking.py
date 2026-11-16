"""Completed dense OCR replay; reports worker evidence and serialized tracking separately.

Optional --baseline loads a trusted local tracking.py for exact policy comparison.
No models, capture, network, UI, or persistent application state.
"""

import argparse
import importlib.util
import json
import statistics
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.presence import prepare_evidence
from dantejp.ocr.tracking import TextTracker, prepare_matching
from dantejp.ocr.values import OcrResult, TextRegion


def observations(length: int, repeats: int):
    size = Rect(0, 0, 3840, 2160)
    geometry = WindowGeometry(size, size, size, 96)
    pixels = bytes((20, 20, 20, 255)) * (size.width * size.height)
    empty = bytes(len(pixels))
    rows = tuple(
        TextRegion(
            ("表示されている文章を確認してください。" * 12)[:length] + str(i),
            Rect(20 + (i % 4) * 950, 20 + (i // 4) * 60, 850, 30),
        )
        for i in range(128)
    )
    for seq in range(1, repeats + 1):
        phase = seq % 12
        current = rows
        if phase in (3, 4):
            current = tuple(
                replace(r, text=r.text + "次", bounds=replace(r.bounds, width=860)) for r in rows
            )
        elif phase in (5, 6, 7, 8):
            current = rows[::2]  # Same-pixel negative observations must retain text.
        elif phase in (9, 10):
            current = ()  # Changed pixels plus completed negative observations.
        source = CapturedFrame(seq, seq * 0.3, geometry, empty if phase in (9, 10) else pixels)
        yield OcrResult(
            source,
            tuple(reversed(current)) if seq % 2 else current,
            900,
            source.captured_at + 0.9,
            (Rect(0, 0, 1900, 2160),) if phase == 8 else None,
        )


def replay(length, repeats, baseline):
    tracker = TextTracker()
    old = baseline.TextTracker() if baseline else None
    tracking, evidence_times, before = [], [], []
    for result in observations(length, repeats):
        started = time.perf_counter()
        evidence = prepare_evidence(result, tracker.evidence_bounds())
        matching = prepare_matching(result, tracker.matching_sources(result.frame))
        evidence_times.append((time.perf_counter() - started) * 1000)
        started = time.perf_counter()
        ids = tracker.observe(result, pixel_evidence=evidence, matching=matching)
        visible = tracker.visible(result.frame, result.completed_at)
        ready = tracker.translation_tracks(result.frame, result.completed_at)
        tracking.append((time.perf_counter() - started) * 1000)
        if old:
            started = time.perf_counter()
            old_ids = old.observe(result)
            old_visible = old.visible(result.frame, result.completed_at)
            old_ready = old.translation_tracks(result.frame, result.completed_at)
            before.append((time.perf_counter() - started) * 1000)
            assert ids == old_ids, (length, result.frame.sequence, "assignment mismatch")
            assert [asdict(t) for t in visible] == [asdict(t) for t in old_visible]
            assert [asdict(t) for t in ready] == [asdict(t) for t in old_ready]

    def timings(values):
        values = sorted(values[1:])
        return {
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[int((len(values) - 1) * 0.95)], 3),
            "max_ms": round(max(values), 3),
        }

    return {
        "characters": length,
        "completed_observations": repeats,
        "tracking": timings(tracking),
        "worker_evidence": timings(evidence_times),
        "baseline": timings(before) if before else None,
        "equivalent": bool(old),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--repeats", type=int, default=60)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.repeats < 12:
        parser.error("Use at least 12 observations to cover the complete replay.")
    baseline = None
    if args.baseline:
        spec = importlib.util.spec_from_file_location("tracking_baseline", args.baseline)
        assert spec and spec.loader
        baseline = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = baseline
        spec.loader.exec_module(baseline)
    report = {
        "fixture": "4K, 128 regions, edits, reordering, misses, removals and partial coverage",
        "cases": [replay(length, args.repeats, baseline) for length in (12, 120, 240)],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
