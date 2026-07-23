"""Tests for the main window UI skeleton."""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from collections.abc import Callable
from pathlib import Path

import pytest

# PySide6 loads native Qt GUI libraries during import.  Skip these widget
# tests when a minimal test container does not provide that runtime instead
# of aborting collection for the entire test suite.
pytest.importorskip("PySide6.QtGui", exc_type=ImportError)

from PySide6.QtCore import QMimeData, QPointF, QUrl, Qt
from PySide6.QtGui import QDropEvent, QValidator
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabWidget,
)

from mmu_control.core.config_manager import ConfigManager
from mmu_control.models.command_set import CommandSet
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType
from mmu_control.models.settings import (
    AppSettings,
    BoardSettings,
    PowerSupplySettings,
    SSHSettings,
    WindowSettings,
)
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.storage.automation_store import AutomationStore
from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog
from mmu_control.ui.main_window import MainWindow


class FakeShell:
    """Interactive shell fake used by the window integration test."""

    def __init__(self) -> None:
        self.is_open = True
        self.sent: list[str] = []
        self.output = "user@server:~$ "

    def send_line(self, command: str) -> int:
        self.sent.append(command)
        if command.startswith("sftp "):
            self.output += f"{command}\r\nsftp> "
        elif command.startswith("ls -alL ") or command.startswith("ls -al ") or command == "ls":
            self.output += (
                f"{command}\r\n"
                "drwxr-xr-x    2 root     root         4096 Jan  1 00:00 mmu-dir\r\n"
                "-rw-r--r--    1 root     root           42 Jan  1 00:00 mmu-file.txt\r\n"
                "sftp> "
            )
        elif command == "pwd":
            self.output += f'{command}\r\nRemote working directory: "/tmp"\r\nsftp> '
        elif command.startswith("cd "):
            self.output += f"{command}\r\nsftp> "
        else:
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
        self.executed_commands: list[str] = []
        self.uploaded_files: list[tuple[str, str]] = []

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

    def execute_command(self, command: str) -> str:
        if command == "printf '%s\n' \"$HOME\"":
            return "/home/user\n"
        self.executed_commands.append(command)
        return (
            "d\t/home/user/server-dir\n"
            "f\t/home/user/server-file.txt\n"
        )

    def upload_file(self, local_path: str, remote_path: str) -> None:
        self.uploaded_files.append((local_path, remote_path))


class HangingSftpShell(FakeShell):
    """SFTP shell fake that never reaches the remote SFTP prompt."""

    def send_line(self, command: str) -> int:
        self.sent.append(command)
        if command.startswith("sftp "):
            self.output += f"{command}\r\n"
        else:
            self.output += f"{command}\r\n"
        return len(command) + 1


class FailingSftpShell(FakeShell):
    """SFTP shell fake that reports a failed SFTP connection."""

    def send_line(self, command: str) -> int:
        self.sent.append(command)
        if command.startswith("sftp "):
            self.output += (
                f"{command}\r\n"
                "ssh: connect to host fe80::1 port 22: Connection refused\r\n"
                "Connection closed.\r\n"
                "user@server:~$ "
            )
        else:
            self.output += f"{command}\r\n"
        return len(command) + 1


class HangingSftpSSHManager(FakeSSHManager):
    """SSH manager fake whose SFTP shell never reaches the SFTP prompt."""

    def open_shell(self) -> FakeShell:
        if self._shell_open_count == 0:
            result = self.shell
        else:
            self.sftp_shell = HangingSftpShell()
            result = self.sftp_shell
        self._shell_open_count += 1
        return result


