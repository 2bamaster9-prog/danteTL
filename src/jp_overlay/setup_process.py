"""Runtime child environments and cancellable setup subprocesses with owned cleanup."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from pathlib import Path

from jp_overlay.owned_process import OwnedProcess
from jp_overlay.setup_values import Cancelled

logger = logging.getLogger(__name__)


def clean_runtime_environment(inherited: Mapping[str, str]) -> dict[str, str]:
    """Copy inherited state without Python/uv overrides; callers add their intended settings.

    -P/-s do not ignore Python environment variables. Setup and app launch must start
    from the same clean baseline: merging a sanitized environment cannot remove leftovers.
    """
    return {
        key: value
        for key, value in inherited.items()
        if not key.startswith(("PYTHON", "UV_")) and key != "VIRTUAL_ENV"
    }


def run_setup_command(
    command: list[str],
    root: Path,
    environment: dict[str, str],
    cancel: threading.Event,
    report: Callable[[str], None],
    *,
    timeout: float = 1800,
) -> None:
    if cancel.is_set():
        raise Cancelled()
    deadline = time.monotonic() + timeout
    process = OwnedProcess(command, root, environment, capture_output=True)
    tail: deque[str] = deque(maxlen=16)
    lock = threading.Lock()

    def read() -> None:
        assert process.stdout is not None
        while chunk := process.stdout.readline(2048):
            line = chunk.strip()
            if line:
                logger.info("Runtime setup: %s", line)
                with lock:
                    tail.append(line)
                report(line)

    reader = threading.Thread(target=read, daemon=True, name="setup-output")
    try:
        reader.start()
        while process.poll() is None:
            if cancel.wait(0.1):
                raise Cancelled()
            if time.monotonic() > deadline:
                raise RuntimeError(
                    "Setup timed out. Check your connection and GPU driver, then retry."
                )
        reader.join(timeout=2)
        if cancel.is_set():
            raise Cancelled()
        if process.returncode:
            with lock:
                details = "\n".join(tail)
            raise RuntimeError(f"Setup command failed ({process.returncode}).\n{details}")
    finally:
        process.close()
        if reader.ident is not None:
            reader.join(timeout=2)
        if process.stdout:
            process.stdout.close()
