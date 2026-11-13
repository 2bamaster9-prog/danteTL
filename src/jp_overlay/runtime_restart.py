"""Launch a verified runtime and acknowledge a real GUI startup before closing the old app."""

import os
import re
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from jp_overlay.paths import is_standalone, module_command
from jp_overlay.runtime_setup import project_root, ready_runtime, select_runtime, selected_runtime
from jp_overlay.setup_process import ProcessTree


def acknowledge_startup() -> None:
    token = os.environ.pop("JP_OVERLAY_RESTART_TOKEN", "")
    if re.fullmatch("[a-f0-9]{32}", token):
        path = project_root() / "data/restarts" / token
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(os.getpid()), encoding="ascii")


class RuntimeRestart:
    def __init__(self, root: Path, target: Path) -> None:
        if ready_runtime(root, target.name.split("-", 1)[0]) != target.resolve():
            raise ValueError("Runtime is no longer ready. Open Runtime setup and retry.")
        self.root, self.target = root, target
        token = uuid4().hex
        self.receipt = root / "data/restarts" / token
        environment = os.environ.copy()
        for key in ("VIRTUAL_ENV", "PYTHONHOME", "PYTHONPATH"):
            environment.pop(key, None)
        environment["JP_OVERLAY_RESTART_TOKEN"] = token
        if is_standalone():
            environment["DANTEJP_DATA_DIR"] = str(root)
        self.process = subprocess.Popen(
            module_command(target / "Scripts/pythonw.exe", "jp_overlay"),
            cwd=root,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.started_pid: int | None = None
        try:
            self._tree = ProcessTree(self.process)
        except OSError:
            self.process.terminate()
            raise
        self.deadline = time.monotonic() + 30

    def poll(self) -> bool:
        if self.receipt.is_file() and self.process.poll() is None:
            previous = selected_runtime(self.root)
            try:
                self.started_pid = int(self.receipt.read_text("ascii"))
                select_runtime(self.root, self.target)
                self._tree.release()
            except (OSError, ValueError):
                self._tree.close()
                if previous:
                    select_runtime(self.root, previous)
                else:
                    (self.root / "data/runtime.json").unlink(missing_ok=True)
                raise
            self.receipt.unlink(missing_ok=True)
            return True
        if self.process.poll() is not None:
            self._tree.close()
            self.receipt.unlink(missing_ok=True)
            raise RuntimeError(
                "The new app could not start. Your current runtime is still selected."
            )
        if time.monotonic() > self.deadline:
            # This process is ours and has not acknowledged startup; never kill another app.
            self._tree.close()
            self.receipt.unlink(missing_ok=True)
            raise RuntimeError(
                "Restart timed out. Your current runtime is still selected; retry setup."
            )
        return False
