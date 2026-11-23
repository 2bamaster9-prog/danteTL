"""Read stable release metadata from DanteTL's public GitHub repository."""

import json
import os
import re
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dantetl.paths import module_command, resource_root
from dantetl.runtime.release_values import ARCHIVE, MANIFEST, SIGNATURE, Release
from dantetl.runtime.setup_process import clean_runtime_environment, run_setup_command

LATEST = "https://api.github.com/repos/nhmelo/dantejp/releases/latest"


def fetch_release(cancel: threading.Event) -> Release | None:
    result: list[str] = []
    environment = clean_runtime_environment(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    run_setup_command(
        module_command(Path(sys.executable), __name__),
        resource_root(),
        environment,
        cancel,
        result.append,
        timeout=15,
    )
    data = json.loads(result[-1])
    if isinstance(data, dict) and "error" in data:
        raise OSError(data["error"])
    return Release(**data) if data else None


def parse_release(data: dict) -> Release | None:
    tag = data["tag_name"]
    if (
        data["draft"]
        or data["prerelease"]
        or not re.fullmatch(r"v(?:0|[1-9]\d{0,8})(?:\.(?:0|[1-9]\d{0,8})){2}", tag, re.ASCII)
    ):
        return None
    sizes = {
        asset["name"]: asset["size"] for asset in data["assets"] if asset["state"] == "uploaded"
    }
    return Release(tag[1:], *(int(sizes.get(name, 0)) for name in (ARCHIVE, MANIFEST, SIGNATURE)))


def latest() -> Release | None:
    try:
        with urlopen(
            Request(
                LATEST, headers={"Accept": "application/vnd.github+json", "User-Agent": "DanteTL"}
            ),
            timeout=8,
        ) as response:
            payload = response.read(256 * 1024 + 1)
    except HTTPError as error:
        if error.code == 404:
            error.close()
            return None
        raise
    if len(payload) > 256 * 1024:
        raise ValueError("Release metadata exceeds the size limit.")
    return parse_release(json.loads(payload))


if __name__ == "__main__":
    from dantetl.runtime.owned_process import restore_child_output

    restore_child_output()
    try:
        release = latest()
        print(json.dumps(asdict(release) if release else None), flush=True)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"error": str(error)[:256]}), flush=True)
