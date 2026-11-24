"""History recalls commands without submitting them or retaining Enter records."""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mmu_control.ui.terminal_widget import TerminalWidget


@pytest.fixture
def terminal():
    app = QApplication.instance() or QApplication([])
    widget = TerminalWidget(prompt="test> ")
    widget.show()
    widget.setFocus()
    app.processEvents()
    yield widget
    widget.close()


def test_blank_enter_is_sent_but_not_stored_or_recalled(terminal):
    submitted = []
    terminal.commandSubmitted.connect(submitted.append)
    QTest.keyClicks(terminal, "echo hello")
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    QTest.keyClick(terminal, Qt.Key.Key_Enter)
    assert submitted == ["echo hello", "", ""]
    assert terminal._history == ["echo hello"]
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "echo hello"
    assert submitted == ["echo hello", "", ""]
    QTest.keyClick(terminal, Qt.Key.Key_Down)
    assert terminal._buffer == ""
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    assert submitted[-1] == "echo hello"


@pytest.mark.parametrize("ending", ["\n", "\r", "\r\n", "\n\r\n"])
def test_submit_removes_only_trailing_enter_characters(terminal, ending):
    submitted = []
    terminal.commandSubmitted.connect(submitted.append)
    command = "  echo first\necho second  "
    terminal._replace_buffer(command + ending)
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    assert submitted == [command]
    assert terminal._history == [command]
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == command
    assert len(submitted) == 1


def test_legacy_history_skips_blank_entries_and_cleans_both_directions(terminal):
    submitted = []
    terminal.commandSubmitted.connect(submitted.append)
    terminal._history = ["", "\n", "first\r\n", "", "\r\n", "second\n", "\n"]
    terminal._history_index = len(terminal._history)
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "second"
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "first"
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "first"
    QTest.keyClick(terminal, Qt.Key.Key_Down)
    assert terminal._buffer == "second"
    QTest.keyClick(terminal, Qt.Key.Key_Down)
    assert terminal._buffer == ""
    assert submitted == []


def test_recalled_command_sends_one_newline_only_when_enter_is_pressed(terminal):
    from mmu_control.core.interactive_shell import InteractiveShell
    class Channel:
        closed = False
        def __init__(self):
            self.sent = []
        def send(self, text):
            self.sent.append(text)
            return len(text)
    channel = Channel()
    shell = InteractiveShell(channel)
    terminal.commandSubmitted.connect(shell.send_line)
    terminal._replace_buffer("echo hello\r\n")
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    assert channel.sent == ["echo hello\n"]
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert channel.sent == ["echo hello\n"]
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    assert channel.sent == ["echo hello\n", "echo hello\n"]


def test_clear_display_preserves_history_and_resets_recall_position(terminal):
    submitted = []
    terminal.commandSubmitted.connect(submitted.append)
    for command in ("first", "second"):
        terminal._replace_buffer(command)
        QTest.keyClick(terminal, Qt.Key.Key_Return)
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    terminal.write_output("old output")
    terminal.clear_terminal()
    assert terminal.toPlainText() == "test> "
    assert terminal._buffer == ""
    assert terminal._history == ["first", "second"]
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "second"
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == "first"
    QTest.keyClick(terminal, Qt.Key.Key_Down)
    assert terminal._buffer == "second"
    assert submitted == ["first", "second"]


def test_explicit_new_session_reset_can_still_clear_history(terminal):
    terminal._replace_buffer("old-session-command")
    QTest.keyClick(terminal, Qt.Key.Key_Return)
    terminal.clear_terminal(clear_history=True)
    assert terminal._history == []
    QTest.keyClick(terminal, Qt.Key.Key_Up)
    assert terminal._buffer == ""
