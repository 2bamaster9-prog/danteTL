# Standard PyInstaller one-folder build. Only app-specific assets and dynamic imports
# are listed here; PyInstaller owns the bootloader, interpreter and dependency collection.
from pathlib import Path
from importlib.metadata import distributions
import sys
import tomllib

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, copy_metadata, collect_delvewheel_libs_directory
from uv import find_uv_bin
from jp_overlay.models import local_model_paths

root = Path(SPECPATH).parent
assets = local_model_paths(root / "models/meiki")  # verify pinned hashes; never download
data = [
    (str(root / name), "app") for name in ("pyproject.toml", "uv.lock", ".python-version")
]
data += [(str(root / "packaging/standalone.json"), "app")]
app_version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
app_wheel = f"jp_overlay-{app_version}-py3-none-any.whl"
data += [(str(root / "dist" / name), "app/application") for name in (app_wheel, app_wheel + ".sha256")]
data += [(str(root / "build/runtime-locks" / f"pylock.{profile}.toml"), "app/runtime-locks") for profile in ("cpu", "nvidia", "amd")]
data += [(str(p), "app/models/meiki") for p in assets]
data += [(str(root / "packaging/notices/meiki"), "third-party/meiki")]
data += [(str(root / "packaging/notices/native"), "third-party/native")]
data += [(str(Path(sys.base_prefix) / "LICENSE.txt"), "licenses/python")]
data += [(str(root / "build/cpu-runtime" / name), "app/cpu-runtime") for name in (
    "llama_cpp_python-0.3.37-py3-none-win_amd64.whl",
    "llama_cpp_python-0.3.37-py3-none-win_amd64.whl.sha256",
)]
for package in distributions():
    # Preserve upstream metadata/licenses. Do not recursively resolve dependencies:
    # uv deliberately substitutes full OpenCV for Meiki's overlapping headless wheel.
    data += copy_metadata(package.metadata["Name"])
data, native_binaries = collect_delvewheel_libs_directory(
    "llama_cpp", libdir_name="llama_cpp_python.libs", datas=data,
    binaries=collect_dynamic_libs("llama_cpp"),
)

a = Analysis(
    [str(root / "packaging/entry.py")],
    pathex=[str(root / "src")],
    binaries=native_binaries + [(find_uv_bin(), ".")],
    datas=data,
    hiddenimports=collect_submodules("jp_overlay") + ["llama_cpp", "_winapi"],
    excludes=["pytest", "PyInstaller", "uv", "setuptools", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DanteJP",
    console=False, disable_windowed_traceback=True, upx=False,
)
app = COLLECT(exe, a.binaries, a.datas, name="DanteJP", upx=False)
