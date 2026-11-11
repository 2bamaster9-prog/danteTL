# JP Overlay engineering instructions

Read `engineering/README.md` first. The agreed product plan is in
`engineering/plan.md`; current implementation scope is in
`engineering/plans/001-capture-overlay.md`.

- Use Python with deep modules: small public interfaces that own meaningful complexity.
- Keep Windows, Qt, capture-library, and model details at their respective boundaries.
- Use explicit dependencies and typed values. Do not create generic frameworks for hypothetical needs.
- Runtime processing is local. Do not add network services, telemetry, or automatic model downloads.
- Keep frames and work queues bounded. The UI thread must not perform capture or inference.
- Preserve physical-pixel coordinate contracts, window identity, and session validity checks.
- Treat capture failures as visible recoverable states. Never silently capture another window or monitor.
- Add behavior tests for meaningful failure modes; avoid tests that only repeat implementation details.
- Run `uv run python tools/check.py` for code changes. Real capture verification is separate:
  `uv run python tools/verify_windows.py`. Read `engineering/verification.md` before running it.
- Update relevant engineering documents when architecture or behavior changes; record major choices
  in `engineering/decisions/`. Keep documentation concise and avoid duplicated instructions.
- Do not claim game, mixed-DPI, HDR, or anti-cheat compatibility based solely on a demo window.
- Do not implement later milestones without a user request. OCR and translation are future work.
