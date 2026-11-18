"""Bounded, deterministic text tracking. No frame history, clocks, Qt, or models.

Observe each completed OCR frame once, then ask for visible tracks using capture's
latest frame and an explicit monotonic time. Display geometry has a deadband around
its last committed position, rather than following every detector fluctuation.
"""

import re
import unicodedata
from dataclasses import dataclass, field, replace
from math import isfinite

from dantejp.domain import CapturedFrame, Rect, WindowGeometry
from dantejp.ocr.lettering import Lettering, sample_lettering
from dantejp.ocr.presence import EvidenceReader, PixelEvidence
from dantejp.ocr.quote_dash import opening_dash_edges
from dantejp.ocr.spatial import SpatialCandidates
from dantejp.ocr.text_content import content_region
from dantejp.ocr.text_distance import LcsSimilarity, within_edits
from dantejp.ocr.track_assignment import assign_tracks
from dantejp.ocr.values import OcrResult, TextRegion


@dataclass(frozen=True, slots=True)
class TextTrack:
    track_id: int
    text: str
    bounds: Rect
    vertical: bool = False
    text_revision: int = 1


@dataclass(frozen=True, slots=True)
class TextActivity:
    """Latest plausible layout and reveal activity, separate from committed display."""

    observation: TextTrack
    changed_at: float
    growing: bool
    pending: bool


@dataclass(frozen=True, slots=True)
class TrackingPolicy:
    max_tracks: int = 128
    missing_frames: int = 3
    missing_seconds: float = 0.35
    static_settle_seconds: float = 0.35
    confirmation_frames: int = 2

    def __post_init__(self) -> None:
        if min(self.max_tracks, self.missing_frames, self.confirmation_frames) < 1:
            raise ValueError("Tracking counts must be positive.")
        if min(self.missing_seconds, self.static_settle_seconds) <= 0:
            raise ValueError("Tracking confirmation times must be positive.")


@dataclass(slots=True)
class _TextCandidate:
    text: str
    confidence: float | None
    correction: bool
    hits: int = 1
    needs_repeat: bool = False

    @property
    def changes_layout(self) -> bool:
        return not self.correction and not self.needs_repeat


@dataclass(slots=True)
class _GeometryCandidate:
    bounds: Rect
    hits: int = 1


@dataclass(frozen=True, slots=True)
class _PresenceReference:
    digest: bytes
    bounds: Rect


@dataclass(slots=True)
class _Absence:
    since: float
    sequence: int
    pattern_lost: bool
    misses: int = 1


@dataclass(slots=True)
class _Track:
    """Accepted display and independent evidence for text, geometry and absence.

    Pending evidence never replaces accepted text until its confirmation rule succeeds.
    None means no candidate/evidence; there are no orphan counters or timestamps.
    """

    value: TextTrack
    observed: Rect
    last_seen: float
    last_sequence: int
    absence: _Absence | None = None
    text_candidate: _TextCandidate | None = None
    geometry_candidate: _GeometryCandidate | None = None
    confirmed: bool = False
    best_confidence: float | None = None
    presence: _PresenceReference | None = None
    reading: str = ""
    changed_at: float = 0
    growing: bool = False
    review_attempts: int = 0
    visual_same: bool = False
    display_predecessor: TextTrack | None = None
    # Only the accepted and most recent candidate can subsequently be displayed.
    appearance: dict[tuple[str, Rect], tuple[int | None, Lettering | None]] = field(
        default_factory=dict
    )

    def record_appearance(
        self, region: TextRegion, edge: int | None, sample: Lettering | None
    ) -> None:
        accepted = (self.value.text, self.value.bounds)
        kept = self.appearance.get(accepted)
        self.appearance.clear()
        if region.text == self.value.text and _edge_distance(
            region.bounds, self.value.bounds
        ) <= _deadband(region.bounds):
            kept = (None if edge is None else edge + self.value.bounds.x - region.bounds.x, sample)
        if kept is not None and kept != (None, None):
            self.appearance[accepted] = kept
        if edge is not None or sample is not None:
            self.appearance[region.text, region.bounds] = (edge, sample)

    def seen(self, frame: CapturedFrame) -> None:
        self.last_seen, self.last_sequence = frame.captured_at, frame.sequence
        self.absence = None

    def discard_candidates(self) -> None:
        self.text_candidate = None
        self.geometry_candidate = None


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


