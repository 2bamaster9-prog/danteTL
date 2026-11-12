"""Read-only, bounded snapshots for the optional overlay diagnostic display."""

from dataclasses import dataclass

from jp_overlay.domain import Rect
from jp_overlay.recognition import OcrSnapshot
from jp_overlay.translation import TranslationSnapshot
from jp_overlay.visual import VisualState


@dataclass(frozen=True, slots=True)
class DebugDisplay:
    changed: tuple[Rect, ...] = ()
    scanned: tuple[Rect, ...] = ()
    text: str = ""


def debug_display(
    visual: VisualState,
    ocr: OcrSnapshot,
    translation: TranslationSnapshot | None,
    now: float,
    *,
    waiting_blocks: int = 0,
) -> DebugDisplay:
    frame, result = visual.frame, ocr.result
    size = frame.geometry.client.size if frame else None
    valid = result is not None and size == result.frame.geometry.client.size
    scanned = ()
    if valid and result is not None:
        scanned = (
            result.scanned
            if result.scanned is not None
            else (Rect(0, 0, result.frame.width, result.frame.height),)
        )
    changed = visual.changed_areas if frame and now - frame.captured_at <= 0.5 else ()
    lines = ["DEBUG  Amber: changed pixels   Cyan: last completed OCR"]
    if result and valid:
        scope = "full" if result.scanned is None else f"{len(scanned)} regions"
        area = sum(b.width * b.height for b in scanned) / (result.frame.width * result.frame.height)
        lines.append(
            f"OCR {result.duration_ms:.0f} ms | wait {ocr.queue_ms:.0f} ms | "
            f"{scope}, {area:.0%} | result age {max(0, now - result.completed_at):.1f}s"
        )
    else:
        lines.append(f"OCR: {ocr.state}")
    if ocr.processing_since is not None:
        lines.append(f"OCR running: {max(0, now - ocr.processing_since):.1f}s")
    lines.append(
        f"Visual {visual.duration_ms:.1f} ms | settling {waiting_blocks} blocks | "
        f"reveal holds {len(visual.blocked)} | hidden {len(visual.hidden)}"
    )
    if translation:
        lines.append(
            f"Translation: {translation.state} | pending {translation.pending} | "
            f"last {translation.last_batch_ms:.0f} ms | wait {translation.queue_ms:.0f} ms"
        )
        lines.append(
            f"Last batch: {translation.cache_hits} cache / "
            f"{translation.translated_sources} model | "
            f"model load {translation.load_ms / 1000:.1f}s"
        )
        lines.append(
            f"Last model inference: {translation.last_inference_ms:.0f} ms (excludes cache)"
        )
        if translation.processing_since is not None:
            lines.append(f"Translation running: {max(0, now - translation.processing_since):.1f}s")
    else:
        lines.append("Translation: off")
    return DebugDisplay(changed, scanned, "\n".join(lines))
