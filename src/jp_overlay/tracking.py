"""Bounded, deterministic text tracking. No images, clocks, Qt, or model ownership.

Observe each completed OCR frame once, then ask for visible tracks using capture's
latest frame and an explicit monotonic time. Display geometry has a deadband around
its last committed position, rather than following every detector fluctuation.
"""

import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.recognition import OcrResult, TextRegion


@dataclass(frozen=True, slots=True)
class TextTrack:
    track_id: int
    text: str
    bounds: Rect
    vertical: bool = False
    text_revision: int = 1


@dataclass(frozen=True, slots=True)
class TrackingPolicy:
    max_tracks: int = 128
    missing_frames: int = 2
    stale_seconds: float = 0.8
    static_settle_seconds: float = 0.35
    confirmation_frames: int = 2

    def __post_init__(self) -> None:
        if min(self.max_tracks, self.missing_frames, self.confirmation_frames) < 1:
            raise ValueError("Tracking counts must be positive.")
        if min(self.stale_seconds, self.static_settle_seconds) <= 0:
            raise ValueError("Tracking expiry must be positive.")


@dataclass(slots=True)
class _Track:
    value: TextTrack
    observed: Rect
    last_seen: float
    last_sequence: int
    misses: int = 0
    pending_text: str = ""
    text_hits: int = 0
    pending_bounds: Rect | None = None
    position_hits: int = 0
    confirmed: bool = False


