"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.core.ssh_manager import SSHManager
from mmu_control.models.command_set import CommandSet
from mmu_control.models.settings import SSHSettings
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.ui.command_editor_dialog import CommandEditorDialog
from mmu_control.ui.terminal_widget import TerminalWidget


class MainWindow(QMainWindow):
    """Primary window for the MMU control application."""

    def __init__(
        self,
        ssh_manager: SSHManager | None = None,
        command_set_store: CommandSetStore | None = None,
    ) -> None:
        super().__init__()
        self._ssh_manager = ssh_manager or SSHManager()
        self._command_set_store = command_set_store or CommandSetStore.create_default()
        self._command_sets: dict[str, CommandSet] = {}
        self._shell: InteractiveShell | None = None
        self._pending_echo: str | None = None
        self._echo_buffer = ""
        self.setWindowTitle("MMU Control")
        self.resize(1180, 760)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self.addToolBar(self._build_toolbar())
        self._shell_timer = QTimer(self)
        self._shell_timer.setInterval(50)
        self._shell_timer.timeout.connect(self._poll_shell)
        self._wire_events()
        self._load_command_sets()

    def _wire_events(self) -> None:
        self.connect_button.clicked.connect(self._connect_ssh)
        self.disconnect_button.clicked.connect(self._disconnect_ssh)
        self.reconnect_button.clicked.connect(self._reconnect_ssh)
        self.terminal_widget.commandSubmitted.connect(self._send_terminal_command)
        self.new_command_button.clicked.connect(self._create_command_set)
        self.edit_command_button.clicked.connect(self._edit_command_set)
        self.delete_command_button.clicked.connect(self._delete_command_set)
        self.run_command_set_button.clicked.connect(self._run_command_set)
        self.command_set_list.currentItemChanged.connect(self._show_selected_command_set)

    def _ssh_settings(self) -> SSHSettings:
        return SSHSettings(
            host=self.ssh_host_input.text().strip(),
            port=self.ssh_port_input.value(),
            username=self.ssh_username_input.text().strip(),
            password=self.ssh_password_input.text(),
        )

    def _connect_ssh(self) -> None:
        self.statusBar().showMessage("Connecting...")
        try:
            self._ssh_manager.connect(self._ssh_settings())
            self._activate_shell(self._ssh_manager.open_shell())
        except Exception as exc:
            self._show_connection_error(exc)

    def _reconnect_ssh(self) -> None:
        self.statusBar().showMessage("Reconnecting...")
        try:
            self._close_shell()
            self._ssh_manager.reconnect()
            self._activate_shell(self._ssh_manager.open_shell())
        except Exception as exc:
            self._show_connection_error(exc)

    def _activate_shell(self, shell: InteractiveShell) -> None:
        self._shell = shell
        self._pending_echo = None
        self._echo_buffer = ""
        self.terminal_widget.clear_terminal()
        self.terminal_widget.set_prompt("")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.reconnect_button.setEnabled(True)
        self.open_sftp_button.setEnabled(True)
        self.connection_status_label.setText("SSH: connected")
        self.statusBar().showMessage("Connected")
        self._shell_timer.start()
        self._poll_shell()

    def _send_terminal_command(self, command: str) -> None:
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Not connected to an SSH shell.")
            return
        try:
            self._shell.send_line(command)
            self._pending_echo = command if command else None
            self._echo_buffer = ""
        except Exception as exc:
            self._show_connection_error(exc)

    def _load_command_sets(self) -> None:
        collection = self._command_set_store.load()
        self._command_sets = dict(collection.command_sets or {})
        self._refresh_command_set_list()

    def _refresh_command_set_list(self, selected_name: str | None = None) -> None:
        self.command_set_list.clear()
        for name in sorted(self._command_sets):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.command_set_list.addItem(item)
            if selected_name == name:
                self.command_set_list.setCurrentItem(item)
        if self.command_set_list.currentItem() is None and self.command_set_list.count():
            self.command_set_list.setCurrentRow(0)
        if self.command_set_list.currentItem() is None:
            self.command_set_output.clear()
            self._set_command_actions_enabled(False)

    def _create_command_set(self) -> None:
        dialog = CommandEditorDialog()
        if dialog.exec() != CommandEditorDialog.DialogCode.Accepted:
            return
        command_set = dialog.command_set()
        self._save_command_set(command_set)

    def _edit_command_set(self) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            return
        dialog = CommandEditorDialog(command_set)
        if dialog.exec() != CommandEditorDialog.DialogCode.Accepted:
            return
        edited = dialog.command_set()
        if edited.name != command_set.name:
            self._command_set_store.delete(command_set.name)
        self._save_command_set(edited)

    def _delete_command_set(self) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            return
        result = QMessageBox.question(
            self,
            "Delete Command Set",
            f"Delete command set '{command_set.name}'?",
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        collection = self._command_set_store.delete(command_set.name)
        self._command_sets = dict(collection.command_sets or {})
        self._refresh_command_set_list()

    def _run_command_set(self) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            return
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Not connected to an SSH shell.")
            return
        for command in command_set.commands.splitlines():
            command = command.strip()
            if command:
                self._shell.send_line(command)

    def _save_command_set(self, command_set: CommandSet) -> None:
        collection = self._command_set_store.upsert(command_set)
        self._command_sets = dict(collection.command_sets or {})
        self._refresh_command_set_list(command_set.name.strip())

    def _selected_command_set(self) -> CommandSet | None:
        item = self.command_set_list.currentItem()
        if item is None:
            return None
        name = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(name, str):
            return None
        return self._command_sets.get(name)

    def _show_selected_command_set(self, *_items: QListWidgetItem | None) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            self.command_set_output.clear()
            self._set_command_actions_enabled(False)
            return
        self.command_set_output.setPlainText(
            f"Name: {command_set.name}\n"
            f"Description: {command_set.description}\n\n"
            f"{command_set.commands}"
        )
        self._set_command_actions_enabled(True)

    def _set_command_actions_enabled(self, enabled: bool) -> None:
        self.edit_command_button.setEnabled(enabled)
        self.delete_command_button.setEnabled(enabled)
        self.run_command_set_button.setEnabled(enabled)

    def _poll_shell(self) -> None:
        if self._shell is None:
            return
        if not self._shell.is_open:
            self._handle_connection_closed("SSH shell closed.")
            return
        try:
            output = self._shell.read_available()
        except Exception as exc:
            self._show_connection_error(exc)
            return
        output = self._filter_command_echo(output)
        if output:
            self.terminal_widget.write_stream(output)

    def _filter_command_echo(self, output: str) -> str:
        """Remove the PTY echo because the widget already displays local input."""
        if self._pending_echo is None or not output:
            return output
        self._echo_buffer += output.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" not in self._echo_buffer:
            return ""
        first_line, remainder = self._echo_buffer.split("\n", 1)
        result = remainder if first_line == self._pending_echo else self._echo_buffer
        self._pending_echo = None
        self._echo_buffer = ""
        return result

    def _disconnect_ssh(self) -> None:
        self._shell_timer.stop()
        self._close_shell()
        self._ssh_manager.disconnect()
        self._set_disconnected_state("Disconnected")

    def _close_shell(self) -> None:
        if self._shell is not None:
            self._shell.close()
            self._shell = None

    def _show_connection_error(self, error: Exception) -> None:
        self._shell_timer.stop()
        self._close_shell()
        self._ssh_manager.disconnect()
        message = str(error) or error.__class__.__name__
        self.terminal_widget.write_output(f"SSH error: {message}")
        self._set_disconnected_state("Connection failed")

    def _handle_connection_closed(self, message: str) -> None:
        self._shell_timer.stop()
        self._shell = None
        self._ssh_manager.disconnect()
        self.terminal_widget.write_output(message)
        self._set_disconnected_state("Connection closed")

    def _set_disconnected_state(self, status_message: str) -> None:
        self.terminal_widget.set_prompt("mmu> ")
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.reconnect_button.setEnabled(True)
        self.open_sftp_button.setEnabled(False)
        self.connection_status_label.setText("SSH: disconnected")
        self.statusBar().showMessage(status_message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Close SSH resources before the application exits."""
        self._shell_timer.stop()
        self._close_shell()
        self._ssh_manager.disconnect()
        super().closeEvent(event)

    def _build_central_widget(self) -> QWidget:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.addWidget(self._build_connection_panel())
        layout.addWidget(self._build_workspace(), stretch=1)
        return container

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar("Main", self)
        toolbar.setMovable(False)

        self.connect_button = QPushButton("Connect", self)
        self.disconnect_button = QPushButton("Disconnect", self)
        self.reconnect_button = QPushButton("Reconnect", self)
        self.disconnect_button.setEnabled(False)
        self.reconnect_button.setEnabled(False)

        toolbar.addWidget(self.connect_button)
        toolbar.addWidget(self.disconnect_button)
        toolbar.addWidget(self.reconnect_button)
        return toolbar

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar(self)
        self.connection_status_label = QLabel("SSH: disconnected", self)
        self.board_status_label = QLabel("Board: not configured", self)
        status_bar.addPermanentWidget(self.connection_status_label)
        status_bar.addPermanentWidget(self.board_status_label)
        status_bar.showMessage("Ready")
        return status_bar

    def _build_connection_panel(self) -> QFrame:
        panel = QFrame(self)
        panel.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QGridLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(10)

        layout.addWidget(self._build_ssh_group(), 0, 0)
        layout.addWidget(self._build_board_group(), 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return panel

    def _build_ssh_group(self) -> QGroupBox:
        group = QGroupBox("SSH Server", self)
        layout = QFormLayout(group)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.ssh_host_input = QLineEdit(self)
        self.ssh_host_input.setPlaceholderText("Host or IP address")
        self.ssh_port_input = QSpinBox(self)
        self.ssh_port_input.setRange(1, 65535)
        self.ssh_port_input.setValue(22)
        self.ssh_username_input = QLineEdit(self)
        self.ssh_username_input.setPlaceholderText("Username")
        self.ssh_password_input = QLineEdit(self)
        self.ssh_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.ssh_password_input.setPlaceholderText("Password")

        layout.addRow("Host", self.ssh_host_input)
        layout.addRow("Port", self.ssh_port_input)
        layout.addRow("User", self.ssh_username_input)
        layout.addRow("Password", self.ssh_password_input)
        return group

    def _build_board_group(self) -> QGroupBox:
        group = QGroupBox("Board", self)
        layout = QFormLayout(group)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.board_ip_input = QLineEdit(self)
        self.board_ip_input.setPlaceholderText("Board IP")
        self.board_username_input = QLineEdit(self)
        self.board_username_input.setPlaceholderText("Username")
        self.board_password_input = QLineEdit(self)
        self.board_password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.board_password_input.setPlaceholderText("Password")
        self.board_interface_input = QLineEdit(self)
        self.board_interface_input.setPlaceholderText("Interface, e.g. eth0")
        self.usb_port_combo = QComboBox(self)
        self.usb_port_combo.addItem("No USB ports detected")
        self.refresh_usb_button = QPushButton("Refresh USB", self)

        usb_row = QWidget(self)
        usb_layout = QHBoxLayout(usb_row)
        usb_layout.setContentsMargins(0, 0, 0, 0)
        usb_layout.addWidget(self.usb_port_combo, stretch=1)
        usb_layout.addWidget(self.refresh_usb_button)

        layout.addRow("IP", self.board_ip_input)
        layout.addRow("User", self.board_username_input)
        layout.addRow("Password", self.board_password_input)
        layout.addRow("Interface", self.board_interface_input)
        layout.addRow("USB Port", usb_row)
        return group

    def _build_workspace(self) -> QTabWidget:
        tabs = QTabWidget(self)
        tabs.addTab(self._build_terminal_tab(), "Terminal")
        tabs.addTab(self._build_commands_tab(), "Commands")
        tabs.addTab(self._build_transfer_tab(), "SFTP")
        return tabs

    def _build_terminal_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        self.terminal_widget = TerminalWidget(prompt="mmu> ")
        layout.addWidget(self.terminal_widget, stretch=1)
        return tab

    def _build_commands_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        button_row = QWidget(self)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.new_command_button = QPushButton("New", self)
        self.edit_command_button = QPushButton("Edit", self)
        self.delete_command_button = QPushButton("Delete", self)
        self.run_command_set_button = QPushButton("Run", self)
        self.edit_command_button.setEnabled(False)
        self.delete_command_button.setEnabled(False)
        self.run_command_set_button.setEnabled(False)

        button_layout.addWidget(self.new_command_button)
        button_layout.addWidget(self.edit_command_button)
        button_layout.addWidget(self.delete_command_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.run_command_set_button)

        self.command_set_output = QPlainTextEdit(self)
        self.command_set_output.setReadOnly(True)
        self.command_set_output.setPlaceholderText("Command sets will be listed here.")

        layout.addWidget(button_row)
        self.command_set_list = QListWidget(self)
        layout.addWidget(self.command_set_list)
        layout.addWidget(self.command_set_output, stretch=1)
        return tab

    def _build_transfer_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        transfer_actions = QWidget(self)
        action_layout = QHBoxLayout(transfer_actions)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self.open_sftp_button = QPushButton("Open SFTP", self)
        self.open_sftp_button.setEnabled(False)
        action_layout.addWidget(self.open_sftp_button, alignment=Qt.AlignmentFlag.AlignLeft)
        action_layout.addStretch(1)

        self.sftp_output = QPlainTextEdit(self)
        self.sftp_output.setReadOnly(True)
        self.sftp_output.setPlaceholderText("SFTP session output will appear here.")

        layout.addWidget(transfer_actions)
        layout.addWidget(self.sftp_output, stretch=1)
        return tab
