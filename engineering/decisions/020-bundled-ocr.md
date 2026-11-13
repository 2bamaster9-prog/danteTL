# 020: Include required OCR models in the standalone release

MeikiOCR is the required recognition backend. Its three pinned ONNX assets total 45,970,040 bytes,
small enough to include so first launch can recognize text without a separate download. Translation
models remain explicit downloads, and GPU runtimes remain optional. Source checkouts retain their
existing explicit setup. This supersedes the earlier exclusion of all weights from standalone ZIPs.

Ship original verified files in read-only app resources, with upstream model cards, LGPL-3.0/GPL-3.0
texts, available inference sources and pinned provenance. The model files stay separate and the
application source/validation hashes remain inspectable and modifiable. The Meiki Python package's
Apache-2.0 metadata remains separate from the weights' LGPL-3.0 declaration.

Resolution honors an explicit `JP_OVERLAY_MODEL_DIR`; otherwise a complete AppData copy takes
precedence over the current bundle. Partial AppData files do not hide a complete bundle. The UI
checks sizes only, and loading/repair still verifies hashes off the GUI thread. Missing/corrupt
files cause the existing visible repair state, never implicit network access.

Verify / repair can validate bundled files without copying them. If repair is necessary, reuse
verified bundled bytes and download only missing/damaged assets, publishing atomically in AppData.
Never modify the installed app. The first-run guide shows included recognition and excludes it from
the download plan. Existing source-mode paths and translation/model-runtime separation stay intact.

Upstream pinned sources:
- [Detection](https://huggingface.co/rtr46/meiki.text.detect.v0/tree/a9cffa4f60cbf72ddb87edf19c6f98a01cd042e6)
- [Recognition](https://huggingface.co/rtr46/meiki.txt.recognition.v0/tree/a28cf5874dc2438ebb1c86336be26bcec51e3375)