def _normalized(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _overlap(a: Rect, b: Rect) -> float:
    width = max(0, min(a.x + a.width, b.x + b.width) - max(a.x, b.x))
    height = max(0, min(a.y + a.height, b.y + b.height) - max(a.y, b.y))
    intersection = width * height
    return intersection / max(1, a.width * a.height + b.width * b.height - intersection)


def _edge_distance(a: Rect, b: Rect) -> int:
    return max(
        abs(a.x - b.x),
        abs(a.y - b.y),
        abs(a.x + a.width - b.x - b.width),
        abs(a.y + a.height - b.y - b.height),
    )


def _deadband(bounds: Rect) -> int:
    # Glyph-scale tolerance, in physical pixels; independent of desktop DPI.
    return max(3, min(12, round(min(bounds.size) * 0.2)))


def _match_score(track: _Track, region: TextRegion) -> float | None:
    if track.value.vertical != region.vertical:
        return None
    old, new = _normalized(track.value.text), _normalized(region.text)
    overlap = _overlap(track.observed, region.bounds)
    distance = _edge_distance(track.observed, region.bounds)
    thickness = max(1, min(track.observed.size), min(region.bounds.size))
    # Text alone cannot attach an identical label on the other side of the screen.
    if overlap < 0.2 and distance > max(24, thickness * 3):
        return None
    if old == new:
        similarity = 1.0
    else:
        similarity = SequenceMatcher(None, old, new, autojunk=False).ratio()
        # Short labels/numbers are meaningful edits, never fuzzy-equivalent content.
        related = min(len(old), len(new)) >= 6 and similarity >= 0.8
        prefix = min(len(old), len(new)) >= 3 and (old.startswith(new) or new.startswith(old))
        if not (related or prefix) and overlap < 0.55:
            return None
    # Spatial proximity is essential for repeated menu labels. Exact text helps
    # distinguish neighboring lines when detector order changes.
    return overlap * 3 + similarity * 2 - min(distance / thickness, 3) * 0.15


class TextTracker:
    def __init__(self, policy: TrackingPolicy = TrackingPolicy()) -> None:
        self._policy = policy
        self._tracks: dict[int, _Track] = {}
        self._next_id = 1
        self._sequence = 0
        self._captured_at = float("-inf")
        self._size: tuple[int, int] | None = None
        self._assignments: tuple[int | None, ...] = ()

    def reset(self) -> None:
        """Invalidate source state; IDs are never reused during this tracker's lifetime."""
        self._tracks.clear()
        self._sequence = 0
        self._captured_at = float("-inf")
        self._size = None
        self._assignments = ()

    def observe(self, result: OcrResult) -> tuple[int | None, ...]:
        """Return IDs in raw OCR row order. Repeated/late frames cannot confirm changes."""
        frame = result.frame
        if frame.sequence <= self._sequence or frame.captured_at < self._captured_at:
            return self._assignments
        if self._size != frame.geometry.client.size:
            self.reset()
            self._size = frame.geometry.client.size
        self._sequence, self._captured_at = frame.sequence, frame.captured_at
        regions = [
            (index, region)
            for index, region in enumerate(result.regions)
            if _normalized(region.text) and min(region.bounds.size) > 0
        ][: self._policy.max_tracks]
        candidates = []
        for key, track in self._tracks.items():
            for index, region in regions:
                score = _match_score(track, region)
                if score is not None:
                    candidates.append((-score, key, index))
        assignments: list[int | None] = [None] * len(result.regions)
        used: set[int] = set()
        # One-to-one matching, deterministic ties. At most 128 x 128 candidates.
        for _, key, index in sorted(candidates):
            if key in used or assignments[index] is not None:
                continue
            used.add(key)
            assignments[index] = key
            self._update(self._tracks[key], result.regions[index], frame)
        for key in list(self._tracks):
            track = self._tracks[key]
            if key not in used:
                track.misses += 1
                track.text_hits = track.position_hits = 0
                track.pending_text, track.pending_bounds = "", None
                if (
                    track.misses >= self._policy.missing_frames
                    or frame.captured_at - track.last_seen > self._policy.stale_seconds
                ):
                    del self._tracks[key]
        for index, region in regions:
            if assignments[index] is not None:
                continue
            # An unrelated replacement at the same location supersedes an unmatched
            # ghost immediately; do not draw two overlapping boxes during the grace period.
            for key in list(self._tracks):
                if key not in used and _overlap(self._tracks[key].observed, region.bounds) >= 0.55:
                    del self._tracks[key]
            if len(self._tracks) >= self._policy.max_tracks:
                continue
            key = self._next_id
            self._next_id += 1
            value = TextTrack(key, region.text, region.bounds, region.vertical)
            self._tracks[key] = _Track(value, region.bounds, frame.captured_at, frame.sequence)
            used.add(key)
            assignments[index] = key
        self._assignments = tuple(assignments)
        return self._assignments

    def _update(self, track: _Track, region: TextRegion, frame: CapturedFrame) -> None:
        # An unchanged source can legitimately stop delivering frames. Keep its ID,
        # but never combine pending edits across a long gap as consecutive evidence.
        if frame.captured_at - track.last_seen > self._policy.stale_seconds:
            track.pending_text, track.pending_bounds = "", None
            track.text_hits = track.position_hits = 0
        track.observed = region.bounds
        track.last_seen, track.last_sequence, track.misses = frame.captured_at, frame.sequence, 0
        text_changed = False
        if _normalized(region.text) == _normalized(track.value.text):
            track.pending_text, track.text_hits = "", 0
            track.confirmed = True
        else:
            if _normalized(region.text) == _normalized(track.pending_text):
                track.text_hits += 1
            else:
                track.pending_text, track.text_hits = region.text, 1
            if track.text_hits >= self._policy.confirmation_frames:
                track.value = replace(
                    track.value, text=region.text, text_revision=track.value.text_revision + 1
                )
                track.pending_text, track.text_hits = "", 0
                text_changed = True
                track.confirmed = True
        distance = _edge_distance(track.value.bounds, region.bounds)
        tolerance = _deadband(track.value.bounds)
        if distance <= tolerance and not text_changed:
            track.pending_bounds, track.position_hits = None, 0
            return
        # Coherent translation of a similarly-sized box should follow immediately;
        # a sudden width/height change can instead be a one-frame detector crop error.
        moved = distance >= tolerance * 3 and all(
            abs(a - b) <= tolerance
            for a, b in zip(track.value.bounds.size, region.bounds.size, strict=True)
        )
        if moved or text_changed:
            track.value = replace(track.value, bounds=region.bounds)
            track.pending_bounds, track.position_hits = None, 0
            return
        if (
            track.pending_bounds
            and _edge_distance(track.pending_bounds, region.bounds) <= tolerance
        ):
            track.position_hits += 1
        else:
            track.pending_bounds, track.position_hits = region.bounds, 1
        if track.position_hits >= self._policy.confirmation_frames:
            track.value = replace(track.value, bounds=region.bounds)
            track.pending_bounds, track.position_hits = None, 0

    def visible(self, latest: CapturedFrame, now: float) -> tuple[TextTrack, ...]:
        """Expire missed/stalled observations, but keep a truly unchanged source visible."""
        if self._size != latest.geometry.client.size:
            self.reset()
            return ()
        for key in list(self._tracks):
            track = self._tracks[key]
            static = track.last_sequence == latest.sequence and track.misses == 0
            if static and now - track.last_seen >= self._policy.static_settle_seconds:
                track.confirmed = True
                # WGC need not emit the same pixels twice. Time on an unchanged latest
                # frame can settle its final edit; repeated polls never count as frames.
                if track.pending_text:
                    track.value = replace(
                        track.value,
                        text=track.pending_text,
                        bounds=track.observed,
                        text_revision=track.value.text_revision + 1,
                    )
                    track.pending_text, track.text_hits = "", 0
                if track.pending_bounds is not None:
                    track.value = replace(track.value, bounds=track.observed)
                    track.pending_bounds, track.position_hits = None, 0
            if not static and now - track.last_seen > self._policy.stale_seconds:
                del self._tracks[key]
        return tuple(track.value for track in self._tracks.values())

    def translation_tracks(self, latest: CapturedFrame, now: float) -> tuple[TextTrack, ...]:
        """Translate confirmed display content; preserve it through jitter/miss grace.

        Initial/typewriter candidates wait for confirmation. Once content is committed,
        keep its English until a new revision commits or its track actually expires.
        """
        visible = self.visible(latest, now)
        return tuple(value for value in visible if self._tracks[value.track_id].confirmed)
