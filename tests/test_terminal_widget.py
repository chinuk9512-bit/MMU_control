"""Tests for the terminal console widget."""

from __future__ import annotations

import sys
import unittest

from PySide6.QtCore import QMimeData, Qt
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

    def test_paste_updates_command_buffer_before_submit(self) -> None:
        """Pasted commands are submitted instead of only changing visible text."""
        widget = TerminalWidget(prompt="mmu> ")
        submitted: list[str] = []
        widget.commandSubmitted.connect(submitted.append)
        mime_data = QMimeData()
        mime_data.setText("echo pasted")

        widget.insertFromMimeData(mime_data)
        QTest.keyClick(widget, Qt.Key.Key_Return)

        self.assertEqual(submitted, ["echo pasted"])

    def test_multiline_paste_submits_completed_lines(self) -> None:
        """Pasting newline-delimited commands submits each completed line."""
        widget = TerminalWidget(prompt="mmu> ")
        submitted: list[str] = []
        widget.commandSubmitted.connect(submitted.append)
        mime_data = QMimeData()
        mime_data.setText("pwd\nuname -a\n")

        widget.insertFromMimeData(mime_data)

        self.assertEqual(submitted, ["pwd", "uname -a"])

    def test_interactive_paste_is_sent_as_raw_input(self) -> None:
        """Interactive programs receive pasted text immediately."""
        widget = TerminalWidget(prompt="")
        raw_input: list[str] = []
        widget.rawInput.connect(raw_input.append)
        widget.set_interactive_mode(True)
        mime_data = QMimeData()
        mime_data.setText("show status")

        widget.insertFromMimeData(mime_data)

        self.assertEqual(raw_input, ["show status"])

    def test_interactive_backspace_sequence_is_configurable(self) -> None:
        """Minicom can use Ctrl-H/BS instead of the default DEL byte."""
        widget = TerminalWidget(prompt="")
        raw_input: list[str] = []
        widget.rawInput.connect(raw_input.append)
        widget.set_backspace_sequence("\x08")
        widget.set_interactive_mode(True)
        widget.show()
        widget.setFocus()

        QTest.keyClick(widget, Qt.Key.Key_Backspace)

        self.assertEqual(raw_input, ["\x08"])

    def test_interactive_mode_sends_q_and_control_c_immediately(self) -> None:
        """Full-screen programs receive keys without waiting for Enter."""
        widget = TerminalWidget(prompt="")
        raw_input: list[str] = []
        widget.rawInput.connect(raw_input.append)
        widget.set_interactive_mode(True)
        widget.show()
        widget.setFocus()

        QTest.keyClick(widget, Qt.Key.Key_Q)
        QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

        self.assertEqual(raw_input, ["q", "\x03"])


if __name__ == "__main__":
    unittest.main()
