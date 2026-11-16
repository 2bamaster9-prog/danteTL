"""Cloud ownership regressions run without constructing any widgets."""

import subprocess
import sys
import threading
import time
from dataclasses import replace

from dantejp.application.cloud_services import CloudServices
from dantejp.translation.cloud.chatgpt_auth import ChatGPTConnections
from dantejp.translation.cloud.profiles import CloudProfile, CloudProfiles
from dantejp.translation.cloud.protected_store import ProtectedStore
from dantejp.translation.cloud.state import CloudDraft


class Secrets:
    def __init__(self):
        self.values = {}
        self.threads = []

    def read(self, key):
        return self.values.get(key)

    def write(self, key, secret):
        self.threads.append(threading.get_ident())
        self.values[key] = secret

    def delete(self, key):
        self.values.pop(key, None)


def finish(service):
    deadline = time.monotonic() + 3
    while service.busy:
        service.advance()
        assert time.monotonic() < deadline
        time.sleep(0.001)
    return service.snapshot()


def create(tmp_path):
    secrets = Secrets()
    service = CloudServices(
        CloudProfiles(tmp_path / "cloud.json"),
        lambda: secrets,
        ChatGPTConnections(ProtectedStore(tmp_path / "accounts")),
    )
    service.start()
    finish(service)
    return service, secrets


def test_save_remove_and_usage_are_application_owned_without_a_view(tmp_path):
    service, secrets = create(tmp_path)
    initial = service.snapshot()
    profile = CloudProfile.new("deepseek")
    service.save(CloudDraft(profile, "", "fixture-key"))
    saved = finish(service)
    assert saved.saved and saved.profiles[0].key == profile.key
    assert saved.available == frozenset((profile.key,))
    assert not initial.profiles and not initial.available
    assert secrets.threads and threading.get_ident() not in secrets.threads
    allowance = service.allowance(profile.key)
    allowance.reserve(profile, 10)
    renamed = replace(saved.profiles[0], name="Renamed")
    service.save(CloudDraft(renamed, renamed.credential_key, ""))
    finish(service)
    assert service.allowance(profile.key) is allowance
    assert service.usage(profile.key).requests == 1
    service.remove(renamed)
    assert not service.available(profile.key)  # revoke before disk completion
    removed = finish(service)
    assert not removed.profiles and secrets.values  # removing does not forget a key


def test_cancelled_worker_drains_before_new_commands_and_owner_cleanup(tmp_path, monkeypatch):
    service, _ = create(tmp_path)
    entered, cancelled, cleanup, release = (threading.Event() for _ in range(4))

    class Backend:
        def translate(self, texts):
            entered.set()
            assert cancelled.wait(3)
            return ("Cancelled",)

        def cancel_pending(self):
            cancelled.set()

        def close(self):
            cleanup.set()
            assert release.wait(3)

    monkeypatch.setattr(
        "dantejp.application.cloud_services.CloudBackend", lambda *a, **k: Backend()
    )
    draft = CloudDraft(CloudProfile.new("deepseek"), "", "fixture")
    service.test(draft)
    assert entered.wait(3)
    service.cancel()
    assert cleanup.wait(3)
    try:
        assert service.busy
        service.save(draft)  # cannot reset cancellation or replace the in-flight result
        assert service.snapshot().busy and not service.snapshot().profiles
    finally:
        release.set()
    completed = finish(service)
    assert not completed.saved and not completed.profiles
    assert "cancelled" in completed.message.lower()


def test_closed_owner_rejects_late_dialog_actions_and_resumes_after_failed_restart(tmp_path):
    service, secrets = create(tmp_path)
    profile = CloudProfile.new("deepseek")
    service.save(CloudDraft(profile, "", "fixture-key"))
    before = finish(service)
    service.close()
    service.remove(profile)
    service.forget_key(before.profiles[0].credential_key)
    service.test(CloudDraft(profile, "", "fixture-key"))
    service.save(CloudDraft(profile, "", "replacement"))
    service.start()
    service._open_browser("https://example.invalid/late")
    assert not service.busy and not service.take_browser()
    assert service.snapshot().available == before.available
    assert set(secrets.values.values()) == {"fixture-key"}
    service.resume()
    service.remove(profile)
    assert not finish(service).profiles


def test_cloud_owner_import_and_startup_reject_all_qt_imports(tmp_path):
    script = """
import importlib.abc, sys, time
from pathlib import Path
class NoQt(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("PySide6", "shiboken6")):
            raise AssertionError("Application owner imported Qt: " + fullname)
sys.meta_path.insert(0, NoQt())
from dantejp.application.cloud_services import CloudServices
from dantejp.translation.cloud.profiles import CloudProfiles
from dantejp.translation.cloud.chatgpt_auth import ChatGPTConnections
from dantejp.translation.cloud.protected_store import ProtectedStore
class NoSecrets:
    def read(self, key): raise AssertionError("Unexpected credential read")
root = Path(sys.argv[1])
service = CloudServices(CloudProfiles(root / "cloud.json"), NoSecrets,
    ChatGPTConnections(ProtectedStore(root / "accounts")))
service.start()
deadline = time.monotonic() + 3
while service.busy:
    service.advance()
    assert time.monotonic() < deadline
    time.sleep(.001)
assert not service.snapshot().problem
"""
    subprocess.run([sys.executable, "-c", script, str(tmp_path)], check=True, timeout=10)
