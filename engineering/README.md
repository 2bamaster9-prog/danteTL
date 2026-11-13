# Engineering guide

DanteJP is a local Windows application that translates Japanese game text into English at the
original text locations. The current slice uses cheap visual evidence to schedule OCR, mask closed
text panels promptly, retain unchanged accepted labels through noisy OCR, and detect continuing
dialogue before the next model result arrives. Changed areas now receive cropped OCR with periodic
full discovery, while tracking retains the rest of the scene.

Read these documents as relevant to the task:

| Document | Purpose |
| --- | --- |
| [Agreed plan](plan.md) | Product behavior, scope, model choices, and milestones |
| [Architecture](architecture.md) | Boundaries, coordinate contracts, concurrency, and ownership |
| [Principles](principles.md) | Python and software design conventions |
| [Verification](verification.md) | Fast checks, live checks, and manual acceptance |
| [Performance](performance.md) | Budgets and measurement rules |
| [Decisions](decisions/001-desktop-foundation.md) | Why the initial architecture was selected |
| [OCR decision](decisions/002-local-ocr.md) | Offline models, CPU inference, and inspection policy |
| [Tracking decision](decisions/003-stable-display.md) | Matching, confirmation, and repaint policy |
| [Translation decision](decisions/004-local-translation.md) | Backend boundary, caching, and English layout |
| [Confidence decision](decisions/005-confidence-stability.md) | Preferred readings and genuine-change safeguards |
| [Content/grouping decision](decisions/006-text-content-and-dialogue.md) | Character bounds, icon evidence, and dialogue units |
| [Persistence decision](decisions/007-evidence-based-persistence.md) | Slow OCR, missed detections, and pixel evidence |
| [Responsive OCR decision](decisions/008-responsive-ocr.md) | Reveal readiness, GPU isolation, and fallback |
| [Visual evidence decision](decisions/009-visual-evidence.md) | Change scheduling, occlusion, and readiness |
| [Regional OCR decision](decisions/010-regional-ocr.md) | Partial coverage, coordinate mapping, and discovery |
| [Gemma/debug decision](decisions/011-gemma-and-diagnostics.md) | Optional quality backend and diagnostic boundaries |
| [Models/context decision](decisions/012-model-management-and-context.md) | Explicit setup, AMD boundaries, and bounded conversation memory |
| [Runtime setup decision](decisions/013-in-app-runtime-setup.md) | Explicit installs, isolated environments, and restart |
| [UI decision](decisions/014-settings-and-inspection.md) | Settings ownership, persistence, and independent inspection |
| [Hotkey decision](decisions/015-global-hotkeys.md) | Native global actions, rebinding and lifecycle ownership |
| [Standalone decision](decisions/016-standalone-windows.md) | Private Python, AppData and relocatable GPU runtimes |
| [Shared CUDA decision](decisions/017-shared-cuda.md) | One NVIDIA library family for OCR and Gemma |
| [CPU language-model decision](decisions/018-cpu-llm-runtime.md) | Bundled CPU translation and model-independent runtimes |
| [First-run decision](decisions/019-first-run-setup.md) | Explicit guided setup and verified download progress |
| [Bundled OCR decision](decisions/020-bundled-ocr.md) | Required recognition included, writable repairs kept separate |
| [Current slice](plans/020-bundled-ocr.md) | Bundled MeikiOCR and first-run translation-only downloads |

The harness consists of these documents, executable checks, deterministic tests, and live capture
verification. Add guidance when it resolves a concrete ambiguity; replace stale guidance instead
of accumulating contradictory rules. Application code is the source of implementation truth.
