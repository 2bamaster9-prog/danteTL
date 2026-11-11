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
One-to-one matching considers at most 128 × 128 candidate pairs per new OCR result; ordinary UI
polls only read/expire the small tracked set. Capture and OCR frequency remain unchanged so new
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
