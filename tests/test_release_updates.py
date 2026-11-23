import hashlib
import io
import json
import threading
import time
from dataclasses import replace
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from dantetl.application.updates import WEEK, Updates
from dantetl.runtime.package import PORTABLE_FILES, bundled_application
from dantetl.runtime.release_feed import parse_release
from dantetl.runtime.release_values import ARCHIVE, MANIFEST, SIGNATURE, Release
from dantetl.runtime.update_install import stage_release
from dantetl.runtime.update_swap import bundle_lease, swap


def settled(service):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        view = service.snapshot()
        if view.phase not in ("checking", "installing", "saving"):
            return view
        time.sleep(0.005)
    pytest.fail("Update command did not settle")


def test_startup_choices_across_launches_and_manual_override(tmp_path):
    release = Release("1.10.0", 100, 80, 64)
    now = 1000
    installs = []

    def launch():
        service = Updates(
            "1.9.0",
            tmp_path,
            fetch=lambda cancel: release,
            install=lambda candidate, cancel, progress: installs.append(candidate),
            clock=lambda: now,
        )
        service.check(automatic=True)
        assert settled(service).phase == "available"
        return service

    service = launch()
    assert service.take_offer() == release
    assert service.take_offer() is None
    service.decide(release, "later")
    assert settled(service).phase == "available"
    service.finish()
    now += WEEK - 1
    service = launch()
    assert service.take_offer() is None
    service.finish()
    now += 1
    service = launch()
    assert service.take_offer() == release
    service.decide(release, "no")
    settled(service)
    service.finish()
    now += 2 * WEEK
    service = launch()
    assert service.take_offer() is None
    service.check()
    assert settled(service).release == release
    service.decide(release, "yes")
    assert settled(service).phase == "restart"
    assert installs == [release]
    service.finish()
    release = replace(release, version="1.11.0")
    service = launch()
    assert service.take_offer() == release
    service.finish()


def test_feed_ignores_prereleases_and_binds_names_to_one_repository():
    data = dict(tag_name="v1.0.0", draft=False, prerelease=False, assets=[])
    release = parse_release(data)
    assert release and not release.signed_assets
    assert release.notes == "https://github.com/nhmelo/dantejp/releases/tag/v1.0.0"
    assert parse_release(data | {"prerelease": True}) is None
    assert parse_release(data | {"tag_name": "../other"}) is None
    assert parse_release(data | {"draft": True}) is None


def test_failed_check_can_retry_and_never_offers_an_older_version(tmp_path):
    responses = iter((OSError("offline"), Release("1.9.0", 100, 90, 64)))

    def fetch(_):
        response = next(responses)
        if isinstance(response, OSError):
            raise response
        return response

    service = Updates("1.10.0", tmp_path, fetch=fetch, install=None)
    try:
        service.check(automatic=True)
        assert settled(service).phase == "error"
        assert service.take_offer() is None
        service.check()
        assert settled(service).phase == "current"
    finally:
        service.finish()


def bundle_files(version):
    wheel = f"dantetl-{version}-py3-none-any.whl"
    data = version.encode()
    checksum = f"{hashlib.sha256(data).hexdigest()}  {wheel}"
    return {name: b"fixture" for name in PORTABLE_FILES} | {
        "_internal/app/standalone.json": b"{}",
        f"_internal/app/application/{wheel}": data,
        f"_internal/app/application/{wheel}.sha256": checksum.encode(),
    }


def installed(folder):
    return bundled_application(folder / "_internal/app").version


@pytest.mark.parametrize(
    "case", ["install", "rollback", "locked", "signature", "digest", "path", "interrupt"]
)
def test_portable_transaction(tmp_path, case):
    cancel = threading.Event()
    old, state = tmp_path / "Portable", tmp_path / "state"
    state.mkdir()
    preferences = state / "preferences.json"
    preferences.write_text("keep me")
    for name, data in bundle_files("1.0.0").items():
        path = old / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    stream = io.BytesIO()
    with ZipFile(stream, "w") as archive:
        for name, data in bundle_files("1.1.0").items():
            archive.writestr("DanteTL/" + name, data)
        if case == "path":
            archive.writestr("DanteTL/_internal/../../outside", b"fixture")
    payload = stream.getvalue()
    key = Ed25519PrivateKey.generate()
    manifest = json.dumps(
        dict(
            file=ARCHIVE,
            version="1.1.0",
            size=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
        )
    ).encode()
    files = {ARCHIVE: payload, MANIFEST: manifest, SIGNATURE: key.sign(manifest)}
    release = Release("1.1.0", len(payload), len(manifest), 64)
    if case == "signature":
        files[SIGNATURE] = bytes(64)
    if case == "digest":
        files[ARCHIVE] = bytes(len(payload))

    def receive(url, destination, size, progress, cancel):
        if case == "interrupt" and destination.name == ARCHIVE:
            raise OSError("connection interrupted")
        destination.write_bytes(files[destination.name])
        assert destination.stat().st_size == size

    def stage():
        return stage_release(
            release, old, key.public_key(), cancel, lambda *_: None, receive=receive
        )

    if case in ("signature", "digest", "path", "interrupt"):
        with pytest.raises((ValueError, OSError)):
            stage()
        assert not list(tmp_path.glob(".dantetl-update-*"))
    else:
        work = stage()

        def launch(path, data, expected):
            assert installed(path) == expected == "1.1.0"
            if case == "rollback":
                raise RuntimeError("Startup failed")

        if case == "locked":
            with bundle_lease(old, state), pytest.raises(OSError):
                swap(old, work, state, release.version, launch=launch)
        elif case == "rollback":
            with pytest.raises(RuntimeError, match="Startup failed"):
                swap(old, work, state, release.version, launch=launch)
        else:
            swap(old, work, state, release.version, launch=launch)
            assert not work.exists()
    assert preferences.read_text() == "keep me"
    assert installed(old) == ("1.1.0" if case == "install" else "1.0.0")
    assert not (tmp_path / "outside").exists()
