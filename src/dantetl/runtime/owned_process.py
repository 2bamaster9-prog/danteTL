"""Windows process ownership from creation through shutdown or acknowledged handoff.

CPython's native CreateProcess bridge retains the primary thread handle here (Popen
closes it). No user code executes before job assignment. Only explicit stdio handles
are inherited; both the bundled and managed interpreters use this same boundary.
"""

import ctypes as ct
import importlib
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import TextIO

from dantetl.i18n import tr

_launch_lock = threading.Lock()


def restore_child_output() -> None:
    """Attach a windowed helper to its inherited pipe; never called in the app process."""
    if sys.stdout is None:
        import msvcrt

        kernel = ct.WinDLL("kernel32", use_last_error=True)
        kernel.GetStdHandle.argtypes = (ct.c_uint32,)
        kernel.GetStdHandle.restype = ct.c_void_p
        handle = kernel.GetStdHandle(-11 & 0xFFFFFFFF)
        if not handle or handle == ct.c_void_p(-1).value:
            raise OSError(tr("Download helper has no output pipe."))
        descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
        sys.stdout = os.fdopen(descriptor, "w", encoding="utf-8", errors="replace")


@contextmanager
def _child_environment(environment: dict[str, str]) -> Iterator[dict[str, str]]:
    """External runtimes must not inherit PyInstaller's bundled DLL search directory."""
    if not getattr(sys, "frozen", False):
        yield environment
        return
    with _launch_lock:
        kernel = ct.WinDLL("kernel32", use_last_error=True)
        kernel.GetDllDirectoryW.argtypes = (ct.c_uint32, ct.c_wchar_p)
        kernel.SetDllDirectoryW.argtypes = (ct.c_wchar_p,)
        previous = ct.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(previous), previous)
        bundle = Path(getattr(sys, "_MEIPASS", "")).resolve()
        clean = dict(environment)
        clean["PATH"] = os.pathsep.join(
            p
            for p in clean.get("PATH", "").split(os.pathsep)
            if p and not Path(p).resolve().is_relative_to(bundle)
        )
        clean["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        if not kernel.SetDllDirectoryW(None):
            raise OSError(ct.get_last_error(), tr("Could not isolate child library loading."))
        try:
            yield clean
        finally:
            kernel.SetDllDirectoryW(previous.value or None)


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


class OwnedProcess:
    """Own launch, descendants and handles; close kills/drains, release hands off."""

    def __init__(
        self,
        command: list[str],
        root: Path,
        environment: dict[str, str],
        *,
        capture_output: bool = False,
        show_window: bool = False,
    ) -> None:
        import msvcrt

        self._api = importlib.import_module("_winapi")
        self._kernel = ct.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.argtypes = (ct.c_void_p, ct.c_wchar_p)
        self._kernel.CreateJobObjectW.restype = ct.c_void_p
        self._kernel.SetInformationJobObject.argtypes = (
            ct.c_void_p,
            ct.c_int,
            ct.c_void_p,
            ct.c_uint32,
        )
        self._kernel.AssignProcessToJobObject.argtypes = (ct.c_void_p, ct.c_void_p)
        self._kernel.TerminateJobObject.argtypes = (ct.c_void_p, ct.c_uint32)
        self._kernel.ResumeThread.argtypes = (ct.c_void_p,)
        self._kernel.ResumeThread.restype = ct.c_uint32
        self._job = self._kernel.CreateJobObjectW(None, None)
        self._process: int | None = None
        self._assigned = False
        self.stdout: TextIO | None = None
        self.returncode: int | None = None
        self.pid = 0
        thread = None
        try:
            self._set_limits(0x2000)  # KILL_ON_JOB_CLOSE, no breakaway.
            with ExitStack() as stack:
                child_environment = stack.enter_context(_child_environment(environment))
                stdin = stack.enter_context(open(os.devnull, "rb"))
                if capture_output:
                    read_fd, write_fd = os.pipe()
                    self.stdout = os.fdopen(read_fd, "r", encoding="utf-8", errors="replace")
                    stdout = stack.enter_context(os.fdopen(write_fd, "wb"))
                else:
                    stdout = stack.enter_context(open(os.devnull, "wb"))
                handles = [msvcrt.get_osfhandle(f.fileno()) for f in (stdin, stdout)]
                for handle in handles:
                    os.set_handle_inheritable(handle, True)
                startup = subprocess.STARTUPINFO(
                    dwFlags=subprocess.STARTF_USESTDHANDLES | subprocess.STARTF_USESHOWWINDOW,
                    wShowWindow=1 if show_window else 0,
                    hStdInput=handles[0],
                    hStdOutput=handles[1],
                    hStdError=handles[1],
                    lpAttributeList={"handle_list": handles},
                )
                self._process, thread, self.pid, _ = self._api.CreateProcess(
                    None,
                    subprocess.list2cmdline(command),
                    None,
                    None,
                    True,
                    subprocess.CREATE_NO_WINDOW | 0x4,  # CREATE_SUSPENDED
                    child_environment,
                    str(root),
                    startup,
                )
                self._assign()
                self._resume(thread)
        except BaseException:
            self.close()
            if self.stdout:
                self.stdout.close()
            raise
        finally:
            if thread:
                self._api.CloseHandle(thread)

    def _set_limits(self, flags: int) -> None:
        limits = _ExtendedLimits()
        limits.basic.flags = flags
        if not self._job or not self._kernel.SetInformationJobObject(
            self._job, 9, ct.byref(limits), ct.sizeof(limits)
        ):
            raise OSError(ct.get_last_error(), tr("Could not configure process ownership."))

    def _assign(self) -> None:
        if not self._kernel.AssignProcessToJobObject(self._job, self._process):
            raise OSError(ct.get_last_error(), tr("Could not isolate the subprocess."))
        self._assigned = True

    def _resume(self, thread: int) -> None:
        if self._kernel.ResumeThread(thread) != 1:
            raise OSError(ct.get_last_error(), tr("Could not start the isolated subprocess."))

    def poll(self) -> int | None:
        if self._process and self._api.WaitForSingleObject(self._process, 0) == 0:
            self.returncode = self._api.GetExitCodeProcess(self._process)
        return self.returncode

    def close(self) -> None:
        """Terminate and wait for all assigned descendants before releasing handles."""
        try:
            if self._job and not self._kernel.TerminateJobObject(self._job, 1):
                raise OSError(ct.get_last_error(), tr("Could not terminate owned processes."))
            if self._process:
                # Covers assignment failure as well as normal job termination.
                if (not self._assigned or not self._job) and self.poll() is None:
                    self._api.TerminateProcess(self._process, 1)
                self._api.WaitForSingleObject(self._process, self._api.INFINITE)
                self.poll()
            if self._job:
                # A terminated job signals only after its associated processes exit.
                self._api.WaitForSingleObject(self._job, self._api.INFINITE)
        finally:
            self._close_handles()

    def release(self) -> None:
        """Only after GUI acknowledgement: let the new app outlive the old owner."""
        self._set_limits(0)
        self._api.CloseHandle(self._job)
        self._job = None

    def __del__(self) -> None:
        # A released child may outlive us. Closing its process handle does not terminate it.
        if hasattr(self, "_process"):
            self._close_handles()

    def _close_handles(self) -> None:
        for handle in (self._process, self._job):
            if handle:
                self._api.CloseHandle(handle)
        self._process = self._job = None
