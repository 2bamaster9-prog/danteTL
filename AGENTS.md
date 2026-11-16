# DanteJP agent guidance

Read [engineering/README.md](engineering/README.md), then the contracts relevant to the task.

- Use typed values, explicit dependencies and deep modules with small public interfaces.
  Extract state ownership, not arbitrary line counts; avoid forwarding layers and speculative frameworks.
- Preserve functionality unless requested otherwise. Qt views submit commands and render snapshots;
  services own policy. Capture, inference, hashing, downloads and teardown stay off Qt.
- Keep work, queues and images bounded. Validate exact source/revision/generation before publication.
  Worker delays are not absence evidence; retain valid OCR and English through delays.
- Test behavior/failure modes through public commands and snapshots. Prefer explicit-time replays
  for policy; reserve Qt tests for interaction, wiring, presentation and responsiveness.
- Run `uv run python tools/check.py` for code changes. Read [verification](engineering/verification.md)
  and run the checks for each changed boundary. Use owned windows, fake providers and disposable state;
  never capture an unrelated application or charge a real account during automated tests.
- Downloads and cloud use require explicit user actions. No telemetry, automatic model downloads
  or silent provider/billing fallback. Capture and OCR remain local.
- Preserve working native environments; test dependency changes in an isolated candidate.
  CPU/GPU ONNX and CPU/CUDA/Vulkan llama runtimes must not be mixed. Use `.venv-gpu/Scripts/python.exe`
  for strict CUDA checks; preserve the default CPU environment.
- Use DanteJP for user-facing branding, `dantejp` for Python/CLI IDs and `DANTEJP_*` for app
  environment variables. Keep modules in their owning subpackage; no compatibility aliases.
  Packaged resources
  are read-only; writable release state belongs in per-user AppData.
- Keep current guidance in one authoritative place. Update relevant contracts with behavior changes;
  do not add historical plans, dated reports or duplicated rules. Git records change history.
  Keep evidence under ignored `artifacts/`; verify absolute paths before deleting disposable outputs.
