"""The release CPU build must consume the same source as the runtime dependency lock."""

import tomllib
from pathlib import Path


def test_cpu_source_requirement_matches_uv_lock():
    root = Path(__file__).resolve().parents[1]
    lock = tomllib.loads((root / "uv.lock").read_text("utf-8"))
    (package,) = (
        p for p in lock["package"] if p["name"] == "llama-cpp-python" and "registry" in p["source"]
    )
    (requirement,) = (
        line
        for line in (root / "packaging/cpu-runtime.txt").read_text("utf-8").splitlines()
        if line and not line.startswith("#")
    )
    assert requirement == (
        f"llama-cpp-python=={package['version']} --hash={package['sdist']['hash']}"
    )
