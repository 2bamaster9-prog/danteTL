"""Compact, accessible model tradeoffs shared by settings and first-run setup."""

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from jp_overlay.controls import InfoButton, set_tone
from jp_overlay.model_advice import ADVICE, COMPARISON_NOTE


class ModelSummary(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ratings = QWidget()
        grid = QGridLayout(self.ratings)
        grid.setContentsMargins(0, 0, 0, 0)
        self.values: list[QLabel] = []
        for index, name in enumerate(("Dialogue", "Game terms", "Speed", "Memory use")):
            row, column = index // 2, (index % 2) * 2
            grid.addWidget(QLabel(name), row, column)
            value = QLabel()
            value.setObjectName("modelRating")
            self.values.append(value)
            grid.addWidget(value, row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        layout.addWidget(self.ratings)
        capabilities = QHBoxLayout()
        self.cpu, self.gpu, self.context = QLabel(), QLabel(), QLabel()
        for label in (self.cpu, self.gpu, self.context):
            label.setWordWrap(True)
            capabilities.addWidget(label)
        layout.addLayout(capabilities)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        self.size_label.setWordWrap(True)
        footer = QHBoxLayout()
        footer.addWidget(self.size_label, 1)
        footer.addWidget(
            InfoButton(
                "Model ratings",
                COMPARISON_NOTE + " Speed assumes GPU for language models. "
                "Capability checks indicate support, not an installed runtime. "
                "Download size is not RAM/VRAM usage.",
            )
        )
        layout.addLayout(footer)
        self.setToolTip(COMPARISON_NOTE)

    def set_model(
        self, key: str, size: int, language_model: bool, *, imported: bool = False
    ) -> None:
        advice = None if imported else ADVICE.get(key)
        self.ratings.setVisible(advice is not None)
        if advice:
            for label, rating in zip(
                self.values,
                (advice.dialogue, advice.terms, advice.speed, advice.memory),
                strict=True,
            ):
                label.setText(rating.text)
                label.setToolTip(rating.detail)
                set_tone(label, rating.tone)
        self.cpu.setText("✓ CPU support")
        self.gpu.setText("✓ GPU support" if language_model else "— CPU only")
        self.context.setText("✓ Dialogue context" if language_model else "✕ No context")
        self.gpu.setToolTip("NVIDIA CUDA or Vulkan; optional runtime setup is separate.")
        self.cpu.setToolTip("CPU execution is supported; larger models can be slow.")
        size_text = f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"
        self.size_label.setText(
            f"{'Local file' if imported else 'Download'}: {size_text}"
            + (" · Not rated" if not advice else "")
        )
        self.setVisible(bool(size))
