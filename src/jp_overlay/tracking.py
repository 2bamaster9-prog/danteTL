"""Bounded, deterministic text tracking. No frame history, clocks, Qt, or models.

Observe each completed OCR frame once, then ask for visible tracks using capture's
latest frame and an explicit monotonic time. Display geometry has a deadband around
its last committed position, rather than following every detector fluctuation.
"""

import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from math import isfinite

from jp_overlay.domain import CapturedFrame, Rect
from jp_overlay.presence import FrameEvidence
from jp_overlay.recognition import OcrResult, TextRegion
from jp_overlay.text_content import content_region


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
    missing_frames: int = 3
    missing_seconds: float = 0.35
    static_settle_seconds: float = 0.35
    confirmation_frames: int = 2
    weaker_reading_seconds: float = 1.25

    def __post_init__(self) -> None:
        if min(self.max_tracks, self.missing_frames, self.confirmation_frames) < 1:
            raise ValueError("Tracking counts must be positive.")
        if min(self.missing_seconds, self.static_settle_seconds, self.weaker_reading_seconds) <= 0:
            raise ValueError("Tracking confirmation times must be positive.")


@dataclass(slots=True)
class _Track:
    value: TextTrack
    observed: Rect
    last_seen: float
    last_sequence: int
    misses: int = 0
    missing_since: float | None = None
    pending_text: str = ""
    text_hits: int = 0
    pending_bounds: Rect | None = None
    position_hits: int = 0
    confirmed: bool = False
    best_confidence: float | None = None
    pending_confidence: float | None = None
    pending_since: float = 0
    pending_protected: bool = False
    fingerprint: bytes | None = None
    fingerprint_bounds: Rect | None = None
    pixels_changed: bool = False


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


def _confidence(region: TextRegion) -> float | None:
    score = region.confidence
    return score if score is not None and isfinite(score) and 0 <= score <= 1 else None


def _best_score(old: float | None, new: float | None) -> float | None:
    return new if old is None else old if new is None else max(old, new)


