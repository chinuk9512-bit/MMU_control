"""Main application window."""

from __future__ import annotations

import json
import os
import posixpath
import shlex
import subprocess

from PySide6.QtCore import QByteArray, QMimeData, QProcess, QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QDragEnterEvent, QDragMoveEvent, QDropEvent, QDrag
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
    QVBoxLayout,
    QWidget,
)

from mmu_control.core.config_manager import ConfigError, ConfigManager
from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.core.minicom_manager import MinicomError, MinicomManager
from mmu_control.core.sftp_manager import SFTPError, SFTPManager
from mmu_control.core.ssh_manager import SSHManager
from mmu_control.models.command_set import CommandSet
from mmu_control.models.settings import AppSettings, BoardSettings, SSHSettings, WindowSettings
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.ui.background_worker import TaskRunner, ThreadPoolTaskRunner
from mmu_control.ui.command_editor_dialog import CommandEditorDialog
from mmu_control.ui.terminal_widget import TerminalWidget


class FileDropLineEdit(QLineEdit):
    """Line edit that accepts local file paths via drag and drop."""

    localFileDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """Accept drags that contain at least one local file URL."""
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if urls and urls[0].isLocalFile():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """Set the input text to the dropped local file path."""
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        if urls and urls[0].isLocalFile():
            local_path = os.path.normpath(urls[0].toLocalFile())
            self.setText(local_path)
            self.localFileDropped.emit(local_path)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class SftpFileListWidget(QListWidget):
    """Draggable file list for one side of the SFTP transfer view."""

    FILE_MIME_TYPE = "application/x-mmu-control-sftp-file"
    fileDropped = Signal(str, str, str)

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.side = side
        self.current_directory = "/tmp"
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # noqa: N802
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        is_dir = item.data(Qt.ItemDataRole.UserRole + 1)
        if not isinstance(path, str) or bool(is_dir):
            return
        payload = json.dumps({"side": self.side, "path": path}).encode("utf-8")
        mime_data = QMimeData()
        mime_data.setData(self.FILE_MIME_TYPE, QByteArray(payload))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(supported_actions, Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._accepted_transfer(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if self._accepted_transfer(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        data = self._transfer_data(event.mimeData())
        if data is None:
            super().dropEvent(event)
            return
        source_side, source_path = data
        target_directory = self._drop_target_directory(event)
        self.fileDropped.emit(source_side, source_path, target_directory)
        event.acceptProposedAction()

    def _accepted_transfer(self, mime_data: QMimeData) -> bool:
        data = self._transfer_data(mime_data)
        return data is not None and data[0] != self.side

    def _transfer_data(self, mime_data: QMimeData) -> tuple[str, str] | None:
        if not mime_data.hasFormat(self.FILE_MIME_TYPE):
            return None
        try:
            payload = json.loads(bytes(mime_data.data(self.FILE_MIME_TYPE)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        side = payload.get("side")
        path = payload.get("path")
        if side not in {"server", "mmu"} or not isinstance(path, str) or not path:
            return None
        return side, path

    def _drop_target_directory(self, event: QDropEvent) -> str:
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return self.current_directory
        path = item.data(Qt.ItemDataRole.UserRole)
        is_dir = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(path, str) and bool(is_dir):
            return path
        return self.current_directory


class MainWindow(QMainWindow):
    """Primary window for the MMU control application."""

    def __init__(
        self,
        ssh_manager: SSHManager | None = None,
        command_set_store: CommandSetStore | None = None,
        config_manager: ConfigManager | None = None,
        task_runner: TaskRunner | None = None,
    ) -> None:
        super().__init__()
        self._ssh_manager = ssh_manager or SSHManager()
        self._command_set_store = command_set_store or CommandSetStore.create_default()
        self._config_manager = config_manager or ConfigManager.create_default()
        self._task_runner = task_runner or ThreadPoolTaskRunner(self)
        self._sftp_manager = SFTPManager()
        self._minicom_manager = MinicomManager()
        self._settings = AppSettings()
        self._command_sets: dict[str, CommandSet] = {}
        self._shell: InteractiveShell | None = None
        self._sftp_shell: InteractiveShell | None = None
        self._pending_echo: str | None = None
        self._echo_buffer = ""
        self._sftp_pending_echo: str | None = None
        self._sftp_pending_listing = False
        self._sftp_echo_buffer = ""
        self._sftp_prompt_buffer = ""
        self._active_sftp_settings: BoardSettings | None = None
        self._sftp_session_active = False
        self._minicom_session_active = False
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self._interactive_program = ""
        self._local_cwd = os.getcwd()
        self._server_sftp_directory = "/tmp/mmu_control_uploads"
        self._mmu_sftp_directory = "/tmp"
        self._closing = False
        self.setWindowTitle("MMU Control")
        self.resize(1180, 760)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self._shell_timer = QTimer(self)
        self._shell_timer.setInterval(50)
        self._shell_timer.timeout.connect(self._poll_shell)
        self._sftp_timer = QTimer(self)
        self._sftp_timer.setInterval(50)
        self._sftp_timer.timeout.connect(self._poll_sftp_shell)
        self._wire_events()
        self._load_command_sets()
        self._load_settings()

    def _wire_events(self) -> None:
        self.connect_button.clicked.connect(self._connect_ssh)
        self.disconnect_button.clicked.connect(self._disconnect_ssh)
        self.terminal_widget.commandSubmitted.connect(self._send_terminal_command)
        self.terminal_widget.rawInput.connect(self._send_terminal_raw)
        self.sftp_terminal.commandSubmitted.connect(self._send_sftp_command)
        self.sftp_terminal.rawInput.connect(self._send_sftp_raw)
        self.new_command_button.clicked.connect(self._create_command_set)
        self.edit_command_button.clicked.connect(self._edit_command_set)
        self.delete_command_button.clicked.connect(self._delete_command_set)
        self.run_command_set_button.clicked.connect(self._run_command_set)
        self.open_sftp_button.clicked.connect(self._open_sftp)
        self.upload_sftp_button.clicked.connect(self._upload_sftp)
        self.download_sftp_button.clicked.connect(self._download_sftp)
        self.close_sftp_button.clicked.connect(self._close_sftp_session)
        self.server_path_input.localFileDropped.connect(self._handle_sftp_file_drop)
        self.server_file_list.fileDropped.connect(self._handle_sftp_list_drop)
        self.mmu_file_list.fileDropped.connect(self._handle_sftp_list_drop)
        self.server_file_list.itemDoubleClicked.connect(self._open_server_list_item)
        self.mmu_file_list.itemDoubleClicked.connect(self._open_mmu_list_item)
        self.refresh_usb_button.clicked.connect(self._refresh_usb_ports)
        self.open_minicom_button.clicked.connect(self._open_minicom)
        self.close_minicom_button.clicked.connect(self._close_minicom)
        self.mmu_ssh_connect_button.clicked.connect(self._connect_mmu_ssh)
        self.mmu_ssh_disconnect_button.clicked.connect(self._disconnect_mmu_ssh)
        self.usb_port_combo.currentTextChanged.connect(self._update_minicom_button)
        self.command_set_list.currentItemChanged.connect(self._show_selected_command_set)

    def _ssh_settings(self) -> SSHSettings:
        return SSHSettings(
            host=self.ssh_host_input.text().strip(),
            port=self.ssh_port_input.value(),
            username=self.ssh_username_input.text().strip(),
            password=self.ssh_password_input.text(),
        )

    def _board_settings(self) -> BoardSettings:
        return BoardSettings(
            ip_address=self.board_ip_input.text().strip(),
            username=self.board_username_input.text().strip(),
            password=self.board_password_input.text(),
            interface=self.board_interface_input.text().strip(),
            usb_port=self._selected_usb_port(),
            ssh_port=self.board_ssh_port_input.value(),
        )

    def _selected_usb_port(self) -> str:
        port = self.usb_port_combo.currentText().strip()
        return port if port.startswith(("/dev/ttyUSB", "/dev/ttyACM")) else ""

    def _load_settings(self) -> None:
        try:
            self._settings = self._config_manager.load()
        except ConfigError as exc:
            self.terminal_widget.write_output(f"Configuration error: {exc}")
            self.statusBar().showMessage("Could not load settings")
            return
        settings = self._settings
        self.ssh_host_input.setText(settings.ssh.host)
        self.ssh_port_input.setValue(settings.ssh.port)
        self.ssh_username_input.setText(settings.ssh.username)
        self.ssh_password_input.setText(settings.ssh.password)
        self.board_ip_input.setText(settings.board.ip_address)
        self.board_username_input.setText(settings.board.username)
        self.board_password_input.setText(settings.board.password)
        self.board_interface_input.setText(settings.board.interface)
        self.board_ssh_port_input.setValue(settings.board.ssh_port)
        if settings.board.usb_port:
            self.usb_port_combo.clear()
            self.usb_port_combo.addItem(settings.board.usb_port)
        self.resize(settings.window.width, settings.window.height)
        if settings.window.is_maximized:
            self.setWindowState(self.windowState() | Qt.WindowState.WindowMaximized)

    def _save_settings(self) -> None:
        geometry = self.normalGeometry() if self.isMaximized() else self.geometry()
        self._settings.ssh = self._ssh_settings()
        self._settings.board = self._board_settings()
        self._settings.window = WindowSettings(
            width=geometry.width(),
            height=geometry.height(),
            is_maximized=self.isMaximized(),
        )
        try:
            self._config_manager.save(self._settings)
        except ConfigError as exc:
            self.terminal_widget.write_output(f"Configuration error: {exc}")

    def _connect_ssh(self) -> None:
        self.statusBar().showMessage("Connecting...")
        self._set_connection_busy(True)
        settings = self._ssh_settings()
        self._task_runner.submit(
            lambda: self._connect_and_open(settings),
            self._connection_ready,
            self._show_connection_error,
        )

    def _connect_and_open(self, settings: SSHSettings) -> InteractiveShell:
        self._ssh_manager.connect(settings)
        return self._ssh_manager.open_shell()

    def _connection_ready(self, shell: InteractiveShell) -> None:
        if self._closing:
            shell.close()
            self._ssh_manager.disconnect()
            return
        self._set_connection_busy(False)
        self._activate_shell(shell)

    def _set_connection_busy(self, busy: bool) -> None:
        self.connect_button.setEnabled(not busy and self._shell is None)
        self.disconnect_button.setEnabled(not busy and self._shell is not None)

    def _activate_shell(self, shell: InteractiveShell) -> None:
        self._shell = shell
        self._pending_echo = None
        self._echo_buffer = ""
        self._sftp_session_active = False
        self._minicom_session_active = False
        self._mmu_ssh_session_active = False
        self._mmu_ssh_prompt_buffer = ""
        self._leave_interactive_mode()
        self.terminal_widget.clear_terminal()
        self.terminal_widget.set_prompt("")
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(True)
        self.open_sftp_button.setEnabled(True)
        self.refresh_usb_button.setEnabled(True)
        self._update_minicom_button()
        self.close_minicom_button.setEnabled(False)
        self.mmu_ssh_connect_button.setEnabled(True)
        self.mmu_ssh_disconnect_button.setEnabled(False)
        self.connection_status_label.setText("SSH: connected")
        self.statusBar().showMessage("Connected")
        self._shell_timer.start()
        self._poll_shell()

    def _send_terminal_command(self, command: str) -> None:
        if self._shell is None or not self._shell.is_open:
            self._run_local_terminal_command(command)
            return
        try:
            self._shell.send_line(command)
            self._interactive_program = self._interactive_program_name(command)
            self.terminal_widget.set_interactive_mode(bool(self._interactive_program))
            self._pending_echo = command
            self._echo_buffer = ""
        except Exception as exc:
            self._show_connection_error(exc)

    def _send_terminal_raw(self, text: str) -> None:
        if self._shell is None or not self._shell.is_open:
            self._write_local_process_input(text)
            return
        try:
            self._shell.send(text)
        except Exception as exc:
            self._show_connection_error(exc)
            return
        if (text == "\x03" and self._interactive_program != "minicom") or (
            text == "q" and self._interactive_program in {"htop", "top", "less", "more"}
        ):
            self._leave_interactive_mode()

    def _local_prompt(self) -> str:
        """Return the prompt for the local fallback terminal."""
        return f"{self._local_cwd}> "

    def _run_local_terminal_command(self, command: str) -> None:
        """Execute a command on the local PC when no SSH shell is connected."""
        command = command.strip()
        if not command:
            return
        if command.lower() in {"clear", "cls"}:
            self.terminal_widget.clear_terminal()
            return
        if command.lower() in {"pwd", "cd"}:
            self.terminal_widget.write_output(self._local_cwd)
            return
        if command.lower().startswith("cd "):
            self._change_local_directory(command[3:].strip())
            return
        try:
            result = subprocess.run(
                command,
                cwd=self._local_cwd,
                shell=True,
                text=True,
                capture_output=True,
                check=False,
            )
        except OSError as exc:
            self.terminal_widget.write_output(str(exc))
            return
        output = f"{result.stdout}{result.stderr}"
        if output:
            self.terminal_widget.write_output(output)

    def _change_local_directory(self, path_text: str) -> None:
        """Change the working directory used by the local fallback terminal."""
        if not path_text:
            self.terminal_widget.write_output(self._local_cwd)
            return
        try:
            parts = shlex.split(path_text)
        except ValueError as exc:
            self.terminal_widget.write_output(str(exc))
            return
        target_text = " ".join(parts) if parts else path_text
        target = os.path.expanduser(os.path.expandvars(target_text))
        if not os.path.isabs(target):
            target = os.path.join(self._local_cwd, target)
        target = os.path.abspath(target)
        if not os.path.isdir(target):
            self.terminal_widget.write_output(f"cd: no such directory: {target_text}")
            return
        self._local_cwd = target
        self.terminal_widget.set_prompt(self._local_prompt())

    def _interactive_program_name(self, command: str) -> str:
        try:
            parts = shlex.split(command)
        except ValueError:
            return ""
        while parts and parts[0] in {"sudo", "env"}:
            parts.pop(0)
        if not parts:
            return ""
        name = parts[0].rsplit("/", 1)[-1]
        interactive_programs = {"htop", "top", "less", "more", "vi", "vim", "nano", "watch"}
        return name if name in interactive_programs else ""

    def _leave_interactive_mode(self) -> None:
        self._interactive_program = ""
        self.terminal_widget.set_interactive_mode(False)
        self.terminal_widget.set_backspace_sequence("\x7f")

    def _open_sftp(self) -> None:
        if self._shell is None or not self._shell.is_open:
            self._append_sftp_output("Not connected to an SSH shell.")
            return
        if self._sftp_session_active:
            self._append_sftp_output("An SFTP session is already open.")
            return
        try:
            settings = self._board_settings()
            command = self._sftp_manager.build_command(settings)
        except SFTPError as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            self.board_status_label.setText("MMU: SFTP failed")
            self.statusBar().showMessage("SFTP failed")
            return
        self.open_sftp_button.setEnabled(False)
        self._append_sftp_output(f"Opening SFTP session: {command}")
        self.board_status_label.setText("MMU: SFTP opening")
        self.statusBar().showMessage("Opening SFTP session...")
        self._task_runner.submit(
            self._ssh_manager.open_shell,
            lambda shell: self._activate_sftp_shell(shell, settings),
            self._show_sftp_error,
        )

    def _activate_sftp_shell(
        self,
        shell: InteractiveShell,
        settings: BoardSettings,
    ) -> None:
        if self._closing or self._shell is None:
            shell.close()
            return
        self._sftp_shell = shell
        self._active_sftp_settings = settings
        try:
            command = self._sftp_manager.open_session(shell, settings)
        except Exception as exc:
            shell.close()
            self._sftp_shell = None
            self._show_sftp_error(exc)
            return
        self._sftp_session_active = True
        self._sftp_pending_echo = command
        self._sftp_echo_buffer = ""
        self._sftp_pending_listing = False
        self._sftp_prompt_buffer = ""
        self.sftp_terminal.set_prompt("sftp> ")
        self._append_sftp_output("SFTP session opened. You can type SFTP commands below.")
        self._sftp_timer.start()
        self._set_sftp_actions_enabled(True)
        self.board_status_label.setText("MMU: SFTP connected")
        self.statusBar().showMessage("SFTP session opened")
        self._refresh_sftp_file_lists()
        self._poll_sftp_shell()

    def _upload_sftp(self) -> None:
        self._run_sftp_transfer(upload=True)

    def _download_sftp(self) -> None:
        self._run_sftp_transfer(upload=False)

    def _run_sftp_transfer(self, upload: bool) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
            self._append_sftp_output("Open an SFTP session first.")
            return
        try:
            if upload:
                server_path = self._selected_file_path(self.server_file_list)
                board_path = posixpath.join(self._mmu_sftp_directory, posixpath.basename(server_path))
                command = self._sftp_manager.upload(
                    self._sftp_shell,
                    server_path,
                    board_path,
                )
            else:
                board_path = self._selected_file_path(self.mmu_file_list)
                server_path = posixpath.join(
                    self._server_sftp_directory,
                    posixpath.basename(board_path),
                )
                command = self._sftp_manager.download(
                    self._sftp_shell,
                    board_path,
                    server_path,
                )
        except SFTPError as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            return
        self._sftp_pending_echo = command
        self._sftp_echo_buffer = ""
        self._append_sftp_output(f"Running: {command}")

    def _selected_file_path(self, file_list: SftpFileListWidget) -> str:
        item = file_list.currentItem()
        if item is None:
            raise SFTPError("Select a file from the file list first.")
        path = item.data(Qt.ItemDataRole.UserRole)
        is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        if not isinstance(path, str) or is_dir:
            raise SFTPError("Select a file, not a directory.")
        return path

    def _handle_sftp_list_drop(self, source_side: str, source_path: str, target_directory: str) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
            self._append_sftp_output("Open an SFTP session first.")
            return
        destination = posixpath.join(target_directory, posixpath.basename(source_path))
        try:
            if source_side == "server":
                command = self._sftp_manager.upload(self._sftp_shell, source_path, destination)
            else:
                command = self._sftp_manager.download(self._sftp_shell, source_path, destination)
        except SFTPError as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            return
        self._sftp_pending_echo = command
        self._sftp_echo_buffer = ""
        self._append_sftp_output(f"Running: {command}")
        self.statusBar().showMessage("SFTP drag-and-drop transfer started")

    def _refresh_sftp_file_lists(self) -> None:
        self._refresh_server_file_list()
        self._refresh_mmu_file_list()

    def _refresh_server_file_list(self) -> None:
        self.server_file_list.current_directory = self._server_sftp_directory
        try:
            output = self._ssh_manager.execute_command(
                "find "
                f"{shlex.quote(self._server_sftp_directory)} "
                "-maxdepth 1 -mindepth 1 -printf '%y\\t%p\\n' 2>/dev/null"
            )
        except Exception as exc:
            self._populate_file_list(
                self.server_file_list,
                [(False, f"Could not list server files: {exc}", "")],
            )
            return
        entries = self._parse_find_listing(output)
        self._populate_file_list(self.server_file_list, entries)

    def _refresh_mmu_file_list(self) -> None:
        self.mmu_file_list.current_directory = self._mmu_sftp_directory
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            self._populate_file_list(self.mmu_file_list, [])
            return
        command = f"ls -la {shlex.quote(self._mmu_sftp_directory)}"
        self._sftp_shell.send_line(command)
        self._sftp_pending_echo = command
        self._sftp_pending_listing = True
        self._sftp_echo_buffer = ""
        self._append_sftp_output(f"Listing MMU files: {command}")
        self._populate_file_list(
            self.mmu_file_list,
            [(True, self._mmu_sftp_directory, self._mmu_sftp_directory)],
        )

    def _parse_find_listing(self, output: str) -> list[tuple[bool, str, str]]:
        entries: list[tuple[bool, str, str]] = []
        for line in output.splitlines():
            if "\t" not in line:
                continue
            kind, path = line.split("\t", 1)
            entries.append((kind == "d", posixpath.basename(path.rstrip("/")), path))
        return entries

    def _parse_sftp_listing(self, output: str) -> list[tuple[bool, str, str]]:
        entries: list[tuple[bool, str, str]] = []
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("Listing MMU files:") or line.startswith("sftp>"):
                continue
            parts = line.split()
            if len(parts) < 9 or parts[-1] in {".", ".."}:
                continue
            name = " ".join(parts[8:])
            is_dir = parts[0].startswith("d")
            path = posixpath.join(self._mmu_sftp_directory, name)
            entries.append((is_dir, name, path))
        return entries

    def _populate_file_list(
        self,
        file_list: SftpFileListWidget,
        entries: list[tuple[bool, str, str]],
    ) -> None:
        file_list.clear()
        parent = posixpath.dirname(file_list.current_directory.rstrip("/")) or "/"
        parent_item = QListWidgetItem("../")
        parent_item.setData(Qt.ItemDataRole.UserRole, parent)
        parent_item.setData(Qt.ItemDataRole.UserRole + 1, True)
        file_list.addItem(parent_item)
        for is_dir, name, path in sorted(entries, key=lambda entry: (not entry[0], entry[1].lower())):
            if not name or not path:
                item = QListWidgetItem(name)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            else:
                item = QListWidgetItem(f"{name}/" if is_dir else name)
                item.setData(Qt.ItemDataRole.UserRole, path)
                item.setData(Qt.ItemDataRole.UserRole + 1, is_dir)
            file_list.addItem(item)

    def _open_server_list_item(self, item: QListWidgetItem) -> None:
        self._open_sftp_list_item(self.server_file_list, item)

    def _open_mmu_list_item(self, item: QListWidgetItem) -> None:
        self._open_sftp_list_item(self.mmu_file_list, item)

    def _open_sftp_list_item(self, file_list: SftpFileListWidget, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if not bool(item.data(Qt.ItemDataRole.UserRole + 1)) or not isinstance(path, str):
            return
        if file_list.side == "server":
            self._server_sftp_directory = path
            self._refresh_server_file_list()
        else:
            self._mmu_sftp_directory = path
            self._refresh_mmu_file_list()

    def _handle_sftp_file_drop(self, local_path: str) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
            self._append_sftp_output("Open an SFTP session before dropping a file to upload.")
            return
        if not os.path.isfile(local_path):
            self._append_sftp_output(f"SFTP error: dropped path is not a file: {local_path}")
            return

        filename = os.path.basename(local_path)
        if not self.board_path_input.text().strip():
            self.board_path_input.setText(posixpath.join("/tmp", filename))
        server_path = self._server_upload_path(local_path)
        self.server_path_input.setText(server_path)
        self._set_sftp_actions_enabled(False)
        self._append_sftp_output(f"Uploading dropped file to SSH server: {server_path}")
        self.statusBar().showMessage("Uploading dropped file to SSH server...")
        self._task_runner.submit(
            lambda: self._upload_dropped_file_to_server(local_path, server_path),
            self._upload_dropped_file_to_mmu,
            self._show_dropped_file_error,
        )

    def _server_upload_path(self, local_path: str) -> str:
        filename = os.path.basename(local_path.strip()) or "upload.bin"
        return posixpath.join("/tmp/mmu_control_uploads", filename)

    def _upload_dropped_file_to_server(self, local_path: str, server_path: str) -> str:
        self._ssh_manager.execute_command(
            f"mkdir -p {shlex.quote(posixpath.dirname(server_path))}"
        )
        self._ssh_manager.upload_file(local_path, server_path)
        return server_path

    def _upload_dropped_file_to_mmu(self, server_path: str) -> None:
        self._set_sftp_actions_enabled(True)
        if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
            self._append_sftp_output("SFTP error: session closed before dropped file upload could finish.")
            self.statusBar().showMessage("SFTP upload failed")
            return
        try:
            command = self._sftp_manager.upload(
                self._sftp_shell,
                server_path,
                self.board_path_input.text(),
            )
        except SFTPError as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            self.statusBar().showMessage("SFTP upload failed")
            return
        self._sftp_pending_echo = command
        self._sftp_echo_buffer = ""
        self._append_sftp_output(f"Running: {command}")
        self.statusBar().showMessage("Dropped file upload started")

    def _show_dropped_file_error(self, error: Exception) -> None:
        self._set_sftp_actions_enabled(
            self._sftp_shell is not None and self._sftp_shell.is_open and self._sftp_session_active
        )
        message = str(error) or error.__class__.__name__
        self._append_sftp_output(f"SFTP error: {message}")
        self.statusBar().showMessage("SFTP upload failed")

    def _close_sftp_session(self) -> None:
        if self._sftp_shell is not None and self._sftp_shell.is_open and self._sftp_session_active:
            self._sftp_manager.close_session(self._sftp_shell)
        self._close_sftp_shell()
        self._append_sftp_output("SFTP session closed. Main terminal remains connected.")
        self.board_status_label.setText("MMU: SFTP closed")
        self.statusBar().showMessage("SFTP session closed")

    def _send_sftp_command(self, command: str) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            self._run_sftp_local_command(command)
            return
        try:
            self._sftp_shell.send_line(command)
            self._sftp_pending_echo = command
            self._sftp_echo_buffer = ""
        except Exception as exc:
            self._show_sftp_error(exc)

    def _run_sftp_local_command(self, command: str) -> None:
        """Mirror the Terminal tab local prompt before an SFTP session is open."""
        before = self.terminal_widget.toPlainText()
        self._run_local_terminal_command(command)
        after = self.terminal_widget.toPlainText()
        if after != before:
            self._copy_new_terminal_output_to_sftp(before, after)
            self.terminal_widget.setPlainText(before)
            self.terminal_widget.refresh_display()
        self.sftp_terminal.set_prompt(self._local_prompt())

    def _copy_new_terminal_output_to_sftp(self, before: str, after: str) -> None:
        prompt = self._local_prompt()
        new_text = after[len(before):] if after.startswith(before) else after
        if new_text.endswith(prompt):
            new_text = new_text[: -len(prompt)]
        new_text = new_text.strip("\n")
        if new_text:
            self._append_sftp_output(new_text)

    def _send_sftp_raw(self, text: str) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            return
        try:
            self._sftp_shell.send(text)
        except Exception as exc:
            self._show_sftp_error(exc)

    def _set_sftp_actions_enabled(self, enabled: bool) -> None:
        self.upload_sftp_button.setEnabled(enabled)
        self.download_sftp_button.setEnabled(enabled)
        self.close_sftp_button.setEnabled(enabled)

    def _refresh_usb_ports(self) -> None:
        if self._shell is None or not self._shell.is_open:
            self.statusBar().showMessage("Connect to SSH before scanning USB ports")
            return
        selected = self._selected_usb_port()
        self.refresh_usb_button.setEnabled(False)
        self.usb_port_combo.clear()
        self.usb_port_combo.addItem("Searching remote USB ports...")
        self.statusBar().showMessage("Searching remote USB ports...")
        self._task_runner.submit(
            self._ssh_manager.list_serial_ports,
            lambda ports: self._usb_ports_ready(ports, selected),
            self._usb_ports_failed,
        )

    def _usb_ports_ready(self, ports: list[str], selected: str) -> None:
        self.usb_port_combo.clear()
        if ports:
            self.usb_port_combo.addItems(ports)
            if selected in ports:
                self.usb_port_combo.setCurrentText(selected)
            self.statusBar().showMessage(f"Found {len(ports)} remote USB port(s)")
        else:
            self.usb_port_combo.addItem("No remote USB ports detected")
            self.statusBar().showMessage("No remote USB ports detected")
        self.refresh_usb_button.setEnabled(self._shell is not None and self._shell.is_open)
        self._update_minicom_button()

    def _usb_ports_failed(self, error: Exception) -> None:
        self.usb_port_combo.clear()
        self.usb_port_combo.addItem("USB scan failed")
        self.refresh_usb_button.setEnabled(self._shell is not None and self._shell.is_open)
        self._update_minicom_button()
        self.terminal_widget.write_output(f"USB scan error: {error}")
        self.statusBar().showMessage("USB scan failed")

    def _update_minicom_button(self, *_args: object) -> None:
        connected = self._shell is not None and self._shell.is_open
        self.open_minicom_button.setEnabled(
            connected
            and not self._minicom_session_active
            and bool(self._selected_usb_port())
        )

    def _connect_mmu_ssh(self) -> None:
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Connect to the SSH server before opening an MMU SSH session.")
            return
        try:
            command = self._build_mmu_ssh_command(self._board_settings())
            self._shell.send_line(SFTPManager.KNOWN_HOSTS_CLEANUP_COMMAND)
            self._shell.send_line(command)
        except ValueError as exc:
            self.terminal_widget.write_output(f"MMU SSH error: {exc}")
            self.board_status_label.setText("MMU: SSH failed")
            return
        self._pending_echo = command
        self._echo_buffer = ""
        self._mmu_ssh_prompt_buffer = ""
        self._mmu_ssh_auth_pending = True
        self._mmu_ssh_session_active = True
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button.setEnabled(True)
        self.board_status_label.setText("MMU: SSH connecting")
        self.statusBar().showMessage("Opening MMU SSH session...")

    def _build_mmu_ssh_command(self, settings: BoardSettings) -> str:
        if not settings.ip_address.strip():
            raise ValueError("MMU IP address is required.")
        if not settings.username.strip():
            raise ValueError("MMU username is required.")
        if not 1 <= settings.ssh_port <= 65535:
            raise ValueError("MMU SSH port must be between 1 and 65535.")
        destination = settings.ip_address.strip()
        interface = settings.interface.strip()
        if interface and "%" not in destination:
            destination = f"{destination}%{interface}"
        command = ["ssh", f"{settings.username.strip()}@{destination}", "-p", str(settings.ssh_port)]
        return " ".join(shlex.quote(part) for part in command)

    def _handle_mmu_ssh_auth(self, output: str) -> None:
        self._mmu_ssh_prompt_buffer = f"{self._mmu_ssh_prompt_buffer}{output}"[-512:]
        lower = self._mmu_ssh_prompt_buffer.lower()
        if "password:" in lower and self._mmu_ssh_auth_pending:
            password = self.board_password_input.text()
            self._shell.send_line(password)
            self._mmu_ssh_auth_pending = False
            self._mmu_ssh_prompt_buffer = ""
            self.terminal_widget.write_output("MMU SSH password sent.")
            self.board_status_label.setText("MMU: SSH connected")
            self.statusBar().showMessage("MMU SSH session opened")
        elif "are you sure you want to continue connecting" in lower:
            self._shell.send_line("yes")
            self._mmu_ssh_prompt_buffer = ""
        elif "permission denied" in lower or "could not resolve" in lower or "connection refused" in lower:
            self._mmu_ssh_auth_pending = False
            self.board_status_label.setText("MMU: SSH failed")
            self.statusBar().showMessage("MMU SSH failed")
        elif output:
            self.board_status_label.setText("MMU: SSH connected")

    def _disconnect_mmu_ssh(self) -> None:
        if self._shell is not None and self._shell.is_open and self._mmu_ssh_session_active:
            self._shell.send_line("exit")
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self.mmu_ssh_connect_button.setEnabled(self._shell is not None and self._shell.is_open)
        self.mmu_ssh_disconnect_button.setEnabled(False)
        self.board_status_label.setText("MMU: SSH disconnected")
        self.statusBar().showMessage("Closing MMU SSH session...")

    def _open_minicom(self) -> None:
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Not connected to an SSH shell.")
            return
        try:
            command = self._minicom_manager.build_command(self._selected_usb_port())
            self._shell.send_line(command)
        except MinicomError as exc:
            self.terminal_widget.write_output(f"Minicom error: {exc}")
            return
        self._pending_echo = command
        self._echo_buffer = ""
        self._minicom_session_active = True
        self._interactive_program = "minicom"
        self.terminal_widget.set_backspace_sequence("\x08")
        self.terminal_widget.set_interactive_mode(True)
        self.open_minicom_button.setEnabled(False)
        self.close_minicom_button.setEnabled(True)
        self.board_status_label.setText(f"MMU: minicom on {self._selected_usb_port()}")
        self.statusBar().showMessage("Opening minicom...")

    def _close_minicom(self) -> None:
        if self._shell is not None and self._shell.is_open and self._minicom_session_active:
            self._minicom_manager.close_session(self._shell)
        self._minicom_session_active = False
        self._leave_interactive_mode()
        self.close_minicom_button.setEnabled(False)
        self._update_minicom_button()
        self.board_status_label.setText("MMU: minicom closed")
        self.statusBar().showMessage("Closing minicom...")

    def _append_sftp_output(self, text: str) -> None:
        self.sftp_terminal.write_output(text.rstrip())

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
        if self._mmu_ssh_session_active:
            self._handle_mmu_ssh_auth(output)
        if output:
            self.terminal_widget.write_stream(output)

    def _poll_sftp_shell(self) -> None:
        if self._sftp_shell is None:
            return
        if not self._sftp_shell.is_open:
            self._handle_sftp_closed("SFTP shell closed.")
            return
        try:
            output = self._sftp_shell.read_available()
        except Exception as exc:
            self._show_sftp_error(exc)
            return
        if not output:
            return
        settings = self._active_sftp_settings
        if settings is not None:
            self._sftp_prompt_buffer = f"{self._sftp_prompt_buffer}{output}"[-512:]
            accepted_host = self._sftp_manager.handle_authenticity_prompt(
                self._sftp_shell,
                self._sftp_prompt_buffer,
            )
            if accepted_host:
                self._sftp_prompt_buffer = ""
                self._append_sftp_output("SFTP host authenticity accepted.")
            else:
                sent_password = self._sftp_manager.handle_password_prompt(
                    self._sftp_shell,
                    self._sftp_prompt_buffer,
                    settings,
                )
                if sent_password:
                    self._sftp_prompt_buffer = ""
                    self._append_sftp_output(
                        f"SFTP password sent: {settings.password or '(empty)'}"
                    )
        output = self._filter_sftp_echo(output)
        output = self._without_trailing_sftp_prompt(output)
        if self._sftp_pending_listing and output.strip():
            self._populate_file_list(self.mmu_file_list, self._parse_sftp_listing(output))
            self._sftp_pending_listing = False
        if output:
            self.sftp_terminal.write_stream(output)

    def _without_trailing_sftp_prompt(self, output: str) -> str:
        """Drop remote SFTP prompts because the widget already shows one locally."""
        while output.endswith("sftp> "):
            output = output.removesuffix("sftp> ")
        return output

    def _filter_command_echo(self, output: str) -> str:
        """Remove the PTY echo because the widget already displays local input."""
        if self._pending_echo is None or not output:
            return output
        self._echo_buffer += output.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" not in self._echo_buffer:
            return ""
        first_line, remainder = self._echo_buffer.split("\n", 1)
        result = (
            self._without_extra_echo_newline(remainder)
            if first_line == self._pending_echo
            else self._echo_buffer
        )
        self._pending_echo = None
        self._echo_buffer = ""
        return result

    def _without_extra_echo_newline(self, output: str) -> str:
        """Drop one blank line left behind after filtering a PTY echo."""
        return output[1:] if output.startswith("\n") else output

    def _filter_sftp_echo(self, output: str) -> str:
        if self._sftp_pending_echo is None or not output:
            return output
        self._sftp_echo_buffer += output.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" not in self._sftp_echo_buffer:
            return ""
        first_line, remainder = self._sftp_echo_buffer.split("\n", 1)
        result = (
            self._without_extra_echo_newline(remainder)
            if first_line == self._sftp_pending_echo
            else self._sftp_echo_buffer
        )
        self._sftp_pending_echo = None
        self._sftp_echo_buffer = ""
        return result

    def _disconnect_ssh(self) -> None:
        self._shell_timer.stop()
        self._close_sftp_shell()
        self._close_shell()
        self._ssh_manager.disconnect()
        self._set_disconnected_state("Disconnected")

    def _close_shell(self) -> None:
        self._close_sftp_shell()
        if self._shell is not None:
            self._shell.close()
            self._shell = None
        self._sftp_session_active = False
        self._minicom_session_active = False
        self._leave_interactive_mode()
        self._set_sftp_actions_enabled(False)
        self.open_sftp_button.setEnabled(False)
        self.refresh_usb_button.setEnabled(False)
        self.open_minicom_button.setEnabled(False)
        self.close_minicom_button.setEnabled(False)
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button.setEnabled(False)

    def _close_local_process(self) -> None:
        """Close a local fallback process if one exists."""
        process = getattr(self, "_local_process", None)
        if process is None:
            return
        if process.state() != QProcess.ProcessState.NotRunning:
            process.kill()
            process.waitForFinished(1000)
        self._local_process = None

    def _close_sftp_shell(self) -> None:
        self._sftp_timer.stop()
        if self._sftp_shell is not None:
            self._sftp_shell.close()
            self._sftp_shell = None
        self._sftp_session_active = False
        self._active_sftp_settings = None
        self._sftp_pending_echo = None
        self._sftp_echo_buffer = ""
        self._sftp_prompt_buffer = ""
        self._set_sftp_actions_enabled(False)
        self.sftp_terminal.set_prompt(self._local_prompt())
        self.open_sftp_button.setEnabled(self._shell is not None and self._shell.is_open)

    def _show_sftp_error(self, error: Exception) -> None:
        message = str(error) or error.__class__.__name__
        self._append_sftp_output(f"SFTP error: {message}")
        self._close_sftp_shell()
        self.board_status_label.setText("MMU: SFTP failed")
        self.statusBar().showMessage("SFTP failed")

    def _handle_sftp_closed(self, message: str) -> None:
        self._append_sftp_output(message)
        self._close_sftp_shell()
        self.board_status_label.setText("MMU: SFTP closed")

    def _show_connection_error(self, error: Exception) -> None:
        self._shell_timer.stop()
        self._close_sftp_shell()
        self._close_shell()
        self._ssh_manager.disconnect()
        message = str(error) or error.__class__.__name__
        self.terminal_widget.write_output(f"SSH error: {message}")
        self._set_disconnected_state("Connection failed")

    def _handle_connection_closed(self, message: str) -> None:
        self._shell_timer.stop()
        self._close_sftp_shell()
        self._shell = None
        self._ssh_manager.disconnect()
        self.terminal_widget.write_output(message)
        self._set_disconnected_state("Connection closed")

    def _set_disconnected_state(self, status_message: str) -> None:
        self.terminal_widget.set_prompt(self._local_prompt())
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(False)
        self.open_sftp_button.setEnabled(False)
        self.refresh_usb_button.setEnabled(False)
        self.open_minicom_button.setEnabled(False)
        self.close_minicom_button.setEnabled(False)
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button.setEnabled(False)
        self._set_sftp_actions_enabled(False)
        self.connection_status_label.setText("SSH: disconnected")
        self.statusBar().showMessage(status_message)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Close SSH resources before the application exits."""
        self._closing = True
        self._save_settings()
        self._close_local_process()
        self._shell_timer.stop()
        self._close_sftp_shell()
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

    def _build_connection_buttons(self) -> QWidget:
        buttons = QWidget(self)
        layout = QHBoxLayout(buttons)
        layout.setContentsMargins(0, 0, 0, 0)

        self.connect_button = QPushButton("Connect", self)
        self.disconnect_button = QPushButton("Disconnect", self)
        self.disconnect_button.setEnabled(False)

        layout.addWidget(self.connect_button)
        layout.addWidget(self.disconnect_button)
        layout.addStretch(1)
        return buttons

    def _build_status_bar(self) -> QStatusBar:
        status_bar = QStatusBar(self)
        self.connection_status_label = QLabel("SSH: disconnected", self)
        self.board_status_label = QLabel("MMU: not configured", self)
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
        layout.setColumnStretch(1, 2)
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
        self.ssh_password_input.setEchoMode(QLineEdit.EchoMode.Normal)
        self.ssh_password_input.setPlaceholderText("Password")

        layout.addRow("Host", self.ssh_host_input)
        layout.addRow("Port", self.ssh_port_input)
        layout.addRow("User", self.ssh_username_input)
        layout.addRow("Password", self.ssh_password_input)
        layout.addRow(self._build_connection_buttons())
        return group

    def _build_board_group(self) -> QGroupBox:
        group = QGroupBox("MMU", self)
        layout = QFormLayout(group)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.board_ip_input = QLineEdit(self)
        self.board_ip_input.setPlaceholderText("MMU IP")
        self.board_username_input = QLineEdit(self)
        self.board_username_input.setPlaceholderText("Username")
        self.board_password_input = QLineEdit(self)
        self.board_password_input.setEchoMode(QLineEdit.EchoMode.Normal)
        self.board_password_input.setPlaceholderText("Password")
        self.board_interface_input = QLineEdit(self)
        self.board_interface_input.setPlaceholderText("Interface, e.g. eth0")
        self.board_ssh_port_input = QSpinBox(self)
        self.board_ssh_port_input.setRange(1, 65535)
        self.board_ssh_port_input.setValue(22)
        self.usb_port_combo = QComboBox(self)
        self.usb_port_combo.addItem("No USB ports detected")
        self.refresh_usb_button = QPushButton("Refresh USB", self)
        self.refresh_usb_button.setEnabled(False)
        self.open_minicom_button = QPushButton("Open Minicom", self)
        self.open_minicom_button.setEnabled(False)
        self.close_minicom_button = QPushButton("Close Minicom", self)
        self.close_minicom_button.setEnabled(False)
        self.mmu_ssh_connect_button = QPushButton("SSH Connect", self)
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button = QPushButton("SSH Disconnect", self)
        self.mmu_ssh_disconnect_button.setEnabled(False)

        usb_row = QWidget(self)
        usb_layout = QHBoxLayout(usb_row)
        usb_layout.setContentsMargins(0, 0, 0, 0)
        usb_layout.addWidget(self.usb_port_combo, stretch=1)
        usb_layout.addWidget(self.refresh_usb_button)

        layout.addRow("IP", self.board_ip_input)
        layout.addRow("User", self.board_username_input)
        layout.addRow("Password", self.board_password_input)
        layout.addRow("Interface", self.board_interface_input)
        layout.addRow("SSH Port", self.board_ssh_port_input)
        layout.addRow("USB Port", usb_row)
        minicom_row = QWidget(self)
        minicom_layout = QHBoxLayout(minicom_row)
        minicom_layout.setContentsMargins(0, 0, 0, 0)
        minicom_layout.addWidget(self.open_minicom_button)
        minicom_layout.addWidget(self.close_minicom_button)

        mmu_ssh_row = QWidget(self)
        mmu_ssh_layout = QHBoxLayout(mmu_ssh_row)
        mmu_ssh_layout.setContentsMargins(0, 0, 0, 0)
        mmu_ssh_layout.addWidget(self.mmu_ssh_connect_button)
        mmu_ssh_layout.addWidget(self.mmu_ssh_disconnect_button)

        console_row = QWidget(self)
        console_layout = QHBoxLayout(console_row)
        console_layout.setContentsMargins(0, 0, 0, 0)
        console_layout.addWidget(QLabel("Serial Console", self))
        console_layout.addWidget(minicom_row, stretch=1)
        console_layout.addSpacing(12)
        console_layout.addWidget(QLabel("SSH Console", self))
        console_layout.addWidget(mmu_ssh_row, stretch=1)
        layout.addRow(console_row)
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
        self.terminal_widget = TerminalWidget(prompt=self._local_prompt())
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
        self.close_sftp_button = QPushButton("Close SFTP", self)
        self.close_sftp_button.setEnabled(False)
        action_layout.addWidget(self.close_sftp_button)
        action_layout.addStretch(1)

        self.server_path_input = FileDropLineEdit(self)
        self.server_path_input.hide()
        self.server_path_input.setPlaceholderText(
            "Drag a local PC file here or enter a Linux server path manually."
        )
        self.server_path_input.setToolTip(
            "SFTP uses a path on the SSH Linux server. Drag and drop only helps fill a "
            "local PC file path; use it when that same path is accessible from the server, "
            "or enter the server path manually."
        )
        self.board_path_input = QLineEdit(self)
        self.board_path_input.hide()
        self.board_path_input.setPlaceholderText("Example: /tmp/firmware.bin")
        self.board_path_input.setToolTip("A source or destination path on the connected MMU.")

        file_lists = QWidget(self)
        file_list_layout = QHBoxLayout(file_lists)
        file_list_layout.setContentsMargins(0, 0, 0, 0)
        server_column = QWidget(self)
        server_layout = QVBoxLayout(server_column)
        server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_file_list = SftpFileListWidget("server", self)
        self.server_file_list.setToolTip("Linux server files. Drag a file to the MMU list to upload it.")
        server_layout.addWidget(QLabel("Linux server files", self))
        server_layout.addWidget(self.server_file_list)
        mmu_column = QWidget(self)
        mmu_layout = QVBoxLayout(mmu_column)
        mmu_layout.setContentsMargins(0, 0, 0, 0)
        self.mmu_file_list = SftpFileListWidget("mmu", self)
        self.mmu_file_list.setToolTip("MMU files. Drag a file to the Linux server list to download it.")
        mmu_layout.addWidget(QLabel("MMU files", self))
        mmu_layout.addWidget(self.mmu_file_list)
        file_list_layout.addWidget(server_column)
        file_list_layout.addWidget(mmu_column)

        transfer_buttons = QWidget(self)
        transfer_button_layout = QHBoxLayout(transfer_buttons)
        transfer_button_layout.setContentsMargins(0, 0, 0, 0)
        self.upload_sftp_button = QPushButton("Upload to MMU", self)
        self.download_sftp_button = QPushButton("Download to Server", self)
        self.upload_sftp_button.setEnabled(False)
        self.download_sftp_button.setEnabled(False)
        transfer_button_layout.addWidget(self.upload_sftp_button)
        transfer_button_layout.addWidget(self.download_sftp_button)
        transfer_button_layout.addStretch(1)

        path_help = QLabel(
            "Drag a file from Linux server files to MMU files to upload, or drag a file "
            "from MMU files to Linux server files to download. Double-click a directory "
            "to browse into it.",
            self,
        )
        path_help.setWordWrap(True)

        self.sftp_terminal = TerminalWidget(prompt=self._local_prompt())
        self.sftp_terminal.setPlaceholderText("The independent SFTP terminal appears here.")
        self.sftp_output = self.sftp_terminal

        layout.addWidget(transfer_actions)
        layout.addWidget(path_help)
        layout.addWidget(file_lists, stretch=1)
        layout.addWidget(transfer_buttons)
        layout.addWidget(self.sftp_terminal, stretch=1)
        return tab
