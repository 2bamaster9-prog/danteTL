"""Compact live diagnostics; reads worker snapshots without owning processing state."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jp_overlay.controls import InfoButton
from jp_overlay.domain import CaptureSnapshot, CaptureState
from jp_overlay.ocr_values import OcrSnapshot
from jp_overlay.translation_values import TranslationSnapshot
from jp_overlay.visual_values import VisualState


class _Card(QWidget):
    def __init__(self, title: str, rows: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self.setObjectName("diagnosticCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        heading = QLabel(title)
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
            label, value = QLabel(name), QLabel("—")
            label.setObjectName("muted")
            value.setObjectName("diagnosticValue")
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            value.setAccessibleName(f"{title}: {name}")
            for widget in (label, value):
                widget.setToolTip(tip)
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
        heading = QLabel("PROCESSING · LIVE")
        heading.setObjectName("eyebrow")
        header.addWidget(heading)
        header.addWidget(
            InfoButton(
                "Processing timings",
                "All processing stays on this PC. Timings describe the last completed work, "
                "not total time from game text to English. Capture sampling, stability checks "
                "and dialogue grouping add waiting time. Pausing inspection does not pause "
                "these live metrics. Preview text is raw OCR; hover English cells for its source.",
            )
        )
        header.addStretch()
        layout.addLayout(header)
        self.capture = _Card(
            "CAPTURE & STABILITY",
            (
                ("Image", "Physical client pixels; DPI appears in the value's tooltip."),
                ("Capture rate", "Actual session average / requested samples per second."),
                ("Visual check", "Last worker pass comparing pixels and accepted text patterns."),
                (
                    "Text settling",
                    "Groups not ready for a new translation; accepted English may remain.",
                ),
                ("Regions held", "Unchanged accepted regions retained through the latest OCR."),
            ),
        )
        self.ocr = _Card(
            "TEXT RECOGNITION",
            (
                ("Device", "Actual ONNX provider; automatic fallback is shown as CPU."),
                ("OCR pass", "Last completed OCR inference; hover for its rolling average."),
                ("Wait to start", "OCR source capture to worker start, including scheduling."),
                ("Scan coverage", "Actual completed OCR coverage, not proposed or changed areas."),
                ("Work skipped", "Captures avoided by visual checks / superseded waiting frames."),
            ),
        )
        self.translation = _Card(
            "TRANSLATION",
            (
                ("Model", "The currently committed translation model."),
                ("Model call", "Most recent inference only; a cache hit does not run the model."),
                ("Queue wait", "Latest batch's wait after text became eligible for translation."),
                (
                    "Pending",
                    "Current requests waiting or running; text still settling is separate.",
                ),
                ("Last batch", "Distinct source/context pairs served from cache or by the model."),
            ),
        )
        cards = QHBoxLayout()
        for card in (self.capture, self.ocr, self.translation):
            cards.addWidget(card, 1)
        layout.addLayout(cards)
        self.capture.status.setText("Capture and OCR stay local")
        self.ocr.status.setText("OCR starts with capture.")
        self.translation.status.setText("Translation starts with capture.")
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
        self.capture.status.setText(capture.state.capitalize() if capture else "Not capturing")
        self.capture.set_values(
            (
                f"{frame.width} × {frame.height}",
                f"{frame.sequence / max(0.1, now - started_at):.1f} / {capture_rate} Hz",
                f"{visual.duration_ms:.1f} ms",
                str(self.waiting_blocks),
                str(len(visual.unchanged)),
            )
            if frame
            else ("—",) * 5
        )
        self.capture.values["Image"].setToolTip(
            f"Physical client pixels · DPI {frame.geometry.dpi}" if frame else "No current frame."
        )
        self.capture.status.setToolTip(visual.message or "Capture and OCR stay local.")
        result = ocr.result if ocr and frame else None
        if result and frame and result.frame.geometry.client.size != frame.geometry.client.size:
            result = None
        provider = {"CUDAExecutionProvider": "NVIDIA GPU", "DmlExecutionProvider": "DirectML GPU"}
        coverage = "—"
        if result:
            area = sum(b.width * b.height for b in result.scanned or ())
            coverage = (
                "Full frame"
                if result.scanned is None
                else f"{len(result.scanned)} {'area' if len(result.scanned) == 1 else 'areas'} · "
                f"{area / (result.frame.width * result.frame.height):.0%}"
            )
        self.ocr.set_values(
            (
                provider.get(ocr.provider, "CPU" if ocr.provider else "—"),
                f"{result.duration_ms:.0f} ms" if result else "—",
                f"{ocr.queue_ms:.0f} ms" if result else "—",
                coverage,
                f"{visual.avoided} visual / {ocr.skipped_frames} queued",
            )
            if ocr and frame
            else ("—",) * 5
        )
        self.ocr.values["OCR pass"].setToolTip(
            f"Last completed pass; mean of last 8: {ocr.mean_duration_ms:.0f} ms. "
            f"{ocr.processed_frames} passes completed."
            if ocr
            else "No OCR pass yet."
        )
        self.translation.set_values(
            (
                model or "None selected",
                f"{translation.last_inference_ms:.0f} ms"
                if translation and translation.last_inference_ms
                else "—",
                f"{translation.queue_ms:.0f} ms" if translation else "—",
                str(translation.pending) if translation else "—",
                f"{translation.cache_hits} cached / {translation.translated_sources} model"
                if translation
                else "—",
            )
        )
        if translation:
            self.translation.values["Last batch"].setToolTip(
                f"Last batch: {translation.last_batch_ms:.0f} ms; "
                f"model preparation: {translation.load_ms / 1000:.1f} s. "
                "Cache reuse requires the same text, model/settings and dialogue context."
            )
