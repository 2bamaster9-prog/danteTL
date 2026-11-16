# Engineering guide

DanteJP captures a selected Windows window, recognizes Japanese locally and overlays English from
an explicitly selected local or cloud translator. These documents describe current behavior.

| Read when changing | Guidance |
| --- | --- |
| Ownership, processing, UI, models, setup or security | [Architecture](architecture.md) |
| Tests or native acceptance | [Verification](verification.md) |
| Packaging, dependencies or CI | [Building](building.md) |
| Performance or model comparisons | [Measurement](performance.md), [benchmark inputs](benchmarks/README.md) |

Keep each contract in one place. Code owns implementation constants; regression tests specify behavior.
Docs explain ownership and constraints needed to change them safely. Update stale guidance rather
than accumulating plans/results. Store disposable evidence under ignored `artifacts/`.
