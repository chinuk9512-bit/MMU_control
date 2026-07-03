"""Console-like terminal widget for command input and output."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from mmu_control.core.terminal_sequences import strip_terminal_sequences


class TerminalWidget(QPlainTextEdit):
    """Single-pane terminal widget that keeps the prompt and output together."""

    commandSubmitted = Signal(str)

    def __init__(self, prompt: str = "$ ") -> None:
        super().__init__()
        self._prompt = prompt
        self._history_text = ""
        self._buffer = ""
        self._history: list[str] = []
        self._history_index = 0
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setUndoRedoEnabled(False)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.refresh_display()

    def set_prompt(self, prompt: str) -> None:
        """Change the prompt text shown before the editable command line."""
        self._prompt = prompt
        self.refresh_display()

    def write_output(self, text: str) -> None:
        """Append command output above the live prompt."""
        if not text:
            return
        text = strip_terminal_sequences(text)
        if not text:
            return
        if self._history_text and not self._history_text.endswith("\n"):
            self._history_text += "\n"
        self._history_text += text
        if not self._history_text.endswith("\n"):
            self._history_text += "\n"
        self.refresh_display()

    def write_stream(self, text: str) -> None:
        """Append raw shell output without forcing a trailing newline."""
        if not text:
            return
        text = strip_terminal_sequences(text)
        if not text:
            return
        self._history_text += text.replace("\r\n", "\n").replace("\r", "\n")
        self.refresh_display()

    def clear_terminal(self) -> None:
        """Clear the terminal and restore the prompt."""
        self._history_text = ""
        self._buffer = ""
        self._history.clear()
        self._history_index = 0
        self.refresh_display()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Handle terminal input like a command prompt."""
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit_buffer()
            return

        if key == Qt.Key.Key_Backspace:
            self._buffer = self._buffer[:-1]
            self.refresh_display()
            return

        if key == Qt.Key.Key_Up:
            self._history_up()
            return

        if key == Qt.Key.Key_Down:
            self._history_down()
            return

        blocked_modifiers = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if event.text() and not (event.modifiers() & blocked_modifiers):
            self._buffer += event.text()
            self.refresh_display()
            return

        super().keyPressEvent(event)

    def _submit_buffer(self) -> None:
        command = self._buffer
        self._history.append(command)
        self._history_index = len(self._history)
        self._history_text += f"{self._prompt}{command}\n"
        self._buffer = ""
        self.refresh_display()
        self.commandSubmitted.emit(command)

    def _history_up(self) -> None:
        if not self._history:
            return
        self._history_index = max(0, self._history_index - 1)
        self._buffer = self._history[self._history_index]
        self.refresh_display()

    def _history_down(self) -> None:
        if not self._history:
            return
        self._history_index = min(len(self._history), self._history_index + 1)
        if self._history_index == len(self._history):
            self._buffer = ""
        else:
            self._buffer = self._history[self._history_index]
        self.refresh_display()

    def refresh_display(self) -> None:
        """Redraw the terminal text from the current history and buffer."""
        self.setPlainText(f"{self._history_text}{self._prompt}{self._buffer}")
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
