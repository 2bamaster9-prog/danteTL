"""PLaMo compatibility/quality experiment using an explicit, newer standalone CPU CLI.

Different runtime and one fresh process per request: timings are NOT warm app measurements.
No server, dependency replacement, app registration or implicit downloads.
"""

import argparse
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

from dantetl.runtime.assets import validate_asset
from dantetl.runtime.owned_process import OwnedProcess
from dantetl.runtime.setup_process import run_setup_command
from tools.benchmark_profiles import specialist_prompt
from tools.benchmark_translation import DATA, MODEL_ROOT, ROOT, candidate_asset, cases, summarize
from tools.verify_translation import process_memory


def memory_probe(command: list[str]) -> dict[str, float]:
    """Read only our owned CLI PID. One sampled process, not a sustained app-memory budget."""
    process = OwnedProcess(command, ROOT, dict(os.environ))
    peak: dict[str, float] = {}
    deadline = time.monotonic() + 90
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("CLI memory probe timed out.")
            try:
                snapshot = process_memory(process.pid)
            except OSError:
                if process.poll() is not None:
                    break
                raise
            for key, value in snapshot.items():
                peak[key] = max(peak.get(key, 0), value)
            time.sleep(0.02)
        if process.returncode or not peak:
            raise RuntimeError("CLI memory probe did not finish successfully.")
        return peak
    finally:
        process.close()


def parse_completion(lines: list[str]) -> tuple[str, float]:
    """Require the native EOS marker and native timing, never score truncated output."""
    generating = False
    body = []
    elapsed = None
    for line in lines:
        if " I generate: n_ctx =" in line:
            generating = True
            continue
        match = re.search(r"common_perf_print:\s+total time\s*=\s*([\d.]+) ms", line)
        if match:
            elapsed = float(match[1])
        if generating and not re.match(r"^\d[\d.]+ [A-Z]", line):
            body.append(line)
    text = "\n".join(body).strip()
    if not text.endswith("[end of text]") or elapsed is None:
        raise ValueError("CLI did not confirm EOS and inference timing; review the native log.")
    text = text.removesuffix("[end of text]").strip()
    if not text or "<|plamo:" in text or len(text) > 4096:
        raise ValueError("Empty/control/oversized CLI answer.")
    return text, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True, help="Verified llama-completion.exe")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=("plamo-2b", "plamo-0.8b"),
        default=["plamo-2b", "plamo-0.8b"],
    )
    parser.add_argument("--corpus", type=Path, default=DATA / "japanese-game-text.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("Limit must be nonnegative.")
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = cases(args.corpus)
    if args.limit:
        fixture = fixture[: args.limit]
    cancel = threading.Event()
    for key in args.models:
        asset = candidate_asset(key)
        model = MODEL_ROOT / key / asset.filename
        validate_asset(model, asset, None)
        output = args.output / f"{key}.json"
        if output.exists():
            raise ValueError("Choose a fresh output directory; never overwrite evidence.")
        report = {
            "model": key,
            "device": "cpu",
            "runtime": str(args.runtime.resolve()),
            "runtime_exe_sha256": hashlib.sha256(args.runtime.read_bytes()).hexdigest(),
            "weights_sha256": asset.sha256,
            "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
            "timing_mode": (
                "New CPU CLI process per request. Native prompt+decode timing excludes load. "
                "Not warm app latency."
            ),
            "rows": [],
        }
        last_command: list[str] | None = None
        for case in fixture:
            prompt = args.output / f"{key}-{case.id}.prompt.txt"
            prompt.write_text(specialist_prompt("plamo", case.source, case.context), "utf-8")
            lines: list[str] = []
            command = [
                str(args.runtime.resolve()),
                "-m",
                str(model),
                "-f",
                str(prompt.resolve()),
                "-ngl",
                "0",
                "-t",
                "4",
                "-tb",
                "4",
                "-c",
                "2048",
                "-b",
                "128",
                "-ub",
                "128",
                "-n",
                "384",
                "--temp",
                "0",
                "--repeat-penalty",
                "1",
                "--seed",
                "42",
                "--no-display-prompt",
                "--no-conversation",
                "--simple-io",
                "-r",
                "<|plamo:tag|>,<|plamo:bos|>",
            ]
            last_command = command
            row = {
                "id": case.id,
                "category": case.category,
                "repeat": 0,
                "source": case.source,
                "reference": case.reference,
                "note": case.note,
                "context": [{"source": t.source, "english": t.english} for t in case.context],
            }
            start = time.perf_counter()
            try:
                run_setup_command(command, ROOT, dict(os.environ), cancel, lines.append, timeout=90)
                answer, elapsed = parse_completion(lines)
                row.update(english=answer, ms=elapsed)
            except Exception as error:
                row.update(error=str(error), ms=0)
            row["wall_with_load_ms"] = round((time.perf_counter() - start) * 1000, 1)
            report["rows"].append(row)
            report["summary"] = summarize(report["rows"])
            (args.output / f"{key}-{case.id}.log").write_text("\n".join(lines), "utf-8")
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
            print(key, case.id, row.get("ms"), row.get("error", ""), flush=True)
        assert last_command is not None
        report["process_memory_probe"] = memory_probe(last_command)
        report["complete"] = True
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
