# Decision 009 — Visual evidence before recognition finishes

Status: implemented. Refines decisions 007 and 008 without replacing model/runtime boundaries.

## Problem

Inference results arrive too late to drive every display decision. Waiting for several OCR misses
leaves closed menus visible; inferring on every capture wastes work on unchanged pixels. Text can
also continue outside an old line's box while its older recognized prefix appears stable.

## Decision

Add one bounded visual worker between capture and inference. Capture defaults to eight samples per
second, independently of OCR requests. A coarse grayscale tile comparison finds novel changes and
settling; local text probes resolve relevant changes. A 1.5-second full refresh prevents indefinite
suppression by ambiguous/small/continuously moving content. Requests coalesce and never overlap
model calls. Use existing OpenCV/NumPy; no new model, dependency, network access, or service.

Known text gets small reference templates. Two captured frames with strong spatial-pattern loss
temporarily mask the exact committed track. Two positive observations restore it. Preserve identity
and published English while masked. Retirement still needs negative OCR: a completed miss plus
fresh visual absence may retire immediately, before new track admissions. Identical crop pixels,
truncated observations, stale references, and mismatched revisions cannot trigger early retirement.
Otherwise retain the older three-miss policy. This is stronger evidence, not certainty of absence.

Match spatial patterns and edges with tolerance for brightness, polarity inversion, and small
shifts. Edge coincidence alone was insufficient against textured replacement backgrounds. Weak
templates defer to OCR. A 640 x 360 thumbnail and tile motion counters avoid checking unchanged
areas repeatedly. Cap current anchors and reading probes at 128 each, templates at 256 x 48, and
sampled input to a crop at 1024 x 192. Keep no full-frame history. The worker owns at most one active
and one waiting job; snapshots retain one current frame. All native image work runs off the UI.

Expanded reading areas include the continuation space to the right and, for likely dialogue,
below. Additions resembling new strokes block stale partial translation before OCR recognizes the
new characters. Detect even a small first continuation character, independently of the larger
general-motion threshold. Background replacement alone is not treated as typing. Stable expanded
pixels may confirm the exact current OCR reading without another model call; they cannot bypass
the protected weaker-reading interval. A static WGC source still settles without another callback.
Appended sentence punctuation on a line with reveal history is treated as normal growth, not a
protected OCR variant. Static labels still keep the longer confidence preference interval.
Reuse identity at a tight shared line origin even when a partially revealed trailing glyph was
misread. Prefix growth also tolerates a shorter first glyph centered in the eventual line. Otherwise
old partial tracks could survive beside a longer new track and independently translate their fragment.

New translation work waits until the visual worker has examined its OCR source. Retained English
does not depend on readiness. Grouping permits completed sentences to continue when reveal activity
supports one paragraph; static menus retain conservative punctuation/geometry safeguards.

## Stationary-label correction after the user's video

The supplied monitor recording showed stationary labels disappearing and alternating translations.
Scheduling fewer model calls alone did not govern replacement: tracking still accepted conflicting
OCR, and exact pixel hashes could fail over animated backgrounds. The video includes camera motion
and the English overlay, so it demonstrates the experience but is not clean capture input for pixel
calibration. It is not checked into Git.

New OCR now waits for the visual worker to compare its exact source against accepted templates.
Local foreground-stroke cells distinguish changed digits from dim moving backgrounds; brightness,
antialiasing and small alignment changes are tolerated. A same-row extension guard detects growing
text beyond its old bounds. Dim stars must not trigger that guard. Unchanged regions retain their
text, bounds and identity despite OCR misses, radically different readings, or detector crop noise.
Only unchanged evidence for the exact current track/revision and candidate frame can grant this.

Below 0.90 accepted OCR confidence (or with an unknown score), permit three matched review attempts.
A correction must exceed the previous score by more than 0.01 and substantially overlap the same
box; weaker/equal readings never win. Attempts survive winning corrections and alternating readings.
They reset on an observed local content change, not elapsed time. Confidence measures recognition,
not English quality; high-confidence OCR can still be wrong.

`EnglishPresentation` owns at most 128 publications. During an explicitly marked same-pixel OCR
correction, it retains the exact old block/English pair until the new pair is ready, then swaps it
atomically. It follows correction lineage across all members and clears on real edits, changed
membership, removal, session invalidation, or backend/grouping changes. Raw inspector results remain
untouched and translation workers still reject stale requests. No arbitrary stale text is relabeled
as a translation of a new source. Reversible masking retains the publication without displaying it.

This is region-specific acceptance, not region-only model inference. Periodic scans can still read
locked regions; their output cannot churn the accepted display. Unknown/weak templates retain the
ordinary OCR fallback, so this policy is not a guarantee for every font/background.

## Tradeoffs and limits

This does not infer true panel boundaries, predict how long a typing pause will last, or cancel
native inference. General animation can still request extra scans; weak visual evidence may keep
closed text until OCR confirms it. Strong flashes/occlusions can temporarily mask valid text.
Full-scene movement costs more than an idle visual pass; record both in benchmarks. Sampling costs
increase with capture rate, so keep it adjustable. Runtime failure falls back visibly to ordinary
OCR and can be retried by restarting the session. Generation guards cover all resets and shutdown.

ROI inference and explicit panel detection remain separate improvements. They need their own
coordinate, recall, and grouping evaluation before replacing full-frame OCR.

References: [OpenCV image derivatives](https://docs.opencv.org/4.x/d2/d2c/tutorial_sobel_derivatives.html)
and [image filtering](https://docs.opencv.org/4.x/d4/d86/group__imgproc__filter.html).
