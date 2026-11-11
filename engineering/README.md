# Engineering guide

JP Overlay is a local Windows application that translates Japanese game text into English at the
original text locations. The current slice connects stabilized MeikiOCR text to Sugoi V4 through
CTranslate2, bounded caching, and English rendering while retaining raw OCR inspection.

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
| [Current slice](plans/004-local-translation.md) | Deliverables, progress, and remaining gaps |

The harness consists of these documents, executable checks, deterministic tests, and live capture
verification. Add guidance when it resolves a concrete ambiguity; replace stale guidance instead
of accumulating contradictory rules. Application code is the source of implementation truth.
