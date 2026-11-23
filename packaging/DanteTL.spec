# Standard PyInstaller one-folder build. Only app-specific assets and dynamic imports
# are listed here; PyInstaller owns the bootloader, interpreter and dependency collection.
from pathlib import Path
from importlib.metadata import distributions
import sys
import os
import tomllib

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules, copy_metadata, collect_delvewheel_libs_directory
from uv import find_uv_bin
from dantetl.ocr.models import ASSETS, PADDLE_ASSETS
from dantetl.runtime.assets import validate_asset

root = Path(SPECPATH).parent
data = [
    (str(root / name), "app") for name in ("pyproject.toml", "uv.lock", ".python-version")
]
data += [(str(root / "packaging/standalone.json"), "app")]
data += [(str(root / "build/update-helper/bin/DanteTL-update.exe"), "app")]
if public_key := os.environ.get("DANTETL_UPDATE_PUBLIC_KEY"):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    if not isinstance(load_pem_public_key(public_key.encode("ascii")), Ed25519PublicKey):
        raise ValueError("Expected an Ed25519 update public key.")
    key_file = root / "build/update-helper/update-public.pem"
    key_file.write_text(public_key, encoding="ascii")
    data += [(str(key_file), "app")]
data += [(str(root / "src/dantetl/ocr/paddle_latin"), "dantetl/ocr/paddle_latin")]
icons = root / "src/dantetl/ui/icons"
data += [(str(root / "src/dantetl/ui/locales"), "dantetl/ui/locales")]
data += [(str(icons), "dantetl/ui/icons")]
app_version = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["project"]["version"]
app_wheel = f"dantetl-{app_version}-py3-none-any.whl"
data += [(str(root / "dist" / name), "app/application") for name in (app_wheel, app_wheel + ".sha256")]
data += [(str(root / "build/runtime-locks" / f"pylock.{profile}.toml"), "app/runtime-locks") for profile in ("cpu", "nvidia", "amd")]
for folder, assets in (("meiki", ASSETS), ("paddle-latin-v5", PADDLE_ASSETS)):
    for asset in assets:
        path = root / "models" / folder / asset.filename
        validate_asset(path, asset)
        data.append((str(path), f"app/models/{folder}"))
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
    hiddenimports=collect_submodules("dantetl") + ["llama_cpp", "_winapi"],
    excludes=["pytest", "PyInstaller", "uv", "setuptools", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="DanteTL",
    console=False, disable_windowed_traceback=True, upx=False, icon=str(icons / "dantetl.ico"),
)
app = COLLECT(exe, a.binaries, a.datas, name="DanteTL", upx=False)
