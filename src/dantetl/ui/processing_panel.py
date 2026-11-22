"""Compact live diagnostics; reads worker snapshots without owning processing state."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from dantetl.domain import CaptureSnapshot, CaptureState
from dantetl.i18n import mark, tr
from dantetl.ocr.values import OcrSnapshot
from dantetl.ocr.visual_values import VisualState
from dantetl.translation.values import TranslationSnapshot
from dantetl.ui.controls import InfoButton
from dantetl.ui.localization import localized


class _Card(QWidget):
    def __init__(self, title: str, rows: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self.setObjectName("diagnosticCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        heading = localized(QLabel(), text=title)
        heading.setObjectName("eyebrow")
        layout.addWidget(heading)
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        fields = QGridLayout()
        fields.setHorizontalSpacing(12)
        fields.setVerticalSpacing(5)
        self.values: dict[str, QLabel] = {}
        for row, (name, tip) in enumerate(rows):
            label, value = localized(QLabel(), text=name), QLabel("—")
            label.setObjectName("muted")
            value.setObjectName("diagnosticValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            localized(value, accessibleName=lambda name=name: f"{tr(title)}: {tr(name)}")
            for widget in (label, value):
                localized(widget, toolTip=tip)
                fields.addWidget(widget, row, 0 if widget is label else 1)
            self.values[name] = value
        fields.setColumnStretch(1, 1)
        layout.addLayout(fields)
        layout.addStretch()

    def set_values(self, values: tuple[str, ...]) -> None:
        for label, text in zip(self.values.values(), values, strict=True):
            if label.text() != text:
                label.setText(text)


class ProcessingPanel(QWidget):
    """Last-pass metrics, refreshed at most four times a second while Advanced is visible.

    Status labels also carry setup/errors used by the main-window notices. Metrics never
    retain frames, drive scheduling, or imply the sum is an end-to-end latency measurement.
    """

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        heading = localized(QLabel(), text=mark("PROCESSING · LIVE"))
        heading.setObjectName("eyebrow")
        header.addWidget(heading)
        header.addWidget(
            InfoButton(
                mark("Processing timings"),
                mark(
                    "Capture and OCR stay local. If you select a cloud model, it receives text. "
                    "Timings describe the last completed work, "
                    "not total time from game text to translation. Capture sampling, "
                    "stability checks "
                    "and dialogue grouping add waiting time. Pausing inspection does not pause "
                    "these live metrics. Hover over a translation to see its OCR source."
                ),
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.capture = _Card(
            mark("CAPTURE & STABILITY"),
            (
                (
                    mark("Image"),
                    mark("Physical client pixels; DPI appears in the value's tooltip."),
                ),
                (
                    mark("Capture rate"),
                    mark("Actual session average / requested samples per second."),
                ),
                (
                    mark("Visual check"),
                    mark("Last worker pass comparing pixels and accepted text patterns."),
                ),
                (
                    mark("Text settling"),
                    mark(
                        "Groups not ready for a new translation; previous translations may remain."
                    ),
                ),
                (
                    mark("Regions held"),
                    mark("Unchanged accepted regions retained through the latest OCR."),
                ),
            ),
        )
        self.ocr = _Card(
            mark("TEXT RECOGNITION"),
            (
                (mark("Device"), mark("Actual ONNX provider; automatic fallback is shown as CPU.")),
                (
                    mark("OCR pass"),
                    mark("Last completed OCR inference; hover for its rolling average."),
                ),
                (
                    mark("Wait to start"),
                    mark("OCR source capture to worker start, including scheduling."),
                ),
                (
                    mark("Scan coverage"),
                    mark("Actual completed OCR coverage, not proposed or changed areas."),
                ),
                (
                    mark("Work skipped"),
                    mark("Captures avoided by visual checks / superseded waiting frames."),
                ),
            ),
        )
        self.translation = _Card(
            mark("TRANSLATION"),
            (
                (mark("Model"), mark("The currently committed translation model.")),
                (
                    mark("Model call"),
                    mark("Most recent inference only; a cache hit does not run the model."),
                ),
                (
                    mark("Queue wait"),
                    mark("Latest batch's wait after text became eligible for translation."),
                ),
                (
                    mark("Pending"),
                    mark("Current requests waiting or running; text still settling is separate."),
                ),
                (
                    mark("Last batch"),
                    mark("Distinct source/context pairs served from cache or by the model."),
                ),
                (
                    mark("Cancelled"),
                    mark(
                        "Cloud calls cancelled because no current box needs their text and context."
                    ),
                ),
            ),
        )
        cards = QHBoxLayout()
        for card in (self.capture, self.ocr, self.translation):
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        localized(self.capture.status, text=mark("Capture and OCR stay local"))
        localized(self.ocr.status, text=mark("OCR starts with capture."))
        localized(self.translation.status, text=mark("Translation starts with capture."))
        self.waiting_blocks = 0
        self._refreshed_at = float("-inf")

    def refresh(
        self,
        capture: CaptureSnapshot | None,
        ocr: OcrSnapshot | None,
        translation: TranslationSnapshot | None,
        visual: VisualState,
        *,
        now: float,
        started_at: float,
        capture_rate: int,
        model: str,
    ) -> None:
        if not self.isVisible() or now - self._refreshed_at < 0.25:
            return
        self._refreshed_at = now
        frame = capture.frame if capture and capture.state == CaptureState.RUNNING else None
        states = {
            CaptureState.STARTING: mark("Starting"),
            CaptureState.RUNNING: mark("Running"),
            CaptureState.STOPPING: mark("Stopping"),
            CaptureState.STOPPED: mark("Stopped"),
            CaptureState.FAILED: mark("Failed"),
        }
        self.capture.status.setText(tr(states[capture.state]) if capture else tr("Not capturing"))
        self.capture.set_values(
            (
                f"{frame.width} × {frame.height}",
                tr(
                    "{value:.1f} / {capture_rate} Hz",
                    value=frame.sequence / max(0.1, now - started_at),
                    capture_rate=capture_rate or "∞",
                ),
                tr("{duration_ms:.1f} ms", duration_ms=visual.duration_ms),
                str(self.waiting_blocks),
                str(len(visual.review.unchanged)),
            )
            if frame
            else ("—",) * 5
        )
        self.capture.values["Image"].setToolTip(
            tr("Physical client pixels · DPI {dpi}", dpi=frame.geometry.dpi)
            if frame
            else tr("No current frame.")
        )
        self.capture.status.setToolTip(visual.message or tr("Capture and OCR stay local."))
        result = ocr.result if ocr and frame else None
        if result and frame and result.frame.geometry.client.size != frame.geometry.client.size:
            result = None
        provider = {
            "CUDAExecutionProvider": tr("NVIDIA GPU"),
            "DmlExecutionProvider": tr("DirectML GPU"),
        }
        coverage = "—"
        if result:
            area = sum(b.width * b.height for b in result.scanned or ())
            coverage = (
                tr("Full frame")
                if result.scanned is None
                else tr(
                    mark("1 area · {coverage:.0%}")
                    if len(result.scanned) == 1
                    else mark("{count} areas · {coverage:.0%}"),
                    count=len(result.scanned),
                    coverage=area / (result.frame.width * result.frame.height),
                )
            )
        self.ocr.set_values(
            (
                provider.get(ocr.provider, "CPU" if ocr.provider else "—"),
                tr("{duration_ms:.0f} ms", duration_ms=result.duration_ms) if result else "—",
                tr("{queue_ms:.0f} ms", queue_ms=ocr.queue_ms) if result else "—",
                coverage,
                tr(
                    "{avoided} visual / {skipped_frames} queued",
                    avoided=visual.avoided,
                    skipped_frames=ocr.skipped_frames,
                ),
            )
            if ocr and frame
            else ("—",) * 5
        )
        self.ocr.values["OCR pass"].setToolTip(
            tr(
                "Last completed pass; mean of last 8: {mean_duration_ms:.0f} ms. "
                "{processed_frames} passes completed.",
                mean_duration_ms=ocr.mean_duration_ms,
                processed_frames=ocr.processed_frames,
            )
            if ocr
            else tr("No OCR pass yet.")
        )
        self.translation.set_values(
            (
                model or tr("None selected"),
                tr("{last_inference_ms:.0f} ms", last_inference_ms=translation.last_inference_ms)
                if translation and translation.last_inference_ms
                else "—",
                tr("{queue_ms:.0f} ms", queue_ms=translation.queue_ms) if translation else "—",
                str(translation.pending) if translation else "—",
                tr(
                    "{cache_hits} cached / {translated_sources} model",
                    cache_hits=translation.cache_hits,
                    translated_sources=translation.translated_sources,
                )
                if translation
                else "—",
                str(translation.cancelled_obsolete) if translation else "—",
            )
        )
        if translation:
            self.translation.values["Last batch"].setToolTip(
                tr(
                    "Last batch: {last_batch_ms:.0f} ms; model preparation: {value:.1f} s. "
                    "Cache reuse requires the same text, model/settings and dialogue "
                    "context.",
                    last_batch_ms=translation.last_batch_ms,
                    value=translation.load_ms / 1000,
                )
            )
