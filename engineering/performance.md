# Performance budgets

## Product targets

Design the compact configuration for a recent midrange PC with 16 GB RAM, initially at 1080p.
Aim for about 2 GB application RAM after warm-up and about 2 GB additional VRAM for optional
compact acceleration. Larger quality presets have explicit separate budgets. These are targets,
not a validated hardware requirement or sustained pipeline measurement.

Start at four capture samples per second, with translation only on stable changes. Measure latency
from first appearance and from stabilization separately. Initial short-dialogue targets are roughly
0.5–1 second typical and below 1.5 seconds at p95. Dense menus require separate measurements.
Compare game frame times with and without the app; a starting goal is under 5% degradation.

## Milestone one behavior

WGC requests a 250 ms update interval and the adapter bounds frame copies to four per second.
Windows update pacing, unchanged sources, and scheduling can produce fewer samples. The UI reports
the average since session start; this is not the game's FPS. Geometry is polled at approximately
30 Hz so window motion remains responsive. The frame mailbox retains one image. Preview rendering
owns one additional image; temporary copies and native capture surfaces also consume memory.

A 4K BGRA image is approximately 31.6 MiB. Never store an unbounded image history. Stop clears
the frame and preview. Model memory and capture/preview overhead must be measured independently.

## Measurement rules

Record CPU/GPU, RAM, Windows version, resolution, DPI, HDR state, source window mode, dependencies,
warm-up, duration, and workload. Report median and p95 timing plus peak/steady RAM and VRAM when
available. Compare the same scene or replay and distinguish app throughput from game performance.
The development RTX 5080 system does not establish the ordinary-PC target.

The user-selected 4K session showed about 3.5–3.8 captured samples/s during UI verification. No
claim about game frame-time impact has been measured yet. Full-pipeline smoke samples are below.

A single process sample during the running capture/preview session reported 286.1 MiB working set
and 711.8 MiB private memory. These are different Windows process metrics, not interchangeable RAM
budgets, and this snapshot does not measure sustained usage or GPU memory. OCR and translation
models were not loaded.

## OCR inspection measurements (2026-11-13)

MeikiOCR 0.3.5 / ONNX Runtime 1.32.0, CPU provider, two intra-op threads, batch size four.
The three pinned ONNX files total 45,970,040 bytes. No CUDA model/runtime is loaded.

On the development machine, an original 1920 × 1080 synthetic fixture with three Japanese regions
gave about 360 ms model initialization, 62 ms first inference, 47 ms median across five warm
inferences, and 63 ms warm maximum. This tiny sample is a smoke measurement, not a p95 estimate.
The live demo at 1575 × 1015, DPI 168, showed 78 ms for the sampled first displayed result.
There was no simultaneous game-impact benchmark, midrange-PC run, or sustained OCR memory test.
A final replay while the other validation processes ran reported a 62 ms warm median and 63 ms
maximum; this illustrates ordinary scheduling variation rather than a throughput guarantee.

OCR retains one active frame, one replaceable pending frame, and one result/source pair. Capture
retains its latest frame; the inspector retains its displayed result and a Qt image copy. These
may share immutable frame objects but must be budgeted as distinct at worst, plus temporary BGR
and native/model buffers. Pausing stops submissions after the in-flight inference and retains only
the reviewed pair plus current capture. No history grows with session length. Revisit limits with
4K dense-menu and prolonged-session measurements before calling the product budget validated.

## Tracking slice

Tracking stores at most 128 entries (strings, rectangles, counters, timestamps) and no images.
One-to-one matching now considers at most 128 × 512 candidate pairs per new OCR result; ordinary UI
polls only read/settle the small tracked set. Capture and OCR frequency remain unchanged so new
text can still be discovered. Equivalent committed display values no longer request an application
overlay repaint; native expose/resize events may still paint. No game frame-time benchmark or
midrange-PC timing claim is inferred from the deterministic/live correctness checks.

## Translation slice measurements (2026-11-13)

