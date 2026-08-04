"""Tests for the application-wide visual theme."""

from __future__ import annotations

import sys
import unittest

import pytest

pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from mmu_control.ui.theme import apply_dark_theme


class ThemeTest(unittest.TestCase):
    """Verify that high-contrast controls and text are applied globally."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_theme_uses_high_contrast_text(self) -> None:
        apply_dark_theme(self.app)

        palette = self.app.palette()
        self.assertEqual(palette.color(QPalette.ColorRole.Text).name(), "#f2f4f7")
        self.assertEqual(
            palette.color(QPalette.ColorRole.ButtonText).name(), "#ffffff"
        )

    def test_theme_defines_clear_control_borders_and_focus_state(self) -> None:
        apply_dark_theme(self.app)

        style_sheet = self.app.styleSheet()
        self.assertIn("QLineEdit,", style_sheet)
        self.assertIn("QPushButton {", style_sheet)
        self.assertIn("border: 2px solid #626a76;", style_sheet)
        self.assertIn("border: 2px solid #79b8f3;", style_sheet)
        self.assertIn("font-weight: 600;", style_sheet)


if __name__ == "__main__":
    unittest.main()
