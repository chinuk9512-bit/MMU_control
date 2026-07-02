"""Tests for the terminal console widget."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mmu_control.ui.terminal_widget import TerminalWidget


class TerminalWidgetTest(unittest.TestCase):
    """Tests for single-pane terminal input and output."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create a QApplication for widget tests."""
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_submit_command_and_append_output(self) -> None:
        """Typing a command emits it and output appears in the same widget."""
        widget = TerminalWidget(prompt="mmu> ")
        submitted: list[str] = []
        widget.commandSubmitted.connect(submitted.append)

        widget.show()
        widget.setFocus()
        QTest.keyClicks(widget, "echo hello")
        QTest.keyClick(widget, Qt.Key.Key_Return)
        widget.write_output("hello")

        self.assertEqual(submitted, ["echo hello"])
        self.assertIn("mmu> echo hello", widget.toPlainText())
        self.assertIn("hello", widget.toPlainText())
        self.assertTrue(widget.toPlainText().endswith("mmu> "))

    def test_raw_stream_output_keeps_remote_prompt_inline(self) -> None:
        """Raw shell output can leave an editable command after its prompt."""
        widget = TerminalWidget(prompt="")

        widget.write_stream("user@server:~$ ")
        QTest.keyClicks(widget, "pwd")

        self.assertEqual(widget.toPlainText(), "user@server:~$ pwd")


if __name__ == "__main__":
    unittest.main()
