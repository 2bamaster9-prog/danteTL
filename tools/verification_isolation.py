"""Keep native local-model fixtures away from personal cloud accounts and inference APIs."""

import socket
import tempfile
import weakref
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

from jp_overlay.chatgpt_auth import ChatGPTConnections
from jp_overlay.cloud_profiles import CloudProfiles
from jp_overlay.cloud_services import CloudServices
from jp_overlay.protected_store import ProtectedStore


class NoCredentials:
    def read(self, key: str) -> str | None:
        raise AssertionError("Local verification must not read credentials")

    def write(self, key: str, secret: str) -> None:
        raise AssertionError("Local verification must not save credentials")

    def delete(self, key: str) -> None:
        raise AssertionError("Local verification must not delete credentials")


def create_cloud() -> CloudServices:
    temporary = tempfile.TemporaryDirectory(prefix="dantejp-verification-")
    root = Path(temporary.name)
    service = CloudServices(
        CloudProfiles(root / "cloud.json"),
        NoCredentials,
        ChatGPTConnections(ProtectedStore(root / "accounts")),
    )
    weakref.finalize(service, temporary.cleanup)
    service.start()
    return service


def create_window(*args, **kwargs):
    from jp_overlay.composition import application_session, setup_coordinator
    from jp_overlay.desktop_driver import DesktopDriver
    from jp_overlay.paths import state_root
    from jp_overlay.ui import MainWindow

    temporary = tempfile.TemporaryDirectory(prefix="dantejp-native-")
    root = Path(temporary.name)
    kwargs.setdefault("preferences_path", root / "preferences.json")
    kwargs.setdefault("cache_path", root / "cache.sqlite3")
    inventory = create_inventory(args, kwargs)
    driver = DesktopDriver()
    options = {
        k: v
        for k, v in kwargs.items()
        if k not in {"models", "backends", "backend_provider", "include_imports"}
    }
    application = application_session(
        *args[:2],
        cloud=create_cloud(),
        inventory=inventory,
        setup=setup_coordinator(inventory, kwargs.get("models", ()), state_root()),
        notify=driver.notify,
        **options,
    )
    weakref.finalize(application, temporary.cleanup)
    return MainWindow(
        application, args[0], driver, hardware=kwargs.get("hardware"), hotkeys=kwargs.get("hotkeys")
    )


def create_inventory(args, kwargs):
    from functools import partial

    from jp_overlay.model_inventory import ModelInventory, inspect_models

    backends = args[2] if len(args) > 2 else kwargs.get("backends", ())
    probe = partial(
        inspect_models,
        kwargs.get("models", ()),
        kwargs.get("backend_provider") or (lambda: backends),
        include_imports=kwargs.get("include_imports", False),
    )
    initial = inspect_models(kwargs.get("models", ()), lambda: backends, include_imports=False)
    return ModelInventory(probe, lambda key: None, initial=initial)


def run_isolated(main: Callable[[], int | None]) -> None:
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Unexpected network")):
        raise SystemExit(main())


def find_model(combo, choice):
    from jp_overlay.model_selection import ModelOption
    from jp_overlay.translation_coordinator import model_reference

    reference = choice.reference if isinstance(choice, ModelOption) else model_reference(choice)
    return next(
        (
            i
            for i in range(combo.count())
            if isinstance(combo.itemData(i), ModelOption)
            and combo.itemData(i).reference == reference
        ),
        -1,
    )


def app_owner(window):
    from typing import cast

    from jp_overlay.application_session import ApplicationSession

    return cast(ApplicationSession, window.application)


def cloud_owner(panel):
    from typing import cast

    from jp_overlay.cloud_services import CloudServices

    return cast(CloudServices, panel.service)


def setup_owner(panel):
    from typing import cast

    from jp_overlay.setup_coordinator import SetupCoordinator

    return cast(SetupCoordinator, panel.service)
