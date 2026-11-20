"""Explicit local model comparison; isolated children, no app/catalog/preferences changes.

Run with python -m tools.benchmark_translation --help. Candidate downloads are a separate action.
"""

import argparse
import hashlib
import json
import math
import os
import random
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from dantetl.runtime.assets import ModelAsset, validate_asset
from dantetl.runtime.model_store import ModelBundle, install_model
from dantetl.runtime.setup_process import run_setup_command
from dantetl.runtime.setup_values import ModelProgress
from dantetl.translation.backend import ContextualBackend, RequestRejected, TranslationBackend
from dantetl.translation.dialogue.context import DialogueTurn
from tools.benchmark_profiles import SpecialistBackend

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "engineering/benchmarks"
MODEL_ROOT = ROOT / "artifacts/translation-benchmark/models"
BASELINES = ("gemma-e4b", "gemma", "qwen35-4b")


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    source: str
    reference: str
    note: str
    context: tuple[DialogueTurn, ...] = ()


def cases(path: Path) -> tuple[Case, ...]:
    if path.stat().st_size > 512_000:
        raise ValueError("Corpus exceeds 512 KB.")
    data = json.loads(path.read_text("utf-8"))
    if data["version"] != 1 or not 1 <= len(data["cases"]) <= 200:
        raise ValueError("Unsupported corpus version/size.")
    result: list[Case] = []
    for entry in data["cases"]:
        entry = dict(entry)
        context = tuple(DialogueTurn(**t) for t in entry.pop("context", []))
        if len(context) > 2 or sum(len(t.source) + len(t.english) for t in context) > 512:
            raise ValueError("Reference history exceeds app bounds.")
        case = Case(**entry, context=context)
        if not re.fullmatch(r"[a-z0-9-]{1,80}", case.id) or not 1 <= len(case.source) <= 512:
            raise ValueError("Invalid case ID/source.")
        if context:
            result.append(
                replace(case, id=case.id + "-without", category="context-control", context=())
            )
        result.append(case)
    if len({c.id for c in result}) != len(result):
        raise ValueError("Duplicate corpus ID.")
    return tuple(result)


def candidates() -> dict[str, Any]:
    return json.loads((DATA / "translation-models.json").read_text("utf-8"))


def candidate_asset(key: str) -> ModelAsset:
    spec = dict(candidates()[key])
    spec.pop("profile")
    return ModelAsset(**spec)


def percentile(values: list[float], fraction: float) -> float:
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    good = [r for r in rows if not r.get("error")]
    times = [r["ms"] for r in good]
    return {
        "requests": len(rows),
        "rejected": len(rows) - len(good),
        "median_ms": round(statistics.median(times), 1) if times else None,
        "p95_ms": round(percentile(times, 0.95), 1) if times else None,
        "by_category": {
            category: round(
                statistics.median([r["ms"] for r in good if r["category"] == category]), 1
            )
            for category in sorted({r["category"] for r in good})
        },
    }


def gpu_snapshot() -> str:
    try:
        return subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.used,utilization.gpu", "--format=csv,noheader"],
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def load_backend(key: str, device: str) -> TranslationBackend:
    if key in candidates():
        asset = candidate_asset(key)
        path = MODEL_ROOT / key / asset.filename
        validate_asset(path, asset, None)
        return SpecialistBackend(path, candidates()[key]["profile"], device)
    if key == "gemma":
        from dantetl.translation.backends.gemma import GemmaBackend, model_directory

        return GemmaBackend(model_directory(), device=device)
    from dantetl.translation.backends.gguf import GgufBackend
    from dantetl.translation.models.curated import MODELS
    from dantetl.translation.models.gguf import describe

    model = next(m for m in MODELS if m.key == key)
    for asset in model.assets:
        validate_asset(model.bundle().directory / asset.filename, asset, None)
    registration = describe(
        model.bundle().directory / model.assets[0].filename,
        model.profile,
        lambda _: None,
        threading.Event(),
    )
    return GgufBackend(registration, device=device, verbose=True)


