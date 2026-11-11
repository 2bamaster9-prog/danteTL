# Performance budgets

## Product targets

Design the compact configuration for a recent midrange PC with 16 GB RAM, initially at 1080p.
Aim for about 2 GB application RAM after warm-up and about 2 GB additional VRAM for optional
compact acceleration. Larger quality presets have explicit separate budgets. These are targets,
not measured results for an implemented OCR/translation pipeline.

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
claim about game frame-time impact or full translation memory consumption has been measured yet.

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
