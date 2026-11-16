"""Explicit compatibility tests in an owned child process; no network or registry mutations."""

import json
import os
import re
import sys
import tempfile
import threading
import time
from dataclasses import asdict
from pathlib import Path

from dantejp.paths import module_command, state_root
from dantejp.runtime.model_store import Cancelled
from dantejp.runtime.setup_process import run_setup_command
from dantejp.runtime.setup_values import ModelProgress, Progress
from dantejp.translation.models.gguf import describe
from dantejp.translation.models.values import ImportedModel
from dantejp.translation.models.values import ProbeResult as ProbeResult


class ImportTest:
    def __init__(self, path: Path, profile: str, device: str, gate: threading.Event) -> None:
        self.path, self.profile, self.device, self.gate = path, profile, device, gate
        self.result: ProbeResult | None = None

    def run(self, progress: Progress, cancel: threading.Event) -> None:
        model = describe(self.path, self.profile, progress, cancel)
        progress(ModelProgress("Waiting for the previous translation model to unload…"))
        deadline = time.monotonic() + 180
        while not self.gate.wait(0.1):
            if cancel.is_set():
                raise Cancelled()
            if time.monotonic() >= deadline:
                raise RuntimeError("Previous model is still busy. Stop capture and retry.")
        if cancel.is_set():
            raise Cancelled()
        root = state_root() / "data/import-probes"
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as directory:
            spec, result = Path(directory) / "model.json", Path(directory) / "result.json"
            spec.write_text(json.dumps(asdict(model)), "utf-8")
            progress(
                ModelProgress(f"Testing on {self.device.upper()}… First GPU use may take a minute.")
            )
            offloaded = 0

            def report(line: str) -> None:
                nonlocal offloaded
                match = re.search(r"offloaded (\d+)/(\d+) layers", line)
                if match:
                    offloaded = int(match[1])

            run_setup_command(
                module_command(
                    Path(sys.executable),
                    "dantejp.translation.models.probe",
                    str(spec),
                    str(result),
                    self.device,
                ),
                state_root(),
                dict(os.environ),
                cancel,
                report,
                timeout=180,
            )
            if result.stat().st_size > 32_768:
                raise ValueError("Oversized compatibility result.")
            data = json.loads(result.read_text("utf-8"))
            if self.device != "cpu" and not offloaded:
                raise RuntimeError(
                    "No GPU layers were observed. Select the CPU runtime or check acceleration."
                )
            self.result = ProbeResult(
                model,
                self.device,
                tuple(tuple(row) for row in data["samples"]),
                data["load_ms"],
                offloaded,
            )
        progress(
            ModelProgress("Local test completed. Review the translations before adding the model.")
        )


def main() -> None:
    import socket
    from unittest.mock import patch

    from dantejp.translation.backends.gguf import GgufBackend
    from dantejp.translation.dialogue.context import DialogueTurn

    spec, output, device = sys.argv[1:]
    model = ImportedModel(**json.loads(Path(spec).read_text("utf-8")))
    with patch.object(
        socket.socket, "connect", side_effect=RuntimeError("Probe must stay offline")
    ):
        start = time.monotonic()
        engine = GgufBackend(model, device=device, verbose=True)
        load_ms = (time.monotonic() - start) * 1000
        try:
            samples = []
            for source, context in (
                ("設定", ()),
                ("先に行って。ここは私が何とかするから。", ()),
                ("リナが待っている。先に行こう。", (DialogueTurn("私はリナ。", "I'm Rina."),)),
            ):
                start = time.monotonic()
                answer = engine.translate_with_context(source, context)
                samples.append((source, answer, round((time.monotonic() - start) * 1000)))
            Path(output).write_text(json.dumps({"samples": samples, "load_ms": load_ms}), "utf-8")
        finally:
            engine.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # The standalone bootstrap shows startup errors in a native message box.
        # Probe failures belong to the parent UI, never an unattended child modal.
        print(f"Model compatibility test failed: {error}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None
