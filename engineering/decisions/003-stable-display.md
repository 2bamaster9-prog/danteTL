# 003 — Stable display state over repeated OCR observations

Status: accepted.

The user confirmed good OCR accuracy but observed jitter as the app replaced boxes every pass.
Treat OCR as observations of persistent regions, not as a fresh overlay layout. Implement this
slice before translation so future translation can key off committed text revisions.

Use a bounded, deterministic Python tracker on the GUI coordinator thread. There are at most
128 tracks and 128 candidate observations per pass, with no image history. Matching occurs only
once per completed OCR sequence. Keep the worker/model boundary unchanged and avoid a tracking
library or extra service for this scale of problem.

## Initial policy

| Situation | Behavior |
| --- | --- |
| New nonempty region | Display immediately with a monotonically allocated ID |
| Reordered detections | Associate one-to-one by proximity, overlap, text, and orientation |
| Small coordinate noise | Hold the previous display box exactly |
| Moderate move or changed crop size | Require two consecutive nearby candidate positions |
| Large coherent move, similar box size | Move immediately, retaining the ID |
| Text differs | Require two consecutive equal normalized candidates, then revise content once |
| A pending edit's captured frame stays latest | Settle it after 350 ms without requiring another identical frame |
| One missing/empty observation | Keep the displayed box briefly and clear pending edits |
| Two missing observations | Remove the track |
| Capture advances but OCR stops confirming | Remove after 800 ms from last observed capture |
| Source frame itself is unchanged | Retain matched tracks; no arbitrary age-based flicker |
| Pause, resize, minimize, failure, stop/source change | Clear tracking with OCR session validity |

Geometry tolerance is 20% of the box's shorter side, clamped to 3–12 physical pixels. It is measured
against committed geometry, so slow cumulative drift eventually exceeds the tolerance. A similarly
sized box moving by at least three tolerances follows immediately. Crop expansion alone does not.

An unchanged WGC source may stop delivering frames. Pending content/geometry can therefore settle
after 350 ms with no newer captured frame. Advancing capture cannot use this exception. A long gap
preserves a still-matching identity but clears pending confirmation counts. Repeated UI polls never
count as additional observations.

Text normalization uses NFKC and removes whitespace for matching/confirmation. Raw OCR text remains
untouched in the inspector. Fuzzy similarity (0.8 for strings at least six characters long), shared
prefixes, or strong spatial overlap can preserve association. They do not make changed content
equivalent forever: meaningful short labels and numbers also commit after confirmation.

Keep observed bounds, pending changes, last-seen time, and misses private to the tracker. The public
immutable `TextTrack` contains only ID, committed text, bounds, orientation, and text revision.
Repeated equivalent observations retain that object. The renderer compares values before requesting
an update, so confidence fluctuations and new frame objects cannot trigger unnecessary repaint.

## Tradeoffs and limits

Two observations normally add one sampling interval (about 250 ms) after the first changed result.
This trades a small delay for stability. A disappearing label may linger for one missed pass, at most
the time limit on an advancing source. New one-frame false positives are still possible. Matching is
greedy, not semantic understanding; crossing duplicate labels and split/merge layout changes can
produce new identities. No optical flow, scene-cut model, or unbounded text history is introduced.

Keep a default-on **Stabilize game boxes** checkbox for comparison. The inspector always displays
the exact raw OCR frame, geometry, and text, using associated persistent IDs. Rendering stabilized
coordinates on the raw preview would obscure the accuracy evidence it was built to expose.
