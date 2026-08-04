"""Application-wide dark theme configuration."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


TERMINAL_BACKGROUND = QColor("#111318")
TERMINAL_FOREGROUND = QColor("#e6e6e6")


def apply_dark_theme(app: QApplication) -> None:
    """Apply a low-glare, high-contrast dark palette to the application."""
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#202328",
        QPalette.ColorRole.WindowText: "#e6e6e6",
        QPalette.ColorRole.Base: "#17191d",
        QPalette.ColorRole.AlternateBase: "#25282e",
        QPalette.ColorRole.ToolTipBase: "#30343b",
        QPalette.ColorRole.ToolTipText: "#ffffff",
        QPalette.ColorRole.Text: "#e6e6e6",
        QPalette.ColorRole.Button: "#2b2f36",
        QPalette.ColorRole.ButtonText: "#e6e6e6",
        QPalette.ColorRole.BrightText: "#ff6b6b",
        QPalette.ColorRole.Link: "#64b5f6",
        QPalette.ColorRole.Highlight: "#356a9a",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#9aa0a8",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777d86")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#777d86"),
    )
    app.setPalette(palette)
    app.setStyleSheet(
        "QToolTip { color: #ffffff; background-color: #30343b; border: 1px solid #555b65; }"
        "QGroupBox { border: 1px solid #454a53; border-radius: 4px; margin-top: 8px; }"
        "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 3px; }"
    )
