# 019: Explicit guided setup and verified download progress

The welcome guide composes the existing model and runtime installers into one confirmed plan.
It is modal and skippable, can be reopened from Settings while idle, and owns one cancellable worker.
Hardware detection recommends a profile without asserting driver compatibility. CPU is always an
option. No download starts merely from startup, selection, detection or entering a page.

Completion/restart preserves first-use model preparation consent. A persisted pending model ID
resumes that selection path after restart; it does not replace the last successfully loaded model.
Existing installations with recognition plus translation weights skip automatic welcome.

uv's piped installer output does not provide reliable per-file byte progress. Instead, export the
locked graph to PEP 751, select compatible Windows x64 CPython 3.12 wheels with `packaging`, stream
their pinned URLs on the worker, verify hashes/sizes, then install local hashed files with uv offline.
This is binary artifact selection from a resolved lock, not a new dependency resolver. Standalone
resources remain read-only, and the AppData environment still uses its own managed Python.

The compressed wheel cache is additional disk usage, shared across runtime profiles. Valid files
survive failure/cancel; an incomplete individual download restarts. Size-unknown files show received
bytes without a percentage. uv's private Python bootstrap retains an explicitly indeterminate
stage; native verification is also activity-only. The UI never parses terminal escape sequences or
guesses download percentages. Existing native probe, activation receipt and restart drain remain.
