"""Compare installed dependencies with uv's exported profile, independently of app releases."""

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dantetl.i18n import tr
from dantetl.runtime.downloads import locked_wheels

RUNTIME_PYTHON = "3.12.16"


@lru_cache(maxsize=12)
def _wheels(export: Path, modified: int, size: int, cpu: Path | None, checksum: str) -> tuple:
    # Metadata keys invalidate this small cache; no model/library hashing on the UI thread.
    return tuple(sorted((w.filename, w.sha256) for w in locked_wheels(export, cpu_wheel=cpu)))


def expected_wheels(project: Path, profile: str) -> tuple[tuple[str, str], ...]:
    if profile not in ("cpu", "nvidia", "amd"):
        raise ValueError(tr("Unknown runtime profile."))
    export = project / "runtime-locks" / f"pylock.{profile}.toml"
    stat = export.stat()
    cpu = project / "cpu-runtime/llama_cpp_python-0.3.37-py3-none-win_amd64.whl"
    checksum = cpu.with_suffix(".whl.sha256").read_text("ascii") if profile == "cpu" else ""
    return _wheels(
        export, stat.st_mtime_ns, stat.st_size, cpu if profile == "cpu" else None, checksum
    )


def dependency_fingerprint(project: Path, profile: str) -> str:
    contract = (RUNTIME_PYTHON, expected_wheels(project, profile))
    return hashlib.sha256(json.dumps(contract).encode("utf-8")).hexdigest()


def dependencies_match(project: Path, profile: str, target: Path) -> bool:
    """The verified install record also permits migration from older app-bound receipts."""
    try:
        config = dict(
            line.split(" = ", 1)
            for line in (target / "pyvenv.cfg").read_text().splitlines()
            if " = " in line
        )
        if (
            config.get("version_info") != RUNTIME_PYTHON
            or config.get("implementation") != "CPython"
        ):
            return False
        requirements = target / "verified-wheels.txt"
        if requirements.stat().st_size > 65_536:
            return False
        installed = []
        for line in requirements.read_text("utf-8").splitlines():
            match = re.fullmatch(r"(file://\S+) --hash=sha256:([a-f0-9]{64})", line)
            if not match:
                return False
            installed.append((unquote(urlsplit(match[1]).path.rsplit("/", 1)[-1]), match[2]))
        return tuple(sorted(installed)) == expected_wheels(project, profile)
    except (OSError, ValueError, TypeError):
        return False
