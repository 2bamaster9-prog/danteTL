# OCR observation fixtures

`button_ocr.json` contains MeikiOCR 0.3.5 text, scores, and boxes measured from the user-supplied
Honkai: Star Rail button crop, placed in synthetic 1920 × 1080 and 3840 × 2160 canvases. Coordinates
are normalized back to the crop's origin. The 4K cases include a weak spurious `中` or `@` on the
adjacent icon. The crop itself and full frames are not included in the repository.

These observations reproduce content/geometry instability deterministically without model downloads
or game access. They are a regression case, not an OCR quality benchmark.
