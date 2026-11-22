"""Bounded HTTP file transfer in an owned child; the caller verifies and publishes it."""

import json
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dantetl.i18n import CatalogText, tr
from dantetl.paths import module_command, resource_root
from dantetl.runtime.owned_process import restore_child_output
from dantetl.runtime.setup_process import clean_runtime_environment, run_setup_command

DOWNLOAD_TIMEOUT = 1800.0


def download_file(
    url: str,
    destination: Path,
    size: int,
    progress: Callable[[int, int], None],
    cancel: threading.Event,
) -> None:
    """Return only after network resources are gone, including on cancel/timeout.

    Socket inactivity timeouts cannot bound trickling headers/body or blocking DNS.
    The existing process owner can terminate every phase without abandoning a thread.
    The caller owns the locked partial file and verifies it before publication.
    """
    environment = clean_runtime_environment(os.environ)
    environment["PYTHONUTF8"] = "1"
    # The running app may be the immutable AppData wheel rather than site-packages.
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    command = module_command(
        Path(sys.executable), __name__, url, str(destination.resolve()), str(size)
    )

    failure = ""

    def report(line: str) -> None:
        nonlocal failure
        # The child emits bounded byte counters; setup_command retains errors separately.
        if line.startswith("{"):
            value = json.loads(line)
            if "failure" in value:
                failure = tr(value["failure"], **value["fields"])
            else:
                progress(value["received"], value["total"])

    try:
        run_setup_command(
            command, resource_root(), environment, cancel, report, timeout=DOWNLOAD_TIMEOUT
        )
    except RuntimeError:
        if failure:
            raise RuntimeError(failure) from None
        raise


class _InvalidRange(ValueError):
    pass


def _transfer(url: str, destination: Path, size: int, offset: int) -> bool:
    """Write one response, returning False if the server supplied a shorter valid range."""
    limit = size or 4 * 2**30
    headers = {"Accept-Encoding": "identity"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    reported = 0.0
    with urlopen(Request(url, headers=headers), timeout=15) as response:
        length = response.headers.get("Content-Length")
        total = int(length) if length is not None else 0
        response_end = total
        if response.status == 206:
            span = re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("Content-Range", "")
            )
            if not span:
                raise _InvalidRange(CatalogText("The server returned an invalid byte range."))
            start, end, total = map(int, span.groups())
            if (
                start != offset
                or end >= total
                or start > end
                or (length is not None and int(length) != end + 1 - start)
            ):
                raise _InvalidRange(CatalogText("The server returned an invalid byte range."))
            response_end = end + 1
        elif response.status == 200:
            offset = 0  # The server returned a complete representation.
        else:
            raise ValueError(
                CatalogText("Unexpected HTTP status {status}.", status=response.status)
            )
        if total > limit:
            raise RuntimeError(CatalogText("Download exceeded its size limit."))
        received = offset
        print(json.dumps({"received": received, "total": total}), flush=True)
        with destination.open("ab" if offset else "wb", buffering=0) as output:
            while chunk := response.read1(256 * 1024):
                received += len(chunk)
                if received > (response_end or limit):
                    raise RuntimeError(CatalogText("Download exceeded its size limit."))
                output.write(chunk)
                now = time.monotonic()
                if now - reported >= 0.1:
                    print(json.dumps({"received": received, "total": total}), flush=True)
                    reported = now
        if response_end and received != response_end:
            raise ConnectionError(CatalogText("Download interrupted. Retry setup to resume."))
        print(json.dumps({"received": received, "total": total}), flush=True)
        if received < total:
            return False
        if size and received != size:
            raise ConnectionError(CatalogText("Download interrupted. Retry setup to resume."))
        return True


def _receive(url: str, destination: Path, size: int) -> None:
    use_range = True
    for attempt in range(3):
        offset = destination.stat().st_size if use_range and destination.exists() else 0
        use_range = True
        try:
            if offset > (size or 4 * 2**30):
                offset = 0
            while not _transfer(url, destination, size, offset):
                offset = destination.stat().st_size
            return
        except _InvalidRange:
            if not offset or attempt == 2:
                raise
            use_range = False
        except HTTPError as error:
            error.close()
            if error.code == 416 and offset and attempt < 2:
                use_range = False
            elif error.code not in (408, 500, 502, 503, 504) or attempt == 2:
                raise
        except (ConnectionError, TimeoutError, URLError, IncompleteRead):
            if attempt == 2:
                raise
        time.sleep(0.5 * (attempt + 1))


if __name__ == "__main__":
    restore_child_output()
    try:
        _receive(sys.argv[1], Path(sys.argv[2]), int(sys.argv[3]))
    except Exception as error:
        # The helper has no Qt catalog. Translate its message in the owning app.
        detail = error.args[0] if error.args else None
        message = (
            detail
            if isinstance(detail, CatalogText)
            else CatalogText("Download failed: {detail}", detail=str(error))
        )
        print(json.dumps({"failure": message.source, "fields": message.fields}), flush=True)
        raise SystemExit(1) from None
