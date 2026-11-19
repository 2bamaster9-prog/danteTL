"""Production dependency assembly. Views never discover accounts or construct services."""

import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from dantejp.application.cloud_services import CloudServices
from dantejp.application.hotkeys import Hotkeys
from dantejp.application.live_session import LiveSession
from dantejp.application.model_inventory import ModelInventory, inspect_models
from dantejp.application.preferences import PreferenceStore
from dantejp.application.session import ApplicationSession
from dantejp.application.setup_coordinator import SetupCoordinator
from dantejp.application.shutdown import ShutdownCoordinator
from dantejp.application.translation_coordinator import TranslationCoordinator
from dantejp.capture.windows import Windows
from dantejp.capture.worker import CaptureSession
from dantejp.languages.selection import DEFAULT_SOURCE
from dantejp.languages.source import SourceLanguage
from dantejp.ocr.visual import VisualSession
from dantejp.ocr.worker import OcrChoice, OcrSession, Recognizer
from dantejp.paths import state_root
from dantejp.runtime.hardware import HardwareCheck
from dantejp.runtime.model_store import ModelBundle, mark_prepared
from dantejp.runtime.restart import RestartOperation, RuntimeRestart
from dantejp.translation.cloud.chatgpt_auth import ChatGPTConnections
from dantejp.translation.cloud.credentials import WindowsSecrets
from dantejp.translation.cloud.profiles import CloudProfiles
from dantejp.translation.routing import RoutedTranslationSession
from dantejp.translation.worker import BackendChoice, TranslationSession


def application_session(
    windows: Windows,
    recognizer_factory: Callable[[], Recognizer],
    *,
    cloud: CloudServices,
    inventory: ModelInventory,
    setup: SetupCoordinator,
    notify: Callable[[], None],
    preferences_path: Path | None = None,
    cache_path: Path | None = None,
    ocr_backends: tuple[OcrChoice, ...] = (),
    hardware: HardwareCheck | None = None,
    hotkeys: Hotkeys | None = None,
    live_session: LiveSession | None = None,
    language: SourceLanguage = DEFAULT_SOURCE,
) -> ApplicationSession:
    preferences = PreferenceStore(preferences_path)
    cache = cache_path or state_root() / "data/translations.sqlite3"
    live = live_session or LiveSession(
        ocr_factory=lambda factory: OcrSession(factory, require_ack=True, on_change=notify),
        visual_factory=lambda: VisualSession(on_change=notify, language=language),
        language=language,
    )
    translation = TranslationCoordinator(
        inventory,
        cloud,
        lambda choice, source: TranslationSession(
            choice.create, cache, on_change=notify, language=source
        ),
        RoutedTranslationSession,
        cache,
        preferences.initial,
        on_change=notify,
    )

    def cancel_setup() -> None:
        inventory.close()
        setup.close()
        cloud.cancel()

    shutdown = ShutdownCoordinator(
        live,
        translation.lifecycle,
        setup_busy=lambda: setup.busy or cloud.busy or not inventory.finished,
        cancel_setup=cancel_setup,
        preferences_idle=lambda: preferences.idle,
        hardware_finished=lambda: hardware is None or hardware.finished,
        release_hotkeys=lambda: hotkeys.release() if hotkeys else None,
        restart=lambda target: RestartOperation(state_root(), target, create=RuntimeRestart),
    )
    return ApplicationSession(
        windows=windows,
        live=live,
        translation=translation,
        inventory=inventory,
        cloud=cloud,
        setup=setup,
        preferences=preferences,
        shutdown=shutdown,
        ocr_choices=ocr_backends or (OcrChoice("CPU", recognizer_factory, key="cpu"),),
        capture=lambda target, fps, border: CaptureSession(
            target, windows, fps=fps, show_border=border, on_change=notify
        ),
        notify=notify,
        hardware=hardware.snapshot if hardware else lambda: None,
    )


def setup_coordinator(inventory: ModelInventory, models: tuple[ModelBundle, ...], root: Path):
    from dantejp.application.setup_coordinator import (
        RuntimeStatus,
        SetupCoordinator,
        SetupDependencies,
    )
    from dantejp.runtime.first_run import run_setup
    from dantejp.runtime.hardware import detect_adapters, recommended_profile
    from dantejp.runtime.model_store import ModelOperation, install_model
    from dantejp.runtime.setup import PROFILES, install_runtime, ready_runtime, select_runtime
    from dantejp.translation.models.gguf import save_registration
    from dantejp.translation.models.probe import ImportTest

    def status() -> RuntimeStatus:
        adapters = detect_adapters()
        return RuntimeStatus(
            adapters,
            tuple((p.key, ready_runtime(root, p.key)) for p in PROFILES),
            Path(sys.prefix).resolve(),
            recommended_profile(adapters),
        )

    return SetupCoordinator(
        inventory,
        models,
        PROFILES,
        SetupDependencies(
            ModelOperation,
            install_model,
            partial(save_registration, remove=True),
            save_registration,
            ImportTest,
            status,
            lambda key, progress, cancel: install_runtime(
                root, next(p for p in PROFILES if p.key == key), progress, cancel
            ),
            partial(select_runtime, root),
            lambda plan, progress, cancel: run_setup(plan, root, progress, cancel),
        ),
    )


def cloud_services(*, language: SourceLanguage = DEFAULT_SOURCE) -> CloudServices:
    service = CloudServices(
        CloudProfiles(), WindowsSecrets, ChatGPTConnections(), language=language
    )
    service.start()
    return service


def model_inventory(
    models: tuple[ModelBundle, ...],
    provider: Callable[[], tuple[BackendChoice, ...]],
) -> ModelInventory:
    inventory = ModelInventory(partial(inspect_models, models, provider), mark_prepared)
    inventory.advance(0)
    return inventory
