"""Production dependency assembly. Views never discover accounts or construct services."""

import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from dantetl.application.cloud_services import CloudServices
from dantetl.application.hotkeys import Hotkeys
from dantetl.application.live_session import LiveSession
from dantetl.application.model_inventory import ModelInventory, inspect_models
from dantetl.application.preferences import PreferenceStore
from dantetl.application.session import ApplicationSession
from dantetl.application.setup_coordinator import SetupCoordinator
from dantetl.application.shutdown import ShutdownCoordinator
from dantetl.application.translation_coordinator import TranslationCoordinator
from dantetl.capture.windows import Windows
from dantetl.capture.worker import CaptureSession
from dantetl.languages.selection import DEFAULT_SOURCE
from dantetl.languages.source import SourceLanguage
from dantetl.ocr.visual import VisualSession
from dantetl.ocr.worker import OcrChoice, OcrSession, Recognizer
from dantetl.paths import state_root
from dantetl.runtime.hardware import HardwareCheck
from dantetl.runtime.model_store import ModelBundle, mark_prepared
from dantetl.runtime.restart import RestartOperation, RuntimeRestart
from dantetl.translation.cloud.chatgpt_auth import ChatGPTConnections
from dantetl.translation.cloud.credentials import WindowsSecrets
from dantetl.translation.cloud.profiles import CloudProfiles
from dantetl.translation.routing import RoutedTranslationSession
from dantetl.translation.worker import BackendChoice, TranslationSession


def application_session(
    windows: Windows,
    recognizer_factory: Callable[[], Recognizer],
    *,
    cloud: CloudServices,
    inventory: ModelInventory,
    setup: SetupCoordinator,
    notify: Callable[[], None],
    preferences_path: Path | None = None,
    preferences: PreferenceStore | None = None,
    cache_path: Path | None = None,
    ocr_backends: tuple[OcrChoice, ...] = (),
    source_models: Callable[[SourceLanguage], tuple[OcrChoice, ...]] | None = None,
    hardware: HardwareCheck | None = None,
    hotkeys: Hotkeys | None = None,
    live_session: LiveSession | None = None,
    language: SourceLanguage = DEFAULT_SOURCE,
) -> ApplicationSession:
    preferences = preferences or PreferenceStore(preferences_path)
    cache = cache_path or state_root() / "data/translations.sqlite3"
    initial_choices = ocr_backends or (OcrChoice("CPU", recognizer_factory, key="cpu"),)

    live = live_session or LiveSession(
        ocr_factory=lambda factory: OcrSession(factory, require_ack=True, on_change=notify),
        visual_factory=lambda: VisualSession(on_change=notify),
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
        preferences.current,
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
        ocr_choices=initial_choices,
        source_models=source_models or (lambda _: initial_choices),
        inventory=inventory,
        cloud=cloud,
        setup=setup,
        preferences=preferences,
        shutdown=shutdown,
        capture=lambda target, fps, border: CaptureSession(
            target, windows, fps=fps, show_border=border, on_change=notify
        ),
        notify=notify,
        hardware=hardware.snapshot if hardware else lambda: None,
    )


def setup_coordinator(inventory: ModelInventory, models: tuple[ModelBundle, ...], root: Path):
    from dantetl.application.setup_coordinator import SetupCoordinator, SetupDependencies
    from dantetl.runtime.first_run import run_setup
    from dantetl.runtime.hardware import detect_adapters
    from dantetl.runtime.hardware_values import recommended_profile
    from dantetl.runtime.model_store import ModelOperation, install_model
    from dantetl.runtime.setup import install_runtime, ready_runtime, select_runtime
    from dantetl.runtime.setup_values import RuntimeStatus
    from dantetl.runtime.values import PROFILES
    from dantetl.translation.models.gguf import save_registration
    from dantetl.translation.models.probe import ImportTest

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
