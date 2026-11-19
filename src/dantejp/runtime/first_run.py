"""Explicit first-run setup plan, using the existing bounded model/runtime installers."""

import threading
from dataclasses import dataclass, replace
from pathlib import Path

from dantejp.i18n import tr
from dantejp.runtime.hardware_values import HardwareStatus
from dantejp.runtime.llama import supports_plamo
from dantejp.runtime.model_store import Cancelled, ModelBundle, install_model
from dantejp.runtime.setup import install_runtime, ready_runtime
from dantejp.runtime.setup_values import ModelProgress, Progress
from dantejp.runtime.values import RuntimeProfile


@dataclass(frozen=True, slots=True)
class SetupPlan:
    models: tuple[ModelBundle, ...]
    runtime: RuntimeProfile | None


def needs_runtime(
    profile: RuntimeProfile, hardware: HardwareStatus, model: ModelBundle | None = None
) -> bool:
    if model is not None and model.needs_plamo and not supports_plamo():
        return True
    if profile.key == "nvidia":
        return not (hardware.cuda_ocr and hardware.llama_device == "cuda")
    device = "vulkan" if profile.key == "amd" else "cpu"
    return hardware.cuda_ocr or hardware.llama_device != device


def run_setup(
    plan: SetupPlan, root: Path, progress: Progress, cancel: threading.Event
) -> Path | None:
    count = len(plan.models) + bool(plan.runtime)
    for index, model in enumerate(plan.models, 1):
        if cancel.is_set():
            raise Cancelled()
        install_model(
            model,
            lambda value, model=model, index=index: progress(
                replace(
                    value,
                    message=f"{model.name}\n{value.message}",
                    stage=index,
                    stages=count,
                )
            ),
            cancel,
        )
    target = None
    profile = plan.runtime
    if profile:
        install_runtime(
            root,
            profile,
            lambda value: progress(
                replace(
                    value,
                    message=f"{profile.name}\n{value.message}",
                    stage=count,
                    stages=count,
                )
            ),
            cancel,
        )
        target = ready_runtime(root, profile.key)
        if target is None:
            raise RuntimeError(tr("The installed runtime did not pass verification. Retry setup."))
    progress(
        ModelProgress(
            tr("Setup files are ready. Model preparation happens before first use."),
            stage=count,
            stages=count,
        )
    )
    return target
