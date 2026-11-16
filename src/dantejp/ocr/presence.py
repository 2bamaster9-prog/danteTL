"""Bounded exact-pixel evidence for missed text; no image history or model calls."""

from hashlib import blake2b

from dantejp.domain import CapturedFrame, Rect


class FrameEvidence:
    """Hash small text crops with a per-observation budget, retaining only digests.

    Equal pixels support keeping previously recognized text. Changed pixels alone
    do not prove absence: the tracker must also receive negative OCR evidence.
    Unavailable/oversized crops return None and fall back to OCR confirmation.
    """

    def __init__(self, frame: CapturedFrame, pixel_budget: int = 1_000_000) -> None:
        self._frame = frame
        self._pixels = memoryview(frame.bgra)
        self._remaining = pixel_budget

    def fingerprint(self, bounds: Rect) -> bytes | None:
        frame = self._frame
        area = bounds.width * bounds.height
        if (
            min(bounds.size) <= 0
            or area > min(65_536, self._remaining)
            or len(self._pixels) != frame.width * frame.height * 4
            or not Rect(0, 0, frame.width, frame.height).contains(bounds)
        ):
            return None
        self._remaining -= area
        digest = blake2b(digest_size=16)
        for y in range(bounds.y, bounds.y + bounds.height):
            offset = (y * frame.width + bounds.x) * 4
            digest.update(self._pixels[offset : offset + bounds.width * 4])
        return digest.digest()
