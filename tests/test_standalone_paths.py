import json
import threading
from pathlib import Path

import pytest

from jp_overlay import gemma, models, paths, runtime_setup, sugoi


@pytest.fixture
def package(tmp_path, monkeypatch):
    resources = tmp_path / "Read only app/_internal/app"
    resources.mkdir(parents=True)
    for name in ("standalone.json", "uv.lock", "pyproject.toml", "bootstrap.py"):
        (resources / name).write_text("fixture")
    (resources.parent / "uv.exe").touch()
    monkeypatch.setattr(paths, "resource_root", lambda: resources)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "User AppData"))
    monkeypatch.delenv("DANTEJP_DATA_DIR", raising=False)
    for name in ("JP_OVERLAY_MODEL_DIR", "JP_OVERLAY_SUGOI_DIR", "JP_OVERLAY_GEMMA_DIR"):
        monkeypatch.delenv(name, raising=False)
    return resources


def test_standalone_models_and_state_share_appdata_without_writing_beside_executable(package):
    before = set(package.rglob("*"))
    state = paths.state_root()
    assert state.name == "DanteJP" and state.parent.name == "User AppData"
    assert runtime_setup.project_root() == state
    assert models.model_directory() == state / "models/meiki"
    assert sugoi.model_directory() == state / "models/sugoi-v4"
    assert gemma.model_directory() == state / "models/gemma-4-e2b"
    assert set(package.rglob("*")) == before
    assert not state.exists()  # Path resolution alone does not install/download anything.


def test_source_checkout_preserves_existing_model_paths(package, monkeypatch):
    (package / "standalone.json").unlink()
    monkeypatch.setenv("DANTEJP_DATA_DIR", "ignored-in-a-source-checkout")
    assert paths.state_root() == package
    assert models.model_directory() == package / "models/meiki"
    assert paths.module_command(Path("python.exe"), "jp_overlay") == [
        "python.exe",
        "-m",
        "jp_overlay",
    ]


def test_explicit_state_override_requires_absolute_path(package, monkeypatch, tmp_path):
    monkeypatch.setenv("DANTEJP_DATA_DIR", "relative")
    with pytest.raises(ValueError, match="absolute"):
        paths.state_root()
    monkeypatch.setenv("DANTEJP_DATA_DIR", str(tmp_path / "test data"))
    assert paths.state_root() == tmp_path / "test data"


def test_packaged_runtime_uses_appdata_python_and_current_resources_after_move(
    package, monkeypatch, tmp_path
):
    state = paths.state_root()
    calls = []

    def command(argv, cwd, environment, *args, **kwargs):
        assert cwd == paths.resource_root()
        assert environment["DANTEJP_DATA_DIR"] == str(state)
        assert environment["UV_PYTHON_INSTALL_DIR"] == str(state / ".python")
        assert environment["UV_PYTHON_PREFERENCE"] == "only-managed"
        calls.append(argv)
        if "venv" in argv:
            target = Path(environment["UV_PROJECT_ENVIRONMENT"])
            (target / "Scripts").mkdir(parents=True)
            (target / "Scripts/pythonw.exe").touch()

    monkeypatch.setattr(runtime_setup, "run_setup_command", command)
    monkeypatch.setattr(
        runtime_setup, "prepare_wheels", lambda export, *args: export.with_suffix(".txt")
    )
    runtime_setup.install_runtime(
        state, runtime_setup.PROFILES[0], lambda p: None, threading.Event()
    )
    assert all("--editable" not in call for call in calls)
    assert "--no-emit-project" in calls[1]
    assert calls[0][0] == str(package.parent / "uv.exe")
    assert calls[-1][1:5] == ["-I", "-B", str(package / "bootstrap.py"), "--module"]
    ready = runtime_setup.ready_runtime(state, "nvidia")
    assert ready
    runtime_setup.select_runtime(state, ready)
    moved = tmp_path / "New app version"
    package.rename(moved)
    monkeypatch.setattr(paths, "resource_root", lambda: moved)
    assert runtime_setup.selected_runtime(state) == ready
    assert str(moved / "bootstrap.py") in paths.module_command(
        ready / "Scripts/pythonw.exe", "jp_overlay"
    )
    # Dependencies changing requires fresh validation; UI/source-only changes do not.
    (moved / "uv.lock").write_text("new dependencies")
    assert runtime_setup.selected_runtime(state) is None
    assert json.loads((state / "data/runtime.json").read_text())["environment"] == ready.name
