"""Read-only, bounded snapshots for the optional overlay diagnostic display."""

from dataclasses import dataclass

from dantetl.domain import Rect
from dantetl.i18n import tr
from dantetl.ocr.values import OcrSnapshot
from dantetl.ocr.visual_values import VisualState
from dantetl.translation.values import TranslationSnapshot


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
    lines = [tr("DEBUG  Amber: changed pixels   Cyan: last completed OCR")]
    if result and valid:
        scope = "full" if result.scanned is None else tr("{count} regions", count=len(scanned))
        area = sum(b.width * b.height for b in scanned) / (result.frame.width * result.frame.height)
        lines.append(
            tr(
                "OCR {duration_ms:.0f} ms | wait {queue_ms:.0f} ms | {scope}, {area:.0%} | "
                "result age {value:.1f}s",
                duration_ms=result.duration_ms,
                queue_ms=ocr.queue_ms,
                scope=scope,
                area=area,
                value=max(0, now - result.completed_at),
            )
        )
    else:
        lines.append(tr("OCR: {state}", state=ocr.state))
    if ocr.processing_since is not None:
        lines.append(tr("OCR running: {value:.1f}s", value=max(0, now - ocr.processing_since)))
    lines.append(
        tr(
            "Visual {duration_ms:.1f} ms | settling {waiting_blocks} blocks | reveal holds "
            "{count} | pattern loss {count2}",
            duration_ms=visual.duration_ms,
            waiting_blocks=waiting_blocks,
            count=len(visual.blocked),
            count2=len(visual.hidden),
        )
    )
    if translation:
        lines.append(
            tr(
                "Translation: {state} | pending {pending} | last {last_batch_ms:.0f} ms | "
                "wait {queue_ms:.0f} ms",
                state=translation.state,
                pending=translation.pending,
                last_batch_ms=translation.last_batch_ms,
                queue_ms=translation.queue_ms,
            )
        )
        lines.append(
            tr(
                "Last batch: {cache_hits} cache / {translated_sources} model | model load "
                "{value:.1f}s",
                cache_hits=translation.cache_hits,
                translated_sources=translation.translated_sources,
                value=translation.load_ms / 1000,
            )
        )
        lines.append(
            tr(
                "Last model inference: {last_inference_ms:.0f} ms (excludes cache)",
                last_inference_ms=translation.last_inference_ms,
            )
        )
        if translation.processing_since is not None:
            lines.append(
                tr(
                    "Oldest active translation: {value:.1f}s",
                    value=max(0, now - translation.processing_since),
                )
            )
        if translation.cancelled_obsolete:
            lines.append(
                tr(
                    "Obsolete cloud requests cancelled: {cancelled_obsolete}",
                    cancelled_obsolete=translation.cancelled_obsolete,
                )
            )
    else:
        lines.append(tr("Translation: off"))
    return DebugDisplay(changed, scanned, "\n".join(lines))
