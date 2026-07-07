"""Tests for the main window UI skeleton."""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QApplication, QLineEdit

from mmu_control.core.config_manager import ConfigManager
from mmu_control.models.settings import AppSettings, BoardSettings, SSHSettings
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

    def send(self, text: str) -> int:
        self.sent.append(text)
        return len(text)

    def respond_to_prompt(self, output: str, prompt: str, response: str) -> bool:
        if prompt.lower() not in output.lower():
            return False
        self.send_line(response)
        return True

    def read_available(self) -> str:
        output, self.output = self.output, ""
        return output

    def close(self) -> None:
        self.is_open = False


class FakeSSHManager:
    """SSH manager fake that exposes one shell."""

    def __init__(self) -> None:
        self.shell = FakeShell()
        self.sftp_shell: FakeShell | None = None
        self._shell_open_count = 0
        self.connected_settings = None

    def connect(self, settings: object) -> None:
        self.connected_settings = settings

    def open_shell(self) -> FakeShell:
        if self._shell_open_count == 0:
            result = self.shell
        else:
            self.sftp_shell = FakeShell()
            result = self.sftp_shell
        self._shell_open_count += 1
        return result

    def reconnect(self) -> None:
        self.shell = FakeShell()
        self.sftp_shell = None
        self._shell_open_count = 0

    def disconnect(self) -> None:
        pass

    def list_serial_ports(self) -> list[str]:
        return ["/dev/ttyACM0", "/dev/ttyUSB0"]


class ImmediateTaskRunner:
    """Run background tasks inline so UI tests stay deterministic."""

    def submit(self, task: object, on_success: object, on_error: object) -> None:
        try:
            result = task()
        except Exception as exc:
            on_error(exc)
        else:
            on_success(result)


