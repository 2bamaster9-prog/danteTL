# Slice 020: Required OCR included

- Bundle only the three verified pinned MeikiOCR model files in the standalone release.
- Preserve upstream notices, licenses, source references and manifest hashes.
- Read directly from the bundle on a fresh installation; do not copy or download at startup.
- Keep explicit model-path overrides and complete AppData models working after relocation.
- Retain Verify / repair with atomic AppData publication, local reuse and explicit downloads.
- Show Included with app in Models; first-run setup focuses on translation/GPU choices.
- Verify missing/corrupt/partial files, repair cancellation, source compatibility, fresh offline
  packaged OCR, native setup/inspection and the relocated EXE without Python on PATH.

No new OCR model version, inference/scheduling changes, translation bundling or runtime upgrades.
