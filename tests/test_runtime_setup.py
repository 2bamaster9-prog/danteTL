import ctypes
import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from jp_overlay import runtime_restart
from jp_overlay import runtime_setup as setup
from jp_overlay.hardware import Adapter, recommended_profile
from jp_overlay.model_store import Cancelled
from jp_overlay.setup_process import run_setup_command


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "uv.lock").write_text("pinned")
    (tmp_path / "pyproject.toml").write_text("project")
    uv = tmp_path / ".bootstrap/Scripts/uv.exe"
    uv.parent.mkdir(parents=True)
    uv.touch()
    calls = []

    def run(args, root, environment, cancel, report, **kwargs):
        calls.append(args)
        assert not environment.get("VIRTUAL_ENV")
        assert "UV_PROJECT_ENVIRONMENT" in environment
        target = Path(environment["UV_PROJECT_ENVIRONMENT"])
        assert target != Path(sys.prefix)
        if "sync" in args:
            (target / "Scripts").mkdir(parents=True)
            (target / "Scripts/python.exe").touch()
            (target / "Scripts/pythonw.exe").touch()
        report("Fixture process complete")

    monkeypatch.setattr(setup, "run_setup_command", run)
    monkeypatch.setenv("VIRTUAL_ENV", "another-project")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "another-project")
    return tmp_path, calls, run


def test_recommends_discrete_gpu_and_preserves_manual_cpu_fallback():
    assert recommended_profile(()) == "cpu"
    assert recommended_profile((Adapter("Intel", 0x8086, 2**30),)) == "cpu"
    integrated = Adapter("AMD integrated", 0x1002, 2**30)
    nvidia = Adapter("RTX", 0x10DE, 16 * 2**30)
    amd = Adapter("Radeon", 0x1002, 16 * 2**30)
    assert recommended_profile((integrated, nvidia)) == "nvidia"
    assert recommended_profile((amd,)) == "amd"


@pytest.mark.parametrize("profile", setup.PROFILES, ids=lambda p: p.key)
def test_install_validates_before_publishing_and_selection_is_explicit(project, profile):
    root, calls, _ = project
    setup.install_runtime(root, profile, lambda p: None, threading.Event())
    ready = setup.ready_runtime(root, profile.key)
    assert ready and "sync" in calls[0] and "--locked" in calls[0]
    assert "--no-default-groups" in calls[0]
    assert calls[1][1:] == ["-m", "jp_overlay.runtime_probe", profile.key]
    assert not setup.selected_runtime(root)
    setup.select_runtime(root, ready)
    assert setup.selected_runtime(root) == ready
    before = set((root / ".runtimes").iterdir())
    setup.install_runtime(root, profile, lambda p: None, threading.Event())
    assert set((root / ".runtimes").iterdir()) == before  # Checks/reuses, never resyncs a live env.
    assert len([c for c in calls if "sync" in c]) == 1
    if profile.key == "amd":
        assert "cpu" in calls[0] and "gemma-vulkan" in calls[0] and "amd" not in calls[0]
    (root / "uv.lock").write_text("updated dependencies")
    assert (
        setup.selected_runtime(root) is None
    )  # A changed package cannot silently reuse stale deps.


@pytest.mark.parametrize("error", [RuntimeError("No compatible driver"), Cancelled()])
def test_failure_or_cancel_keeps_active_runtime_and_models(project, monkeypatch, error):
    root, _, run = project
    setup.install_runtime(root, setup.PROFILES[2], lambda p: None, threading.Event())
    previous = setup.ready_runtime(root, "cpu")
    assert previous
    setup.select_runtime(root, previous)
    (root / "models").mkdir()
    (root / "models/weights").write_bytes(b"user data")

    def fail(args, *a, **kw):
        if "jp_overlay.runtime_probe" in args:
            raise error
        run(args, *a, **kw)

    monkeypatch.setattr(setup, "run_setup_command", fail)
    with pytest.raises(type(error)):
        setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    assert setup.selected_runtime(root) == previous
    assert not setup.ready_runtime(root, "nvidia")
    assert list((root / ".runtimes").iterdir()) == [previous]
    assert (root / "models/weights").read_bytes() == b"user data"


