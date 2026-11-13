"""Cancellable setup subprocesses, with bounded output and owned process-tree cleanup."""

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

from jp_overlay.model_store import Cancelled
from jp_overlay.owned_process import OwnedProcess

logger = logging.getLogger(__name__)


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
        deadline = time.monotonic() + timeout
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