def child(args: argparse.Namespace) -> None:
    from dantetl.runtime.llama import installed_device
    from tools.verify_translation import process_memory

    if installed_device() != args.device:
        raise RuntimeError("Wrong runtime; CPU fallback is not a GPU measurement.")
    fixture = list(cases(args.corpus))
    if args.limit:
        fixture = fixture[: args.limit]
    report: dict[str, Any] = {
        "model": args.model,
        "device": args.device,
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "profiles_sha256": hashlib.sha256(
            (ROOT / "tools/benchmark_profiles.py").read_bytes()
        ).hexdigest(),
        "provenance": "Original fixtures, not a validated game-quality benchmark.",
        "memory_note": "Process snapshots; GPU numbers are whole-device totals, not process VRAM.",
        "network": "Python socket connections blocked; local native files only, no service.",
        "gpu_before": gpu_snapshot(),
        "process_before": process_memory(),
        "rows": [],
    }
    if args.model in candidates():
        report["weights"] = candidates()[args.model]
    engine = None

    def save() -> None:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")

    try:
        with patch.object(socket.socket, "connect", side_effect=RuntimeError("Offline inference")):
            start = time.perf_counter()
            engine = load_backend(args.model, args.device)
            engine.translate(("準備ができました。",))
            report["load_and_warm_ms"] = round((time.perf_counter() - start) * 1000, 1)
            report["backend_identity"] = engine.cache_identity
            report["process_loaded"] = process_memory()
            report["gpu_loaded"] = gpu_snapshot()
            report["context_supported"] = isinstance(engine, ContextualBackend)
            save()
            for repeat in range(args.repeats):
                order = fixture.copy()
                random.Random(42 + repeat).shuffle(order)
                for case in order:
                    row: dict[str, Any] = {
                        "id": case.id,
                        "category": case.category,
                        "repeat": repeat,
                        "source": case.source,
                        "reference": case.reference,
                        "note": case.note,
                        "context": [
                            {"source": t.source, "english": t.english} for t in case.context
                        ],
                    }
                    start = time.perf_counter()
                    try:
                        row["english"] = (
                            engine.translate_with_context(case.source, case.context)
                            if isinstance(engine, ContextualBackend)
                            else engine.translate((case.source,))[0]
                        )
                    except RequestRejected as error:
                        row["error"] = str(error)
                    row["ms"] = round((time.perf_counter() - start) * 1000, 2)
                    if isinstance(engine, SpecialistBackend):
                        row["prompt"] = engine.last_prompt
                        row["usage"] = engine.last_usage
                    report["rows"].append(row)
                    report["summary"] = summarize(report["rows"])
                    save()
                    print(f"BENCH {args.model} {repeat + 1} {case.id} {row['ms']} ms", flush=True)
            report["process_finished"] = process_memory()
            report["gpu_finished"] = gpu_snapshot()
            report["complete"] = True
    except Exception as error:
        report["fatal_error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if engine is not None:
            engine.close()
        save()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=(*BASELINES, *candidates()),
        default=["gemma-e4b", "plamo-2b", "cat-3.3b"],
    )
    parser.add_argument("--device", choices=("cpu", "cuda", "vulkan"), default="cpu")
    parser.add_argument("--corpus", type=Path, default=DATA / "japanese-game-text.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    parser.add_argument(
        "--limit", type=int, default=0, help="Optional initial compatibility subset"
    )
    parser.add_argument(
        "--download", action="store_true", help="Only download/verify selected candidates"
    )
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--model", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("Limit must be nonnegative.")
    if args.child:
        child(args)
        return
    args.output.mkdir(parents=True, exist_ok=True)
    cancel = threading.Event()
    if args.download:
        for key in args.models:
            if key not in candidates():
                parser.error("Use the existing app model downloader for baselines.")
            previous = ""

            def progress(value: ModelProgress, key: str = key) -> None:
                nonlocal previous
                message = f"{key}: {value.message} {value.received * 100 // max(1, value.total)}%"
                if message != previous:
                    print(message, flush=True)
                    previous = message

            install_model(
                ModelBundle(key, key, MODEL_ROOT / key, (candidate_asset(key),), ""),
                progress,
                cancel,
            )
        return
    cases(args.corpus)  # Validate before launching or loading any native code.
    for key in args.models:
        output = (args.output / f"{key}.json").resolve()
        if output.exists():
            raise ValueError(
                f"Refusing to overwrite evidence: {output}. Choose a fresh output folder."
            )
        log = args.output / f"{key}.log"
        layers = 0
        with log.open("w", encoding="utf-8") as stream:

            def line(value: str) -> None:
                nonlocal layers
                match = re.search(r"offloaded (\d+)/(\d+) layers", value)
                if match:
                    layers = int(match[1])
                stream.write(value + "\n")
                stream.flush()
                if value.startswith("BENCH ") or "error" in value.lower():
                    print(value, flush=True)

            environment = dict(os.environ)
            environment["PYTHONUTF8"] = "1"
            environment.setdefault("CUDA_CACHE_PATH", str(ROOT / "data/cuda-cache"))
            try:
                run_setup_command(
                    [
                        sys.executable,
                        "-m",
                        "tools.benchmark_translation",
                        "--child",
                        "--model",
                        key,
                        "--device",
                        args.device,
                        "--corpus",
                        str(args.corpus.resolve()),
                        "--output",
                        str(output),
                        "--repeats",
                        str(args.repeats),
                        "--limit",
                        str(args.limit),
                    ],
                    ROOT,
                    environment,
                    cancel,
                    line,
                    timeout=1200,
                )
                data = json.loads(output.read_text("utf-8"))
                data["offloaded_layers"] = layers
                # E2B's unchanged production adapter suppresses native logs. Its result is
                # explicitly unverified here; E4B/candidates have strict layer evidence.
                data["gpu_offload_verified"] = bool(layers)
                if args.device != "cpu" and key != "gemma" and not layers:
                    data["complete"] = False
                    data["fatal_error"] = "No actual GPU offload observed."
                output.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
                print(key, data.get("summary"), data.get("fatal_error", ""), flush=True)
            except Exception as error:
                print(f"FAILED {key}: {error}", flush=True)
                data = json.loads(output.read_text("utf-8")) if output.exists() else {"model": key}
                data["complete"] = False
                data.setdefault("fatal_error", str(error))
                output.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
