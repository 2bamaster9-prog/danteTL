"""Verified, byte-counted downloads of uv's locked Windows CPython 3.12 wheel selection."""

import hashlib
import os
import re
import tempfile
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

from dantejp.i18n import tr
from dantejp.runtime.download_transport import download_file
from dantejp.runtime.setup_values import Cancelled, DownloadProgress, ModelProgress, Progress


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    name: str
    filename: str
    url: str
    sha256: str
    size: int = 0
    local_path: Path | None = None


def locked_wheels(path: Path, *, cpu_wheel: Path | None = None) -> tuple[RuntimeArtifact, ...]:
    """uv resolves dependencies; we choose only compatible binaries from its PEP 751 export."""
    with path.open("rb") as stream:
        lock = tomllib.load(stream)
    if lock.get("lock-version") != "1.0" or not 0 < len(lock.get("packages", ())) <= 128:
        raise ValueError(tr("Unsupported runtime lock export."))
    environment = {key: str(value) for key, value in default_environment().items()} | {
        "sys_platform": "win32",
        "os_name": "nt",
        "platform_machine": "AMD64",
        "platform_system": "Windows",
        "python_version": "3.12",
        "python_full_version": "3.12.16",
        "implementation_name": "cpython",
        "platform_python_implementation": "CPython",
        "implementation_version": "3.12.16",
        "extra": "",
    }
    tags = list(cpython_tags((3, 12), abis=["cp312"], platforms=["win_amd64"]))
    tags += list(compatible_tags((3, 12), interpreter="cp312", platforms=["win_amd64"]))
    ranks = {tag: i for i, tag in enumerate(tags)}
    result = []
    for package in lock["packages"]:
        if package.get("marker") and not Marker(package["marker"]).evaluate(environment):
            continue
        candidates = []
        for entry in package.get("wheels", ()) or (package.get("archive", {}),):
            url = entry.get("url", "")
            filename = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
            if not filename.endswith(".whl"):
                continue
            if (
                not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename)
                or urlsplit(url).scheme != "https"
            ):
                raise ValueError(tr("Invalid runtime wheel URL."))
            _, _, _, wheel_tags = parse_wheel_filename(filename)
            compatible = [ranks[tag] for tag in wheel_tags if tag in ranks]
            if compatible:
                digest = entry.get("hashes", {}).get("sha256", "")
                if not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise ValueError(tr("A runtime wheel is missing its pinned SHA-256."))
                size = entry.get("size", 0)
                if not isinstance(size, int) or not 0 <= size <= 4 * 2**30:
                    raise ValueError(tr("Invalid runtime wheel size."))
                wheel = RuntimeArtifact(package["name"], filename, url, digest, size)
                candidates.append((min(compatible), wheel))
        if not candidates:
            if package["name"] == "llama-cpp-python" and package.get("sdist"):
                # CPU is built by upstream's PEP 517 backend on the release machine.
                # Install the included complete wheel; players never need a C++ compiler.
                if cpu_wheel is None or not cpu_wheel.is_file():
                    raise ValueError(
                        tr(
                            "The upstream CPU wheel is missing. Extract the complete release, or "
                            "run tools/build.ps1 -CpuWheelOnly in a source checkout."
                        )
                    )
                name, version, _, wheel_tags = parse_wheel_filename(cpu_wheel.name)
                if (
                    name != package["name"]
                    or str(version) != package["version"]
                    or not any(tag in ranks for tag in wheel_tags)
                ):
                    raise ValueError(tr("Bundled CPU wheel does not match the locked dependency."))
                fields = cpu_wheel.with_suffix(".whl.sha256").read_text("ascii").split()
                if (
                    len(fields) != 2
                    or fields[1] != cpu_wheel.name
                    or not re.fullmatch(r"[a-f0-9]{64}", fields[0])
                ):
                    raise ValueError(tr("Invalid bundled CPU wheel checksum."))
                result.append(RuntimeArtifact(name, cpu_wheel.name, "", fields[0], 0, cpu_wheel))
                continue
            raise ValueError(
                tr("No pinned Windows Python 3.12 wheel for {value}.", value=package["name"])
            )
        result.append(min(candidates, key=lambda item: item[0])[1])
    if len({w.name for w in result}) != len(result):
        raise ValueError(tr("Conflicting runtime distributions in export."))
    return tuple(result)


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def _valid(path: Path, wheel: RuntimeArtifact, cancel: threading.Event) -> bool:
    if not path.is_file() or (wheel.size and path.stat().st_size != wheel.size):
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check(cancel)
            digest.update(chunk)
    return digest.hexdigest() == wheel.sha256


def download_artifact(
    wheel: RuntimeArtifact,
    cache: Path,
    progress: Progress,
    cancel: threading.Event,
    *,
    offline: bool = False,
) -> Path:
    _check(cancel)
    if wheel.local_path is not None:
        if not _valid(wheel.local_path, wheel, cancel):
            raise RuntimeError(
                tr("Bundled CPU wheel checksum mismatch. Extract the complete release.")
            )
        progress(ModelProgress(tr("Using the included CPU runtime wheel.")))
        return wheel.local_path
    directory = cache / wheel.sha256
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / wheel.filename
    if not destination.resolve().is_relative_to(cache.resolve()):
        raise ValueError(tr("Runtime download cache path escaped its directory."))
    if _valid(destination, wheel, cancel):
        progress(ModelProgress(tr("Reusing verified {name}.", name=wheel.name)))
        return destination
    if offline:
        raise RuntimeError(
            tr("Verified runtime asset is not cached: {filename}", filename=wheel.filename)
        )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
            temporary = Path(output.name)

        def report(received: int, total: int) -> None:
            progress(
                ModelProgress(
                    tr("Downloading {name}…", name=wheel.name),
                    download=DownloadProgress(wheel.filename, received, wheel.size or total),
                )
            )

        download_file(wheel.url, temporary, wheel.size or 4 * 2**30, report, cancel)
        _check(cancel)
        if not _valid(temporary, wheel, cancel):
            raise RuntimeError(
                tr("Checksum/size mismatch for {name}. Retry setup.", name=wheel.name)
            )
        _check(cancel)
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_wheels(
    export: Path,
    cache: Path,
    progress: Progress,
    cancel: threading.Event,
    *,
    cpu_wheel: Path | None = None,
    offline: bool = False,
) -> Path:
    wheels = locked_wheels(export, cpu_wheel=cpu_wheel)
    requirements = []
    for number, wheel in enumerate(wheels, 1):
        progress(
            ModelProgress(
                tr(
                    "Checking dependency {number}/{count} · {name}…",
                    number=number,
                    count=len(wheels),
                    name=wheel.name,
                )
            )
        )
        path = download_artifact(wheel, cache, progress, cancel, offline=offline)
        requirements.append(f"{path.resolve().as_uri()} --hash=sha256:{wheel.sha256}")
    path = export.with_name("verified-wheels.txt")
    path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
    return path
