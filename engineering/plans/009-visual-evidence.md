# Slice nine — Frame evidence and stable English publication

The user requested smarter, efficient decisions using frame differences: fewer redundant OCR
passes, faster menu appearance/disappearance, and fewer partial dialogue translations.

## Delivered

- Separate lightweight visual worker with bounded jobs, sampled templates, and generation guards.
- Adaptive full-frame OCR requests for changes/settling, plus periodic refresh; capture and inference
  rates are independent. Default capture is eight samples/second, adjustable from two to twelve.
- Reversible text masking before OCR completes, with two-frame appearance evidence. Fresh visual
  absence plus a completed negative OCR observation can retire an old track and free capacity.
- Expanded reading-area checks for new characters/continuations, exact-observation confirmation,
  and a guard against scheduling translation before its visual source check completes.
- Revealed paragraphs can contain multiple sentences. Static menu grouping stays conservative.
- Regression coverage and live panel-close/reopen checks. Failure reporting is safe on Windows
  terminals that cannot encode Japanese, and visual initialization failure cannot strand shutdown.
- Exact-source visual checks gate OCR reconciliation, not just inference scheduling. Stationary
  regions retain text/geometry through noisy readings and misses, including animated backgrounds.
  Low-confidence readings have three bounded reviews; same-pixel corrections publish English atomically.

## Verification

The fast suite covers 194 behaviors, including tiny continuation additions, static WGC settling,
texture replacement versus background motion, color inversion, stale evidence/generations, capacity
recovery, reordered dense observations, and worker failure/teardown. The live fixture uses actual
Meiki and Sugoi, starts with an empty translation cache, and checks no partial dialogue during its
reveal cadence, profile/grouping toggles, pause, resize, minimize/restore, restart, and shutdown.
Terminal punctuation appended to an actively revealing line uses ordinary confirmation, avoiding
the static-label confidence delay; a replay verifies that static labels keep their protection.
Growing lines reuse their spatial identity even if an unfinished glyph was misread. Thin initial
glyphs use prefix and line-center evidence, preventing duplicate old partial tracks beside new text.
The separate stationary-label fixture uses real capture, Meiki and Sugoi, then deliberately corrupts
and drops OCR output over a moving background. Six English blocks remained identical across 256
display polls and eight noisy OCR passes during twelve seconds. This addresses the failure shown
in the supplied video; that exact game scene still needs a new interactive run.

Recorded performance and final run evidence are in [performance](../performance.md) and
[verification](../verification.md). These are synthetic fixtures, not a claim of perfect behavior
in Honkai: Star Rail or a game frame-time benchmark.

## Try it and remaining limits

Restart using the normal launcher; no setup/download step is needed. Keep eight capture samples
per second initially. Check a crowded menu opening/closing, then reveal dialogue over both static
and animated backgrounds. Status distinguishes visual processing, capture samples, and OCR work.

There is no semantic certainty from pixels. Long pauses can still look complete; low-contrast text,
occlusions, background patterns, and unusual line layouts remain heuristic cases. Already-running
OCR cannot be canceled, so a slow model still delays new English. Inference still covers the full
frame; targeted region OCR is a separate potential speed improvement.
