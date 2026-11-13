"""Shared desktop styling; overlay painting stays independent."""

STYLE = """
            QMainWindow, QWidget { background: #111923; color: #e7edf5; font: 10pt 'Segoe UI'; }
            QLabel#heading { font-size: 23pt; font-weight: 600; }
            QLabel#muted { color: #9baabc; font-size: 9pt; }
            QLabel#eyebrow { color: #92a4b7; font-size: 8pt; font-weight: 600; }
            QPushButton, QComboBox { background: #243142; border: 1px solid #3c4c60;
                border-radius: 6px; padding: 9px 12px; }
            QPushButton:hover { background: #304259; }
            QPushButton:disabled, QComboBox:disabled { color: #64748b; }
            QPushButton#primary { background: #257c73; border-color: #359c90; }
            QPushButton#primary:hover { background: #2d9185; }
            QComboBox QAbstractItemView { background: #1d2938;
                selection-background-color: #257c73; }
            QTableWidget { background: #172230; gridline-color: #304259;
                selection-background-color: #31544f; }
            QHeaderView::section { background: #243142; padding: 6px; border: 0; }
            QSlider::groove:horizontal { height: 4px; background: #35475c; }
            QSlider::handle:horizontal { background: #5eead4; width: 12px; margin: -4px 0;
                border-radius: 6px; }
            QProgressBar { border: 1px solid #3c4c60; border-radius: 4px;
                background: #172230; min-height: 18px; text-align: center; }
            QProgressBar::chunk { background: #257c73; border-radius: 3px; }

    QToolButton { color: #e7edf5; border: 1px solid transparent; padding: 6px; }
    QToolButton:hover { background: #243142; border-radius: 5px; }
    QToolButton:focus, QPushButton:focus, QComboBox:focus, QSpinBox:focus {
        border: 1px solid #5eead4; }
    QToolButton#info { color: #9fb7cb; font-size: 13pt; }
    QTabWidget::pane { border: 1px solid #344557; border-radius: 5px; }
    QTabBar::tab { background: #172230; padding: 10px 14px; color: #aabacc; }
    QTabBar::tab:selected { background: #243142; color: #e7edf5; }
    QSpinBox { padding: 7px; background: #243142; border: 1px solid #3c4c60; border-radius: 5px; }
    QSpinBox:disabled { color: #64748b; }
    QToolTip { background: #243142; color: #e7edf5; border: 1px solid #5eead4; padding: 7px; }
    QWidget#statusBanner { border-radius: 6px; }
    QWidget#statusBanner[tone="warning"] { background: #30291c; border: 1px solid #b58b3c; }
    QWidget#statusBanner[tone="error"] { background: #382127; border: 1px solid #c87580; }
    QWidget#statusBanner[tone="info"] { background: #1b2b39; border: 1px solid #557d9b; }
    QWidget#statusBanner QLabel { background: transparent; }
    QLabel#modelBadge { padding: 9px 12px; border-radius: 6px; font-weight: 600; }
    QLabel#modelBadge[tone="success"] { background: #183b32; color: #82e6bd;
        border: 1px solid #3ca983; }
    QLabel#modelBadge[tone="warning"] { background: #30291c; color: #f0ca7c;
        border: 1px solid #b58b3c; }
"""
