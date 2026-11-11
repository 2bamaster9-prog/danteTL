# Engineering guide

JP Overlay is a local Windows application that will translate Japanese game text into English
at the original text locations. Window capture and overlay alignment are established; the current
milestone adds local MeikiOCR with frame-matched accuracy inspection.

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
| [Current milestone](plans/002-ocr-inspection.md) | Deliverables, progress, and remaining gaps |

The harness consists of these documents, executable checks, deterministic tests, and live capture
verification. Add guidance when it resolves a concrete ambiguity; replace stale guidance instead
of accumulating contradictory rules. Application code is the source of implementation truth.