class FailingSftpSSHManager(FakeSSHManager):
    """SSH manager fake whose SFTP shell cannot connect to the board."""

    def open_shell(self) -> FakeShell:
        if self._shell_open_count == 0:
            result = self.shell
        else:
            self.sftp_shell = FailingSftpShell()
            result = self.sftp_shell
        self._shell_open_count += 1
        return result


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
        self.assertEqual(window.terminal_widget.toPlainText(), f"{window._local_cwd}> ")
        self.assertEqual(window.ssh_password_input.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(window.board_console_tabs.count(), 2)
        self.assertEqual(window.board_console_tabs.tabText(0), "Serial Console")
        self.assertEqual(window.workspace_tabs.count(), 2)
        self.assertEqual(window.workspace_tabs.tabText(0), "Terminal")
        self.assertEqual(window.workspace_tabs.tabText(1), "SFTP")
        sftp_tab = window.workspace_tabs.widget(1)
        sftp_button_labels = {button.text() for button in sftp_tab.findChildren(QPushButton)}
        self.assertNotIn("Upload to MMU", sftp_button_labels)
        self.assertNotIn("Download to Server", sftp_button_labels)
        terminal_tab = window.workspace_tabs.widget(0)
        terminal_side_tabs = terminal_tab.findChild(QTabWidget)
        self.assertIsNotNone(terminal_side_tabs)
        assert terminal_side_tabs is not None
        self.assertEqual(terminal_side_tabs.count(), 2)
        self.assertEqual(terminal_side_tabs.tabText(0), "Commands")
        self.assertEqual(terminal_side_tabs.tabText(1), "Scenarios")
        self.assertEqual(
            terminal_side_tabs.sizePolicy().horizontalPolicy(),
            QSizePolicy.Policy.Minimum,
        )
        self.assertIsNotNone(window.command_set_list)
        self.assertEqual(window.commands_group.title(), "Commands")
        self.assertEqual(window.new_command_button.text(), "New Command")
        self.assertEqual(window.new_folder_button.text(), "New Folder")
        self.assertEqual(window.new_automation_button.text(), "New Scenario")
        self.assertEqual(window.copy_automation_button.text(), "Copy")
        self.assertFalse(window.copy_automation_button.isEnabled())
        self.assertEqual(window.run_automation_button.text(), "Run Scenario")
        self.assertEqual(window.automation_start_step_input.count(), 0)
        self.assertIsNotNone(window.automation_list)
        command_actions = window.new_folder_button.parentWidget().layout()
        self.assertIs(command_actions.itemAt(0).widget(), window.new_folder_button)
        self.assertIs(command_actions.itemAt(1).widget(), window.new_command_button)
        automation_layout = window.new_automation_button.parentWidget().layout()
        automation_actions = automation_layout.itemAt(0).layout()
        automation_run_controls = automation_layout.itemAt(1).layout()
        assert automation_actions is not None
        assert automation_run_controls is not None
        self.assertIs(automation_actions.itemAt(0).widget(), window.new_automation_button)
        self.assertIs(automation_run_controls.itemAt(0).widget(), window.automation_start_step_input)
        self.assertIs(automation_run_controls.itemAt(1).widget(), window.run_automation_button)
        self.assertIs(automation_run_controls.itemAt(2).widget(), window.stop_automation_button)
        self.assertEqual(window.board_console_tabs.tabText(1), "SSH Console")
        self.assertEqual(window.usb_port_combo.currentText(), "No USB ports detected")
        self.assertFalse(window.refresh_usb_button.isEnabled())
        self.assertFalse(window.open_minicom_button.isEnabled())
        self.assertFalse(window.close_minicom_button.isEnabled())
        self.assertEqual(window.board_password_input.echoMode(), QLineEdit.EchoMode.Normal)
        self.assertEqual(window.board_ssh_port_input.value(), 22)
        self.assertFalse(window.mmu_ssh_connect_button.isEnabled())
        self.assertFalse(window.mmu_ssh_disconnect_button.isEnabled())
        self.assertEqual(window.server_current_path_input.text(), os.path.expanduser("~"))
        self.assertTrue(window.server_current_path_input.isReadOnly())
        self.assertEqual(window.mmu_current_path_input.text(), "/tmp")
        self.assertTrue(window.mmu_current_path_input.isReadOnly())
        self.assertFalse(window.open_sftp_button.isEnabled())
        self.assertFalse(window.refresh_server_file_list_button.isEnabled())
        self.assertFalse(window.refresh_mmu_file_list_button.isEnabled())
        self.assertEqual(window.connection_status_label.text(), "SSH: disconnected")
        self.assertEqual(window.power_supply_group.title(), "Power Supply")
        self.assertEqual(window.power_supply_ip_input.placeholderText(), "Power Supply IPv4")
        self.assertIsNotNone(window.power_supply_ip_input.validator())
        valid_state = window.power_supply_ip_input.validator().validate("192.168.0.100", 13)[0]
        invalid_state = window.power_supply_ip_input.validator().validate("fe80::1", 7)[0]
        self.assertEqual(valid_state, QValidator.State.Acceptable)
        self.assertNotEqual(invalid_state, QValidator.State.Acceptable)
        self.assertEqual(window.power_supply_voltage_input.placeholderText(), "Voltage")
        self.assertIsNotNone(window.power_supply_voltage_input.validator())
        self.assertEqual(window.power_supply_current_input.placeholderText(), "Current")
        self.assertIsNotNone(window.power_supply_current_input.validator())
        self.assertEqual(window.power_set_button.text(), "Set")
        self.assertEqual(window.power_on_button.text(), "ON")
        self.assertEqual(window.power_off_button.text(), "OFF")
        self.assertEqual(window.power_status_button.text(), "Status")
        self.assertEqual(window.power_all_status_button.text(), "All Status")

    def test_power_supply_buttons_send_configured_commands(self) -> None:
        """Power supply buttons send JSON-configured commands to the SSH shell."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window._activate_shell(manager.shell)
        window.power_supply_ip_input.setText("192.168.0.50")
        window.power_supply_voltage_input.setText("12.5")
        window.power_supply_current_input.setText("1.25")

        window.power_set_button.click()
        window.power_on_button.click()
        window.power_off_button.click()
        window.power_status_button.click()
        window.power_all_status_button.click()

        self.assertEqual(
            manager.shell.sent,
            [
                "psu 192.168.0.50 set 12.5 1.25",
                "psu 192.168.0.50 on",
                "psu 192.168.0.50 off",
                "psu 192.168.0.50 status",
                "psu all-status",
            ],
        )

    def test_power_supply_button_requires_ssh_shell(self) -> None:
        """Power supply commands are sent through the connected SSH shell."""
        window = self.create_window()

        window.power_all_status_button.click()

        self.assertIn("Not connected to an SSH shell.", window.terminal_widget.toPlainText())

    def test_connection_panel_toggle_hides_all_top_groups_without_disabling_state(self) -> None:
        """The top toggle collapses all connection groups while preserving control state."""
        window = self.create_window()
        window.ssh_host_input.setText("server")
        window.connect_button.setEnabled(False)
        window.refresh_usb_button.setEnabled(True)

        self.assertTrue(window.connection_panel_toggle_button.isChecked())
        self.assertEqual(window.connection_panel_toggle_button.text(), "Hide connection info")
        self.assertFalse(window.connection_panel_content.isHidden())
        self.assertFalse(window.ssh_group.isCheckable())
        self.assertFalse(window.power_supply_group.isCheckable())
        self.assertFalse(window.mmu_group.isCheckable())

        self.assertEqual(window.ssh_group.title(), "SSH Server")
        self.assertEqual(window.power_supply_group.title(), "Power Supply")
        self.assertEqual(window.mmu_group.title(), "Client")

        window.connection_panel_toggle_button.setChecked(False)

        self.assertTrue(window.connection_panel_content.isHidden())
        self.assertEqual(window.connection_panel_toggle_button.text(), "Show connection info")
        self.assertEqual(window.ssh_host_input.text(), "server")
        self.assertFalse(window.connect_button.isEnabled())
        self.assertTrue(window.refresh_usb_button.isEnabled())

        window.connection_panel_toggle_button.setChecked(True)

        self.assertFalse(window.connection_panel_content.isHidden())
        self.assertEqual(window.connection_panel_toggle_button.text(), "Hide connection info")
        self.assertEqual(window.ssh_host_input.text(), "server")
        self.assertFalse(window.connect_button.isEnabled())
        self.assertTrue(window.refresh_usb_button.isEnabled())

    def test_connection_panel_uses_white_background(self) -> None:
        """Connection controls should not inherit the platform grey scroll-area background."""
        window = self.create_window()

        self.assertIn("background-color: white", window.connection_panel.styleSheet())
        self.assertIn(
            "background-color: white", window.connection_panel_scroll_area.styleSheet()
        )

    def test_response_panel_can_be_hidden_and_shown(self) -> None:
        """The response pane folds away without resizing the main workspace."""
        window = self.create_window()
        window.show()
        self.app.processEvents()
        window.response_panel_content.setPlainText("response output")

        self.assertEqual(window.response_panel.parent(), window.main_response_splitter)
        self.assertEqual(
            window.response_panel_toggle_button.parent(), window.connection_panel_toggle_button.parent()
        )
        self.assertTrue(window.response_panel_toggle_button.isChecked())
        self.assertEqual(window.response_panel_toggle_button.text(), "Hide")
        self.assertFalse(window.response_panel_content.isHidden())
        main_width = window.main_content.width()
        window_width = window.width()

        window.response_panel_toggle_button.setChecked(False)
        self.app.processEvents()

        self.assertTrue(window.response_panel.isHidden())
        self.assertEqual(window.response_panel_toggle_button.text(), "Show")
        self.assertEqual(window.response_panel_content.toPlainText(), "response output")
        self.assertEqual(window.main_content.width(), main_width)
        self.assertLess(window.width(), window_width)

        window.response_panel_toggle_button.setChecked(True)
        self.app.processEvents()

        self.assertFalse(window.response_panel.isHidden())
        self.assertEqual(window.response_panel_toggle_button.text(), "Hide")

    def test_initial_shell_echo_newline_is_not_rendered_as_a_blank_command(self) -> None:
        """A leading PTY line advance before the first echo is filtered out."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window._activate_shell(manager.shell)
        manager.shell.output = "\r\npwd\r\n/home/user\r\nuser@server:~$ "

        window.terminal_widget.commandSubmitted.emit("pwd")
        window._poll_shell()

        self.assertEqual(manager.shell.sent, ["pwd"])
        self.assertNotIn("\n\npwd", window.terminal_widget.toPlainText())
        self.assertIn("/home/user", window.terminal_widget.toPlainText())

    def test_pending_echo_survives_initial_prompt_in_a_separate_chunk(self) -> None:
        """A startup prompt must not discard the command echo awaited next."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window._activate_shell(manager.shell)
        window.terminal_widget.commandSubmitted.emit("pwd")

        manager.shell.output = "user@server:~$ "
        window._poll_shell()

        self.assertEqual(window._pending_echo, "pwd")
        manager.shell.output = "pwd\r\n/home/user\r\nuser@server:~$ "
        window._poll_shell()

        self.assertIsNone(window._pending_echo)
        self.assertIn("/home/user", window.terminal_widget.toPlainText())
        self.assertNotIn("\n\n", window.terminal_widget.toPlainText())

    def test_pending_echo_survives_a_split_command_echo(self) -> None:
        """A command echo split between reads is removed only once complete."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window._activate_shell(manager.shell)
        window.terminal_widget.commandSubmitted.emit("pwd")

        manager.shell.output = "pw"
        window._poll_shell()

        self.assertEqual(window._pending_echo, "pwd")
        manager.shell.output = "d\r\n/home/user\r\nuser@server:~$ "
        window._poll_shell()

        self.assertIsNone(window._pending_echo)
        self.assertIn("/home/user", window.terminal_widget.toPlainText())
        self.assertNotIn("\n\n", window.terminal_widget.toPlainText())

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

    def test_clear_command_clears_connected_ssh_terminal(self) -> None:
        """Clear removes prior terminal content while SSH is connected."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()
        window.terminal_widget.write_output("old command output")

        window.terminal_widget.commandSubmitted.emit("clear")

        self.assertEqual(window.terminal_widget.toPlainText(), "")
        self.assertEqual(manager.shell.sent, [])

    def test_empty_ssh_enter_filters_remote_echo_newline(self) -> None:
        """Blank Enter on SSH should leave a single prompt line, not a double newline."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()

        window.terminal_widget.commandSubmitted.emit("")
        # Some PTYs emit two line endings for an empty command: the command
        # echo and the remote prompt's line advance.
        manager.shell.output = "\r\n\r\nuser@server:~$ "
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

    def test_command_groups_run_all_commands_in_order(self) -> None:
        """A command group runs each of its commands in order."""
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
            self.assertIn("pwd\nuname -a", window.command_set_output.toPlainText())

            window.ssh_host_input.setText("server")
            window.ssh_username_input.setText("user")
            window._connect_ssh()
            self.assertTrue(window.run_command_set_button.isEnabled())
            window._run_command_set()

            self.assertEqual(manager.shell.sent, ["pwd", "uname -a"])

    def test_new_automation_button_opens_editor_and_saves_scenario(self) -> None:
        """The New Scenario action creates an editor with the main window as parent."""
        store = AutomationStore(Path(self.temp_dir.name) / "automation.json")
        window = self.create_window(automation_store=store)
        scenario = AutomationScenario(
            name="boot",
            steps=[AutomationStep("wait", "start", CompletionType.DELAY, timeout_seconds=1)],
        )
        created_parents: list[MainWindow] = []

        class AcceptedAutomationDialog:
            def __init__(self, parent: MainWindow) -> None:
                self.parent = parent
                created_parents.append(parent)

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def scenario(self) -> AutomationScenario:
                return scenario

        with patch("mmu_control.ui.main_window.AutomationEditorDialog", AcceptedAutomationDialog):
            window.new_automation_button.click()

        self.assertEqual(created_parents, [window])
        self.assertEqual(store.load().scenarios, {"boot": scenario})
        self.assertEqual(window.automation_list.count(), 1)
        self.assertEqual(window.automation_list.currentItem().text(), "boot")

    def test_copy_automation_scenario_opens_a_separate_named_copy(self) -> None:
        """Copy preserves the selected scenario data while saving a distinct scenario."""
        store = AutomationStore(Path(self.temp_dir.name) / "automation.json")
        original = AutomationScenario(
            name="boot",
            description="Boot the board",
            transport="minicom",
            steps=[AutomationStep("wait", "start", CompletionType.DELAY, timeout_seconds=1)],
        )
        store.upsert(original)
        window = self.create_window(automation_store=store)
        dialog_scenarios: list[AutomationScenario] = []

        class AcceptedAutomationDialog:
            def __init__(self, scenario: AutomationScenario, parent: MainWindow) -> None:
                self.parent = parent
                dialog_scenarios.append(scenario)

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def scenario(self) -> AutomationScenario:
                return dialog_scenarios[-1]

        with patch("mmu_control.ui.main_window.AutomationEditorDialog", AcceptedAutomationDialog):
            window.copy_automation_button.click()

        copied = AutomationScenario(
            name="boot (Copy)",
            description=original.description,
            transport=original.transport,
            steps=[AutomationStep.from_dict(step.to_dict()) for step in original.steps],
        )
        self.assertEqual(dialog_scenarios, [copied])
        self.assertIsNot(dialog_scenarios[0].steps[0], original.steps[0])
        self.assertEqual(store.load().scenarios, {"boot": original, "boot (Copy)": copied})
        self.assertEqual(window.automation_list.currentItem().text(), "boot (Copy)")

    def test_run_automation_uses_filtered_current_console_snapshot_for_start_condition(self) -> None:
        """Run Scenario evaluates its first start condition against visible remote output."""
        manager = FakeSSHManager()
        store = AutomationStore(Path(self.temp_dir.name) / "automation.json")
        start_marker = "service-ready"
        scenario = AutomationScenario(
            name="current-output",
            steps=[
                AutomationStep(
                    "start",
                    "command",
                    start_type=CompletionType.OUTPUT_CONTAINS,
                    start_value=start_marker,
                )
            ],
        )
        store.upsert(scenario)
        window = self.create_window(ssh_manager=manager, automation_store=store)
        window._activate_shell(manager.shell)
        manager.shell.output = f"\x1b[32mdevice state: {start_marker}\x1b[0m "
        window._poll_shell()

        window._run_automation_scenario()

        self.assertEqual(manager.shell.sent, ["command"])

    def test_scenario_selection_keeps_the_last_execution_progress(self) -> None:
        """Returning to a running scenario retains its displayed progress."""
        manager = FakeSSHManager()
        store = AutomationStore(Path(self.temp_dir.name) / "automation.json")
        first = AutomationScenario(
            name="first",
            steps=[AutomationStep("run first", "first-command", CompletionType.OUTPUT_CONTAINS, "done")],
        )
        second = AutomationScenario(name="second", steps=[AutomationStep("run second", "second-command")])
        store.upsert(first)
        store.upsert(second)
        window = self.create_window(ssh_manager=manager, automation_store=store)
        window._activate_shell(manager.shell)

        window._run_automation_scenario()
        window.automation_list.setCurrentRow(1)
        window.automation_list.setCurrentRow(0)

        self.assertIn("Execution progress: Running step 1: run first", window.automation_output.toPlainText())
        self.assertIn("[▶ running] run first", window.automation_output.toPlainText())

    def test_run_automation_can_start_at_the_selected_step(self) -> None:
        manager = FakeSSHManager()
        store = AutomationStore(Path(self.temp_dir.name) / "automation.json")
        scenario = AutomationScenario(
            name="resume",
            steps=[
                AutomationStep("first", "first-command"),
                AutomationStep("middle", "middle-command", CompletionType.OUTPUT_CONTAINS, "done"),
            ],
        )
        store.upsert(scenario)
        window = self.create_window(ssh_manager=manager, automation_store=store)
        window._activate_shell(manager.shell)

        self.assertEqual(window.automation_start_step_input.count(), 2)
        window.automation_start_step_input.setCurrentIndex(1)
        window._run_automation_scenario()

        self.assertEqual(manager.shell.sent, ["middle-command"])
        self.assertIn("[↷ not run] first", window.automation_output.toPlainText())

    def test_create_automation_scenario_keeps_list_when_store_save_fails(self) -> None:
        """A failed new scenario save reports its path without changing the selected scenario."""
        path = Path(self.temp_dir.name) / "automation.json"
        store = AutomationStore(path)
        existing = AutomationScenario(name="existing")
        store.upsert(existing)
        window = self.create_window(automation_store=store)
        created = AutomationScenario(name="new")

        class AcceptedAutomationDialog:
            def __init__(self, parent: MainWindow) -> None:
                self.parent = parent

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def scenario(self) -> AutomationScenario:
                return created

        with (
            patch("mmu_control.ui.main_window.AutomationEditorDialog", AcceptedAutomationDialog),
            patch.object(store, "upsert", side_effect=OSError("disk is full")),
        ):
            window._create_automation_scenario()

        self.assertEqual(window.automation_list.count(), 1)
        self.assertEqual(window.automation_list.currentItem().text(), "existing")
        self.assertIn("disk is full", window.automation_status_label.text())
        self.assertIn(str(path), window.automation_status_label.text())
        self.assertEqual(window.statusBar().currentMessage(), window.automation_status_label.text())

    def test_rename_automation_scenario_keeps_list_when_store_delete_fails(self) -> None:
        """A failed rename deletion preserves the existing scenario and its selection."""
        path = Path(self.temp_dir.name) / "automation.json"
        store = AutomationStore(path)
        existing = AutomationScenario(name="existing")
        store.upsert(existing)
        window = self.create_window(automation_store=store)
        renamed = AutomationScenario(name="renamed")

        class AcceptedAutomationDialog:
            def __init__(self, scenario: AutomationScenario, parent: MainWindow) -> None:
                self.scenario_arg = scenario
                self.parent = parent

            def exec(self) -> QDialog.DialogCode:
                return QDialog.DialogCode.Accepted

            def scenario(self) -> AutomationScenario:
                return renamed

        with (
            patch("mmu_control.ui.main_window.AutomationEditorDialog", AcceptedAutomationDialog),
            patch.object(store, "delete", side_effect=OSError("permission denied")) as delete,
        ):
            window._edit_automation_scenario()

        delete.assert_called_once_with("existing")
        self.assertEqual(window.automation_list.count(), 1)
        self.assertEqual(window.automation_list.currentItem().text(), "existing")
        self.assertIn("permission denied", window.automation_status_label.text())
        self.assertIn(str(path), window.automation_status_label.text())
        self.assertEqual(window.statusBar().currentMessage(), window.automation_status_label.text())

    def test_new_scenario_dialog_accepts_a_named_scenario_without_steps(self) -> None:
        """A scenario can be created before the user configures its first step."""
        dialog = AutomationEditorDialog(parent=self.create_window())
        dialog.name_input.setText("new scenario")

        dialog.accept()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.scenario(), AutomationScenario(name="new scenario"))

    def test_automation_editor_saves_none_condition_without_value_or_file_path(self) -> None:
        """No-condition steps discard irrelevant completion values and paths."""
        dialog = self._automation_editor_dialog(CompletionType.NONE)
        dialog.condition_value_input.setText("stale value")
        dialog.file_path_input.setText("/tmp/stale")

        dialog.accept()

        step = dialog.scenario().steps[0]
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(step.completion_value, "")
        self.assertEqual(step.file_path, "")

    def test_automation_editor_saves_delay_condition_without_value_or_file_path(self) -> None:
        """Delay steps discard irrelevant completion values and paths."""
        dialog = self._automation_editor_dialog(CompletionType.DELAY)
        dialog.condition_value_input.setText("stale value")
        dialog.file_path_input.setText("/tmp/stale")

        dialog.accept()

        step = dialog.scenario().steps[0]
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(step.completion_value, "")
        self.assertEqual(step.file_path, "")

    def test_automation_editor_saves_output_contains_text_without_file_path(self) -> None:
        """Console text conditions retain text while discarding a device path."""
        dialog = self._automation_editor_dialog(CompletionType.OUTPUT_CONTAINS)
        dialog.condition_value_input.setText("ready")
        dialog.file_path_input.setText("/tmp/stale")

        dialog.accept()

        step = dialog.scenario().steps[0]
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(step.completion_value, "ready")
        self.assertEqual(step.file_path, "")

    def test_automation_editor_rejects_remote_file_contains_without_text_or_path(self) -> None:
        """Remote-file text conditions require both a value and a device path."""
        for value, file_path, error in (
            ("", "/tmp/state", "completion value is required"),
            ("ready", "", "device file path is required"),
        ):
            with self.subTest(value=value, file_path=file_path):
                dialog = self._automation_editor_dialog(CompletionType.REMOTE_FILE_CONTAINS)
                dialog.condition_value_input.setText(value)
                dialog.file_path_input.setText(file_path)

                dialog.accept()

                self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
                self.assertIn(error, dialog.error_label.text())

    def _automation_editor_dialog(self, completion_type: CompletionType) -> AutomationEditorDialog:
        """Create an editor with one valid command step of ``completion_type``."""
        dialog = AutomationEditorDialog(
            AutomationScenario(
                name="test scenario",
                steps=[AutomationStep("test step", "echo ready", completion_type)],
            ),
            self.create_window(),
        )
        dialog.condition_type_input.setCurrentIndex(dialog.condition_type_input.findData(completion_type))
        return dialog

    def test_server_path_input_accepts_dropped_local_file(self) -> None:
        """Dropping a local file path fills the Linux server path input."""
        window = self.create_window()
        local_file = Path(self.temp_dir.name) / "update file.bin"
        local_file.write_text("firmware", encoding="utf-8")
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(local_file))])
        drop_event = QDropEvent(
            QPointF(1, 1),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        window.server_path_input.dropEvent(drop_event)

        self.assertEqual(window.server_path_input.text(), str(local_file))
        self.assertTrue(drop_event.isAccepted())

    def test_dropped_file_uploads_through_server_and_sftp_session(self) -> None:
        """Dropping a file during SFTP uploads it to the server, then to the MMU."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")
        local_file = Path(self.temp_dir.name) / "update file.bin"
        local_file.write_text("firmware", encoding="utf-8")
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(str(local_file))])
        drop_event = QDropEvent(
            QPointF(1, 1),
            Qt.DropAction.CopyAction,
            mime_data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )

        window._connect_ssh()
        window.open_sftp_button.click()
        window.server_path_input.dropEvent(drop_event)

        local_path = str(local_file)
        server_path = "/tmp/mmu_control_uploads/update file.bin"
        self.assertEqual(manager.executed_commands, ["mkdir -p /tmp/mmu_control_uploads"])
        self.assertEqual(manager.uploaded_files, [(local_path, server_path)])
        self.assertEqual(window.server_path_input.text(), server_path)
        self.assertEqual(window.board_path_input.text(), "/tmp/update file.bin")
        self.assertIn(f"put '{server_path}' '/tmp/update file.bin'", manager.sftp_shell.sent)
        self.assertTrue(drop_event.isAccepted())


    def test_sftp_file_lists_allow_multiple_selection(self) -> None:
        """SFTP file lists support multi-select file operations."""
        window = self.create_window()

        self.assertEqual(
            window.server_file_list.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )
        self.assertEqual(
            window.mmu_file_list.selectionMode(),
            QAbstractItemView.SelectionMode.ExtendedSelection,
        )

    def test_drag_and_drop_uploads_multiple_server_files(self) -> None:
        """The drag-and-drop upload action handles every selected server file."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()
        window._populate_file_list(
            window.server_file_list,
            [
                (False, "one.bin", "/home/user/one.bin"),
                (False, "two.bin", "/home/user/two.bin"),
            ],
        )
        window._handle_sftp_list_drop(
            "server", ["/home/user/one.bin", "/home/user/two.bin"], "/tmp"
        )

        self.assertIn("put /home/user/one.bin /tmp/one.bin", manager.sftp_shell.sent)
        self.assertIn("put /home/user/two.bin /tmp/two.bin", manager.sftp_shell.sent)

    def test_delete_key_requests_confirmed_mmu_file_delete(self) -> None:
        """Delete key confirms, removes all selected MMU files, and refreshes the list."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()
        window._populate_file_list(
            window.mmu_file_list,
            [
                (False, "one.bin", "/tmp/one.bin"),
                (False, "two file.bin", "/tmp/two file.bin"),
            ],
        )
        window.mmu_file_list.item(1).setSelected(True)
        window.mmu_file_list.item(2).setSelected(True)

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ) as question:
            QTest.keyClick(window.mmu_file_list, Qt.Key.Key_Delete)

        question.assert_called_once()
        self.assertIn("rm /tmp/one.bin", manager.sftp_shell.sent)
        self.assertIn("rm '/tmp/two file.bin'", manager.sftp_shell.sent)
        self.assertEqual(manager.sftp_shell.sent[-1], "ls -la /tmp")

    def test_delete_key_can_delete_multiple_server_files(self) -> None:
        """Delete key also removes selected Linux server files after confirmation."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window._server_sftp_directory = "/home/user"
        window._populate_file_list(
            window.server_file_list,
            [
                (False, "one.bin", "/home/user/one.bin"),
                (False, "two file.bin", "/home/user/two file.bin"),
            ],
        )
        window.server_file_list.item(1).setSelected(True)
        window.server_file_list.item(2).setSelected(True)

        with patch.object(
            QMessageBox,
            "question",
            return_value=QMessageBox.StandardButton.Yes,
        ):
            QTest.keyClick(window.server_file_list, Qt.Key.Key_Delete)

        self.assertIn(
            "rm -f -- /home/user/one.bin '/home/user/two file.bin'",
            manager.executed_commands,
        )

    def test_drag_drop_sftp_transfer_shows_progress_and_refreshes_target(self) -> None:
        """SFTP list drag-and-drop shows percentage progress and refreshes the destination."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()
        window._handle_sftp_list_drop("server", "/home/user/update.bin", "/tmp")

        self.assertIsNotNone(window._sftp_transfer_progress_dialog)
        self.assertIn("put /home/user/update.bin /tmp/update.bin", manager.sftp_shell.sent)
        manager.sftp_shell.output += (
            "update.bin 45% 45KB 1.0MB/s 00:01 ETA\r"
            "update.bin 100% 100KB 1.0MB/s 00:00\r\nsftp> "
        )
        window._poll_sftp_shell()

        self.assertIsNone(window._sftp_transfer_progress_dialog)
        self.assertEqual(manager.sftp_shell.sent[-1], "ls -la /tmp")

    def test_drag_drop_sftp_transfer_handles_multiple_files(self) -> None:
        """SFTP list drag-and-drop sends transfer commands for all dropped files."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()
        window._handle_sftp_list_drop(
            "server",
            ["/home/user/one.bin", "/home/user/two.bin"],
            "/tmp",
        )

        self.assertIn("put /home/user/one.bin /tmp/one.bin", manager.sftp_shell.sent)
        self.assertIn("put /home/user/two.bin /tmp/two.bin", manager.sftp_shell.sent)

    def test_mmu_sftp_listing_keeps_parent_directory_entry(self) -> None:
        """MMU listings keep the remote ../ row available for parent navigation."""
        window = self.create_window()
        window._mmu_sftp_directory = "/tmp"
        window.mmu_file_list.current_directory = "/tmp"

        entries = window._parse_sftp_listing(
            "drwxrwxrwt    8 root     root          280 Jan  1 00:00 .\r\n"
            "drwxr-xr-x   20 root     root         4096 Jan  1 00:00 ..\r\n"
            "-rw-r--r--    1 root     root           42 Jan  1 00:00 mmu-file.txt\r\n"
        )
        window._populate_file_list(window.mmu_file_list, entries)

        parent_item = window.mmu_file_list.item(0)
        self.assertEqual(parent_item.text(), "../")
        self.assertEqual(parent_item.data(Qt.ItemDataRole.UserRole), "/")
        self.assertEqual(window.mmu_file_list.item(1).text(), "mmu-file.txt")

    def test_mmu_sftp_symlink_directory_opens_target(self) -> None:
        """MMU listings parse symlink names and allow directory symlinks to open."""
        window = self.create_window()
        shell = FakeShell()
        window._sftp_shell = shell
        window._sftp_session_active = True
        window._mmu_sftp_directory = "/tmp"
        window.mmu_file_list.current_directory = "/tmp"

        entries = window._parse_sftp_listing(
            "lrwxrwxrwx    1 root     root           12 Jan  1 00:00 link -> /target\r\n"
        )
        window._populate_file_list(window.mmu_file_list, entries)

        link_item = window.mmu_file_list.item(1)
        self.assertEqual(link_item.text(), "link/")

        window._open_mmu_list_item(link_item)

        self.assertEqual(window._mmu_sftp_directory, "/target")
        self.assertIn("ls -ldL /tmp/link", shell.sent)
        self.assertIn("ls -la /target", shell.sent)

    def test_mmu_sftp_relative_symlink_directory_opens_resolved_target(self) -> None:
        """Relative MMU symlinks resolve from the link parent before opening."""
        window = self.create_window()
        shell = FakeShell()
        window._sftp_shell = shell
        window._sftp_session_active = True
        window._mmu_sftp_directory = "/tmp"
        window.mmu_file_list.current_directory = "/tmp"

        entries = window._parse_sftp_listing(
            "lrwxrwxrwx    1 root     root           12 Jan  1 00:00 link -> ../target\r\n"
        )
        window._populate_file_list(window.mmu_file_list, entries)

        link_item = window.mmu_file_list.item(1)
        self.assertEqual(link_item.text(), "link/")

        window._open_mmu_list_item(link_item)

        self.assertEqual(window._mmu_sftp_directory, "/target")
        self.assertIn("ls -ldL /tmp/link", shell.sent)
        self.assertIn("ls -la /target", shell.sent)

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
            [
                "rm -f ~/.ssh/known_hosts",
                "sftp root@[fe80::1%eth0]",
                "cd /tmp",
                "ls -la /tmp",
            ],
        )
        self.assertIn(
            "Opening SFTP session: sftp root@[fe80::1%eth0]",
            window.terminal_widget.toPlainText(),
        )
        self.assertIn(
            "SFTP session opened.",
            window.terminal_widget.toPlainText(),
        )
        self.assertEqual(window.board_status_label.text(), "MMU: SFTP connected")
        self.assertEqual(
            manager.executed_commands,
            [
                "find /home/user -maxdepth 1 -mindepth 1 "
                "-printf '%y\\t%p\\n' 2>/dev/null"
            ],
        )
        self.assertEqual(window.server_file_list.item(1).text(), "server-dir/")
        self.assertEqual(window.server_file_list.item(2).text(), "server-file.txt")
        self.assertEqual(window.mmu_file_list.item(0).text(), "../")
        self.assertEqual(window.mmu_file_list.item(0).data(Qt.ItemDataRole.UserRole), "/")
        self.assertEqual(window.mmu_file_list.item(1).text(), "mmu-dir/")
        self.assertEqual(window.mmu_file_list.item(2).text(), "mmu-file.txt")
        self.assertEqual(window.server_current_path_input.text(), "/home/user")
        self.assertEqual(window.mmu_current_path_input.text(), "/tmp")
        self.assertTrue(window.refresh_server_file_list_button.isEnabled())
        self.assertTrue(window.refresh_mmu_file_list_button.isEnabled())

        command_count = len(manager.executed_commands)
        window.refresh_server_file_list_button.click()
        self.assertEqual(len(manager.executed_commands), command_count + 1)
        sftp_command_count = len(manager.sftp_shell.sent)
        window.refresh_mmu_file_list_button.click()
        self.assertEqual(manager.sftp_shell.sent[sftp_command_count], "ls -la /tmp")

        window._open_server_list_item(window.server_file_list.item(1))
        self.assertEqual(window.server_current_path_input.text(), "/home/user/server-dir")
        window._open_mmu_list_item(window.mmu_file_list.item(1))
        self.assertEqual(window.mmu_current_path_input.text(), "/tmp/mmu-dir")

        window.server_path_input.setText("/tmp/update file.bin")
        window.board_path_input.setText("/opt/update.bin")
        window._refresh_mmu_file_list()
        window._handle_sftp_list_drop("server", "/tmp/update file.bin", "/opt")
        window._handle_sftp_list_drop("mmu", "/opt/update.bin", "/tmp")

        self.assertEqual(
            manager.sftp_shell.sent,
            [
                "rm -f ~/.ssh/known_hosts",
                "sftp root@[fe80::1%eth0]",
                "cd /tmp",
                "ls -la /tmp",
                "ls -la /tmp",
                "put '/tmp/update file.bin' '/opt/update file.bin'",
                "get /opt/update.bin '/tmp/update file.bin'",
            ],
        )

        window.close_sftp_button.click()
        window.terminal_widget.commandSubmitted.emit("pwd")

        self.assertEqual(manager.shell.sent, ["pwd"])
        self.assertTrue(manager.shell.is_open)
        self.assertFalse(manager.sftp_shell.is_open)


    def test_sftp_progress_carriage_return_is_not_hidden_by_echo_filter(self) -> None:
        """SFTP progress updates that use carriage returns are shown in the terminal."""
        window = self.create_window()
        window._sftp_pending_echo = "put /tmp/file.bin /tmp/file.bin"
        output = window._filter_sftp_echo(
            "put /tmp/file.bin /tmp/file.bin\rUploading /tmp/file.bin to /tmp/file.bin\r"
            "file.bin 50% 512KB 1.0MB/s 00:01 ETA\r"
        )

        self.assertIn("Uploading /tmp/file.bin", output)
        self.assertIn("50%", output)
        self.assertIsNone(window._sftp_pending_echo)

    def test_sftp_pwd_parser_accepts_common_remote_path_formats(self) -> None:
        """SFTP pwd parsing handles OpenSSH quotes and bare remote paths."""
        window = self.create_window()

        self.assertEqual(
            window._extract_sftp_pwd_path('Remote working directory: "/opt/mmu"\r\nsftp> '),
            "/opt/mmu",
        )
        self.assertEqual(window._extract_sftp_pwd_path("/var/log\nsftp> "), "/var/log")
        self.assertIsNone(window._extract_sftp_pwd_path("Local working directory: /home/user"))

    def test_sftp_pwd_pending_survives_echo_only_chunk(self) -> None:
        """A chunk split between pwd echo and path still updates the MMU path."""
        window = self.create_window()
        window._sftp_pending_pwd = "pwd"
        window._sftp_pending_echo = "pwd"

        echo_output = window._filter_sftp_echo("pwd\r\n")
        if echo_output.strip():
            handled_pwd = window._handle_sftp_pwd_output(echo_output)
            if handled_pwd or "sftp>" in echo_output:
                window._sftp_pending_pwd = None

        self.assertEqual(window._sftp_pending_pwd, "pwd")
        self.assertTrue(window._handle_sftp_pwd_output('Remote working directory: "/opt/mmu"\r\nsftp> '))
        self.assertEqual(window.mmu_current_path_input.text(), "/opt/mmu")

    def test_open_sftp_times_out_when_prompt_never_arrives(self) -> None:
        """SFTP startup fails when the remote prompt does not appear within the timeout."""
        manager = HangingSftpSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()
        window._handle_sftp_startup_timeout()

        self.assertIn("SFTP connection failed", window.terminal_widget.toPlainText())
        self.assertIn("3 seconds", window.terminal_widget.toPlainText())
        self.assertEqual(window.board_status_label.text(), "MMU: SFTP failed")
        self.assertFalse(window.close_sftp_button.isEnabled())

    def test_open_sftp_reports_connection_failure_in_terminal(self) -> None:
        """Failed SFTP startup reports failure instead of leaving a misleading prompt."""
        manager = FailingSftpSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")

        window._connect_ssh()
        window.open_sftp_button.click()

        self.assertIn("SFTP connection failed.", window.terminal_widget.toPlainText())
        self.assertIn("Connection refused", window.terminal_widget.toPlainText())
        self.assertEqual(window.board_status_label.text(), "MMU: SFTP failed")
        self.assertFalse(window.close_sftp_button.isEnabled())

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
            "SFTP error: MMU IP address is required.",
            window.terminal_widget.toPlainText(),
        )
        self.assertEqual(window.board_status_label.text(), "MMU: SFTP failed")

    def test_settings_are_loaded_and_saved_on_close(self) -> None:
        """Connection, board, USB, and window settings survive a restart."""
        config = ConfigManager(Path(self.temp_dir.name) / "settings.json")
        config.save(
            AppSettings(
                ssh=SSHSettings(host="server", port=2200, username="user", password="pw"),
                board=BoardSettings(
                    ip_address="fe80::1",
                    ip_version="IPv6",
                    username="root",
                    usb_port="/dev/ttyUSB0",
                ),
                power_supply=PowerSupplySettings(
                    ip_address="192.168.0.100", voltage="12.5", current="1.25"
                ),
                window=WindowSettings(ssh_group_expanded=False, mmu_group_expanded=True),
            )
        )
        window = self.create_window(config_manager=config)

        self.assertEqual(window.ssh_host_input.text(), "server")
        self.assertEqual(window.ssh_port_input.value(), 2200)
        self.assertEqual(window.board_ip_version_combo.currentText(), "IPv6")
        self.assertEqual(window.board_ip_input.placeholderText(), "fe80::1")
        self.assertEqual(window.usb_port_combo.currentText(), "/dev/ttyUSB0")
        self.assertEqual(window.power_supply_ip_input.text(), "192.168.0.100")
        self.assertEqual(window.power_supply_voltage_input.text(), "12.5")
        self.assertEqual(window.power_supply_current_input.text(), "1.25")
        self.assertFalse(window.ssh_group.isChecked())
        self.assertTrue(window.ssh_group_content.isHidden())
        self.assertTrue(window.mmu_group.isChecked())

        window.ssh_group.setChecked(True)
        window.mmu_group.setChecked(False)
        window.board_ip_version_combo.setCurrentText("IPv4")
        window.board_ip_input.setText("192.168.0.10")
        window.board_interface_input.setText("eth0")
        window.power_supply_ip_input.setText("192.168.0.101")
        window.power_supply_voltage_input.setText("24")
        window.power_supply_current_input.setText("2")
        window.close()

        saved_settings = config.load()
        saved_board = saved_settings.board
        self.assertEqual(saved_board.interface, "eth0")
        self.assertEqual(saved_board.ip_version, "IPv4")
        self.assertEqual(saved_board.ip_address, "192.168.0.10")
        self.assertEqual(saved_settings.power_supply.ip_address, "192.168.0.101")
        self.assertEqual(saved_settings.power_supply.voltage, "24")
        self.assertEqual(saved_settings.power_supply.current, "2")
        self.assertTrue(saved_settings.window.ssh_group_expanded)
        self.assertFalse(saved_settings.window.mmu_group_expanded)

    def test_board_ip_version_combo_updates_placeholder_and_settings(self) -> None:
        """IP version choice updates placeholders and is included in board settings."""
        window = self.create_window()

        self.assertEqual(window.board_ip_version_combo.currentText(), "IPv4")
        self.assertEqual(window.board_ip_input.placeholderText(), "192.168.0.10")

        window.board_ip_version_combo.setCurrentText("IPv6")

        self.assertEqual(window.board_ip_input.placeholderText(), "fe80::1")
        self.assertEqual(window._board_settings().ip_version, "IPv6")

    def test_board_ip_version_does_not_change_ipv6_interface_commands(self) -> None:
        """The saved IP version does not interfere with IPv6 link-local command suffixes."""
        window = self.create_window()
        settings = BoardSettings(
            ip_address="fe80::1",
            ip_version="IPv6",
            username="root",
            interface="eth0",
            ssh_port=2222,
        )

        self.assertEqual(
            window._build_mmu_ssh_command(settings),
            "ssh root@fe80::1%eth0 -p 2222",
        )
        self.assertEqual(
            window._sftp_manager.build_command(settings),
            "sftp root@[fe80::1%eth0]",
        )

    def test_mmu_ssh_command_uses_board_inputs(self) -> None:
        """MMU SSH uses the board fields and toggles disconnect through the server shell."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_password_input.setText("secret")
        window.board_interface_input.setText("eth0")
        window.board_ssh_port_input.setValue(2222)
        window._connect_ssh()
        window.mmu_ssh_connect_button.click()

        self.assertEqual(
            manager.shell.sent,
            ["rm -f ~/.ssh/known_hosts", "ssh root@fe80::1%eth0 -p 2222"],
        )
        self.assertFalse(window.mmu_ssh_connect_button.isEnabled())
        self.assertTrue(window.mmu_ssh_disconnect_button.isEnabled())
        self.assertEqual(window.board_status_label.text(), "MMU: SSH connecting")

        window.mmu_ssh_disconnect_button.click()

        self.assertEqual(manager.shell.sent[-1], "exit")
        self.assertTrue(window.mmu_ssh_connect_button.isEnabled())
        self.assertFalse(window.mmu_ssh_disconnect_button.isEnabled())
        self.assertEqual(window.board_status_label.text(), "MMU: SSH disconnected")

    def test_mmu_ssh_failure_restores_server_shell_controls(self) -> None:
        """Failed MMU SSH startup re-enables connect without sending exit to the server shell."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_interface_input.setText("eth0")
        window._connect_ssh()
        window.mmu_ssh_connect_button.click()

        window._handle_mmu_ssh_auth("ssh: connect to host fe80::1 port 22: Connection refused")
        sent_after_failure = list(manager.shell.sent)
        window.mmu_ssh_disconnect_button.click()

        self.assertEqual(manager.shell.sent, sent_after_failure)
        self.assertTrue(window.mmu_ssh_connect_button.isEnabled())
        self.assertFalse(window.mmu_ssh_disconnect_button.isEnabled())
        self.assertEqual(window.board_status_label.text(), "MMU: SSH failed")

    def test_mmu_ssh_password_is_sent_only_for_initial_auth_prompt(self) -> None:
        """MMU SSH password automation does not answer later shell password prompts."""
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager)
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window.board_ip_input.setText("fe80::1")
        window.board_username_input.setText("root")
        window.board_password_input.setText("secret")
        window.board_interface_input.setText("eth0")
        window._connect_ssh()
        window.mmu_ssh_connect_button.click()

        window._handle_mmu_ssh_auth("root@fe80::1's password:")
        self.assertEqual(manager.shell.sent[-1], "secret")
        sent_after_initial_auth = list(manager.shell.sent)

        window._handle_mmu_ssh_auth("Password:")

        self.assertEqual(manager.shell.sent, sent_after_initial_auth)
        window.close()

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

        window.terminal_widget.show()
        window.terminal_widget.setFocus()
        QTest.keyClick(window.terminal_widget, Qt.Key.Key_Backspace)

        self.assertEqual(manager.shell.sent[-1], "\x7f")

        window.close_minicom_button.click()

        self.assertEqual(manager.shell.sent[-1], "\x01x\n")


    def test_command_group_tree_and_folder_selection(self) -> None:
        """Folders render groups as children and cannot execute commands themselves."""
        store = CommandSetStore(Path(self.temp_dir.name) / "command_sets.json")
        store.create_folder("A")
        for name, command in (("B", "echo b"), ("C", "echo c"), ("D", "echo d")):
            store.upsert(CommandSet(name=name, commands=command, parent_path="A"))
        manager = FakeSSHManager()
        window = self.create_window(ssh_manager=manager, command_set_store=store)

        self.assertEqual(window.run_command_set_button.text(), "Run")

        self.assertEqual(window.command_set_list.topLevelItemCount(), 1)
        folder = window.command_set_list.topLevelItem(0)
        self.assertEqual(folder.text(0), "A")
        self.assertEqual(folder.childCount(), 3)
        window.command_set_list.setCurrentItem(folder)
        self.assertFalse(window.run_command_set_button.isEnabled())

        group = folder.child(1)
        window.command_set_list.setCurrentItem(group)
        self.assertIn("echo c", window.command_set_output.toPlainText())
        window.ssh_host_input.setText("server")
        window.ssh_username_input.setText("user")
        window._connect_ssh()
        window._run_command_set()
        self.assertEqual(manager.shell.sent, ["echo c"])

    def test_dragged_command_set_moves_into_folder(self) -> None:
        """Dropping a command set on a folder persists its new parent folder."""
        store = CommandSetStore(Path(self.temp_dir.name) / "command_sets.json")
        store.create_folder("Diagnostics")
        store.upsert(CommandSet(name="status", commands="uname -a"))
        window = self.create_window(command_set_store=store)

        window._move_command_set("status", "Diagnostics")

        self.assertEqual(store.load().command_sets["status"].parent_path, "Diagnostics")
        folder = window.command_set_list.topLevelItem(0)
        self.assertEqual(folder.text(0), "Diagnostics")
        self.assertEqual(folder.child(0).text(0), "status")


if __name__ == "__main__":
    unittest.main()
