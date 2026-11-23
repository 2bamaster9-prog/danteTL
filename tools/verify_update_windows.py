"""Install the real portable ZIP over a disposable old revision using a local signed release."""

import argparse
import functools
import hashlib
import json
import os
import shutil
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dantetl.application.updates import Updates
from dantetl.runtime.owned_process import OwnedProcess
from dantetl.runtime.package import PORTABLE_FILES, bundled_application
from dantetl.runtime.release_values import ARCHIVE, MANIFEST, SIGNATURE, Release
from dantetl.runtime.update_launcher import install_release

ROOT = Path(__file__).resolve().parents[1]


def offer(output: Path) -> None:
    old = output / "Portable 日本語"
    project, state = old / "_internal/app", output / "state"
    application = project / "application"
    application.mkdir(parents=True)
    for name in PORTABLE_FILES:
        (old / name).write_text("old version fixture", "ascii")
    (project / "standalone.json").write_text("{}", "ascii")
    wheel = application / "dantetl-0.0.0-py3-none-any.whl"
    wheel.write_bytes(b"old")
    wheel.with_suffix(".whl.sha256").write_text(
        f"{hashlib.sha256(b'old').hexdigest()}  {wheel.name}", "ascii"
    )
    shutil.copyfile(
        ROOT / "dist/DanteTL/_internal/app/DanteTL-update.exe", project / "DanteTL-update.exe"
    )

    feed = output / "feed"
    feed.mkdir()
    archive = feed / ARCHIVE
    os.link(ROOT / "dist" / ARCHIVE, archive)
    current = bundled_application(ROOT / "dist/DanteTL/_internal/app").version
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = json.dumps(
        dict(version=current, file=ARCHIVE, size=archive.stat().st_size, sha256=digest)
    ).encode()
    key = Ed25519PrivateKey.generate()
    (feed / MANIFEST).write_bytes(manifest)
    (feed / SIGNATURE).write_bytes(key.sign(manifest))
    release = Release(current, archive.stat().st_size, len(manifest), 64)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(SimpleHTTPRequestHandler, directory=feed)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    service = Updates(
        "0.0.0",
        state,
        fetch=lambda _: release,
        install=functools.partial(
            install_release, project=project, state=state, key=key.public_key()
        ),
    )
    try:
        with patch.object(
            Release, "asset", lambda self, name: f"http://127.0.0.1:{server.server_port}/{name}"
        ):
            service.check(automatic=True)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                view = service.snapshot()
                if offered := service.take_offer():
                    service.decide(offered, "yes")
                if view.phase == "restart":
                    return
                if view.phase == "error":
                    raise RuntimeError(view.error)
                time.sleep(0.1)
            raise TimeoutError("Update staging timed out")
    finally:
        service.finish()
        server.shutdown()
        server.server_close()
        thread.join()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offer", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / "artifacts"):
        raise ValueError("Use a disposable directory under artifacts.")
    if args.offer:
        offer(output)
        return
    output.mkdir(parents=True, exist_ok=False)
    state = output / "state"
    state.mkdir()
    sentinel = state / "keep.txt"
    sentinel.write_text("preserve user state")
    environment = os.environ.copy() | {
        "DANTETL_DISABLE_UPDATE_CHECK": "1",
        "LOCALAPPDATA": str(output / "AppData"),
        "DANTETL_DATA_DIR": str(state),
    }
    owner = OwnedProcess(
        [sys.executable, str(Path(__file__).resolve()), "--offer", "--output", str(output)],
        ROOT,
        environment,
        capture_output=True,
    )
    try:
        deadline = time.monotonic() + 180
        while owner.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        if owner.poll() != 0:
            detail = owner.stdout.read() if owner.poll() is not None and owner.stdout else ""
            raise RuntimeError(f"Fixture offer failed: {detail}")
        # The helper removes the previous bundle only after the real Qt window acknowledges.
        while list(output.glob(".dantetl-update-*")):
            if (state / "logs/update-error.log").exists():
                raise RuntimeError((state / "logs/update-error.log").read_text("utf-8"))
            if time.monotonic() >= deadline:
                raise TimeoutError("Packaged GUI acknowledgement timed out")
            time.sleep(0.1)
        installed = bundled_application(output / "Portable 日本語/_internal/app").version
        assert installed == bundled_application(ROOT / "dist/DanteTL/_internal/app").version
        assert sentinel.read_text() == "preserve user state"
        print(f"Verified signed installation, GUI acknowledgement and state retention: {installed}")
    finally:
        owner.close()
        if owner.stdout:
            owner.stdout.close()
    (output / "results.json").write_text(
        json.dumps({"installed": installed, "gui_acknowledged": True, "state_preserved": True}),
        "utf-8",
    )
    for name in ("feed", "Portable 日本語"):
        directory = output / name
        if directory.resolve() != directory or directory.parent != output:
            raise ValueError("Unexpected fixture cleanup path.")
        shutil.rmtree(directory)


if __name__ == "__main__":
    main()
