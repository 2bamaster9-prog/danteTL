"""Cheap frame evidence, OCR pacing, and reversible occlusion on a bounded worker."""

import logging
import threading
import time
from dataclasses import dataclass, field, replace
from math import ceil
from typing import Any

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.recognition import OcrResult
from jp_overlay.regions import padded, scan_regions
from jp_overlay.text_content import content_region, has_japanese
from jp_overlay.tracking import TextActivity, TextTrack

logger = logging.getLogger(__name__)
cv2: Any
np: Any


@dataclass(frozen=True, slots=True)
class VisualState:
    frame: CapturedFrame | None = None
    request_ocr: bool = False
    hidden: frozenset[TextTrack] = frozenset()
    blocked: frozenset[int] = frozenset()
    stable_regions: tuple[int, ...] = ()
    ocr_sequence: int = 0
    duration_ms: float = 0
    avoided: int = 0
    message: str = ""
    absent: frozenset[TextTrack] = frozenset()
    checked_sequence: int = 0
    unchanged: frozenset[TextTrack] = frozenset()
    checked: frozenset[TextTrack] = frozenset()
    scan_areas: tuple[Rect, ...] | None = None
    stable_tracks: tuple[tuple[int, int, str], ...] = ()
    changed_areas: tuple[Rect, ...] = ()


@dataclass(frozen=True, slots=True)
class _Job:
    frame: CapturedFrame
    result: OcrResult | None
    tracks: tuple[TextTrack, ...]
    assignments: tuple[int | None, ...]
    activity: tuple[TextActivity, ...]
    candidate: OcrResult | None = None


def _pixels(frame: CapturedFrame) -> Any:
    if len(frame.bgra) != frame.width * frame.height * 4:
        return None
    return np.frombuffer(frame.bgra, np.uint8).reshape(frame.height, frame.width, 4)


def _crop(pixels: Any, bounds: Rect, *, wide: bool = False) -> Any:
    h, w = pixels.shape[:2]
    if min(bounds.size) < 2 or not Rect(0, 0, w, h).contains(bounds):
        return None
    # Every template is at most 256 x 48; no source-sized crop copies are retained.
    size = (256 if wide else min(256, bounds.width), min(48, bounds.height))
    step = max(1, ceil(max(bounds.width / 1024, bounds.height / 192)))
    small = cv2.resize(
        pixels[
            bounds.y : bounds.y + bounds.height : step,
            bounds.x : bounds.x + bounds.width : step,
        ],
        size,
        interpolation=cv2.INTER_AREA,
    )
    return cv2.cvtColor(small, cv2.COLOR_BGRA2GRAY).astype(np.float32)


def _edges(gray: Any) -> tuple[Any, Any]:
    return (
        cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=1),
        cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=1),
    )


def _changed(a: Any, b: Any) -> bool:
    if np.array_equal(a, b):
        return False
    # Gradients reject uniform brightness shifts; require more than a few noisy pixels.
    ax, ay = _edges(a)
    bx, by = _edges(b)
    return float(np.mean(np.maximum(np.abs(ax - bx), np.abs(ay - by)) > 35)) > 0.018


def _added_ink(a: Any, b: Any, *, foreground: bool = False) -> bool:
    """Append-like stroke additions, rather than general background replacement."""
    if foreground:
        dark = float(np.median(a)) > float(np.mean(a))
        old, new = _ink(a, dark), _ink(b, dark)
        if old is None or new is None:
            return False
        before, after = (old >= 0.65).astype(np.uint8), (new >= 0.65).astype(np.uint8)
    else:
        ax, ay = _edges(a)
        bx, by = _edges(b)
        before = (np.maximum(np.abs(ax), np.abs(ay)) > 45).astype(np.uint8)
        after = (np.maximum(np.abs(bx), np.abs(by)) > 45).astype(np.uint8)
    kernel = np.ones((3, 3), np.uint8)
    added = int(np.count_nonzero(after & ~cv2.dilate(before, kernel)))
    removed = int(np.count_nonzero(before & ~cv2.dilate(after, kernel)))
    return added > max(12, removed * 1.8) and (foreground or added < after.size * 0.2)


