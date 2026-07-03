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

    def test_typing_and_output_do_not_replace_the_whole_document(self) -> None:
        """Incremental rendering avoids the old full-document redraw bottleneck."""

        class CountingTerminal(TerminalWidget):
            def __init__(self) -> None:
                self.replace_count = 0
                super().__init__(prompt="mmu> ")

            def setPlainText(self, text: str) -> None:  # noqa: N802
                self.replace_count += 1
                super().setPlainText(text)

        widget = CountingTerminal()
        initial_count = widget.replace_count

        QTest.keyClicks(widget, "status")
        widget.write_stream(" ready")

        self.assertEqual(widget.replace_count, initial_count)


if __name__ == "__main__":
    unittest.main()
