"""Cancellable setup subprocesses, with bounded output and owned process-tree cleanup."""

import ctypes as ct
import logging
import os
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jp_overlay.model_store import Cancelled

logger = logging.getLogger(__name__)


class _Limits(ct.Structure):
    _fields_ = [
        ("process_time", ct.c_int64),
        ("job_time", ct.c_int64),
        ("flags", ct.c_uint32),
        ("minimum", ct.c_size_t),
        ("maximum", ct.c_size_t),
        ("processes", ct.c_uint32),
        ("affinity", ct.c_size_t),
        ("priority", ct.c_uint32),
        ("scheduling", ct.c_uint32),
    ]


class _ExtendedLimits(ct.Structure):
    _fields_ = [
        ("basic", _Limits),
        ("io", ct.c_uint64 * 6),
        ("process_memory", ct.c_size_t),
        ("job_memory", ct.c_size_t),
        ("peak_process", ct.c_size_t),
        ("peak_job", ct.c_size_t),
    ]


class ProcessTree:
    """A Windows job owns only this setup command and its descendants."""

    def __init__(self, process: subprocess.Popen[Any]) -> None:
        self.handle = None
        self.kernel = ct.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (ct.c_void_p, ct.c_wchar_p)
        self.kernel.CreateJobObjectW.restype = ct.c_void_p
        self.kernel.OpenProcess.argtypes = (ct.c_uint32, ct.c_int, ct.c_uint32)
        self.kernel.OpenProcess.restype = ct.c_void_p
        self.kernel.AssignProcessToJobObject.argtypes = (ct.c_void_p, ct.c_void_p)
        self.kernel.SetInformationJobObject.argtypes = (
            ct.c_void_p,
            ct.c_int,
            ct.c_void_p,
            ct.c_uint32,
        )
        self.kernel.TerminateJobObject.argtypes = (ct.c_void_p, ct.c_uint32)
        self.kernel.CloseHandle.argtypes = (ct.c_void_p,)
        job = self.kernel.CreateJobObjectW(None, None)
        handle = self.kernel.OpenProcess(0x0101, False, process.pid)  # SET_QUOTA | TERMINATE
        try:
            limits = _ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if (
                not job
                or not handle
                or not self.kernel.SetInformationJobObject(
                    job, 9, ct.byref(limits), ct.sizeof(limits)
                )
                or not self.kernel.AssignProcessToJobObject(job, handle)
            ):
                raise OSError(ct.get_last_error(), "Could not isolate the setup subprocess.")
            self.handle = job
        finally:
            if handle:
                self.kernel.CloseHandle(handle)
            if job and self.handle is None:
                self.kernel.CloseHandle(job)

    def close(self) -> None:
        if self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            self.kernel.CloseHandle(self.handle)
            self.handle = None

    def release(self) -> None:
        """Successful app handoff: let the child outlive this handle and process."""
        if self.handle:
            limits = _ExtendedLimits()
            if not self.kernel.SetInformationJobObject(
                self.handle, 9, ct.byref(limits), ct.sizeof(limits)
            ):
                self.close()
                raise OSError(ct.get_last_error(), "Could not complete the app handoff.")
            self.kernel.CloseHandle(self.handle)
            self.handle = None


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
    process = subprocess.Popen(
        command,
        cwd=root,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    job = None
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
        if os.name == "nt":
            job = ProcessTree(process)
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
        if job:
            job.close()
        if process.poll() is None:
            process.kill()
        process.wait()
        if reader.ident is not None:
            reader.join(timeout=2)
        if process.stdout:
            process.stdout.close()