Sugoi V4 revision `71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b`, CTranslate2 4.9.0,
SentencePiece 0.2.3, CPU int8, two threads, beam two. The supplied model.bin is 1,102,425,134 bytes;
runtime quantizes it for CPU computation. Loading validates all pinned files before inference.

On the user's Ryzen 9800X3D / 64 GB / RTX 5080 development PC, the final offline check measured
1,453 ms load/validation and 94 ms for a batch of three short Japanese phrases. The process snapshot
while loaded was 327.5 MiB working set, 333.5 MiB private memory, and 1,095.3 MiB peak working set.
The earlier smoke run measured 1,594 ms load and 109 ms for the same batch. These single runs do
not establish median, p95, long-dialogue latency, or midrange-PC throughput.

The live capture + OCR + translation + inspector fixture at 1575 × 1015 and DPI 168 passed after
switching from beam two to beam five. Its sampled process values were 862.4 MiB working set,
1,412.2 MiB private memory, and 1,623.3 MiB peak working set. Peak includes startup and model
switching. The GUI and its demo are in the same verification process. These Windows metrics are
not interchangeable, and this short run is not a sustained-memory or VRAM measurement. Inference
uses CPU; the game and compositor GPU overhead was not measured. Game frame-time impact, 4K dense
menus, and long sessions remain unbenchmarked.

Translation retains at most 128 desired requests/results, one in-flight batch of four distinct
sources, 512 in-memory cache entries, and 20,000 SQLite rows. Layout caches 256 combinations.
Source text is capped at 512 characters and 512 model tokens; generated output is capped at 256
tokens and checked for termination. These bounds prevent a growing queue/history; they do not
guarantee every workload stays below the product's memory/latency targets.

## Confidence stability slice

Confidence preference adds a few scores/flags and one candidate timestamp per existing track.
It stores no images or spelling history and keeps the 128-track limit. Similarity work runs only on
new OCR observations; unchanged polling never creates votes. Rejected variants keep the same public
track values, so they do not invalidate translation or request overlay repaints. The integration
replay verifies one translation call across repeated noisy readings. No new sustained-memory or
real-game performance measurement is implied.

## Icon cleanup and dialogue grouping

Content cleanup reuses OCR character values and does not add an inference pass, frame copy, or
model. Grouping retains only current signatures/timestamps for at most 128 blocks, capped at six
lines and 512 characters each. It introduces a 350 ms group-settling interval, while singleton
readiness remains unchanged. Longer combined text can cost more per translation but avoids
independently translating each constituent line; benchmark representative dialogue before claiming
a net throughput/latency improvement. Worker batch and cache limits are unchanged.

The grouped live fixture at DPI 168 sampled 855.1 MiB working set, 1,373.3 MiB private memory, and
1,627.3 MiB peak working set after model and grouping toggles. This is a short development-PC
snapshot including its own demo, not a sustained-memory or game-frame-time benchmark.

## Busy-screen persistence (2026-11-13)

`verify_ocr.py --dense` draws 80 labels at 38-pixel font size in a 3840 × 2160 image. Meiki detected
64 regions and made some spelling errors, so this is not a perfect-recognition fixture. With the
existing two-thread CPU settings, five warm passes measured median 468 ms and maximum 485 ms;
earlier runs measured 453/469 and 469/593 ms. Approximate inference capacity for this workload is two passes
per second, below the four-sample capture rate. More capture requests would primarily replace
waiting frames. Real game contents, fonts, and hardware can change these timings substantially.

Reconciliation of those 64 detections, including exact-pixel reference hashes, measured median
8.53 ms and maximum 9.19 ms over five warm passes after moving text normalization behind spatial
rejection (the earlier reconciliation run measured 9.70/10.87 ms). The hash budget is one million pixels per
observation, at most 65,536 per crop, with no crop copies or retained images. Persistent hashes
occupy 16 bytes per track plus Python metadata. Diagnostics retain only eight inference durations
and counters. No new model, frame queue, or thread is added. The ordinary three-region fixture
measured about 0.30 ms tracking in a parallel verification run.

