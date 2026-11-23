import time
from dataclasses import replace

import pytest

from dantetl.application.updates import WEEK, Updates
from dantetl.runtime.release_feed import parse_release
from dantetl.runtime.release_values import Release


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
