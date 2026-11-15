# Translation benchmark inputs

`japanese-game-text.json` is the fixed synthetic corpus; references aid review rather than specify
unique correct translations. `translation-models.json` pins candidates. Both are executable inputs
of `tools/benchmark_translation.py` and must remain with that tool.

Use an installed matching runtime and existing weights. Downloads require explicit `--download`;
benchmarks do not change app selections or register models. Read each tool's `--help`.

```powershell
.venv-gpu/Scripts/python.exe -m tools.benchmark_translation --device cuda --models gemma sugoi --repeats 3 --output artifacts/comparison
.venv/Scripts/python.exe -m tools.report_translation_benchmark artifacts/comparison --output artifacts/comparison-review
```

Run models serially, verify actual GPU offload, and separate loading/warm-up from request latency.
Report errors/rejections and category timings; these exclude capture/OCR/rendering and game FPS.
Review omissions, actors/targets, negation, numbers, names and tone. Exact English-reference matches
are not quality scores; a tuned corpus is not held-out evidence. Keep reports in ignored `artifacts/`.
