import pytest
from test_live_session import frame

from dantejp.domain import Rect
from dantejp.languages.source import SourceLanguage
from dantejp.ocr.tracking import TextTracker, prepare_matching
from dantejp.ocr.values import OcrResult, TextRegion

# Exercise the generic policy without registering another supported OCR language.
PORTUGUESE = SourceLanguage("pt", "Portuguese", warmup_text="Mapa")


def test_matching_evidence_is_scoped_to_its_source_language():
    source = frame(1)
    result = OcrResult(source, (TextRegion("por que", Rect(10, 10, 100, 25)),), 25, 1.0)
    tracker = TextTracker(language=PORTUGUESE)
    with pytest.raises(ValueError, match="evidence"):
        tracker.observe(result, matching=prepare_matching(result, ()))
    assert tracker.observe(result, matching=prepare_matching(result, (), language=PORTUGUESE)) == (
        1,
    )
