import ctypes
import os
import sys
from pathlib import Path

import pytest

from dantetl import bootstrap as app
from dantetl import desktop, paths
from dantetl.runtime import setup as runtime_setup
from dantetl.runtime.owned_process import _child_environment


def test_relocated_frozen_helpers_use_executable_but_managed_runtimes_use_installed_module(
    tmp_path, monkeypatch
):
    bundle = tmp_path / "Moved app 日本語"
    resources = bundle / "_internal/app"
    resources.mkdir(parents=True)
    (resources / "standalone.json").write_text("{}")
    exe = bundle / "DanteTL.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(resources.parent), raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    assert paths.resource_root() == resources
    assert paths.gui_executable() == exe
    assert paths.module_command(exe, "dantetl.translation.models.probe", "request.json") == [
        str(exe),
        "--module",
        "dantetl.translation.models.probe",
        "request.json",
    ]
    managed = tmp_path / "AppData/pythonw.exe"
    assert paths.module_command(managed, "dantetl") == [
        str(managed),
        "-P",
        "-s",
        "-B",
        "-m",
        "dantetl",
    ]


def test_managed_wheel_resources_follow_launcher_but_frozen_resources_ignore_inherited_path(
    tmp_path, monkeypatch
):
    resources = tmp_path / "Current release 日本語/app"
    resources.mkdir(parents=True)
    (resources / "standalone.json").write_text("{}")
    monkeypatch.setenv("DANTETL_RESOURCE_DIR", str(resources))
    assert paths.resource_root() == resources
    assert paths.is_standalone()
    monkeypatch.setenv("DANTETL_RESOURCE_DIR", "missing")
    with pytest.raises(ValueError, match="complete standalone"):
        paths.resource_root()
    monkeypatch.setattr(sys, "_MEIPASS", str(resources.parent), raising=False)
    assert paths.resource_root() == resources


def test_cpu_recovery_starts_without_attempting_saved_runtime(monkeypatch, tmp_path):
    monkeypatch.setattr(desktop, "state_root", lambda: tmp_path)
    monkeypatch.setattr(sys, "argv", ["DanteTL.exe", "--cpu"])
    monkeypatch.setattr(
        runtime_setup, "selected_runtime", lambda _: pytest.fail("Recovery must bypass selection")
    )
    started = []
    monkeypatch.setattr(app, "main", lambda: started.append(True))
    desktop.main()
    assert started == [True]
    assert sys.argv == ["DanteTL.exe"]


def test_helper_dispatch_does_not_start_ui_or_selected_runtime(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["DanteTL.exe", "--module", "dantetl.runtime.probe", "cpu"])
    called = []
    monkeypatch.setattr(
        desktop.runpy, "run_module", lambda module, **kw: called.append((module, sys.argv[:]))
    )
    monkeypatch.setattr(
        runtime_setup, "selected_runtime", lambda _: pytest.fail("Helper must not hand off")
    )
    desktop.main()
    assert called == [("dantetl.runtime.probe", ["dantetl.runtime.probe", "cpu"])]
    monkeypatch.setattr(sys, "argv", ["DanteTL.exe", "--module", "unrelated"])
    with pytest.raises(ValueError, match="Only DanteTL"):
        desktop.main()


def test_external_launch_restores_native_search_path_even_on_failure(tmp_path, monkeypatch):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetDllDirectoryW.argtypes = (ctypes.c_wchar_p,)
    kernel.GetDllDirectoryW.argtypes = (ctypes.c_uint32, ctypes.c_wchar_p)
    previous = ctypes.create_unicode_buffer(32768)
    kernel.GetDllDirectoryW(len(previous), previous)
    bundle = tmp_path / "_internal"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    original = {
        "PATH": os.pathsep.join((str(bundle), str(bundle / "PySide6"), str(tmp_path))),
        "KEY": "kept",
    }
    try:
        assert kernel.SetDllDirectoryW(str(bundle))
        with (
            pytest.raises(RuntimeError, match="launch failed"),
            _child_environment(original) as clean,
        ):
            current = ctypes.create_unicode_buffer(32768)
            assert kernel.GetDllDirectoryW(len(current), current) == 0
            assert clean["PATH"] == str(tmp_path)
            assert clean["KEY"] == "kept"
            assert clean["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
            raise RuntimeError("launch failed")
        restored = ctypes.create_unicode_buffer(32768)
        kernel.GetDllDirectoryW(len(restored), restored)
        assert Path(restored.value) == bundle
        assert "PYINSTALLER_RESET_ENVIRONMENT" not in original
    finally:
        kernel.SetDllDirectoryW(previous.value or None)
