# Slice ten — Regional OCR and faster new text

The user confirmed that visual retention substantially improved stability and requested OCR only
for changed regions, occasional full scans, preserved dialogue grouping, and lower new-label latency.

## Implementation

- Dirty tiles accumulate until serviced. Padded regions merge and expand over whole known lines;
  up to four crops / 45% coverage are processed, otherwise one full scan is selected.
- Full discovery scans run on a separate three-second cadence. Revealing dialogue defers only its
  own region; unrelated menus can request OCR on the next capture (120 ms minimum request interval).
- The OCR worker crops source pixels, maps every line/character back to full client coordinates,
  and returns explicit coverage. Artificially clipped detections fall back to a full scan.
- Unscanned tracks never receive absence votes. Existing accepted translations and confidence
  protections remain. Pending crop coverage is unioned on the newest frame; results wait for tracker
  acknowledgement before subsequent work can overwrite them.
- Preserved dialogue probes keep their original per-line observation sequence across unrelated
  scans. Stable pixels can confirm that observation without waiting for another full scan.
- The inspector shows only real observations from its exact frame. Status identifies full/area
  scans; old detections are never relabeled as freshly recognized on a newer image.
- Fixed CUDA recognition batches remove repeated shape-switch stalls when alternating full scans
  and individual labels. Padded outputs are discarded; CPU batching and model weights are unchanged.

## Verification

209 model-free tests cover coverage, coordinate offsets, boundary fallback, coalescing, acknowledgement,
per-line confirmation, dialogue preservation, independent discovery and discarded GPU padding.
Real CPU/GPU crop benchmarks and native dialogue/stationary/new-label fixtures are recorded in
[verification](../verification.md) and [performance](../performance.md). The user confirmed the prior
retention improvement; this slice's exact in-game latency still needs interactive evaluation.

## Limits

Regions include padding and whole neighboring lines; they are not exact per-character masks.
Broad changes, more than four separate regions, or clipped text may require a full scan. The
detector uses a fixed tensor size, so multiple crops have per-call overhead. Very faint/tiny new
text can still require periodic discovery. In-flight model calls cannot be canceled.
