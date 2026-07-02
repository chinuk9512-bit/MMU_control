"""Tests for the main window UI skeleton."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PySide6.QtWidgets import QApplication

from mmu_control.models.command_set import CommandSet
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.ui.main_window import MainWindow


class FakeShell:
    """Interactive shell fake used by the window integration test."""

    def __init__(self) -> None:
        self.is_open = True
        self.sent: list[str] = []
        self.output = "user@server:~$ "

    def send_line(self, command: str) -> int:
        self.sent.append(command)
        self.output += f"{command}\r\n/home/user\r\nuser@server:~$ "
        return len(command) + 1

    def read_available(self) -> str:
        output, self.output = self.output, ""
        return output

    def close(self) -> None:
        self.is_open = False


class FakeSSHManager:
    """SSH manager fake that exposes one shell."""

    def __init__(self) -> None:
        self.shell = FakeShell()
        self.connected_settings = None

    def connect(self, settings: object) -> None:
        self.connected_settings = settings

    def open_shell(self) -> FakeShell:
        return self.shell

    def reconnect(self) -> None:
        self.shell = FakeShell()

    def disconnect(self) -> None:
        pass


class MainWindowTest(unittest.TestCase):
    """Tests for the main application window."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create a QApplication for widget tests."""
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_main_window_initial_state(self) -> None:
        """Main window exposes the expected Task 2 controls."""
        window = MainWindow()

        self.assertEqual(window.windowTitle(), "MMU Control")
        self.assertEqual(window.ssh_port_input.value(), 22)
        self.assertFalse(window.disconnect_button.isEnabled())
        self.assertFalse(window.reconnect_button.isEnabled())
        self.assertEqual(window.terminal_widget.toPlainText(), "mmu> ")
        self.assertFalse(window.open_sftp_button.isEnabled())
        self.assertEqual(window.connection_status_label.text(), "SSH: disconnected")

    def test_terminal_commands_are_sent_to_connected_ssh_shell(self) -> None:
        """Terminal input and SSH output share the terminal widget."""
        manager = FakeSSHManager()
        window = MainWindow(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")

        window._connect_ssh()
        window.terminal_widget.commandSubmitted.emit("pwd")
        window._poll_shell()

        self.assertEqual(manager.shell.sent, ["pwd"])
        self.assertIn("/home/user", window.terminal_widget.toPlainText())
        self.assertEqual(window.connection_status_label.text(), "SSH: connected")

    def test_command_sets_can_be_saved_selected_and_run(self) -> None:
        """The Commands tab persists command sets and runs them in the SSH shell."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeSSHManager()
            store = CommandSetStore(Path(temp_dir) / "command_sets.json")
            window = MainWindow(ssh_manager=manager, command_set_store=store)
            command_set = CommandSet(
                name="diagnostics",
                description="Collect status",
                commands="pwd\nuname -a",
            )

            window._save_command_set(command_set)

            self.assertEqual(window.command_set_list.count(), 1)
            self.assertEqual(window.command_set_list.currentItem().text(), "diagnostics")
            self.assertTrue(window.edit_command_button.isEnabled())
            self.assertIn("Collect status", window.command_set_output.toPlainText())

            window.ssh_host_input.setText("server")
            window.ssh_username_input.setText("user")
            window._connect_ssh()
            window._run_command_set()

            self.assertEqual(manager.shell.sent, ["pwd", "uname -a"])


if __name__ == "__main__":
    unittest.main()
