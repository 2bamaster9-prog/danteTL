# Decision 007 — Screen state survives slow OCR

Status: accepted and implemented. Supersedes the age-based expiry in decision 003.

## Problem and evidence

The user reported repeated disappearing/reappearing English on crowded screens. The tracker
expired observations 800 ms after capture, even while OCR was running. A replay with 80 labels
and 1.1-second inference returned zero visible tracks immediately after recognition. Slow gaps
also reset pending edits, preventing consecutive observations from confirming new content.
Limiting input to the first 128 detections made detector ordering another source of false misses.

OCR already owns one active frame and one replaceable waiting frame. Increasing the capture rate
cannot increase inference throughput when the worker is saturated. Keep four samples/second and
the existing two-thread CPU model settings; measure processing separately from capture.

## State and removal

Committed text, IDs, bounds, group membership, and English remain available while newer work runs.
Only new completed OCR observations can contribute negative votes. Duplicate polls, skipped frames,
and elapsed processing time cannot remove a track. Two consecutive misses are tolerated; three
misses spanning at least 350 ms remove it unless exact crop pixels still support presence.
Redetection resets the absence run. Slow but consecutive positive observations still confirm edits.
Resize, pause, minimize, stop, source failure, and OCR failure retain their explicit clearing rules.

`presence.FrameEvidence` hashes accepted text crops in the completed observation's source frame.
Each track keeps a 16-byte digest and bounds, never an image. On a miss, identical crop pixels
retain the committed text and reset its missing run. Changed pixels alone do not remove it.
An unchanged crop in a second completed observation can also confirm initial content for translation.
A negative OCR result plus changed crop pixels can settle after 350 ms from completion when that
frame remains the latest capture; this handles static screens without requiring duplicate WGC frames.
Without pixel evidence, static time alone cannot supply additional negative votes.

Hashes cover at most 65,536 pixels per crop and 1,000,000 pixels per observation (four million BGRA
bytes). Memoryview row slices avoid crop copies. Missing checks have budget priority. Unavailable,
large, invalid, or over-budget crops fall back to OCR votes. Only accepted source readings refresh
references; committing a different source invalidates its previous reference. No OCR/model work is
added to the UI thread; bounded matching and fingerprinting remain part of observation reconciliation.

Up to 512 observations are considered for 128 live tracks. Existing matches are assigned before
new admissions. Truncated input does not prove a missing track is absent. An incompatible overlapping
candidate waits for the old track's absence confirmation instead of erasing it on one observation.

## Diagnostics and tradeoffs

Worker snapshots expose completed/skipped counts, capture-to-start time, average inference time
over eight passes, and current-pass start time. They store no additional screenshots or text history.
The UI shows processing and skipped-frame status, with details in its tooltip.

This is evidence-based persistence, not perfect visual understanding. Animated backgrounds can
change crop pixels while text remains. Repeated genuine OCR failures can still remove a present
label. A false positive on identical pixels can persist until the crop changes or the session resets.
Unknown visual evidence on a static screen can retain a box longer. A hung worker retains the last
state until recovery/failure/reset; its elapsed processing time remains visible. Discovery/removal
latency is still bounded by actual inference throughput, and scene cuts/optical flow remain future work.
