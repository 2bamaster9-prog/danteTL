# Decision 010 — Partial observations with explicit coverage

Status: implemented; refines visual scheduling in decision 009.

Keep the existing `Recognizer.recognize(frame)` boundary. Cropping and coordinate translation live
on the OCR worker and work with either local CPU or CUDA inference. The visual worker returns
bounded physical-pixel areas, using accumulated change tiles, local reveal evidence, and whole-line
closure. Padding protects line recall. Full discovery is independent of local scan requests, so
continuous small changes cannot starve it. Excessive area/count and edge-clipped detections fall
back to full inference.

`OcrResult.scanned` is authoritative: `None` means full frame; a tuple contains the actually scanned
rectangles. Missing detections are negative evidence only for fully covered tracks. A prior miss
cannot settle merely because an unrelated later crop completed. Raw inspection contains only this
frame's real observations, while tracking and English publication retain the accepted scene.

The newest pending frame replaces older pixels but unions pending coverage. Losing an unprocessed
dirty area would leave stale state until discovery. A bounded result acknowledgement prevents a fast
crop from overwriting an earlier result while its visual evidence is still being checked. Pause,
resize and stop invalidate the handshake and all pending work without blocking the UI.

Dialogue probes persist across scans elsewhere, retaining their actual observation sequence and
text. Confirmation validates each track's own last positive observation, never the global latest
OCR sequence. Newline growth continues to reserve groups and block partial translation. Whole-line
coverage and overlap merging keep spatial context around changed dialogue; grouping itself still
uses the accepted full scene, not just the latest crop's rows.

The request interval drops from 200 to 120 ms; capture stays at eight Hz. Visual readiness waits
remain to avoid translating the first characters of a reveal. No speculative translation or new
model/dependency is introduced. Speed must be reported as both warm model time and measured
appearance-to-English time, with first-use costs separately visible.

An alternating full/one-region benchmark exposed a separate CUDA cost: recognition batch changes
repeatedly incurred roughly 0.5 seconds on the installed cuDNN/ORT runtime. Padding CUDA recognition
to four entries and slicing outputs back to the real count removed that stall. Horizontal and
vertical output-count tests prevent padded entries from becoming detections. CPU does not pad.
Warming batch one at initialization did not solve the repeated shape-switch cost and was not kept.
