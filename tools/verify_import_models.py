"""Run explicit local GGUF compatibility checks without registering/downloading any model."""

import argparse
import json
import threading
from dataclasses import asdict
from pathlib import Path

from dantetl.runtime.llama import installed_device
from dantetl.translation.models.probe import ImportTest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", type=Path)
    parser.add_argument("--device", choices=("cpu", "cuda", "vulkan"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert installed_device() == args.device, "Unexpected engine; no silent fallback"
    gate = threading.Event()
    gate.set()
    reports = []
    for path in args.models:
        print(f"Testing {path.name} on {args.device}", flush=True)
        test = ImportTest(path, "auto", args.device, gate)
        test.run(lambda _: None, threading.Event())
        assert test.result
        reports.append(asdict(test.result))
        print(json.dumps(reports[-1], ensure_ascii=True), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(reports, indent=2), "utf-8")


if __name__ == "__main__":
    main()