Removal latency follows completed OCR evidence, not a fixed 800 ms age timeout. Three misses
span at least 350 ms; slow OCR can therefore retain disappeared labels longer. Identical crop
pixels retain them, while changed pixels plus a static negative result can settle after 350 ms.
These development-machine smoke measurements do not establish p95, sustained memory, or game impact.

The live slow-worker run took 15.44 seconds including startup, model/profile switching and lifecycle
checks. Its snapshot was 863.0 MiB working set, 1,381.0 MiB private memory, and 1,640.7 MiB peak working
set. The added 900 ms sleep simulates latency; it does not simulate equivalent CPU contention.

## Optional GPU OCR and revealing dialogue (2026-11-13)

RTX 5080 (16,303 MiB reported), NVIDIA driver 610.88, Ryzen 9800X3D, 64 GB. CPU ONNX Runtime 1.32.0;
GPU ONNX Runtime 1.26.0 (CUDA 12.8 build), cuDNN 9.10.2.21, cublas 12.9.2.10. Both use Meiki 0.3.5,
the same model files, two CPU threads, and batches of four. GPU uses HEURISTIC convolution selection
and TF32 disabled. The final benchmark uses perf_counter for sub-tick duration precision on Windows.

| Fixture | CPU warm median / maximum | GPU warm median / maximum | GPU first inference after cache warm-up |
| --- | --- | --- | --- |
| 4K, 80 drawn labels / 64 detections | 476.1 / 483.3 ms | 237.7 / 258.6 ms | 1,308.7 ms |
| 1080p, three Japanese regions | Not remeasured in this slice | 35.7 / 36.6 ms | 1,081.4 ms |

Each warm statistic covers five passes. Dense output included spelling variants on both providers;
this is not an 80/80 recognition result. These development-machine samples are not p95 or game FPS.
GPU model initialization took about 890–915 ms. First use with an empty CUDA kernel cache took
about 54 seconds, dominated by compilation; setup primes a project-local 512 MiB-budget cache.
Subsequent processes reuse it. New kernels or a driver change can require compilation again.

A live GPU typewriter run at 1575 × 1015 / DPI 168 showed complete English 0.75 seconds after the
last character, starting with an empty translation cache. No partial dialogue requests were
published during its reveal cadence. An earlier warm-translation-cache run measured 0.50 seconds.
These include discovery, readiness, Sugoi, UI polling, and rendering; they are single samples.
The GPU live OCR sample for the fixture's mixed English/Japanese content was 156 ms, illustrating
why sparse Japanese-only timings do not predict every screen. A six-Hz capture target can still
outpace a dense OCR worker; only its newest pending frame is retained.

After profile/grouping swaps, the GPU live process (including its demo) sampled 1,656.1 MiB working
set, 3,459.5 MiB private memory, and 2,443.1 MiB peak working set. The slow CPU run sampled 861.8 /
1,380.3 / 1,640.3 MiB respectively. These metrics differ; private memory is not physical RAM usage.
The GPU option has a larger memory footprint and is not a validated 2 GB private-memory budget.
The 512 MiB arena setting applies per ONNX session; total VRAM includes other allocations and has
not been measured independently of the game/desktop. CPU remains the lower-resource option.

Reveal activity adds a few fields per existing track; request retention still caps the combined
ready/retained set at 128. No new frame history, concurrent OCR, or polling inference is introduced.
The old fixed 350 ms post-commit group wait is superseded by source-time quiet periods; see
[decision 008](decisions/008-responsive-ocr.md).

## Visual scheduling and stable accepted regions (2026-11-13)

On the same development PC, the dense 4K fixture (80 drawn labels, 64 detections) measured:

| Work | Median | Maximum | Samples |
| --- | --- | --- | --- |
| Warm GPU OCR | 226.6 ms | 229.4 ms | 5 |
| Tracking with pixel hashes | 11.36 ms | 11.96 ms | 5 |
| Visual checks, unchanged captures | 7.82 ms | 8.86 ms | 15 warm |
| Visual checks, whole image shifted 4–6 pixels | 74.23 ms | 74.88 ms | 8 |
| Visual checks including exact-source OCR review | 27.85 ms | 59.23 ms | 8 |

