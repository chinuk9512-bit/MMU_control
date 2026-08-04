"""Application-wide dark theme configuration."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


TERMINAL_BACKGROUND = QColor("#111318")
TERMINAL_FOREGROUND = QColor("#f2f4f7")


APPLICATION_STYLE_SHEET = """
QWidget {
    color: #f2f4f7;
    font-weight: 500;
}
QToolTip {
    color: #ffffff;
    background-color: #30343b;
    border: 2px solid #6d7582;
    padding: 3px;
}
QGroupBox {
    border: 2px solid #626a76;
    border-radius: 5px;
    margin-top: 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QLineEdit,
QTextEdit,
QPlainTextEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox,
QListWidget,
QTreeWidget,
QTableWidget {
    color: #f7f8fa;
    background-color: #17191d;
    border: 2px solid #626a76;
    border-radius: 4px;
    padding: 3px;
    font-weight: 500;
}
QLineEdit:focus,
QTextEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus,
QListWidget:focus,
QTreeWidget:focus,
QTableWidget:focus {
    border: 2px solid #79b8f3;
}
QPushButton {
    color: #ffffff;
    background-color: #343943;
    border: 2px solid #737c89;
    border-radius: 4px;
    padding: 5px 10px;
    font-weight: 600;
}
QPushButton:hover {
    background-color: #414854;
    border-color: #91a0b2;
}
QPushButton:focus {
    border-color: #79b8f3;
}
QPushButton:pressed {
    background-color: #262b33;
    border-color: #a7b2c1;
}
QPushButton:disabled,
QLineEdit:disabled,
QTextEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    color: #939aa5;
    background-color: #292d34;
    border-color: #4d535d;
}
"""


def apply_dark_theme(app: QApplication) -> None:
    """Apply a low-glare, high-contrast dark palette to the application."""
    app.setStyle("Fusion")
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#202328",
        QPalette.ColorRole.WindowText: "#f2f4f7",
        QPalette.ColorRole.Base: "#17191d",
        QPalette.ColorRole.AlternateBase: "#25282e",
        QPalette.ColorRole.ToolTipBase: "#30343b",
        QPalette.ColorRole.ToolTipText: "#ffffff",
        QPalette.ColorRole.Text: "#f2f4f7",
        QPalette.ColorRole.Button: "#2b2f36",
        QPalette.ColorRole.ButtonText: "#ffffff",
        QPalette.ColorRole.BrightText: "#ff6b6b",
        QPalette.ColorRole.Link: "#64b5f6",
        QPalette.ColorRole.Highlight: "#356a9a",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#9aa0a8",
    }
    for role, color in colors.items():
        palette.setColor(role, QColor(color))
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#939aa5")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#939aa5"),
    )
    app.setPalette(palette)
    app.setStyleSheet(APPLICATION_STYLE_SHEET)
