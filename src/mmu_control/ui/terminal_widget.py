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
        self._buffer = ""
        self._history: list[str] = []
        self._history_index = 0
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setUndoRedoEnabled(False)
        self.setMaximumBlockCount(10_000)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setPlainText(self._prompt)
        self._move_cursor_to_end()

    def set_prompt(self, prompt: str) -> None:
        """Change the prompt text shown before the editable command line."""
        cursor = self._remove_live_input()
        self._prompt = prompt
        self._insert_live_input(cursor)

    def write_output(self, text: str) -> None:
        """Append command output above the live prompt."""
        if not text:
            return
        text = strip_terminal_sequences(text)
        if not text:
            return
        cursor = self._remove_live_input()
        if cursor.position() and str(self.document().characterAt(cursor.position() - 1)) != "\n":
            cursor.insertText("\n")
        cursor.insertText(text)
        if not text.endswith("\n"):
            cursor.insertText("\n")
        self._insert_live_input(cursor)

    def write_stream(self, text: str) -> None:
        """Append raw shell output without forcing a trailing newline."""
        if not text:
            return
        text = strip_terminal_sequences(text)
        if not text:
            return
        cursor = self._remove_live_input()
        cursor.insertText(text.replace("\r\n", "\n").replace("\r", "\n"))
        self._insert_live_input(cursor)

    def clear_terminal(self) -> None:
        """Clear the terminal and restore the prompt."""
        self._buffer = ""
        self._history.clear()
        self._history_index = 0
        self.setPlainText(self._prompt)
        self._move_cursor_to_end()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Handle terminal input like a command prompt."""
        key = event.key()

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit_buffer()
            return

        if key == Qt.Key.Key_Backspace:
            self._replace_buffer(self._buffer[:-1])
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
            self._replace_buffer(self._buffer + event.text())
            return

        super().keyPressEvent(event)

    def _submit_buffer(self) -> None:
        command = self._buffer
        self._history.append(command)
        self._history_index = len(self._history)
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\n")
        self._buffer = ""
        self._insert_live_input(cursor)
        self.commandSubmitted.emit(command)

    def _history_up(self) -> None:
        if not self._history:
            return
        self._history_index = max(0, self._history_index - 1)
        self._replace_buffer(self._history[self._history_index])

    def _history_down(self) -> None:
        if not self._history:
            return
        self._history_index = min(len(self._history), self._history_index + 1)
        if self._history_index == len(self._history):
            buffer = ""
        else:
            buffer = self._history[self._history_index]
        self._replace_buffer(buffer)

    def refresh_display(self) -> None:
        """Keep the cursor at the live command line."""
        self._move_cursor_to_end()

    def _replace_buffer(self, buffer: str) -> None:
        cursor = self._remove_live_input()
        self._buffer = buffer
        self._insert_live_input(cursor)

    def _remove_live_input(self) -> QTextCursor:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        tail_length = len(self._prompt) + len(self._buffer)
        if tail_length:
            cursor.movePosition(
                QTextCursor.MoveOperation.Left,
                QTextCursor.MoveMode.KeepAnchor,
                tail_length,
            )
            cursor.removeSelectedText()
        return cursor

    def _insert_live_input(self, cursor: QTextCursor) -> None:
        cursor.insertText(f"{self._prompt}{self._buffer}")
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _move_cursor_to_end(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
