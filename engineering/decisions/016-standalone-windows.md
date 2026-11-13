# 016: Standalone Windows folder with private Python

Distribute a ZIP containing a small native GUI `DanteJP.exe` and `_internal`. Bundle uv-managed
CPython 3.12.16 and the locked CPU dependencies. The launcher resolves paths relative to itself and
starts private pythonw with isolated mode and bytecode writes disabled. It needs no system Python,
PATH changes, installer, administrator rights or one-file extraction on each launch.

This keeps ordinary Python/native package loading for Qt, ONNX, CTranslate2 and optional llama.cpp.
Avoiding a frozen import environment makes in-app runtime installation and child probing simpler.
Build using uv 0.13.8 and Zig 0.14.1; users need neither. CPU base excludes development tools, GPU
dependencies and translation weights. [Decision 020](020-bundled-ocr.md) adds required OCR weights.
Preserve package license metadata, CPython/uv/model notices and
generate a file manifest. The launcher is unsigned; signing/installer delivery are later work.

`paths` separates current read-only app resources from writable state. A bundled marker selects
`%LOCALAPPDATA%/DanteJP`; source checkouts retain existing project-local paths. Explicit model-path
overrides remain supported; `DANTEJP_DATA_DIR` permits isolated packaged acceptance profiles.
Models, preferences, SQLite, preparation receipts, driver cache, runtime receipts and dependency
cache all use state. Multiple app versions share it; no silent copying/deletion of developer models.

Explicit GPU setup runs bundled uv against the current locked project with `--no-install-project`.
It manages Python in AppData, never links a venv's base to the movable EXE folder, and never edits a
loaded runtime. App/probe/demo subprocesses load source from the current bundle using an isolated
bootstrap. Runtime receipts fingerprint dependencies; ordinary UI/source updates can reuse them.
After dependencies change, revalidation/setup is required. A failed selected-runtime launch retains
the bundled CPU fallback and a visible explanation. Qt acknowledgement and hotkey handoff remain
unchanged. No downloads occur at startup; model and runtime setup remain explicit UI actions.

Uninstalling the folder leaves AppData intact. Users can remove AppData separately to delete models
and settings. A portable folder does not mean data is stored beside the EXE.

References: [uv Python distributions](https://docs.astral.sh/uv/concepts/python-versions/) and
[standalone distribution layout](https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html).