def _improves(score: float | None, accepted: float | None) -> bool:
    # Character means can differ by floating-point rounding alone.
    return score is not None and (accepted is None or score > accepted + 1e-6)


_AMOUNT = re.compile(r"[-±]?\d+(?:[.,]\d+)*%?")


def _minor_variant(old: str, new: str) -> bool:
    """Conservative OCR ambiguity, not general semantic equivalence."""
    if min(len(old), len(new)) < 4:
        # A dropped bracket can surround even a two-character menu label. Keep
        # ordinary single-character substitutions on short names/choices meaningful.
        brackets = "()[]「」『』【】"
        core = old.strip(brackets)
        return bool(core) and core == new.strip(brackets) and abs(len(old) - len(new)) <= 2
    numbers = tuple(c for c in old if c.isnumeric())
    if numbers != tuple(c for c in new if c.isnumeric()):
        return False
    # A sign, decimal point or percent can change a stat with every digit intact.
    if numbers and _AMOUNT.findall(old.replace("−", "-")) != _AMOUNT.findall(new.replace("−", "-")):
        return False
    shorter, longer = sorted((old, new), key=len)
    if (
        longer.startswith(shorter)
        and any(unicodedata.category(c)[0] not in "PS" for c in longer[len(shorter) :])
        and not (len(shorter) >= 10 and len(longer) == len(shorter) + 1)
    ):
        return False  # Typewriter growth/contraction needs the normal confirmation path.
    # Tolerate an isolated letter in a short label and a few scattered OCR errors
    # in a long paragraph. A fixed edit cap keeps the comparison band narrow.
    return within_edits(old, new, min(4, max(1, len(shorter) // 10)))


def _same_location(old: Rect, new: Rect) -> bool:
    return _overlap(old, new) >= 0.7 and _edge_distance(old, new) <= max(
        12, min(*old.size, *new.size)
    )


def _inside_line(fragment: Rect, line: Rect) -> bool:
    width = max(0, min(fragment.x + fragment.width, line.x + line.width) - max(fragment.x, line.x))
    height = max(
        0, min(fragment.y + fragment.height, line.y + line.height) - max(fragment.y, line.y)
    )
    return width * height >= fragment.width * fragment.height * 0.9


def _commit_text(track: _Track) -> None:
    candidate = track.text_candidate
    assert candidate is not None
    if candidate.needs_repeat:
        return  # Quiet pixels cannot independently confirm a weak OCR interpretation.
    track.display_predecessor = track.value if candidate.correction else None
    track.value = replace(
        track.value,
        text=candidate.text,
        bounds=track.observed,
        text_revision=track.value.text_revision + 1,
    )
    # A genuinely new reading starts a new confidence baseline, even if it scores lower.
    track.best_confidence = candidate.confidence
    track.presence = None
    track.confirmed = True
    track.text_candidate = None


def _match_score(
    track: TextTrack, region: TextRegion, old: str, new: str, scorer: LcsSimilarity
) -> float | None:
    if track.vertical != region.vertical:
        return None
    overlap = _overlap(track.bounds, region.bounds)
    distance = _edge_distance(track.bounds, region.bounds)
    thickness = max(1, min(track.bounds.size), min(region.bounds.size))
    a, b = track.bounds, region.bounds
    tolerance = _deadband(a)
    same_origin = (
        abs(a.x - b.x) <= tolerance
        and abs(a.y - b.y) <= tolerance
        and abs(
            (a.width if region.vertical else a.height) - (b.width if region.vertical else b.height)
        )
        <= tolerance
    )
    if not region.vertical and (old.startswith(new) or new.startswith(old)):
        same_origin |= (
            abs(a.x - b.x) <= tolerance
            and abs((a.y + a.height / 2) - (b.y + b.height / 2)) <= max(a.height, b.height) * 0.3
            and max(a.height, b.height) <= min(a.height, b.height) * 2.5
        )  # A first glyph such as 二 can be shorter than the eventual full line.
    # Text alone cannot attach an identical label on the other side of the screen.
    if overlap < 0.2 and distance > max(24, thickness * 3) and not same_origin:
        return None
    if old == new:
        similarity = 1.0
    else:
        similarity = scorer.ratio(new)
        # Short labels/numbers are meaningful edits, never fuzzy-equivalent content.
        related = min(len(old), len(new)) >= 6 and similarity >= 0.8
        prefix = (min(len(old), len(new)) >= 3 or same_origin) and (
            old.startswith(new) or new.startswith(old)
        )
        if not (related or prefix or same_origin) and overlap < 0.55:
            return None
    # Spatial proximity is essential for repeated menu labels. Exact text helps
    # distinguish neighboring lines when detector order changes.
    return overlap * 3 + similarity * 2 - min(distance / thickness, 3) * 0.15


@dataclass(frozen=True, slots=True)
class MatchingEvidence:
    """Pure scoring output for one exact OCR source and immutable prior track state."""

    sequence: int
    captured_at: float
    geometry: WindowGeometry
    sources: tuple[TextTrack, ...]
    limit: int
    regions: tuple[tuple[int, TextRegion], ...]
    normalized: tuple[tuple[int, str], ...]
    candidates: tuple[tuple[float, int, int], ...]
    dash_edges: tuple[tuple[int, int], ...]
    lettering: tuple[tuple[int, Lettering], ...]

    def matches(self, result: OcrResult, sources: tuple[TextTrack, ...], limit: int = 512) -> bool:
        frame = result.frame
        return (self.sequence, self.captured_at, self.geometry, self.sources, self.limit) == (
            frame.sequence,
            frame.captured_at,
            frame.geometry,
            sources,
            limit,
        )


def prepare_matching(
    result: OcrResult, sources: tuple[TextTrack, ...], limit: int = 512
) -> MatchingEvidence:
    """Worker-side geometry gating and text scoring; does not own or mutate tracks."""
    regions, normalized = [], {}
    for index, raw in enumerate(result.regions[:limit]):
        region = content_region(raw)
        text = _normalized(region.text)
        if text and min(region.bounds.size) > 0:
            regions.append((index, region))
            normalized[index] = text
    nearby = SpatialCandidates(regions)
    candidates = []
    for track in sources:
        old = _normalized(track.text)
        scorer = LcsSimilarity(old)
        for index, region in nearby.for_bounds(track.bounds):
            score = _match_score(track, region, old, normalized[index], scorer)
            if score is not None:
                candidates.append((score, track.track_id, index))
    frame = result.frame
    return MatchingEvidence(
        frame.sequence,
        frame.captured_at,
        frame.geometry,
        sources,
        limit,
        tuple(regions),
        tuple(normalized.items()),
        tuple(candidates),
        tuple(
            opening_dash_edges(
                frame,
                result.regions,
                regions,
                tuple(t.bounds for t in sources if not t.vertical) if result.scanned else (),
            ).items()
        ),
        sample_lettering(frame, regions),
    )


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

    def matching_sources(self, frame: CapturedFrame) -> tuple[TextTrack, ...]:
        if self._size != frame.geometry.client.size:
            return ()  # A resize resets tracking before this observation is committed.
        return tuple(replace(t.value, bounds=t.observed) for t in self._tracks.values())

    def evidence_bounds(self) -> tuple[Rect, ...]:
        """Bounded crop proposals, including geometry that may settle before OCR returns."""
        return tuple(
            dict.fromkeys(
                box
                for track in self._tracks.values()
                for box in (
                    track.value.bounds,
                    track.observed,
                    track.presence.bounds if track.presence else track.value.bounds,
                    track.geometry_candidate.bounds
                    if track.geometry_candidate
                    else track.value.bounds,
                )
            )
        )

    def observe(
        self,
        result: OcrResult,
        *,
        visually_absent: frozenset[TextTrack] = frozenset(),
        pattern_loss: frozenset[TextTrack] = frozenset(),
        visually_present: frozenset[TextTrack] = frozenset(),
        visual_sequence: int = 0,
        unchanged: frozenset[TextTrack] = frozenset(),
        visual_checked: frozenset[TextTrack] = frozenset(),
        checked_sequence: int = 0,
        pixel_evidence: PixelEvidence | None = None,
        matching: MatchingEvidence | None = None,
    ) -> tuple[int | None, ...]:
        """Return IDs in raw OCR row order. Repeated/late frames cannot confirm changes."""
        frame = result.frame
        if frame.sequence <= self._sequence or frame.captured_at < self._captured_at:
            return self._assignments
        sources = self.matching_sources(frame)
        if matching is not None and not matching.matches(
            result, sources, self._policy.max_tracks * 4
        ):
            raise ValueError("Tracking evidence does not match the current source/state.")
        # Direct deterministic replays may score inline. LiveSession always supplies
        # source/state-checked worker evidence and never performs scoring on Qt.
        matching = matching or prepare_matching(result, sources, self._policy.max_tracks * 4)
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
        evidence = EvidenceReader(frame, pixel_evidence)
        regions = matching.regions
        normalized = dict(matching.normalized)
        candidates = list(matching.candidates)
        observations = dict(regions)
        # Evidence must describe the exact source being reconciled and the current
        # accepted revision. Evidence from a newer/older capture is not interchangeable.
        checked = visual_checked if checked_sequence == frame.sequence else frozenset()
        unchanged = unchanged & checked
        for track in self._tracks.values():
            track.visual_same = track.value in unchanged
            if track.value in checked and not track.visual_same:
                track.review_attempts = 0
        assignments: list[int | None] = [None] * len(result.regions)
        used: set[int] = set()
        # Canonical columns make ties independent of detector order. Raw result rows
        # remain untouched and returned IDs still refer to their original indices.
        order = tuple(
            index
            for index, _ in sorted(
                regions,
                key=lambda item: (
                    item[1].bounds.y,
                    item[1].bounds.x,
                    item[1].bounds.width,
                    item[1].bounds.height,
                    item[1].vertical,
                    normalized[item[0]],
                    item[1].text,
                    -(_confidence(item[1]) or 0),
                ),
            )
        )
        for key, index in assign_tracks(candidates, order):
            used.add(key)
            assignments[index] = key
            track = self._tracks[key]
            if track.visual_same:
                self._review_unchanged(track, observations[index], frame)
            else:
                lost_pattern = track.value in visually_absent and visual_sequence == frame.sequence
                self._update(track, observations[index], frame, lost_pattern=lost_pattern)
        for key in list(self._tracks):
            track = self._tracks[key]
            if key not in used and complete and result.covers(track.value.bounds):
                reference = track.presence
                current = evidence.fingerprint(reference.bounds) if reference else None
                if (
                    track.visual_same
                    or (reference and current == reference.digest)
                    or (visual_sequence >= frame.sequence and track.value in visually_present)
                ):
                    # Presence vetoes a miss. Only exact unchanged glyph evidence
                    # may override a positive OCR reading on the edit path above.
                    track.absence = None
                    track.confirmed = True
                    track.discard_candidates()
                    continue
                lost = visual_sequence == frame.sequence and track.value in pattern_loss
                if track.absence is None:
                    track.absence = _Absence(frame.captured_at, frame.sequence, lost)
                else:
                    track.absence.misses += 1
                    track.absence.sequence = frame.sequence
                    track.absence.pattern_lost = lost
                track.discard_candidates()
                if (
                    track.absence.misses >= self._policy.missing_frames
                    and frame.captured_at - track.absence.since >= self._policy.missing_seconds
                ) or (track.value in visually_absent and visual_sequence >= frame.sequence):
                    del self._tracks[key]
        for index, region in regions:
            if assignments[index] is not None:
                continue
            # A detector can split one unchanged line into several observations. Its
            # unmatched fragments must not become duplicate tracks beside the retained
            # full line. Only exact source-matched visual proof permits this suppression.
            if any(
                track.visual_same
                and track.value.vertical == region.vertical
                and _inside_line(region.bounds, track.value.bounds)
                for track in self._tracks.values()
            ):
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
                reading=region.text,
                changed_at=frame.captured_at,
            )
            used.add(key)
            assignments[index] = key
        # Capture a reference only for accepted content, never for a rejected candidate.
        # Missing-track checks run first so reference refresh cannot consume their budget.
        dash_edges = dict(matching.dash_edges)
        lettering = dict(matching.lettering)
        for index, key in enumerate(assignments):
            if key is None:
                continue
            track = self._tracks[key]
            track.record_appearance(
                observations[index], dash_edges.get(index), lettering.get(index)
            )
            if _normalized(observations[index].text) == _normalized(track.value.text):
                digest = evidence.fingerprint(track.value.bounds)
                track.presence = (
                    _PresenceReference(digest, track.value.bounds) if digest is not None else None
                )
        self._assignments = tuple(assignments)
        return self._assignments

    def _review_unchanged(self, track: _Track, region: TextRegion, frame: CapturedFrame) -> None:
        """Hold accepted geometry and review strictly better readings.

        Confidence is OCR confidence, not translation quality. Retries belong to this
        visual content lifetime and do not reset when OCR alternates or a review wins.
        """
        track.seen(frame)
        track.discard_candidates()
        track.observed = track.value.bounds
        track.confirmed = True
        score = _confidence(region)
        old, new = _normalized(track.value.text), _normalized(region.text)
        eligible = track.review_attempts < 3 and (
            track.best_confidence is None or track.best_confidence < 0.9
        )
        if eligible:
            track.review_attempts += 1
        if old == new:
            track.best_confidence = _best_score(track.best_confidence, score)
        elif (
            _improves(score, track.best_confidence)
            and _same_location(track.value.bounds, region.bounds)
            and (
                _minor_variant(old, new)
                or (
                    eligible
                    and score is not None
                    and (track.best_confidence is None or score > track.best_confidence + 0.01)
                )
            )
        ):
            # This is an OCR correction on unchanged pixels, not a new game sentence.
            # Its predecessor remains eligible for display until the replacement
            # English arrives; the renderer must still validate the explicit lineage.
            track.display_predecessor = track.value
            track.value = replace(
                track.value, text=region.text, text_revision=track.value.text_revision + 1
            )
            track.best_confidence = score
        track.reading = track.value.text

    def display_predecessors(self) -> tuple[tuple[TextTrack, TextTrack], ...]:
        """Previous accepted reading of each live OCR correction."""
        return tuple(
            (track.value, track.display_predecessor)
            for track in self._tracks.values()
            if track.display_predecessor is not None
        )

    def _update(
        self, track: _Track, region: TextRegion, frame: CapturedFrame, *, lost_pattern: bool
    ) -> None:
        # Completed observations count as evidence regardless of inference speed.
        # Actual misses, rather than elapsed processing time, break candidate runs.
        track.seen(frame)
        old, new = _normalized(track.value.text), _normalized(region.text)
        candidate = track.text_candidate
        repeat = (
            candidate is not None
            and _normalized(candidate.text) == new
            and _same_location(track.observed, region.bounds)
        )
        minor = old != new and _minor_variant(old, new)
        if lost_pattern:
            correction = False
        elif repeat and candidate:
            correction = candidate.correction
        else:
            # A freshly revealing line can acquire its final glyph. A past
            # reveal must not exempt a settled box from confidence checks forever.
            reveal_ending = (
                track.growing
                and frame.captured_at - track.changed_at <= 1.25
                and new.startswith(old)
                and all(c in "。、！？!?」』" or c.isalnum() for c in new[len(old) :])
            )
            correction = (
                minor and _same_location(track.value.bounds, region.bounds) and not reveal_ending
            )
        score = _confidence(region)
        track.observed = region.bounds
        # A repeat of a better pending spelling can confirm its peak score.
        if correction and not repeat and not _improves(score, track.best_confidence):
            track.text_candidate = None
            track.reading = track.value.text
            track.confirmed = True
            # A rejected spelling with clipped or extra glyphs cannot resize the box.
            if region.bounds.size == track.value.bounds.size:
                self._observe_geometry(track, region)
            else:
                track.geometry_candidate = None
            return
        if (
            old != new
            and not repeat
            and not lost_pattern
            and track.confirmed
            and _same_location(track.value.bounds, region.bounds)
            and score is not None
            and score < 0.5
            and track.best_confidence is not None
            and score < track.best_confidence - 0.25
        ):
            track.text_candidate = _TextCandidate(region.text, score, correction, needs_repeat=True)
            track.geometry_candidate = None
            return
        previous = _normalized(track.reading)
        if previous != new and not (minor if previous == old else _minor_variant(previous, new)):
            track.changed_at = frame.captured_at
            track.growing = bool(previous) and (
                new.startswith(previous)
                or previous.startswith(new)
                or (
                    len(new) > len(previous)
                    and region.bounds.width > track.value.bounds.width
                    and abs(region.bounds.x - track.value.bounds.x) <= _deadband(region.bounds)
                    and not region.vertical
                )
            )
        track.reading = region.text
        if old == new:
            track.text_candidate = None
            track.best_confidence = _best_score(track.best_confidence, score)
            track.confirmed = True
        else:
            if repeat and candidate and candidate.correction == correction:
                candidate.hits += 1
                candidate.confidence = _best_score(candidate.confidence, score)
                candidate.needs_repeat = False
            else:
                candidate = track.text_candidate = _TextCandidate(region.text, score, correction)
            if candidate.hits >= self._policy.confirmation_frames:
                _commit_text(track)
        self._observe_geometry(track, region)

    def _observe_geometry(self, track: _Track, region: TextRegion) -> None:
        distance = _edge_distance(track.value.bounds, region.bounds)
        tolerance = _deadband(track.value.bounds)
        if distance <= tolerance:
            track.geometry_candidate = None
            return
        # Coherent translation of a similarly-sized box should follow immediately;
        # a sudden width/height change can instead be a one-frame detector crop error.
        moved = distance >= tolerance * 3 and all(
            abs(a - b) <= tolerance
            for a, b in zip(track.value.bounds.size, region.bounds.size, strict=True)
        )
        if moved:
            track.value = replace(track.value, bounds=region.bounds)
            track.geometry_candidate = None
            return
        if (
            track.geometry_candidate
            and _edge_distance(track.geometry_candidate.bounds, region.bounds) <= tolerance
        ):
            track.geometry_candidate.hits += 1
        else:
            track.geometry_candidate = _GeometryCandidate(region.bounds)
        if track.geometry_candidate.hits >= self._policy.confirmation_frames:
            track.value = replace(track.value, bounds=region.bounds)
            track.geometry_candidate = None

    def visible(self, latest: CapturedFrame, now: float) -> tuple[TextTrack, ...]:
        """Retain committed state between observations; time alone cannot prove absence."""
        if self._size != latest.geometry.client.size:
            self.reset()
            return ()
        for key in list(self._tracks):
            track = self._tracks[key]
            static = track.last_sequence == latest.sequence and track.absence is None
            if static and now - track.last_seen >= self._policy.static_settle_seconds:
                track.confirmed = True
                # WGC need not emit the same pixels twice. Time on an unchanged latest
                # frame can settle its final edit; repeated polls never count as frames.
                if track.text_candidate:
                    _commit_text(track)
                if track.geometry_candidate is not None:
                    track.value = replace(track.value, bounds=track.observed)
                    track.geometry_candidate = None
                    track.presence = None
            # A static source may never emit a second frame. Require a covered
            # miss and strong stroke-pattern loss on that same frame to retire it.
            if (
                track.absence
                and self._complete_observation
                and track.absence.pattern_lost
                and track.absence.sequence == self._sequence
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

    def translation_activity(self) -> tuple[TextActivity, ...]:
        """Expose reveal timing without allowing candidate text to alter displayed English."""
        return tuple(
            TextActivity(
                replace(track.value, text=track.text_candidate.text, bounds=track.observed)
                if track.text_candidate and track.text_candidate.changes_layout
                else track.value,
                track.changed_at,
                track.growing,
                track.text_candidate is not None and track.text_candidate.changes_layout,
            )
            for track in self._tracks.values()
        )

    def opening_dash_edges(self) -> dict[TextTrack, int]:
        """Only offer pixel evidence for the committed reading and location."""
        return {
            track.value: edge
            for track in self._tracks.values()
            if (appearance := track.appearance.get((track.value.text, track.value.bounds)))
            and (edge := appearance[0]) is not None
        }

    def lettering(self) -> dict[TextTrack, Lettering]:
        return {
            track.value: sample
            for track in self._tracks.values()
            if (appearance := track.appearance.get((track.value.text, track.value.bounds)))
            and (sample := appearance[1]) is not None
        }

    def confirm_visual(self, sequence: int, indices: tuple[int, ...], now: float) -> None:
        """Settle a current OCR reading whose expanded pixels stayed stable afterward.

        Evidence belongs to this exact observation, never a later revision.
        """
        if sequence != self._sequence:
            return
        for index in indices:
            key = self._assignments[index] if 0 <= index < len(self._assignments) else None
            track = self._tracks.get(key) if key is not None else None
            if track is None or track.last_sequence != sequence or track.absence:
                continue
            track.confirmed = True
            if track.text_candidate:
                _commit_text(track)

    def confirm_observations(
        self, observations: tuple[tuple[int, int, str], ...], now: float
    ) -> None:
        """Confirm preserved probes even after an unrelated partial scan completes.

        The track's own last positive sequence and reading must match; global latest
        OCR sequence is not a substitute for the provenance of each partial update.
        """
        for key, sequence, text in observations[:128]:
            track = self._tracks.get(key)
            if (
                track is None
                or track.last_sequence != sequence
                or track.absence
                or track.reading != text
            ):
                continue
            track.confirmed = True
            if track.text_candidate:
                _commit_text(track)
