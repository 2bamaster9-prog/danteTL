"""Offline accuracy gate for cost-aware scans, with real CPU/strict CUDA inference."""

import argparse
import json
import socket
from dataclasses import asdict, replace
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any
from unittest.mock import patch

import shiboken6
from PySide6.QtWidgets import QApplication
from region_corpus import CASES, Case, accuracy, fixture

from dantejp.domain import union_bounds
from dantejp.ocr.meiki import MeikiRecognizer
from dantejp.ocr.models import model_directory
from dantejp.ocr.scan_plan import ScanLine, ScanPlanner, choose_scan
from dantejp.ocr.worker import recognize_planned, recognize_regions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--case", action="append", help="Restrict measurement to named corpus cases."
    )
    args = parser.parse_args()
    if not 2 <= args.repeats <= 20:
        parser.error("Use 2..20 measured repetitions.")
    app = QApplication([])
    cases = [(c, c) for c in CASES]
    base = Case("seed")
    cases.extend(
        (
            (replace(base, name="edited", phrases=("私は彼を信じていない。",) * 4), base),
            (replace(base, name="font_shrink", font=14), base),
            (replace(base, name="removal", blank=True), base),
            (replace(base, name="arrival"), replace(base, blank=True)),
            (replace(base, name="shift", offset=(12, 12)), base),
            (replace(base, name="polarity_change", light=True), base),
            (replace(base, name="contrast_drop", light=True, faint=True), base),
        )
    )
    if args.case:
        unknown = set(args.case) - {case.name for case, _ in cases}
        if unknown:
            parser.error(f"Unknown cases: {', '.join(sorted(unknown))}")
        cases = [(case, prior) for case, prior in cases if case.name in args.case]
    reports: list[dict[str, Any]] = []
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        engine = MeikiRecognizer(model_directory(), device=args.device)
        # Use the shipped adapter profile, never tune costs per fixture or use
        # target annotations to choose a scan.
        costs = engine.scan_costs
        assert costs is not None
        detected: list[float] = []
        recognized: list[float] = []
        detection = engine._engine.run_detection
        recognition = engine._engine._run_recognition_inference

        def detect(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            result = detection(*args, **kwargs)
            detected.append((perf_counter() - start) * 1000)
            return result

        def recognize(*args: Any, **kwargs: Any) -> Any:
            start = perf_counter()
            result = recognition(*args, **kwargs)
            recognized.append((perf_counter() - start) * 1000)
            return result

        try:
            assert args.device != "cuda" or engine.provider == "CUDAExecutionProvider"
            with (
                patch.object(engine._engine, "run_detection", detect),
                patch.object(engine._engine, "_run_recognition_inference", recognize),
            ):
                for case, prior in cases:
                    frame, areas, targets = fixture(case)
                    seed, _, _ = fixture(prior)
                    prior_rows = engine.recognize(seed)
                    lines = tuple(
                        ScanLine(r.bounds, r.confidence, r.vertical)
                        for r in prior_rows
                        if r.text.strip()
                    )
                    start = perf_counter()
                    plan = choose_scan(areas, frame.geometry.client.size, lines, costs)
                    planning_ms = (perf_counter() - start) * 1000
                    planner = ScanPlanner()
                    cold = planner.plan(areas, frame.geometry.client.size, 0, costs)
                    assert not cold.changed
                    planner.observe(lines, None, cold)
                    plans = {
                        "baseline": areas,
                        "paired": (union_bounds(areas[:2]), union_bounds(areas[2:])),
                        "merged": (union_bounds(areas),),
                        "full": None,
                        "selected_raw": plan.areas,
                        "selected": plan.areas,
                    }
                    samples: dict[str, list[dict[str, Any]]] = {name: [] for name in plans}
                    for trial in range(args.repeats + 1):
                        order = list(plans)
                        turn = trial % len(order)
                        order = order[turn:] + order[:turn]
                        for name in order:
                            detected.clear()
                            recognized.clear()
                            start = perf_counter()
                            active = (
                                planner.plan(areas, frame.geometry.client.size, 0, costs)
                                if name == "selected"
                                else plan
                            )
                            rejected = False
                            if name == "selected":
                                rows, coverage, rejected = recognize_planned(engine, frame, active)
                            else:
                                rows, coverage = recognize_regions(engine, frame, plans[name])
                            if name == "selected":
                                planner.observe(
                                    tuple(
                                        ScanLine(r.bounds, r.confidence, r.vertical)
                                        for r in rows
                                        if r.text.strip()
                                    ),
                                    coverage,
                                    active,
                                    rejected=rejected,
                                )
                            elapsed = (perf_counter() - start) * 1000
                            samples[name].append(
                                dict(
                                    ms=elapsed,
                                    plan=asdict(active) if name == "selected" else None,
                                    retried=rejected,
                                    detector_ms=sum(detected),
                                    detector_calls=len(detected),
                                    recognition_ms=sum(recognized),
                                    recognition_batches=len(recognized),
                                    coverage=None
                                    if coverage is None
                                    else [asdict(b) for b in coverage],
                                    covers_demand=coverage is None
                                    or all(any(c.contains(a) for c in coverage) for a in areas),
                                    accuracy=accuracy(targets, rows),
                                    regions=[asdict(r) for r in rows],
                                )
                            )
                    summaries = {
                        name: dict(
                            median_ms=median(r["ms"] for r in runs[1:]),
                            worst_ms=max(r["ms"] for r in runs[1:]),
                            detector_calls=[r["detector_calls"] for r in runs[1:]],
                            recognition_batches=[r["recognition_batches"] for r in runs[1:]],
                            trials=runs,
                        )
                        for name, runs in samples.items()
                    }
                    regressions = []
                    for index, (old, new) in enumerate(
                        zip(samples["baseline"], samples["selected"], strict=True)
                    ):
                        for target, (a, b) in enumerate(
                            zip(old["accuracy"]["targets"], new["accuracy"]["targets"], strict=True)
                        ):
                            if b["errors"] > a["errors"]:
                                regressions.append(
                                    dict(trial=index, target=target, before=a, after=b)
                                )
                        if new["accuracy"]["extra_regions"] > old["accuracy"]["extra_regions"]:
                            regressions.append(dict(trial=index, unexpected_blank_text=True))
                        if not new["covers_demand"]:
                            regressions.append(dict(trial=index, lost_coverage=True))
                    reports.append(
                        dict(
                            case=case.name,
                            fixture=asdict(case),
                            seed=asdict(prior),
                            seed_regions=[asdict(r) for r in prior_rows],
                            targets=[asdict(t) for t in targets],
                            plan=asdict(plan),
                            changed=plan.changed,
                            planning_ms=planning_ms,
                            regressions=regressions,
                            results=summaries,
                        )
                    )
                    before, after = (summaries[n]["median_ms"] for n in ("baseline", "selected"))
                    print(
                        f"{case.name}: changed={plan.changed}, {before:.1f} -> {after:.1f} ms, "
                        f"regressions={len(regressions)}",
                        flush=True,
                    )
        finally:
            engine.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    failed = [r["case"] for r in reports if r["regressions"]]
    args.output.write_text(
        json.dumps(
            dict(
                device=args.device,
                costs=asdict(costs),
                cases=reports,
                gate_passed=not failed,
                failed_cases=failed,
            ),
            ensure_ascii=False,
            indent=2,
        ),
        "utf-8",
    )
    shiboken6.delete(app)
    if failed:
        raise SystemExit("Accuracy/coverage gate failed: " + ", ".join(failed))


if __name__ == "__main__":
    main()