def _ink(gray: Any, dark: bool) -> Any:
    """High-contrast glyph cores; ignore dim texture behind translucent game labels."""
    gray = 255 - gray if dark else gray
    low, high = np.percentile(gray, (15, 99))
    if high - low < 45:
        return None
    return np.clip((gray - low) / (high - low), 0, 1)


def _same_ink(reference: Any, current: Any) -> bool | None:
    if np.array_equal(reference, current):
        return True
    dark = float(np.median(reference)) > float(np.mean(reference))
    before = _ink(reference, dark)
    if before is None or np.count_nonzero(before >= 0.75) < 24:
        return None
    # Hover states may invert colors. Align at most one sampled pixel; never follow
    # detector geometry to decide whether the accepted region changed.
    padded = cv2.copyMakeBorder(current, 1, 1, 1, 1, cv2.BORDER_REPLICATE)
    scores = cv2.matchTemplate(padded, reference, cv2.TM_CCOEFF_NORMED)
    y, x = np.unravel_index(np.argmax(np.abs(scores)), scores.shape)
    aligned = padded[y : y + reference.shape[0], x : x + reference.shape[1]]
    after = _ink(aligned, dark if scores[y, x] >= 0 else not dark)
    if after is None:
        return False
    # Local cells catch one changed digit/stroke in a long label. Whole-box averages
    # would conceal a small but meaningful edit among many unchanged characters.
    step = max(6, reference.shape[0] // 2)
    for left in range(0, reference.shape[1], step):
        a, b = before[:, left : left + step], after[:, left : left + step]
        difference = int(np.count_nonzero(((a >= 0.75) & (b < 0.55)) | ((b >= 0.75) & (a < 0.55))))
        if difference > max(4, int(np.count_nonzero((a >= 0.65) | (b >= 0.65))) * 0.12):
            return False
    return True


@dataclass(slots=True)
class _Anchor:
    value: TextTrack
    reference: Any
    extension_bounds: Rect | None = None
    extension: Any = None
    x: Any = field(init=False)
    y: Any = field(init=False)
    mask: Any = field(init=False)
    misses: int = 0
    hits: int = 0
    hidden: bool = False
    last_sequence: int = 0

    def __post_init__(self) -> None:
        self.x, self.y = _edges(self.reference)
        strength = np.maximum(np.abs(self.x), np.abs(self.y))
        self.mask = strength >= max(35, float(np.percentile(strength, 80)))

    def content_matches(self, pixels: Any) -> bool | None:
        crop = _crop(pixels, self.value.bounds)
        same = None if crop is None else _same_ink(self.reference, crop)
        if same is True and self.extension is not None and self.extension_bounds is not None:
            extension = _crop(pixels, self.extension_bounds, wide=True)
            if extension is not None and _added_ink(self.extension, extension, foreground=True):
                return False  # Newly revealing characters can extend past the accepted box.
        return same

    def observe(self, pixels: Any, sequence: int, changed: bool) -> bool:
        if sequence == self.last_sequence:
            return self.hidden
        needs_check = (
            changed
            or not self.last_sequence
            or self.misses == 1
            or (self.hidden and self.hits == 1)
        )
        self.last_sequence = sequence
        if not needs_check:
            return self.hidden
        current = _crop(pixels, self.value.bounds)
        if current is None or int(self.mask.sum()) < 24:
            return False  # Insufficient stroke evidence: let OCR decide.
        if _same_ink(self.reference, current) is True:
            self.misses = 0
            self.hits += 1
            if self.hits >= 2:
                self.hidden = False
            return self.hidden
        x, y = _edges(current)
        # A one-pixel tolerance allows antialiasing and tiny camera/text shifts.
        kernel = np.ones((3, 3), np.uint8)
        matches = np.zeros(self.mask.shape, dtype=bool)
        for old, new in ((self.x, x), (self.y, y)):
            for sign in (-1, 1):
                wanted = old * sign >= 35
                nearby = cv2.dilate(new * sign, kernel)
                matches |= wanted & (nearby >= np.maximum(12, np.abs(old) * 0.3))
        coverage = float(np.mean(matches[self.mask]))
        correlation = float(
            np.max(
                np.abs(
                    cv2.matchTemplate(
                        cv2.copyMakeBorder(current, 1, 1, 1, 1, cv2.BORDER_REPLICATE),
                        self.reference,
                        cv2.TM_CCOEFF_NORMED,
                    )
                )
            )
        )
        # Unrelated textured backgrounds can accidentally match many individual
        # edges. Require the spatial pattern too, with brightness/shift tolerance.
        if (coverage < 0.12 and correlation < 0.4) or correlation < 0.1:
            self.hits = 0
            self.misses += 1
            if self.misses >= 2:
                self.hidden = True
        elif coverage >= 0.4 or correlation >= 0.6:
            self.misses = 0
            self.hits += 1
            if self.hits >= 2:
                self.hidden = False
        else:
            self.misses = 0  # Ambiguous evidence cannot accumulate disappearance votes.
        return self.hidden


@dataclass(slots=True)
class _Probe:
    index: int
    track_id: int | None
    bounds: Rect
    reference: Any
    previous: Any
    changed_at: float
    dialogue: bool
    source_sequence: int = 0
    source_text: str = ""
    requested_at: float = float("-inf")
    checked: bool = False
    dirty: bool = False
    growth: bool = False


def _touches(tiles: Any, bounds: Rect, size: tuple[int, int]) -> bool:
    w, h = size
    x1, y1 = max(0, bounds.x * 32 // w), max(0, bounds.y * 18 // h)
    x2, y2 = (
        min(32, ceil((bounds.x + bounds.width) * 32 / w)),
        min(18, ceil((bounds.y + bounds.height) * 18 / h)),
    )
    return bool(np.any(tiles[y1:y2, x1:x2]))


class VisualAnalyzer:
    """Pure, explicitly timed policy. Templates are bounded to the current 128 tracks.

    Coarse novelty discovers new UI; local stroke evidence masks vanished text without
    retiring identity. Expanded reading areas catch typewriter growth beyond old boxes.
    A periodic full OCR refresh covers uncertain changes and missed small/animated text.
    """

    def __init__(self) -> None:
        global cv2, np
        import cv2
        import numpy as np

        cv2.setNumThreads(1)
        self._previous: Any = None
        self._streak: Any = np.zeros((18, 32), np.uint8)
        self._anchors: dict[TextTrack, _Anchor] = {}
        self._probes: list[_Probe] = []
        self._ocr_sequence = 0
        self._sequence = 0
        self._size: tuple[int, int] | None = None
        self._last_request = float("-inf")
        self._last_full = float("-inf")
        self._dirty: Any = np.zeros((18, 32), dtype=bool)
        self._followup: float | None = None
        self._followup_areas: tuple[Rect, ...] | None = None
        self._avoided = 0
        self._reference_key: Any = None
        self._checked_key: Any = None
        self._checked: frozenset[TextTrack] = frozenset()
        self._unchanged: frozenset[TextTrack] = frozenset()

    def _references(self, job: _Job, pixels: Any) -> None:
        key = (job.result.frame.sequence if job.result else 0, job.tracks)
        if key == self._reference_key:
            return
        self._reference_key = key
        self._anchors = {t: a for t, a in self._anchors.items() if t in job.tracks}
        result = job.result
        if result is None:
            return
        source = _pixels(result.frame)
        if source is None or source.shape != pixels.shape:
            return
        cleaned = [content_region(r) for r in result.regions[:512]]
        by_id = {
            key: region
            for key, region in zip(job.assignments, cleaned, strict=False)
            if key is not None
        }
        for track in job.tracks[:128]:
            region = by_id.get(track.track_id)
            if track not in self._anchors and region is not None and region.text == track.text:
                crop = _crop(source, track.bounds)
                if crop is not None:
                    b = track.bounds
                    width = max(
                        b.width + b.height * 3, b.height * 36 if len(track.text) >= 10 else 0
                    )
                    area = Rect(b.x, b.y, min(width, job.frame.width - b.x), b.height)
                    self._anchors[track] = _Anchor(
                        track, crop, area, _crop(source, area, wide=True)
                    )
        if result.frame.sequence == self._ocr_sequence:
            return
        self._ocr_sequence = result.frame.sequence
        # A partial observation says nothing about the rest of the screen. Keep
        # those bounded dialogue probes and their exact original pixel references.
        prior = [
            p
            for p in self._probes
            if p.track_id in {t.track_id for t in job.tracks}
            and p.track_id not in by_id
            and result.scanned is not None
        ]
        self._probes = []
        growing = {a.observation.track_id for a in job.activity if a.growing}
        for index, region in enumerate(cleaned):
            if len(self._probes) >= 128:
                break
            key = job.assignments[index] if index < len(job.assignments) else None
            if key is None or not has_japanese(region.text):
                continue
            b = region.bounds
            dialogue = not region.vertical and (len(region.text) >= 10 or key in growing)
            width = max(b.width, b.height * 36) if dialogue else b.width + b.height * 3
            area = Rect(
                b.x,
                b.y,
                min(width, job.frame.width - b.x),
                min(round(b.height * (4 if dialogue else 1.35)), job.frame.height - b.y),
            )
            crop = _crop(source, area, wide=True)
            if crop is not None:
                self._probes.append(
                    _Probe(
                        index,
                        key,
                        area,
                        crop,
                        crop,
                        result.frame.captured_at,
                        dialogue,
                        result.frame.sequence,
                        region.text,
                    )
                )
        self._probes.extend(prior[: 128 - len(self._probes)])

    def observe(
        self,
        frame: CapturedFrame,
        result: OcrResult | None = None,
        tracks: tuple[TextTrack, ...] = (),
        assignments: tuple[int | None, ...] = (),
        activity: tuple[TextActivity, ...] = (),
        candidate: OcrResult | None = None,
    ) -> VisualState:
        started = time.perf_counter()
        pixels = _pixels(frame)
        if pixels is None:
            return VisualState(frame, True, message="Visual evidence unavailable; using OCR.")
        if self._size != frame.geometry.client.size:
            self.__init__()
            self._size = frame.geometry.client.size
        size = frame.geometry.client.size
        fresh = frame.sequence > self._sequence
        self._references(_Job(frame, result, tracks, assignments, activity), pixels)
        checked_key = (candidate.frame.sequence if candidate else 0, tracks)
        if checked_key != self._checked_key:
            self._checked_key = checked_key
            source = _pixels(candidate.frame) if candidate else None
            matches = (
                {t: a.content_matches(source) for t, a in self._anchors.items()}
                if source is not None and source.shape == pixels.shape
                else {}
            )
            self._checked = frozenset(t for t, same in matches.items() if same is not None)
            self._unchanged = frozenset(t for t, same in matches.items() if same is True)
        now = frame.captured_at
        small = cv2.cvtColor(
            cv2.resize(pixels, (640, 360), interpolation=cv2.INTER_AREA), cv2.COLOR_BGRA2GRAY
        )
        changed_tiles = np.ones((18, 32), dtype=bool)
        significant = np.zeros((18, 32), dtype=bool)
        if self._previous is not None and fresh:
            delta = np.abs(small.astype(np.int16) - self._previous.astype(np.int16))
            energy = delta.reshape(18, 20, 32, 20).mean(axis=(1, 3))
            changed_tiles = energy > 0
            tiles = energy > 1.5
            significant = tiles
            self._dirty |= (tiles & (self._streak == 0)) | (~tiles & (self._streak >= 2))
            self._streak = np.where(tiles, np.minimum(self._streak + 1, 8), 0).astype(np.uint8)
        hidden = frozenset(
            key
            for key, anchor in self._anchors.items()
            if anchor.observe(pixels, frame.sequence, _touches(changed_tiles, key.bounds, size))
        )
        stable, blocked = [], set()
        stable_tracks = []
        growing_areas = []
        local_areas = []
        for probe in self._probes:
            if not probe.checked or _touches(changed_tiles, probe.bounds, size):
                current = _crop(pixels, probe.bounds, wide=True)
                if current is None:
                    continue
                if fresh and (
                    _changed(probe.previous, current) or _added_ink(probe.previous, current)
                ):
                    probe.changed_at = now
                probe.dirty = _changed(probe.reference, current)
                probe.growth = _added_ink(probe.reference, current)
                probe.previous, probe.checked = current, True
            dirty, growth = probe.dirty, probe.growth
            quiet = now - probe.changed_at >= 0.16
            if growth and probe.track_id is not None:
                blocked.add(probe.track_id)
            if not dirty and not growth and quiet and frame.sequence > probe.source_sequence:
                if probe.track_id is not None:
                    stable_tracks.append((probe.track_id, probe.source_sequence, probe.source_text))
                if result and probe.source_sequence == result.frame.sequence:
                    stable.append(probe.index)
            if probe.dialogue and growth and not quiet:
                growing_areas.append(probe.bounds)
            if (dirty or growth) and quiet and probe.changed_at > probe.requested_at:
                local_areas.append(padded(probe.bounds, size))
        due = self._followup is not None and now >= self._followup
        refresh = now - self._last_full >= 3.0
        # Delay only the revealing area, not unrelated newly opened UI. Dirty tiles
        # accumulate until requested so rate limiting never loses a one-frame change.
        eligible = self._dirty.copy()
        for b in growing_areas:
            x1, y1 = max(0, b.x * 32 // size[0]), max(0, b.y * 18 // size[1])
            x2, y2 = (
                min(32, ceil((b.x + b.width) * 32 / size[0])),
                min(18, ceil((b.y + b.height) * 18 / size[1])),
            )
            eligible[y1:y2, x1:x2] = False
        count, _, stats, _ = cv2.connectedComponentsWithStats(eligible.astype(np.uint8), 8)
        areas = list(local_areas)
        for x, y, w, h, _ in stats[1:count]:
            left, top = int(x) * size[0] // 32, int(y) * size[1] // 18
            right, bottom = ceil(int(x + w) * size[0] / 32), ceil(int(y + h) * size[1] / 18)
            areas.append(padded(Rect(left, top, right - left, bottom - top), size, 48))
        if due and not growing_areas:
            proposed = None if self._followup_areas is None else (*areas, *self._followup_areas)
        else:
            proposed = tuple(areas)
        coverage = (
            None if refresh else scan_regions(proposed, size, tuple(t.bounds for t in tracks))
        )
        request = fresh and now - self._last_request >= 0.12 and coverage != ()
        if request:
            self._last_request = now
            for probe in self._probes:
                if coverage is None or any(area.contains(probe.bounds) for area in coverage):
                    probe.requested_at = now
            if coverage is None:
                self._last_full = now
                self._dirty[:] = False
            else:
                self._dirty &= ~eligible
            self._followup = None if due or (refresh and self._previous is not None) else now + 0.3
            self._followup_areas = coverage
        elif fresh:
            self._avoided += 1
        self._previous, self._sequence = small, max(frame.sequence, self._sequence)
        return VisualState(
            frame,
            request,
            hidden,
            frozenset(blocked),
            tuple(stable),
            self._ocr_sequence,
            (time.perf_counter() - started) * 1000,
            self._avoided,
            absent=frozenset(t for t, a in self._anchors.items() if a.hidden and a.misses >= 2),
            checked_sequence=candidate.frame.sequence if candidate else 0,
            unchanged=self._unchanged,
            checked=self._checked,
            scan_areas=coverage,
            stable_tracks=tuple(stable_tracks),
            changed_areas=tuple(
                Rect(
                    int(x) * size[0] // 32,
                    int(y) * size[1] // 18,
                    ceil(int(x + 1) * size[0] / 32) - int(x) * size[0] // 32,
                    ceil(int(y + 1) * size[1] / 18) - int(y) * size[1] // 18,
                )
                for y, x in zip(*np.nonzero(significant), strict=True)
            ),
        )


class VisualSession:
    """One replaceable analysis job. No inference, Qt, full-frame history, or IO."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._pending: tuple[int, _Job] | None = None
        self._last_key: Any = None
        self._generation = 0
        self._stop = False
        self._done = threading.Event()
        self._snapshot = VisualState()
        self._thread = threading.Thread(target=self._run, name="visual-owner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def submit(
        self,
        frame: CapturedFrame,
        result: OcrResult | None,
        tracks: tuple[TextTrack, ...],
        assignments: tuple[int | None, ...],
        activity: tuple[TextActivity, ...],
        candidate: OcrResult | None = None,
    ) -> None:
        tracks, assignments, activity = tracks[:128], assignments[:512], activity[:128]
        key = (
            frame.sequence,
            result.frame.sequence if result else 0,
            tracks,
            candidate.frame.sequence if candidate else 0,
        )
        with self._condition:
            if (
                self._stop
                or key == self._last_key
                or (self._last_key is not None and frame.sequence < self._last_key[0])
            ):
                return
            self._last_key = key
            self._pending = (
                self._generation,
                _Job(frame, result, tracks, assignments, activity, candidate),
            )
            self._condition.notify()

    def invalidate(self) -> None:
        with self._condition:
            self._generation += 1
            self._pending, self._last_key = None, None
            self._snapshot = VisualState()

    def request_stop(self) -> None:
        with self._condition:
            self._stop = True
            self._pending = None
            self._snapshot = VisualState()
            self._condition.notify()

    @property
    def finished(self) -> bool:
        return self._done.is_set()

    def poll(self) -> VisualState:
        """Read current evidence and acknowledge the coalesced OCR request."""
        with self._condition:
            value = self._snapshot
            self._snapshot = replace(value, request_ocr=False)
            return value

    def _run(self) -> None:
        analyzer, generation = None, -1
        failed = False
        try:
            while True:
                with self._condition:
                    self._condition.wait_for(lambda: self._stop or self._pending is not None)
                    if self._stop:
                        return
                    pending, self._pending = self._pending, None
                assert pending is not None
                current, job = pending
                if current != generation:
                    analyzer, generation, failed = None, current, False
                try:
                    if analyzer is None and not failed:
                        analyzer = VisualAnalyzer()
                    state = (
                        VisualState(job.frame, True, message="Visual checks failed; using OCR.")
                        if analyzer is None or failed
                        else analyzer.observe(
                            job.frame,
                            job.result,
                            job.tracks,
                            job.assignments,
                            job.activity,
                            job.candidate,
                        )
                    )
                except Exception:
                    logger.exception("Visual checks failed; using ordinary OCR")
                    failed = True
                    state = VisualState(job.frame, True, message="Visual checks failed; using OCR.")
                with self._condition:
                    if not self._stop and current == self._generation:
                        old = self._snapshot
                        areas = state.scan_areas
                        if old.request_ocr:
                            areas = (
                                None
                                if old.scan_areas is None or (state.request_ocr and areas is None)
                                else scan_regions(
                                    (*old.scan_areas, *(areas or ())),
                                    job.frame.geometry.client.size,
                                )
                            )
                        self._snapshot = replace(
                            state,
                            request_ocr=state.request_ocr or old.request_ocr,
                            scan_areas=areas,
                        )
                del pending, job, state
        finally:
            self._done.set()