def _minor_variant(old: str, new: str) -> bool:
    """Conservative OCR ambiguity, not general semantic equivalence."""
    if min(len(old), len(new)) < 4:
        return False  # Short choices/names can change meaning with just one character.
    if tuple(c for c in old if c.isnumeric()) != tuple(c for c in new if c.isnumeric()):
        return False
    shorter, longer = sorted((old, new), key=len)
    if longer.startswith(shorter) and any(
        unicodedata.category(c)[0] not in "PS" for c in longer[len(shorter) :]
    ):
        return False  # Typewriter growth/contraction needs the normal confirmation path.
    matcher = SequenceMatcher(None, old, new, autojunk=False)
    edits = sum(max(b - a, d - c) for tag, a, b, c, d in matcher.get_opcodes() if tag != "equal")
    return matcher.ratio() >= 0.75 and edits <= min(2, max(1, len(shorter) // 5))


def _same_location(old: Rect, new: Rect) -> bool:
    return _overlap(old, new) >= 0.7 and _edge_distance(old, new) <= max(
        12, min(*old.size, *new.size)
    )


def _clear_text_candidate(track: _Track) -> None:
    track.pending_text, track.text_hits = "", 0
    track.pending_confidence, track.pending_since, track.pending_protected = None, 0, False


def _commit_text(track: _Track) -> None:
    track.value = replace(
        track.value,
        text=track.pending_text,
        bounds=track.observed,
        text_revision=track.value.text_revision + 1,
    )
    # A genuinely new reading starts a new confidence baseline, even if it scores lower.
    track.best_confidence = track.pending_confidence
    track.fingerprint, track.fingerprint_bounds = None, None
    track.confirmed = True
    _clear_text_candidate(track)


def _match_score(track: _Track, region: TextRegion) -> float | None:
    if track.value.vertical != region.vertical:
        return None
    overlap = _overlap(track.observed, region.bounds)
    distance = _edge_distance(track.observed, region.bounds)
    thickness = max(1, min(track.observed.size), min(region.bounds.size))
    # Text alone cannot attach an identical label on the other side of the screen.
    if overlap < 0.2 and distance > max(24, thickness * 3):
        return None
    old, new = _normalized(track.value.text), _normalized(region.text)
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
        self._completed_at = float("-inf")
        self._complete_observation = True
        self._size: tuple[int, int] | None = None
        self._assignments: tuple[int | None, ...] = ()

    def reset(self) -> None:
        """Invalidate source state; IDs are never reused during this tracker's lifetime."""
        self._tracks.clear()
        self._sequence = 0
        self._captured_at = float("-inf")
        self._completed_at = float("-inf")
        self._complete_observation = True
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
        self._completed_at = result.completed_at
        # Consider more observations than display slots so detector ordering cannot
        # evict an existing track on a dense screen. Truncation is not absence evidence.
        raw_regions = result.regions[: self._policy.max_tracks * 4]
        complete = len(raw_regions) == len(result.regions)
        self._complete_observation = complete
        evidence = FrameEvidence(frame)
        regions = [
            (index, region)
            for index, raw in enumerate(raw_regions)
            for region in (content_region(raw),)
            if _normalized(region.text) and min(region.bounds.size) > 0
        ]
        candidates = []
        observations = dict(regions)
        for key, track in self._tracks.items():
            for index, region in regions:
                score = _match_score(track, region)
                if score is not None:
                    candidates.append((-score, key, index))
        assignments: list[int | None] = [None] * len(result.regions)
        used: set[int] = set()
        # One-to-one matching, deterministic ties. At most 128 x 512 candidates.
        for _, key, index in sorted(candidates):
            if key in used or assignments[index] is not None:
                continue
            used.add(key)
            assignments[index] = key
            self._update(self._tracks[key], observations[index], frame)
        for key in list(self._tracks):
            track = self._tracks[key]
            if key not in used and complete:
                current = (
                    evidence.fingerprint(track.fingerprint_bounds)
                    if track.fingerprint is not None and track.fingerprint_bounds is not None
                    else None
                )
                track.pixels_changed = current is not None and current != track.fingerprint
                if current is not None and current == track.fingerprint:
                    # The same crop still contains the pixels that produced this text.
                    # A missed detector result cannot erase or split its translation.
                    track.misses, track.missing_since = 0, None
                    track.confirmed = True
                    _clear_text_candidate(track)
                    track.position_hits, track.pending_bounds = 0, None
                    continue
                track.misses += 1
                if track.missing_since is None:
                    track.missing_since = frame.captured_at
                _clear_text_candidate(track)
                track.position_hits, track.pending_bounds = 0, None
                if (
                    track.misses >= self._policy.missing_frames
                    and frame.captured_at - track.missing_since >= self._policy.missing_seconds
                ):
                    del self._tracks[key]
        for index, region in regions:
            if assignments[index] is not None:
                continue
            # Wait for absence confirmation before admitting an incompatible overlapping
            # observation (e.g. a one-pass orientation error). Never draw both boxes.
            if any(
                key not in used and _overlap(track.observed, region.bounds) >= 0.55
                for key, track in self._tracks.items()
            ):
                continue
            if len(self._tracks) >= self._policy.max_tracks:
                continue
            key = self._next_id
            self._next_id += 1
            value = TextTrack(key, region.text, region.bounds, region.vertical)
            self._tracks[key] = _Track(
                value,
                region.bounds,
                frame.captured_at,
                frame.sequence,
                best_confidence=_confidence(region),
            )
            used.add(key)
            assignments[index] = key
        # Capture a reference only for accepted content, never for a rejected candidate.
        # Missing-track checks run first so reference refresh cannot consume their budget.
        for index, key in enumerate(assignments):
            if key is None:
                continue
            track = self._tracks[key]
            if _normalized(observations[index].text) == _normalized(track.value.text):
                digest = evidence.fingerprint(track.value.bounds)
                track.fingerprint, track.fingerprint_bounds = digest, track.value.bounds
        self._assignments = tuple(assignments)
        return self._assignments

    def _update(self, track: _Track, region: TextRegion, frame: CapturedFrame) -> None:
        # Completed observations count as evidence regardless of inference speed.
        # Actual misses, rather than elapsed processing time, break candidate runs.
        track.observed = region.bounds
        track.last_seen, track.last_sequence, track.misses = frame.captured_at, frame.sequence, 0
        track.missing_since = None
        track.pixels_changed = False
        text_changed = self._observe_text(track, region, frame.captured_at)
        if track.pending_protected:
            # An icon/crop variant must not move the winning box while its text is rejected.
            track.pending_bounds, track.position_hits = None, 0
            return
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

    def _observe_text(self, track: _Track, region: TextRegion, captured_at: float) -> bool:
        old, new = _normalized(track.value.text), _normalized(region.text)
        score = _confidence(region)
        if old == new:
            _clear_text_candidate(track)
            track.best_confidence = _best_score(track.best_confidence, score)
            track.confirmed = True
            return False
        if new == _normalized(track.pending_text):
            track.text_hits += 1
            track.pending_confidence = _best_score(track.pending_confidence, score)
        else:
            track.pending_text, track.text_hits = region.text, 1
            track.pending_confidence, track.pending_since = score, captured_at
            track.pending_protected = _same_location(track.value.bounds, region.bounds) and (
                _minor_variant(old, new)
            )
        track.pending_protected = (
            track.pending_protected
            and track.best_confidence is not None
            and track.pending_confidence is not None
            # Mean scores can differ by floating-point rounding when an icon adds a character.
            and track.pending_confidence <= track.best_confidence + 1e-6
            and _same_location(track.value.bounds, region.bounds)
        )
        if track.text_hits >= self._policy.confirmation_frames and self._text_ready(
            track, captured_at
        ):
            _commit_text(track)
            return True
        return False

    def _text_ready(self, track: _Track, now: float) -> bool:
        # Never let an old high score permanently suppress a genuine, similar-looking edit.
        return (
            not track.pending_protected
            or now - track.pending_since >= self._policy.weaker_reading_seconds
        )

    def visible(self, latest: CapturedFrame, now: float) -> tuple[TextTrack, ...]:
        """Retain committed state between observations; time alone cannot prove absence."""
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
                if track.pending_text and self._text_ready(track, now):
                    _commit_text(track)
                if track.pending_bounds is not None:
                    track.value = replace(track.value, bounds=track.observed)
                    track.pending_bounds, track.position_hits = None, 0
                    track.fingerprint, track.fingerprint_bounds = None, None
            # Changed crop pixels AND a completed miss can settle on a now-static
            # source without duplicate WGC frames. Time/unchanged pixels alone cannot.
            if (
                track.misses
                and self._complete_observation
                and track.pixels_changed
                and latest.sequence == self._sequence
                and now - max(latest.captured_at, self._completed_at)
                >= self._policy.static_settle_seconds
            ):
                del self._tracks[key]
        return tuple(track.value for track in self._tracks.values())

    def translation_tracks(self, latest: CapturedFrame, now: float) -> tuple[TextTrack, ...]:
        """Translate confirmed display content; preserve it through jitter/miss grace.

        Initial/typewriter candidates wait for confirmation. Once content is committed,
        keep its English until a new revision commits or its track actually expires.
        """
        visible = self.visible(latest, now)
        return tuple(value for value in visible if self._tracks[value.track_id].confirmed)
