"""Console-like terminal widget for command input and output."""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QFontDatabase, QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import QApplication, QPlainTextEdit

from mmu_control.core.terminal_sequences import TerminalStreamFilter, strip_terminal_sequences


class TerminalWidget(QPlainTextEdit):
    """Single-pane terminal widget that keeps the prompt and output together."""

    commandSubmitted = Signal(str)
    rawInput = Signal(str)

    def __init__(self, prompt: str = "$ ") -> None:
        super().__init__()
        self._prompt = prompt
        self._buffer = ""
        self._history: list[str] = []
        self._history_index = 0
        self._interactive_mode = False
        self._backspace_sequence = "\x7f"
        self._stream_filter = TerminalStreamFilter()
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

    def set_interactive_mode(self, enabled: bool) -> None:
        """Switch between line editing and immediate remote key input."""
        if self._interactive_mode == enabled:
            return
        if enabled and self._buffer:
            self._replace_buffer("")
        self._interactive_mode = enabled

    @property
    def is_interactive_mode(self) -> bool:
        """Return whether key presses are sent immediately."""
        return self._interactive_mode

    def set_backspace_sequence(self, sequence: str) -> None:
        """Set the bytes sent for Backspace in interactive mode."""
        self._backspace_sequence = sequence

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
        text = self._stream_filter.feed(text)
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
        self._stream_filter.reset()
        self.setPlainText(self._prompt)
        self._move_cursor_to_end()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Handle terminal input like a command prompt."""
        key = event.key()

        if (
            event.matches(QKeySequence.StandardKey.Copy)
            and self.textCursor().hasSelection()
        ):
            self.copy()
            return

        if event.matches(QKeySequence.StandardKey.Paste):
            self._paste_text(self._clipboard_text())
            return

        if (
            key == Qt.Key.Key_C
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self.rawInput.emit("\x03")
            if self._buffer:
                self._replace_buffer("")
            return

        if self._interactive_mode:
            raw_input = self._interactive_key(event)
            if raw_input:
                self.rawInput.emit(raw_input)
            return

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit_buffer()
            return

        if key == Qt.Key.Key_Backspace:
            index = self._buffer_cursor_index()
            if index > 0:
                self._replace_buffer(
                    f"{self._buffer[: index - 1]}{self._buffer[index:]}",
                    index - 1,
                )
            else:
                self._set_cursor_at_buffer_index(0)
            return

        if key == Qt.Key.Key_Delete:
            index = self._buffer_cursor_index()
            if index < len(self._buffer):
                self._replace_buffer(
                    f"{self._buffer[:index]}{self._buffer[index + 1:]}",
                    index,
                )
            else:
                self._set_cursor_at_buffer_index(len(self._buffer))
            return

        if key == Qt.Key.Key_Left:
            self._set_cursor_at_buffer_index(self._buffer_cursor_index() - 1)
            return

        if key == Qt.Key.Key_Right:
            self._set_cursor_at_buffer_index(self._buffer_cursor_index() + 1)
            return

        if key == Qt.Key.Key_Home:
            self._set_cursor_at_buffer_index(0)
            return

        if key == Qt.Key.Key_End:
            self._set_cursor_at_buffer_index(len(self._buffer))
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
            index = self._buffer_cursor_index()
            self._replace_buffer(
                f"{self._buffer[:index]}{event.text()}{self._buffer[index:]}",
                index + len(event.text()),
            )
            return

        super().keyPressEvent(event)

    def _interactive_key(self, event: QKeyEvent) -> str:
        key = event.key()
        special_keys = {
            Qt.Key.Key_Return: "\r",
            Qt.Key.Key_Enter: "\r",
            Qt.Key.Key_Backspace: self._backspace_sequence,
            Qt.Key.Key_Tab: "\t",
            Qt.Key.Key_Escape: "\x1b",
            Qt.Key.Key_Up: "\x1b[A",
            Qt.Key.Key_Down: "\x1b[B",
            Qt.Key.Key_Right: "\x1b[C",
            Qt.Key.Key_Left: "\x1b[D",
            Qt.Key.Key_Home: "\x1b[H",
            Qt.Key.Key_End: "\x1b[F",
            Qt.Key.Key_Delete: "\x1b[3~",
            Qt.Key.Key_PageUp: "\x1b[5~",
            Qt.Key.Key_PageDown: "\x1b[6~",
        }
        if key in special_keys:
            return special_keys[key]
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
                return chr(key - Qt.Key.Key_A + 1)
            return ""
        text = event.text()
        if text and event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return f"\x1b{text}"
        return text

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        """Route pasted text through the terminal input buffer."""
        self._paste_text(source.text() if source.hasText() else "")

    def _clipboard_text(self) -> str:
        return QApplication.clipboard().text()

    def _paste_text(self, text: str) -> None:
        if not text:
            return
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self._interactive_mode:
            self.rawInput.emit(text)
            return
        lines = text.split("\n")
        for line in lines[:-1]:
            index = self._buffer_cursor_index()
            self._replace_buffer(
                f"{self._buffer[:index]}{line}{self._buffer[index:]}",
                index + len(line),
            )
            self._submit_buffer()
        if lines[-1]:
            index = self._buffer_cursor_index()
            self._replace_buffer(
                f"{self._buffer[:index]}{lines[-1]}{self._buffer[index:]}",
                index + len(lines[-1]),
            )

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

    def _replace_buffer(self, buffer: str, cursor_index: int | None = None) -> None:
        cursor = self._remove_live_input()
        self._buffer = buffer
        self._insert_live_input(cursor)
        if cursor_index is not None:
            self._set_cursor_at_buffer_index(cursor_index)

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

    def _buffer_cursor_index(self) -> int:
        """Return the current cursor location relative to the editable buffer."""
        text_length = len(self.toPlainText())
        live_length = len(self._prompt) + len(self._buffer)
        command_start = max(0, text_length - live_length + len(self._prompt))
        index = self.textCursor().position() - command_start
        return max(0, min(len(self._buffer), index))

    def _set_cursor_at_buffer_index(self, index: int) -> None:
        """Move the cursor to an index inside the editable command buffer."""
        index = max(0, min(len(self._buffer), index))
        text_length = len(self.toPlainText())
        live_length = len(self._prompt) + len(self._buffer)
        command_start = max(0, text_length - live_length + len(self._prompt))
        cursor = self.textCursor()
        cursor.setPosition(command_start + index)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

    def _move_cursor_to_end(self) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
