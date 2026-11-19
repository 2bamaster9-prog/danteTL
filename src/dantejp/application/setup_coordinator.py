"""Application-owned setup jobs, including import suspension and reviewed first-run intent.

The fixed lanes preserve existing concurrency: model download and import are mutually
exclusive; runtime setup and the explicit first-run guide have their own bounded jobs.
Views may disappear while these owners continue to advance and drain.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from dantejp.application.model_inventory import ModelInventory
from dantejp.application.model_values import ModelFile
from dantejp.i18n import tr
from dantejp.runtime.first_run import SetupPlan
from dantejp.runtime.hardware_values import HardwareStatus
from dantejp.runtime.model_store import ModelBundle, ModelOperation
from dantejp.runtime.setup_values import ModelProgress, Progress
from dantejp.runtime.setup_values import RuntimeStatus as RuntimeStatus
from dantejp.runtime.setup_values import SetupJob as SetupJob
from dantejp.runtime.setup_values import SetupLane as SetupLane
from dantejp.runtime.setup_values import SetupReview as SetupReview
from dantejp.runtime.values import RuntimeProfile
from dantejp.translation.models.probe import ImportTest
from dantejp.translation.models.values import ImportedModel, ProbeResult


@dataclass(frozen=True)
class SetupDependencies:
    operation: Callable[[Callable[[Progress, threading.Event], None]], ModelOperation]
    install_model: Callable[[ModelBundle, Progress, threading.Event], None]
    remove_import: Callable[[ImportedModel], None]
    save_import: Callable[[ImportedModel], None]
    probe: Callable[[Path, str, str, threading.Event], ImportTest]
    runtime_status: Callable[[], RuntimeStatus]
    install_runtime: Callable[[str, Progress, threading.Event], None]
    select_runtime: Callable[[Path], None]
    run_setup: Callable[[SetupPlan, Progress, threading.Event], Path | None]


class SetupCoordinator:
    def __init__(
        self,
        inventory: ModelInventory,
        models: tuple[ModelBundle, ...],
        profiles: tuple[RuntimeProfile, ...],
        dependencies: SetupDependencies,
    ) -> None:
        self.inventory, self._models, self.profiles, self._dependencies = (
            inventory,
            {m.key: m for m in models},
            profiles,
            dependencies,
        )
        self._jobs = {lane: SetupJob() for lane in SetupLane}
        self._operations: dict[SetupLane, ModelOperation] = {}
        self._closed = False
        self._serial = 0
        self._gate = threading.Event()
        self._probe: ImportTest | None = None
        self._expected: ImportedModel | None = None
        self._probe_result: ProbeResult | None = None
        self._runtime = RuntimeStatus()
        self._runtime_result: RuntimeStatus | None = None
        self._review: SetupReview | None = None
        self._plan: SetupPlan | None = None
        self._guide_target: Path | None = None
        self._completed_review: int | None = None

    def set_models(self, models: tuple[ModelBundle, ...]) -> None:
        self._models = {model.key: model for model in models}
        self._review = self._plan = None

    @property
    def inventory_revision(self) -> int:
        return self.inventory.snapshot().revision

    @property
    def files(self) -> tuple[ModelFile, ...]:
        return self.inventory.snapshot().data.files

    @property
    def guide_models(self) -> tuple[ModelFile, ...]:
        """Only downloadable bundles participate in the guide's install/review flow."""
        return tuple(
            model
            for model in self.files
            if model.key in self._models and model.category == "translation"
        )

    def job(self, lane: SetupLane) -> SetupJob:
        job = self._jobs[lane]
        operation = self._operations.get(lane)
        return replace(job, progress=operation.snapshot()) if operation else job

    @property
    def busy(self) -> bool:
        return bool(self._operations)

    @property
    def problem(self) -> str:
        return next((j.progress.error for j in self._jobs.values() if j.progress.error), "")

    def _start(
        self,
        lane: SetupLane,
        action: str,
        key: str,
        work: Callable[[Progress, threading.Event], None],
    ) -> bool:
        if self._closed or lane in self._operations:
            return False
        self._serial += 1
        operation = self._dependencies.operation(work)
        self._jobs[lane] = SetupJob(self._serial, action, key, True)
        self._operations[lane] = operation
        operation.start()
        return True

    def download(self, key: str) -> bool:
        bundle = self._models.get(key)
        if bundle is None:
            return False
        return self._start(
            SetupLane.MODELS,
            "download",
            key,
            lambda progress, cancel: self._dependencies.install_model(bundle, progress, cancel),
        )

    def remove(self, key: str) -> bool:
        model = next((f.imported for f in self.files if f.key == key), None)
        if model is None:
            return False
        return self._start(
            SetupLane.MODELS,
            "remove",
            key,
            lambda progress, cancel: self._dependencies.remove_import(model),
        )

    def begin_import(self, expected: ImportedModel | None = None) -> bool:
        if self._closed or self.job(SetupLane.MODELS).busy:
            return False
        if expected == self._expected and self._probe_result is not None:
            return True
        self._expected, self._probe_result = expected, None
        return True

    def invalidate_import(self) -> None:
        if not self.job(SetupLane.MODELS).busy:
            self._probe_result = None

    @property
    def probe_result(self) -> ProbeResult | None:
        return self._probe_result

    @property
    def probing(self) -> bool:
        job = self.job(SetupLane.MODELS)
        return job.busy and job.action == "probe"

    def permit_probe(self) -> None:
        if self.probing:
            self._gate.set()

    def test_import(self, path: str, profile: str) -> bool:
        if self._closed or self.job(SetupLane.MODELS).busy:
            return False
        device = self.inventory.snapshot().data.device
        if not device:
            self._serial += 1
            self._jobs[SetupLane.MODELS] = SetupJob(
                self._serial,
                "probe",
                progress=ModelProgress(
                    done=True,
                    error=tr(
                        "A language-model engine is needed. "
                        "Open Settings → Acceleration and select CPU or GPU."
                    ),
                ),
            )
            return False
        self._gate.clear()
        self._probe_result = None
        self._probe = self._dependencies.probe(Path(path), profile, device, self._gate)
        return self._start(SetupLane.MODELS, "probe", path, self._probe.run)

    def save_import(self, name: str) -> bool:
        result = self._probe_result
        if result is None:
            return False
        model = replace(
            result.model, name=" ".join(name.split()) or Path(result.model.path).stem[:100]
        )
        return self._start(
            SetupLane.MODELS,
            "register",
            model.key,
            lambda progress, cancel: self._dependencies.save_import(model),
        )

    @property
    def runtime(self) -> RuntimeStatus:
        return self._runtime

    def detect_runtime(self) -> bool:
        def work(progress: Progress, cancel: threading.Event) -> None:
            self._runtime_result = self._dependencies.runtime_status()
            progress(ModelProgress(tr("Hardware check complete. Nothing has been installed.")))

        return self._start(SetupLane.RUNTIME, "detect", "", work)

    def install_runtime(self, key: str) -> bool:
        if key not in {p.key for p in self.profiles}:
            return False

        def work(progress: Progress, cancel: threading.Event) -> None:
            self._dependencies.install_runtime(key, progress, cancel)
            self._runtime_result = self._dependencies.runtime_status()

        return self._start(SetupLane.RUNTIME, "install", key, work)

    def use_next_launch(self, key: str) -> bool:
        target = self._runtime.target(key)
        if target is None:
            return False

        def work(progress: Progress, cancel: threading.Event) -> None:
            self._dependencies.select_runtime(target)
            progress(
                ModelProgress(tr("Selected for next launch. This session continues unchanged."))
            )

        return self._start(SetupLane.RUNTIME, "select", key, work)

    def review(self, model_key: str, runtime_key: str, hardware: HardwareStatus) -> SetupReview:
        if self.job(SetupLane.GUIDE).busy:
            raise ValueError(
                tr("Wait for the active setup to finish before reviewing another plan.")
            )
        selected_file = next((f for f in self.guide_models if f.key == model_key), None)
        if selected_file is None:
            raise ValueError(tr("Choose a translation model offered by the setup guide."))
        model, ocr = self._models[model_key], self._models["ocr"]
        files = {f.key: f for f in self.files}
        profile = next(p for p in self.profiles if p.key == runtime_key)
        needs = selected_file.upgrade or (
            not (hardware.cuda_ocr and hardware.llama_device == "cuda")
            if runtime_key == "nvidia"
            else hardware.cuda_ocr
            or hardware.llama_device != ("vulkan" if runtime_key == "amd" else "cpu")
        )
        plan = SetupPlan(
            (() if files["ocr"].included else (ocr,)) + (model,), profile if needs else None
        )
        self._serial += 1
        self._plan = plan
        self._review = SetupReview(
            self._serial,
            model_key,
            runtime_key,
            sum(m.size for m in plan.models if not files[m.key].present),
            bool(plan.runtime),
            tuple(m.key for m in plan.models),
        )
        return self._review

    def start_review(self, token: int) -> bool:
        if (
            self._closed
            or self.job(SetupLane.GUIDE).busy
            or self._review is None
            or self._review.token != token
            or self._completed_review == token
            or self._plan is None
        ):
            return False
        plan = self._plan
        self._guide_target = None

        def work(progress: Progress, cancel: threading.Event) -> None:
            self._guide_target = self._dependencies.run_setup(plan, progress, cancel)

        return self._start(SetupLane.GUIDE, "setup", self._review.model, work)

    @property
    def reviewed(self) -> SetupReview | None:
        return self._review

    @property
    def guide_target(self) -> Path | None:
        job = self.job(SetupLane.GUIDE)
        return (
            self._guide_target
            if (
                job.progress.done and not (job.busy or job.progress.cancelled or job.progress.error)
            )
            else None
        )

    def selection_id(self, key: str) -> str:
        return self._models[key].selection_id

    def cancel(self, lane: SetupLane) -> None:
        operation = self._operations.get(lane)
        if operation:
            self._jobs[lane] = replace(self._jobs[lane], cancelling=True)
            operation.cancel()

    def close(self) -> None:
        self._closed = True
        for lane in SetupLane:
            self.cancel(lane)

    def resume(self) -> None:
        assert not self.busy
        self._closed = False

    def advance(self) -> None:
        for lane, operation in tuple(self._operations.items()):
            value = operation.snapshot()
            if not value.done:
                continue
            job = self._jobs[lane]
            if job.cancelling and not (value.cancelled or value.error):
                value = replace(
                    value, cancelled=True, message=tr("Cancelled. Verified files were kept.")
                )
            succeeded = not (value.error or value.cancelled)
            if lane == SetupLane.MODELS and job.action == "probe":
                result = self._probe.result if self._probe and succeeded else None
                if result and self._expected and result.model.key != self._expected.key:
                    value = replace(
                        value,
                        error=tr(
                            "This is a different model. Import it separately; "
                            "the original registration was kept."
                        ),
                    )
                    result = None
                self._probe_result, self._probe = result, None
            if lane == SetupLane.RUNTIME and self._runtime_result is not None:
                if succeeded:
                    self._runtime = self._runtime_result
                self._runtime_result = None
            self._jobs[lane] = replace(job, busy=False, progress=value)
            del self._operations[lane]
            if succeeded and lane == SetupLane.GUIDE and self._review is not None:
                self._completed_review = self._review.token
            if succeeded and lane == SetupLane.MODELS and job.action == "register":
                self._probe_result = None
            if succeeded and job.action in {"download", "remove", "register", "install", "setup"}:
                self.inventory.invalidate()