def test_repair_creates_replacement_without_modifying_running_environment(project, monkeypatch):
    root, _, run = project
    setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    old = setup.ready_runtime(root, "nvidia")
    assert old
    (old / "keep").write_text("loaded dll")

    def fail_old(args, *a, **kw):
        if args[0] == str(old / "Scripts/python.exe"):
            raise RuntimeError("Broken library")
        run(args, *a, **kw)

    monkeypatch.setattr(setup, "run_setup_command", fail_old)
    setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    assert setup.ready_runtime(root, "nvidia") != old
    assert (old / "keep").read_text() == "loaded dll"


@pytest.mark.parametrize("name", ["../.venv", "cpu-../../elsewhere", "C:/Python", ".venv"])
def test_receipts_cannot_launch_or_delete_arbitrary_paths(project, name):
    root, _, _ = project
    with pytest.raises(ValueError):
        setup.runtime_path(root, name)
    (root / "data/runtimes").mkdir(parents=True)
    (root / "data/runtimes/cpu.json").write_text(json.dumps({"environment": name}))
    assert setup.ready_runtime(root, "cpu") is None


def test_restart_commits_only_after_new_window_acknowledges(project, monkeypatch):
    root, _, _ = project
    setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    target = setup.ready_runtime(root, "nvidia")
    assert target
    process = Mock()
    process.poll.return_value = None
    monkeypatch.setattr(runtime_restart.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime_restart, "ProcessTree", Mock())
    restart = runtime_restart.RuntimeRestart(root, target)
    assert not restart.poll() and not setup.selected_runtime(root)
    restart.receipt.parent.mkdir(parents=True)
    restart.receipt.write_text("12345")
    assert restart.poll() and setup.selected_runtime(root) == target


def test_failed_restart_preserves_previous_selection(project, monkeypatch):
    root, _, _ = project
    setup.install_runtime(root, setup.PROFILES[2], lambda p: None, threading.Event())
    previous = setup.ready_runtime(root, "cpu")
    assert previous
    setup.select_runtime(root, previous)
    setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    target = setup.ready_runtime(root, "nvidia")
    assert target
    process = Mock()
    process.poll.return_value = 1
    monkeypatch.setattr(runtime_restart.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime_restart, "ProcessTree", Mock())
    restart = runtime_restart.RuntimeRestart(root, target)
    with pytest.raises(RuntimeError, match="could not start"):
        restart.poll()
    assert setup.selected_runtime(root) == previous


def test_subprocess_failure_reports_output_and_cancel_stops_owned_child(tmp_path):
    env = os.environ.copy()
    with pytest.raises(RuntimeError, match="native failure"):
        run_setup_command(
            [sys.executable, "-c", "print('native failure'); raise SystemExit(2)"],
            tmp_path,
            env,
            threading.Event(),
            lambda line: None,
        )
    cancel = threading.Event()
    with pytest.raises(Cancelled):
        run_setup_command(
            [sys.executable, "-u", "-c", "import time; print('started'); time.sleep(20)"],
            tmp_path,
            env,
            cancel,
            lambda line: cancel.set(),
            timeout=3,
        )


def test_cancel_also_stops_installer_descendants(tmp_path):
    cancel = threading.Event()
    child_pid = []

    def started(line):
        child_pid.append(int(line))
        cancel.set()

    command = (
        "import subprocess,sys,time; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); "
        "print(child.pid,flush=True); time.sleep(20)"
    )
    with pytest.raises(Cancelled):
        run_setup_command(
            [sys.executable, "-u", "-c", command],
            tmp_path,
            os.environ.copy(),
            cancel,
            started,
        )
    assert len(child_pid) == 1
    kernel = ctypes.WinDLL("kernel32")
    kernel.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel.OpenProcess(0x100000, False, child_pid[0])  # SYNCHRONIZE
    if handle:
        try:
            assert kernel.WaitForSingleObject(handle, 2000) == 0
        finally:
            kernel.CloseHandle(handle)


def test_restart_timeout_stops_tree_without_activating_runtime(project, monkeypatch):
    root, _, _ = project
    setup.install_runtime(root, setup.PROFILES[0], lambda p: None, threading.Event())
    target = setup.ready_runtime(root, "nvidia")
    assert target
    process = Mock()
    process.poll.return_value = None
    tree = Mock()
    monkeypatch.setattr(runtime_restart.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(runtime_restart, "ProcessTree", lambda p: tree)
    restart = runtime_restart.RuntimeRestart(root, target)
    restart.deadline = 0
    with pytest.raises(RuntimeError, match="timed out"):
        restart.poll()
    tree.close.assert_called_once()
    assert setup.selected_runtime(root) is None
