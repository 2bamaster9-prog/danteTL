"""Two explicit translation lanes, sharing scene validity but never blocking each other."""

from collections.abc import Callable
from pathlib import Path

from jp_overlay.grouping import TextBlock
from jp_overlay.model_selection import CloudIdentity, LocalIdentity
from jp_overlay.tracking import TextTrack
from jp_overlay.translation import TranslationSession
from jp_overlay.translation_backend import TranslationBackend
from jp_overlay.translation_plan import TranslationPlan, is_long_text
from jp_overlay.translation_values import (
    TranslationLaneSnapshot,
    TranslationRequest,
    TranslationSnapshot,
    TranslationState,
)

type ModelIdentity = LocalIdentity | CloudIdentity | str

ROUTES = {
    "local": "Local only",
    "cloud": "Cloud for all text",
    "long": "Cloud for dialogue & longer text",
    "short": "Cloud for short labels",
}


def use_cloud(item: TextTrack | TextBlock, mode: str) -> bool:
    long = is_long_text(item)
    return mode == "cloud" or (mode == "long" and long) or (mode == "short" and not long)


class RoutedTranslationSession:
    """At most two model workers, with unchanged request routes pinned.

    Local preparation can hand over an already-started worker. Existing model
    prompts and loading contracts remain the responsibility of TranslationSession.
    """

    def __init__(
        self,
        local: TranslationSession | None,
        cloud: Callable[[], TranslationBackend],
        cache_path: Path,
        *,
        mode: str,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.local = local
        self.cloud: TranslationSession | None = TranslationSession(
            cloud, cache_path, on_change=on_change
        )
        self._cache_path, self._notify = cache_path, on_change
        self._mode = mode
        self._routes: dict[TranslationRequest, str] = {}
        self._stopping = False
        self._generation = 0
        self._plan: TranslationPlan | None = None
        self._workers = {"local": local, "cloud": self.cloud}
        self._unstarted = (self.cloud,)
        self._retiring: list[TranslationSession] = []
        self._factories: dict[str, Callable[[], TranslationBackend]] = {}
        self._identities: dict[str, ModelIdentity] = {}
        self._names: dict[str, str] = {}

    @classmethod
    def assigned(
        cls,
        plan: TranslationPlan,
        factories: dict[str, Callable[[], TranslationBackend]],
        cache_path: Path,
        *,
        prepared: tuple[str, TranslationSession] | None = None,
        on_change: Callable[[], None] | None = None,
        identities: dict[str, ModelIdentity] | None = None,
        names: dict[str, str] | None = None,
    ) -> "RoutedTranslationSession":
        """Adopt one prepared owner and share one worker for identical assignments.

        Missing models remain unavailable; never silently change a billing route.
        Reconfiguration retains identical owners and drains only replaced workers.
        """
        if prepared and prepared[0] not in plan.active_models:
            raise ValueError("Prepared model does not belong to the active translation plan.")
        result = cls.__new__(cls)
        result._cache_path, result._notify = cache_path, on_change
        result._mode, result._plan = "assigned", plan
        result._routes = {}
        result._stopping, result._generation = False, 0
        result._workers = {}
        result._retiring = []
        result._factories = {k: factories[k] for k in plan.active_models if k in factories}
        result._identities = {k: (identities or {}).get(k, k) for k in plan.active_models}
        result._names = {k: (names or {}).get(k, k) for k in plan.active_models}
        unstarted = []
        for key in plan.active_models:
            if prepared and prepared[0] == key:
                result._workers[key] = prepared[1]
            elif key in factories:
                worker = TranslationSession(factories[key], cache_path, on_change=on_change)
                result._workers[key] = worker
                unstarted.append(worker)
        result._unstarted = tuple(unstarted)
        result.local = result.cloud = None
        return result

    def start(self) -> None:
        for worker in self._unstarted:
            worker.start()
        self._unstarted = ()

    @property
    def stopping(self) -> bool:
        return self._stopping

    def reconfigure(
        self,
        plan: TranslationPlan,
        factories: dict[str, Callable[[], TranslationBackend]],
        *,
        identities: dict[str, ModelIdentity] | None = None,
        names: dict[str, str] | None = None,
    ) -> None:
        """Keep unchanged owners; coalesce pending replacements until cleanup completes.

        Retiring workers never publish. No replacement starts until retirement finishes,
        so repeated edits cannot accumulate native models or cloud clients. Existing
        workers keep processing while a changed lane drains.
        """
        if self._plan is None or self._stopping:
            raise ValueError("Cannot reconfigure an unassigned or stopping session.")
        desired = {k: factories[k] for k in plan.active_models if k in factories}
        next_identities = {k: (identities or {}).get(k, k) for k in plan.active_models}
        for key, worker in tuple(self._workers.items()):
            if key not in desired or self._identities.get(key) != next_identities[key]:
                del self._workers[key]
                if worker:
                    worker.request_stop()
                    self._retiring.append(worker)
        self._plan, self._factories = plan, desired
        self._identities = next_identities
        self._names = {k: (names or {}).get(k, k) for k in plan.active_models}
        self._generation += 1
        self._routes.clear()
        self.advance()

    def advance(self) -> None:
        """Adopt completed cleanup without making snapshot reads change resource state."""
        self._retiring = [worker for worker in self._retiring if not worker.finished]
        if self._stopping or self._plan is None or self._retiring:
            return
        for key, factory in self._factories.items():
            if key not in self._workers:
                worker = TranslationSession(factory, self._cache_path, on_change=self._notify)
                self._workers[key] = worker
                worker.start()

    def update(
        self,
        tracks: tuple[TextTrack | TextBlock, ...],
        *,
        retain: tuple[TextBlock, ...] = (),
        reset_context: bool = False,
        corrections: tuple[tuple[TextTrack, TextTrack], ...] = (),
    ) -> None:
        self.advance()

        def key(item: TextTrack | TextBlock) -> TranslationRequest:
            return (
                TranslationRequest.from_block(item)
                if isinstance(item, TextBlock)
                else TranslationRequest.from_track(item)
            )

        current = {key(item): item for item in (*tracks[:128], *retain[:128])}
        self._routes = {
            request: self._routes.get(request, self._destination(item))
            for request, item in list(current.items())[:128]
        }
        for remote, worker in self._workers.items():
            if worker is not None:
                worker.update(
                    tuple(item for item in tracks[:128] if self._routes.get(key(item)) == remote),
                    retain=tuple(
                        item for item in retain[:128] if self._routes.get(key(item)) == remote
                    ),
                    reset_context=reset_context,
                    corrections=corrections,
                )

    def _destination(self, item: TextTrack | TextBlock) -> str:
        if self._plan:
            return self._plan.model_for(item)
        return "cloud" if use_cloud(item, self._mode) else "local"

    def invalidate(self) -> None:
        self._routes.clear()
        for worker in self._workers.values():
            if worker:
                worker.invalidate()

    def switch_backend(self, factory: Callable[[], TranslationBackend]) -> None:
        if self._plan:
            raise ValueError("Assigned model changes require reconfigure().")
        self._generation += 1
        self.invalidate()
        if self._mode == "cloud":
            return
        if self.local is None:
            self.local = TranslationSession(factory, self._cache_path, on_change=self._notify)
            self._workers["local"] = self.local
            self.local.start()
        else:
            self.local.switch_backend(factory)

    def request_stop(self) -> None:
        self._stopping = True
        self.invalidate()
        for worker in self._workers.values():
            if worker:
                worker.request_stop()
        for worker in self._retiring:
            worker.request_stop()

    @property
    def finished(self) -> bool:
        return (
            self._stopping
            and all(worker.finished for worker in self._workers.values() if worker)
            and all(worker.finished for worker in self._retiring)
        )

    def snapshot(self) -> TranslationSnapshot:
        lanes = {key: worker.snapshot() for key, worker in self._workers.items() if worker}
        snapshots = list(lanes.values())
        pending_models = tuple(k for k in self._factories if k not in self._workers)
        if self._stopping:
            state = TranslationState.STOPPED if self.finished else TranslationState.STOPPING
        elif not pending_models and all(s.state == TranslationState.FAILED for s in snapshots):
            state = TranslationState.FAILED
        elif any(s.state == TranslationState.READY for s in snapshots):
            state = TranslationState.READY
        else:
            state = TranslationState.LOADING
        processing = [s.processing_since for s in snapshots if s.processing_since is not None]
        results = []
        for remote, snapshot in lanes.items():
            results.extend(
                result for result in snapshot.results if self._routes.get(result.request) == remote
            )
        return TranslationSnapshot(
            state,
            tuple(results),
            sum(s.pending for s in snapshots),
            max((s.last_batch_ms for s in snapshots), default=0),
            " · ".join(s.message for s in snapshots if s.message),
            processing_since=min(processing) if processing else None,
            queue_ms=max((s.queue_ms for s in snapshots), default=0),
            cache_hits=sum(s.cache_hits for s in snapshots),
            translated_sources=sum(s.translated_sources for s in snapshots),
            load_ms=max((s.load_ms for s in snapshots), default=0),
            last_inference_ms=max((s.last_inference_ms for s in snapshots), default=0),
            backend_generation=self._generation,
            rejected=tuple(r for s in snapshots for r in s.rejected),
            lanes=tuple(
                TranslationLaneSnapshot(
                    key,
                    self._names.get(key, key),
                    lanes[key].state if key in lanes else TranslationState.LOADING,
                    lanes[key].message if key in lanes else "Waiting for previous model to unload…",
                )
                for key in (*lanes, *pending_models)
            ),
        )
