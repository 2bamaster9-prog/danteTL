import ctypes as ct
import os
import sys
import threading
import time
from unittest.mock import patch

import pytest

from dantejp.runtime.owned_process import OwnedProcess


def test_child_cannot_execute_before_assignment_and_descendants_are_drained(tmp_path):
    marker = tmp_path / "child-pid"
    code = (
        "import subprocess,sys,time; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']); "
        f"Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    entered, allow = threading.Event(), threading.Event()
    original = OwnedProcess._assign
    result = []

    def delayed(owner):
        entered.set()
        assert allow.wait(3)
        original(owner)

    def launch():
        result.append(OwnedProcess([sys.executable, "-c", code], tmp_path, dict(os.environ)))

    with patch.object(OwnedProcess, "_assign", delayed):
        thread = threading.Thread(target=launch)
        thread.start()
        try:
            assert entered.wait(3)
            assert not marker.exists()
        finally:
            allow.set()
            thread.join(5)
    assert not thread.is_alive() and result
    owner = result[0]
    kernel = ct.WinDLL("kernel32")
    kernel.OpenProcess.argtypes = (ct.c_uint32, ct.c_int, ct.c_uint32)
    kernel.OpenProcess.restype = ct.c_void_p
    kernel.WaitForSingleObject.argtypes = (ct.c_void_p, ct.c_uint32)
    kernel.CloseHandle.argtypes = (ct.c_void_p,)
    child = None
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() or not marker.read_text():
            assert time.monotonic() < deadline
            time.sleep(0.01)
        child = kernel.OpenProcess(0x100000, False, int(marker.read_text()))
        assert child
        owner.close()
        assert kernel.WaitForSingleObject(child, 0) == 0
    finally:
        owner.close()
        if child:
            kernel.CloseHandle(child)


@pytest.mark.parametrize("stage", ["_assign", "_resume"])
def test_launch_failure_never_executes_and_reaps_suspended_process(tmp_path, stage):
    marker = tmp_path / "should-not-exist"
    owners = []

    def fail(owner, *args):
        owners.append(owner)
        raise OSError("fixture failure")

    code = f"from pathlib import Path; Path({str(marker)!r}).touch()"
    with patch.object(OwnedProcess, stage, fail), pytest.raises(OSError, match="fixture failure"):
        OwnedProcess([sys.executable, "-c", code], tmp_path, dict(os.environ))
    assert owners[0].returncode is not None
    assert owners[0]._process is None and owners[0]._job is None
    assert not marker.exists()
