"""Bounded HTTP file transfer in an owned child; the caller verifies and publishes it."""

import json
import os
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen

from dantejp.paths import module_command, resource_root
from dantejp.runtime.owned_process import restore_child_output
from dantejp.runtime.setup_process import clean_runtime_environment, run_setup_command

DOWNLOAD_TIMEOUT = 1800.0


def download_file(
    url: str,
    destination: Path,
    limit: int,
    progress: Callable[[int, int], None],
    cancel: threading.Event,
) -> None:
    """Return only after network resources are gone, including on cancel/timeout.

    Socket inactivity timeouts cannot bound trickling headers/body or blocking DNS.
    The existing process owner can terminate every phase without abandoning a thread.
    Only the caller's disposable .part file is written; no destination is published here.
    """
    environment = clean_runtime_environment(os.environ)
    environment["PYTHONUTF8"] = "1"
    # The running app may be the immutable AppData wheel rather than site-packages.
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    command = module_command(
        Path(sys.executable), __name__, url, str(destination.resolve()), str(limit)
    )

    def report(line: str) -> None:
        # The child emits bounded byte counters; setup_command retains errors separately.
        if line.startswith("{"):
            value = json.loads(line)
            progress(value["received"], value["total"])

    run_setup_command(
        command, resource_root(), environment, cancel, report, timeout=DOWNLOAD_TIMEOUT
    )


def _receive(url: str, destination: Path, limit: int) -> None:
    received = 0
    reported = 0.0
    with urlopen(url, timeout=15) as response, destination.open("wb") as output:
        total = max(0, int(response.headers.get("Content-Length", "0")))
        if total > limit:
            raise RuntimeError("Download exceeded its size limit.")
        print(json.dumps({"received": 0, "total": total}), flush=True)
        while chunk := response.read1(256 * 1024):
            received += len(chunk)
            if received > limit:
                raise RuntimeError("Download exceeded its size limit.")
            output.write(chunk)
            now = time.monotonic()
            if now - reported >= 0.1:
                print(json.dumps({"received": received, "total": total}), flush=True)
                reported = now
        print(json.dumps({"received": received, "total": total}), flush=True)


if __name__ == "__main__":
    restore_child_output()
    try:
        _receive(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]))
    except Exception as error:
        print(f"Download failed: {error}", flush=True)
        raise SystemExit(1) from None
