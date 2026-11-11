# Engineering guide

JP Overlay is a local Windows application that translates Japanese game text into English at the
original text locations. The current slice adds confidence-aware OCR stability to the existing
MeikiOCR → Sugoi V4 → English overlay pipeline while retaining raw OCR inspection.

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
| [Current slice](plans/005-confidence-stability.md) | Deliverables, progress, and remaining gaps |

The harness consists of these documents, executable checks, deterministic tests, and live capture
verification. Add guidance when it resolves a concrete ambiguity; replace stale guidance instead
of accumulating contradictory rules. Application code is the source of implementation truth.
