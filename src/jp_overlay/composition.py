"""Production dependency assembly. Views never discover accounts or construct services."""

import sys
from collections.abc import Callable
from functools import partial
from pathlib import Path

from jp_overlay.application_session import ApplicationSession
from jp_overlay.capture import CaptureSession
from jp_overlay.chatgpt_auth import ChatGPTConnections
from jp_overlay.cloud_profiles import CloudProfiles
from jp_overlay.cloud_services import CloudServices
from jp_overlay.credentials import WindowsSecrets
from jp_overlay.hardware import HardwareCheck
from jp_overlay.hotkeys import Hotkeys
from jp_overlay.live_session import LiveSession
from jp_overlay.model_inventory import ModelInventory, inspect_models
from jp_overlay.model_store import ModelBundle, mark_prepared
from jp_overlay.paths import state_root
from jp_overlay.preferences import PreferenceStore
from jp_overlay.recognition import OcrChoice, OcrSession, Recognizer
from jp_overlay.runtime_restart import RestartOperation, RuntimeRestart
from jp_overlay.setup_coordinator import SetupCoordinator
from jp_overlay.shutdown import ShutdownCoordinator
from jp_overlay.translation import BackendChoice, TranslationSession
from jp_overlay.translation_coordinator import TranslationCoordinator
from jp_overlay.translation_routing import RoutedTranslationSession
from jp_overlay.visual import VisualSession
from jp_overlay.windows import Windows


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
) -> ApplicationSession:
    preferences = PreferenceStore(preferences_path)
    cache = cache_path or state_root() / "data/translations.sqlite3"
    live = live_session or LiveSession(
        ocr_factory=lambda factory: OcrSession(factory, require_ack=True, on_change=notify),
        visual_factory=lambda: VisualSession(on_change=notify),
    )
    translation = TranslationCoordinator(
        inventory,
        cloud,
        lambda choice: TranslationSession(choice.create, cache, on_change=notify),
        RoutedTranslationSession.assigned,
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
        translation,
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
    from jp_overlay.first_run import run_setup
    from jp_overlay.gguf_models import save_registration
    from jp_overlay.gguf_probe import ImportTest
    from jp_overlay.hardware import detect_adapters, recommended_profile
    from jp_overlay.model_store import ModelOperation, install_model
    from jp_overlay.runtime_setup import PROFILES, install_runtime, ready_runtime, select_runtime
    from jp_overlay.setup_coordinator import RuntimeStatus, SetupCoordinator, SetupDependencies

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


def cloud_services() -> CloudServices:
    service = CloudServices(CloudProfiles(), WindowsSecrets, ChatGPTConnections())
    service.start()
    return service


def model_inventory(
    models: tuple[ModelBundle, ...],
    provider: Callable[[], tuple[BackendChoice, ...]],
) -> ModelInventory:
    inventory = ModelInventory(partial(inspect_models, models, provider), mark_prepared)
    inventory.advance(0)
    return inventory
