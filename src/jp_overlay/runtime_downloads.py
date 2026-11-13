"""Verified, byte-counted downloads of uv's locked Windows CPython 3.12 wheel selection."""

import hashlib
import os
import re
import tempfile
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

from packaging.markers import Marker, default_environment
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

from jp_overlay.model_store import Cancelled, DownloadProgress, ModelProgress, Progress


@dataclass(frozen=True, slots=True)
class RuntimeWheel:
    name: str
    filename: str
    url: str
    sha256: str
    size: int = 0


def locked_wheels(path: Path) -> tuple[RuntimeWheel, ...]:
    """uv resolves dependencies; we choose only compatible binaries from its PEP 751 export."""
    with path.open("rb") as stream:
        lock = tomllib.load(stream)
    if lock.get("lock-version") != "1.0" or not 0 < len(lock.get("packages", ())) <= 128:
        raise ValueError("Unsupported runtime lock export.")
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
                raise ValueError("Invalid runtime wheel URL.")
            _, _, _, wheel_tags = parse_wheel_filename(filename)
            compatible = [ranks[tag] for tag in wheel_tags if tag in ranks]
            if compatible:
                digest = entry.get("hashes", {}).get("sha256", "")
                if not re.fullmatch(r"[a-f0-9]{64}", digest):
                    raise ValueError("A runtime wheel is missing its pinned SHA-256.")
                size = entry.get("size", 0)
                if not isinstance(size, int) or not 0 <= size <= 4 * 2**30:
                    raise ValueError("Invalid runtime wheel size.")
                wheel = RuntimeWheel(package["name"], filename, url, digest, size)
                candidates.append((min(compatible), wheel))
        if not candidates:
            raise ValueError(f"No pinned Windows Python 3.12 wheel for {package['name']}.")
        result.append(min(candidates, key=lambda item: item[0])[1])
    if len({w.name for w in result}) != len(result):
        raise ValueError("Conflicting runtime distributions in export.")
    return tuple(result)


def _check(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled()


def _valid(path: Path, wheel: RuntimeWheel, cancel: threading.Event) -> bool:
    if not path.is_file() or (wheel.size and path.stat().st_size != wheel.size):
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check(cancel)
            digest.update(chunk)
    return digest.hexdigest() == wheel.sha256


def download_wheel(
    wheel: RuntimeWheel, cache: Path, progress: Progress, cancel: threading.Event
) -> Path:
    _check(cancel)
    directory = cache / wheel.sha256
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / wheel.filename
    if not destination.resolve().is_relative_to(cache.resolve()):
        raise ValueError("Runtime download cache path escaped its directory.")
    if _valid(destination, wheel, cancel):
        progress(ModelProgress(f"Reusing verified {wheel.name}."))
        return destination
    temporary = None
    received = 0
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            digest = hashlib.sha256()
            started = time.monotonic()
            with urlopen(wheel.url, timeout=15) as response:
                total = wheel.size or max(0, int(response.headers.get("Content-Length", "0")))
                progress(
                    ModelProgress(
                        f"Downloading {wheel.name}…",
                        download=DownloadProgress(wheel.filename, 0, total),
                    )
                )
                while chunk := response.read(256 * 1024):
                    _check(cancel)
                    received += len(chunk)
                    if received > (wheel.size or 4 * 2**30):
                        raise RuntimeError("Runtime download exceeded its size limit.")
                    if time.monotonic() - started > 1800:
                        raise RuntimeError("Runtime download timed out. Retry setup.")
                    output.write(chunk)
                    digest.update(chunk)
                    progress(
                        ModelProgress(
                            f"Downloading {wheel.name}…",
                            download=DownloadProgress(wheel.filename, received, total),
                        )
                    )
            _check(cancel)
            if (wheel.size and received != wheel.size) or digest.hexdigest() != wheel.sha256:
                raise RuntimeError(f"Checksum/size mismatch for {wheel.name}. Retry setup.")
        os.replace(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def prepare_wheels(export: Path, cache: Path, progress: Progress, cancel: threading.Event) -> Path:
    wheels = locked_wheels(export)
    requirements = []
    for number, wheel in enumerate(wheels, 1):
        progress(ModelProgress(f"Checking dependency {number}/{len(wheels)} · {wheel.name}…"))
        path = download_wheel(wheel, cache, progress, cancel)
        requirements.append(f"{path.resolve().as_uri()} --hash=sha256:{wheel.sha256}")
    path = export.with_name("verified-wheels.txt")
    path.write_text("\n".join(requirements) + "\n", encoding="utf-8")
    return path
