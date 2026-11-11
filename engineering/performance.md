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
