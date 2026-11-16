"""Bounded background model discovery and preparation receipts.

The UI reads cached values only. A refresh during an active scan invalidates that
scan and coalesces into one follow-up. A slow fallback detects external file edits,
with its deadline measured from completion. Successful preparation remains owned by
the model lifecycle even if receipt persistence fails or an older scan completes.
"""

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

from dantejp.application.model_values import ModelFile as ModelFile
from dantejp.runtime.model_store import ModelBundle
from dantejp.translation.models.gguf import available
from dantejp.translation.worker import BackendChoice

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InventoryData:
    backends: tuple[BackendChoice, ...] = ()
    files: tuple[ModelFile, ...] = ()
    prepared: frozenset[str] = frozenset()
    device: str | None = None
    import_problem: str = ""

    @property
    def ocr_ready(self) -> bool:
        return all(item.present for item in self.files if item.key == "ocr")


@dataclass(frozen=True)
class InventorySnapshot:
    revision: int = 0
    data: InventoryData = InventoryData()
    loaded: bool = False
    problem: str = ""


def inspect_models(
    bundles: tuple[ModelBundle, ...],
    backends: Callable[[], tuple[BackendChoice, ...]],
    *,
    include_imports: bool = True,
) -> InventoryData:
    """Worker-side filesystem/runtime boundary, shared by startup and explicit refresh."""
    from dantejp.runtime.llama import installed_device, supports_plamo
    from dantejp.runtime.model_store import is_prepared, model_status
    from dantejp.translation.models.gguf import read_registry

    choices = backends()
    device = installed_device()
    plamo = supports_plamo()
    files = tuple(
        ModelFile(
            b.key,
            b.name,
            b.description,
            b.category,
            b.size,
            b.present(),
            b.included,
            b.language_model,
            b.needs_plamo,
            str(b.directory),
            str(b.bundled_directory or ""),
            str(b.local_directory),
            model_status(b),
            device,
            b.needs_plamo and not plamo,
        )
        for b in bundles
    )
    import_problem = ""
    try:
        imported = read_registry() if include_imports else ()
    except (OSError, ValueError) as error:
        imported = ()
        import_problem = f"Cannot read imported models: {error}"
    for model in imported:
        present = available(model)
        files += (
            ModelFile(
                model.key,
                model.name,
                f"Imported · {model.architecture} · {model.size / 2**30:.2f} GiB on disk. "
                "Local Japanese → English translation. Quality depends on the model.",
                "translation",
                model.size,
                present,
                False,
                True,
                model.profile == "plamo3",
                model.path,
                "",
                model.path,
                "File is missing or changed size. Use Locate file to check its new location."
                if not present
                else "Language-model engine missing. Open Acceleration to set up CPU or GPU."
                if device is None
                else "Local model registered. Select it on the main screen to prepare and use it.",
                device,
                model.profile == "plamo3" and not plamo,
                model,
            ),
        )
    return InventoryData(
        choices,
        files,
        frozenset(c.preparation_id for c in choices if is_prepared(c.preparation_id)),
        device,
        import_problem,
    )


class ModelInventory:
    def __init__(
        self,
        inspect: Callable[[], InventoryData],
        record: Callable[[str], None],
        *,
        on_change: Callable[[], None] = lambda: None,
        initial: InventoryData | None = None,
        interval: float = 30.0,
    ) -> None:
        self._inspect, self._record, self._notify = inspect, record, on_change
        self._snapshot = InventorySnapshot(
            data=initial or InventoryData(), loaded=initial is not None
        )
        self._interval = interval
        self._due = 0.0
        self._epoch = 0
        self._worker: threading.Thread | None = None
        self._result: tuple[int, InventoryData | None, str] | None = None
        self._receipts: set[str] = set()
        self._receipt_problem = ""
        self._closed = False

    def snapshot(self) -> InventorySnapshot:
        return self._snapshot

    def prepared(self, choice: BackendChoice) -> bool:
        return not choice.preparation_id or choice.preparation_id in self._snapshot.data.prepared

    def invalidate(self) -> None:
        self._epoch += 1
        self._due = 0.0

    def record_prepared(self, key: str) -> None:
        if key:
            if len(self._receipts) >= 64 and key not in self._receipts:
                raise OSError("Preparation receipt queue is full.")
            self._receipts.add(key)
            self.invalidate()

    def close(self) -> None:
        self._closed = True

    def resume(self) -> None:
        """Restart failure leaves this process usable, after all workers have drained."""
        assert self.finished
        self._closed = False
        self.invalidate()

    @property
    def finished(self) -> bool:
        return self._worker is None and not self._receipts

    def advance(self, now: float) -> bool:
        changed = False
        if self._worker is not None:
            if self._worker.is_alive():
                return False
            self._worker = None
            result, self._result = self._result, None
            if result is not None:
                epoch, data, problem = result
                if epoch == self._epoch:
                    # Successful and failed scans both get an idle interval. An invalidated
                    # scan must instead leave its immediate follow-up pending.
                    self._due = now + self._interval
                    current = self._snapshot
                    changed = data is not None and data != current.data
                    self._snapshot = InventorySnapshot(
                        current.revision
                        + int(changed or current.problem != problem or not current.loaded),
                        data if data is not None else current.data,
                        current.loaded or data is not None,
                        problem,
                    )
        if self._worker is not None or (self._closed and not self._receipts):
            return changed
        if now < self._due and not self._receipts:
            return changed
        epoch = self._epoch
        receipts = tuple(self._receipts)
        self._receipts.clear()

        def work() -> None:
            if receipts:
                self._receipt_problem = ""
            for key in receipts:
                try:
                    self._record(key)
                except OSError as error:
                    logger.warning("Could not save preparation receipt: %s", error)
                    self._receipt_problem = f"Could not save model preparation: {error}"
            try:
                data = self._inspect()
                problem = "\n".join(p for p in (self._receipt_problem, data.import_problem) if p)
                result = (epoch, data, problem)
            except Exception as error:
                result = (epoch, None, str(error))
            self._result = result
            self._notify()

        self._worker = threading.Thread(target=work, name="model-inventory", daemon=True)
        self._worker.start()
        return changed
