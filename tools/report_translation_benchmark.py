"""Build an auditable comparison and a shuffled, anonymous wording review from local results."""

import argparse
import json
import random
from pathlib import Path
from typing import Any


def cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def primary_results(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Prefer warm GPU wording; use separate CLI evidence only for unsupported models."""
    hashes = {r["corpus_sha256"] for r in reports if r.get("rows")}
    if len(hashes) != 1:
        raise ValueError("Reports must use the same corpus.")
    selected: dict[str, dict[str, Any]] = {}
    for report in reports:
        if not report.get("complete") or not report.get("rows"):
            continue
        key = report["model"]
        if key not in selected or report["device"] == "cuda":
            selected[key] = report
    sets = [{r["id"] for r in report["rows"]} for report in selected.values()]
    if not sets or any(s != sets[0] for s in sets):
        raise ValueError("Completed comparisons must contain the same case IDs.")
    return selected


def render(reports: list[dict[str, Any]], output: Path) -> None:
    selected = primary_results(reports)
    output.mkdir(parents=True, exist_ok=True)
    named = [
        "# Local translation experiment",
        "",
        "Original game-style fixtures; references are review aids. No automatic quality score.",
        "Timing excludes OCR and overlay latency. PLaMo's CLI processes use a different runtime;",
        "their native prompt/decode times exclude load and are not warm app latency.",
        "RAM is a loaded-process snapshot for embedded models and one sampled peak for the CLI.",
        "",
        "| Model | Mode | Requests | Rejected | Median ms | p95 ms | RAM working/private MiB |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for report in reports:
        summary = report.get("summary", {})
        memory = report.get("process_loaded", report.get("process_memory_probe", {}))
        mode = "CPU CLI, fresh process" if "timing_mode" in report else report.get("device", "?")
        if not report.get("complete"):
            mode += " INCOMPLETE"
        named.append(
            "| "
            + " | ".join(
                cell(v)
                for v in (
                    report["model"],
                    mode,
                    summary.get("requests", 0),
                    summary.get("rejected", 0),
                    summary.get("median_ms", "—"),
                    summary.get("p95_ms", "—"),
                    f"{memory.get('working_set_mib', '—')} / {memory.get('private_mib', '—')}",
                )
            )
            + " |"
        )
    named += [
        "",
        "Only complete runs are included in wording comparisons. First-pass answers follow;",
        "raw JSON retains every repeat, exact prompts for specialists, and errors.",
    ]
    blind = [
        "# Anonymous wording review",
        "",
        "Review meaning, omissions, numbers, names and tone.",
        "Each case shuffles models independently. A reference is one possible translation,",
        "not the only acceptable wording. Record a preferred letter or a tie and your reason.",
        "Model identities are in the separate model-key.json; this file contains no timings.",
    ]
    key_map = {}
    rows = {
        key: {r["id"]: r for r in reversed(report["rows"]) if r["repeat"] == 0}
        for key, report in selected.items()
    }
    first = next(iter(rows.values()))
    for index, (case_id, case) in enumerate(sorted(first.items())):
        heading = ["", f"## {case_id}", "", case["source"], ""]
        if case.get("context"):
            heading += [
                "Reference history: " + cell(json.dumps(case["context"], ensure_ascii=False)),
                "",
            ]
        heading += ["Review aid: " + cell(case["reference"]), "", "Check: " + case["note"], ""]
        named.extend(heading)
        blind.extend(heading)
        named += ["| Model | Translation |", "|---|---|"]
        blind += ["| Option | Translation |", "|---|---|"]
        order = sorted(selected)
        random.Random(71 + index).shuffle(order)
        key_map[case_id] = {}
        for i, model in enumerate(order):
            row = rows[model][case_id]
            answer = row.get("english", "REJECTED: " + row.get("error", "unknown"))
            label = chr(65 + i)
            key_map[case_id][label] = model
            named.append(f"| {cell(model)} | {cell(answer)} |")
            blind.append(f"| {label} | {cell(answer)} |")
    (output / "comparison.md").write_text("\n".join(named) + "\n", "utf-8")
    (output / "blind-review.md").write_text("\n".join(blind) + "\n", "utf-8")
    (output / "model-key.json").write_text(json.dumps(key_map, indent=2), "utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directories", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reports = [
        json.loads(path.read_text("utf-8"))
        for directory in args.directories
        for path in sorted(directory.glob("*.json"))
    ]
    render(reports, args.output)


if __name__ == "__main__":
    main()