class MainWindowTest(unittest.TestCase):
    """Tests for the main application window."""

    @classmethod
    def setUpClass(cls) -> None:
        """Create a QApplication for widget tests."""
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def process_events_until(
        self,
        condition: Callable[[], bool],
        timeout_seconds: float = 2.0,
    ) -> None:
        """Process Qt events until a condition is met or a timeout expires."""
        deadline = time.monotonic() + timeout_seconds
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def create_window(self, **kwargs: object) -> MainWindow:
        kwargs.setdefault(
            "config_manager",
            ConfigManager(Path(self.temp_dir.name) / "settings.json"),
        )
        kwargs.setdefault("task_runner", ImmediateTaskRunner())
        return MainWindow(**kwargs)

    def test_main_window_initial_state(self) -> None:
        """Main window exposes the expected Task 2 controls."""
        window = self.create_window()

        self.assertEqual(window.windowTitle(), "MMU Control")
        self.assertEqual(window.ssh_port_input.value(), 22)
        self.assertFalse(window.disconnect_button.isEnabled())
        self.assertFalse(window.reconnect_button.isEnabled())
        self.assertEqual(window.terminal_widget.toPlainText(), f"{window._local_cwd}> ")
        self.assertEqual(window.ssh_password_input.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(window.board_password_input.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertFalse(window.open_sftp_button.isEnabled())
        self.assertEqual(window.connection_status_label.text(), "SSH: disconnected")

    def test_terminal_commands_run_locally_without_ssh_shell(self) -> None:
        """Terminal input runs against the local PC when SSH is disconnected."""
        window = self.create_window()

        window.terminal_widget.commandSubmitted.emit("pwd")

        self.assertIn(window._local_cwd, window.terminal_widget.toPlainText())
        self.assertEqual(window.connection_status_label.text(), "SSH: disconnected")

    def test_terminal_commands_are_sent_to_connected_ssh_shell(self) -> None:
        """Terminal input and SSH output share the terminal widget."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")

        window._connect_ssh()
        window.terminal_widget.commandSubmitted.emit("pwd")
        window._poll_shell()

        self.assertEqual(manager.shell.sent, ["pwd"])
        self.assertIn("/home/user", window.terminal_widget.toPlainText())
        self.assertEqual(window.connection_status_label.text(), "SSH: connected")

    def test_empty_ssh_enter_filters_remote_echo_newline(self) -> None:
        """Blank Enter on SSH should leave a single prompt line, not a double newline."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()

        window.terminal_widget.commandSubmitted.emit("")
        manager.shell.output = "\r\nuser@server:~$ "
        window._poll_shell()

        self.assertNotIn("\n\nuser@server", window.terminal_widget.toPlainText())

    def test_htop_q_and_control_c_are_sent_as_raw_input(self) -> None:
        """Interactive commands can be exited without pressing Enter."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()

        window.terminal_widget.commandSubmitted.emit("htop")
        self.assertTrue(window.terminal_widget.is_interactive_mode)
        window.terminal_widget.rawInput.emit("q")

        self.assertEqual(manager.shell.sent, ["htop", "q"])
        self.assertFalse(window.terminal_widget.is_interactive_mode)

    def test_command_sets_can_be_saved_selected_and_run(self) -> None:
        """The Commands tab persists command sets and runs them in the SSH shell."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = FakeSSHManager()
            store = CommandSetStore(Path(temp_dir) / "command_sets.json")
            window = self.create_window(ssh_manager=manager, command_set_store=store)
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

    def test_open_sftp_starts_session_from_connected_ssh_shell(self) -> None:
        """Open SFTP sends a board SFTP command through the connected shell."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_password_input.setText("secret")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()

        self.assertEqual(manager.shell.sent, [])
        self.assertIsNotNone(manager.sftp_shell)
        self.assertEqual(
            manager.sftp_shell.sent,
            ["rm -f ~/.ssh/known_hosts", "sftp root@[fe80::1%eth0]"],
        )
        self.assertIn(
            "Opening SFTP session: sftp root@[fe80::1%eth0]",
            window.sftp_output.toPlainText(),
        )
        self.assertEqual(window.board_status_label.text(), "Board: SFTP connected")

        window.server_path_input.setText("/tmp/update file.bin")
        window.board_path_input.setText("/opt/update.bin")
        window.sftp_terminal.commandSubmitted.emit("ls")
        window.upload_sftp_button.click()
        window.download_sftp_button.click()

        self.assertEqual(
            manager.sftp_shell.sent,
            [
                "rm -f ~/.ssh/known_hosts",
                "sftp root@[fe80::1%eth0]",
                "ls",
                "put '/tmp/update file.bin' /opt/update.bin",
                "get /opt/update.bin '/tmp/update file.bin'",
            ],
        )

        window.close_sftp_button.click()
        window.terminal_widget.commandSubmitted.emit("pwd")

        self.assertEqual(manager.shell.sent, ["pwd"])
        self.assertTrue(manager.shell.is_open)
        self.assertFalse(manager.sftp_shell.is_open)

    def test_open_sftp_reports_missing_board_ip(self) -> None:
        """Open SFTP surfaces validation errors instead of doing nothing."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_username_input.setText("root")

        window._connect_ssh()
        window.open_sftp_button.click()

        self.assertEqual(manager.shell.sent, [])
        self.assertIn(
            "SFTP error: Board IP address is required.",
            window.sftp_output.toPlainText(),
        )
        self.assertEqual(window.board_status_label.text(), "Board: SFTP failed")

    def test_settings_are_loaded_and_saved_on_close(self) -> None:
        """Connection, board, USB, and window settings survive a restart."""
        config = ConfigManager(Path(self.temp_dir.name) / "settings.json")
        config.save(
            AppSettings(
                ssh=SSHSettings(host="server", port=2200, username="user", password="pw"),
                board=BoardSettings(ip_address="10.0.0.2", username="root", usb_port="/dev/ttyUSB0"),
            )
        )
        window = self.create_window(config_manager=config)

        self.assertEqual(window.ssh_host_input.text(), "server")
        self.assertEqual(window.ssh_port_input.value(), 2200)
        self.assertEqual(window.usb_port_combo.currentText(), "/dev/ttyUSB0")

        window.board_interface_input.setText("eth0")
        window.close()

        self.assertEqual(config.load().board.interface, "eth0")

    def test_remote_usb_refresh_and_minicom(self) -> None:
        """Remote serial ports can be discovered and opened with minicom."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()

        window.refresh_usb_button.click()
        window.usb_port_combo.setCurrentText("/dev/ttyUSB0")
        window.open_minicom_button.click()

        self.assertEqual(window.usb_port_combo.count(), 2)
        self.assertEqual(manager.shell.sent, ["minicom -o -c off -D /dev/ttyUSB0"])

        window.close_minicom_button.click()

        self.assertEqual(manager.shell.sent[-1], "\x01x\n")


if __name__ == "__main__":
    unittest.main()