The first source-review sample also returns from the shifted stress image to the reference image;
its maximum includes those crop checks. Heavy scene changes cost substantially more than idle frames.
These are bounded-worker costs, not UI-thread work, p95, or measured game frame-time impact. The
worker replaces its pending job when behind; no inference queue grows. Candidate and accepted OCR
source frames are referenced alongside the newest capture, with no historical frame list.

Sixteen unchanged captures at eight Hz requested three model passes (initial, settling follow-up,
periodic refresh). This does not imply thirteen additional completed inferences were previously
performed: the original OCR worker already coalesced waiting captures. Regions are locked for
acceptance individually; scheduled model calls still scan the full frame.

Live GPU final-dialogue latency was 0.625 seconds; the CPU test with an added 900 ms sleep measured
1.938 seconds. Menu hiding measured 0.438/0.375 seconds and restoring 0.250/0.250 seconds respectively.
The CPU hide preceded its next OCR result. These are single synthetic runs, not general guarantees.
The GPU process snapshot including the demo was 1,664.6 MiB working set, 3,481.2 MiB private, and
2,438.1 MiB peak working set; CPU slow fixture was 908.1/1,427.7/1,664.7 MiB. Added sleep simulates
latency, not equivalent CPU contention. Capture defaults to eight Hz, adjustable from two to twelve.

The stationary-label stress fixture kept six translations and their geometry unchanged over twelve
seconds, 256 display polls and eight deliberately hostile OCR passes. It tests publication stability,
not translation quality. See [decision 009](decisions/009-visual-evidence.md).

## Regional inference and batch switching (2026-11-13)

The same original 4K fixture draws 80 labels (64 full-scan detections). A regional scan reads one
475 × 130 crop, 61,750 pixels / 0.74% of the image, and recognizes its Japanese label correctly.
OCR crop copying and inference run on the OCR worker.

| Work | CPU median / maximum | CUDA median / maximum |
| --- | --- | --- |
| Full frame, five warm calls | 431.2 / 436.4 ms | 206.4 / 365.3 ms |
| One region, five warm calls | 35.1 / 37.0 ms | 26.3 / 28.3 ms |
| Region immediately after full scan, three alternations | 36.7 / 37.7 ms | 21.6 / 27.1 ms |

The first regional call after model warm-up was 37.1 ms CPU / 24.9 ms CUDA. Initial model loading
and first full inference remain separate (GPU 940.9 + 1,219.2 ms in this run). These are small-sample
development-machine measurements, not p95 or a game frame-time benchmark. Dense whole-frame motion
still costs more in the visual stage; the CPU benchmark recorded 7.70 ms median idle, 72.74 ms for
the shifted-frame stress case, and 28.02 ms including exact-source review.

Before fixed CUDA batches, direct alternating profiling measured one-region calls at 568.6, 572.7,
and 559.5 ms after full scans, versus approximately 21 ms when repeating only the crop. The delay
was in recognition, not detection. Warming a batch of one once did not solve repeated switching.
CUDA now pads recognition to four and discards unused output rows; CPU batching is unchanged. The
extra GPU arithmetic trades a little warm single-region cost for removal of the recurrent stall.

The live new-label fixture scans 3.22% of its client, including padding/context. GPU OCR took 16 ms
and English appeared after 0.468 seconds. The CPU fixture at a separate DPI used 3.66% coverage,
31 ms OCR and 0.469 seconds to English. Both began with a fresh translation cache and retained six
existing translations; CPU explicitly checks their publication and geometry during the update.
These are end-to-end single samples after model loading, not a guaranteed latency for all games.

Discovery targets three seconds independently of local requests. Sixteen unchanged captures now
request two startup scans, versus three in slice nine; later idle scans use the independent deadline.
Broad regions, excessive crop count and edge-clipped detections still use full scans. Multiple crops
pay separate detector overhead, so cropping is not automatically faster for every screen.
