"""Main application window."""

from __future__ import annotations

import json
import os
import posixpath
import re
import shlex
import subprocess
import time
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QProcess, QRegularExpression, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QDrag,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QPainter,
    QPixmap,
    QKeyEvent,
    QRegularExpressionValidator,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QInputDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressDialog,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mmu_control.core.config_manager import ConfigError, ConfigManager
from mmu_control.core.automation_runner import AutomationRunner, AutomationStatus
from mmu_control.core.automation_terminal import AutomationTerminal, AutomationTerminalCapability
from mmu_control.core.interactive_shell import InteractiveShell
from mmu_control.core.minicom_manager import MinicomError, MinicomManager
from mmu_control.core.power_supply_manager import PowerSupplyCommandError, PowerSupplyManager
from mmu_control.core.sftp_manager import SFTPError, SFTPManager
from mmu_control.core.ssh_manager import SSHManager
from mmu_control.core.terminal_sequences import TerminalStreamFilter
from mmu_control.models.command_set import CommandFolder, CommandSet
from mmu_control.models.automation import AutomationScenario
from mmu_control.models.settings import (
    AppSettings,
    BoardSettings,
    PowerSupplySettings,
    SSHSettings,
    WindowSettings,
)
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.storage.automation_store import AutomationStore
from mmu_control.ui.background_worker import TaskRunner, ThreadPoolTaskRunner
from mmu_control.ui.command_editor_dialog import CommandEditorDialog
from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog
from mmu_control.ui.automation_import_dialog import AutomationImportDialog
from mmu_control.ui.terminal_widget import TerminalWidget


@dataclass(frozen=True)
class SftpListEntry:
    """Entry shown in an SFTP file list."""

    is_dir: bool
    name: str
    path: str
    is_link: bool = False
    link_target: str | None = None
    navigate_path: str | None = None

    @classmethod
    def from_tuple(cls, entry: tuple[bool, str, str]) -> "SftpListEntry":
        is_dir, name, path = entry
        return cls(is_dir=is_dir, name=name, path=path)


@dataclass(frozen=True)
class AutomationProgressSnapshot:
    """The most recently observed execution state for one scenario."""

    status: AutomationStatus
    skipped_step_indices: frozenset[int]
    start_step_index: int
    terminal_display_name: str = ""


@dataclass(frozen=True)
class _ShellAutomationTerminal:
    """Adapt the application's interactive shell to the automation contract."""

    shell: InteractiveShell
    name: str
    recent_output: str

    @property
    def is_open(self) -> bool:
        return self.shell.is_open

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def capabilities(self) -> frozenset[AutomationTerminalCapability]:
        return frozenset({AutomationTerminalCapability.REMOTE_FILE_CHECKS})

    def send_line(self, command: str) -> None:
        self.shell.send_line(command)

    def read_recent_output(self) -> str:
        return self.recent_output


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
    fileDropped = Signal(str, list, str)
    deleteRequested = Signal(str, list)

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.side = side
        self.current_directory = "/tmp"
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def resizeEvent(self, event) -> None:  # noqa: N802, ANN001
        """Keep scroll bars matched to the visible file-list viewport."""
        super().resizeEvent(event)
        self.update_scroll_bars()

    def showEvent(self, event) -> None:  # noqa: N802, ANN001
        """Refresh scroll bars when the list first receives a real viewport size."""
        super().showEvent(event)
        self.update_scroll_bars()

    def update_scroll_bars(self) -> None:
        """Show scroll bars only when file entries exceed the current list area."""
        viewport_size = self.viewport().size()
        if viewport_size.isEmpty():
            return

        content_height = sum(max(self.sizeHintForRow(row), 0) for row in range(self.count()))
        vertical_needed = content_height > viewport_size.height()
        vertical_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if vertical_needed
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if self.verticalScrollBarPolicy() != vertical_policy:
            self.setVerticalScrollBarPolicy(vertical_policy)

        available_width = viewport_size.width()
        if vertical_needed:
            available_width -= self.verticalScrollBar().sizeHint().width()
        max_content_width = max(
            (self.sizeHintForColumn(column) for column in range(self.model().columnCount())),
            default=0,
        )
        horizontal_needed = max_content_width > available_width
        horizontal_policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if horizontal_needed
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if self.horizontalScrollBarPolicy() != horizontal_policy:
            self.setHorizontalScrollBarPolicy(horizontal_policy)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # noqa: N802
        selected_paths = self._selected_file_paths()
        if not selected_paths:
            return
        payload = json.dumps({"side": self.side, "paths": selected_paths}).encode("utf-8")
        mime_data = QMimeData()
        mime_data.setData(self.FILE_MIME_TYPE, QByteArray(payload))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        pixmap = self._drag_pixmap(selected_paths)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, pixmap.height() // 2))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        try:
            drag.exec(supported_actions, Qt.DropAction.CopyAction)
        finally:
            self.unsetCursor()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Request deletion for selected file rows when Delete is pressed."""
        if event.key() in {Qt.Key.Key_Delete, Qt.Key.Key_Backspace}:
            selected_paths = self._selected_file_paths()
            if selected_paths:
                self.deleteRequested.emit(self.side, selected_paths)
                event.accept()
                return
        super().keyPressEvent(event)

    def _selected_file_paths(self) -> list[str]:
        paths: list[str] = []
        for item in self.selectedItems():
            path = item.data(Qt.ItemDataRole.UserRole)
            is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 1))
            if isinstance(path, str) and path and not is_dir:
                paths.append(path)
        return paths

    def _drag_pixmap(self, paths: list[str]) -> QPixmap:
        """Build a visible drag badge so transfers feel like grabbing files."""
        text = posixpath.basename(paths[0]) if len(paths) == 1 else f"{len(paths)} files"
        metrics = self.fontMetrics()
        width = min(max(metrics.horizontalAdvance(text) + 28, 140), 360)
        height = max(metrics.height() + 14, 34)
        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(50, 115, 220, 210))
        painter.setPen(QColor(30, 70, 150))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 8, 8)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(12, 0, width - 24, height, Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()
        return pixmap

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
        source_side, source_paths = data
        target_directory = self._drop_target_directory(event)
        self.fileDropped.emit(source_side, source_paths, target_directory)
        event.acceptProposedAction()

    def _accepted_transfer(self, mime_data: QMimeData) -> bool:
        data = self._transfer_data(mime_data)
        return data is not None and data[0] != self.side

    def _transfer_data(self, mime_data: QMimeData) -> tuple[str, list[str]] | None:
        if not mime_data.hasFormat(self.FILE_MIME_TYPE):
            return None
        try:
            payload = json.loads(bytes(mime_data.data(self.FILE_MIME_TYPE)).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        side = payload.get("side")
        paths = payload.get("paths")
        if paths is None:
            path = payload.get("path")
            paths = [path] if isinstance(path, str) else []
        if not isinstance(paths, list):
            return None
        clean_paths = [path for path in paths if isinstance(path, str) and path]
        if side not in {"server", "mmu"} or not clean_paths:
            return None
        return side, clean_paths

    def _drop_target_directory(self, event: QDropEvent) -> str:
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return self.current_directory
        path = item.data(Qt.ItemDataRole.UserRole)
        is_dir = item.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(path, str) and bool(is_dir):
            return path
        return self.current_directory


class CommandSetTreeWidget(QTreeWidget):
    """Command-set tree that persists drops onto command folders."""

    COMMAND_SET_MIME_TYPE = "application/x-mmu-control-command-set"
    commandSetDropped = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def startDrag(self, supported_actions: Qt.DropActions) -> None:  # noqa: N802
        item = self.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(data, tuple) or data[0] != "group":
            return
        mime_data = QMimeData()
        mime_data.setData(self.COMMAND_SET_MIME_TYPE, QByteArray(data[1].encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(supported_actions, Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasFormat(self.COMMAND_SET_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802
        if event.mimeData().hasFormat(self.COMMAND_SET_MIME_TYPE):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(self.COMMAND_SET_MIME_TYPE):
            super().dropEvent(event)
            return
        name = bytes(event.mimeData().data(self.COMMAND_SET_MIME_TYPE)).decode("utf-8")
        target = self.itemAt(event.position().toPoint())
        target_data = target.data(0, Qt.ItemDataRole.UserRole) if target else None
        parent_path = target_data[1] if isinstance(target_data, tuple) and target_data[0] == "folder" else ""
        self.commandSetDropped.emit(name, parent_path)
        event.acceptProposedAction()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Keep saved-command selection accessible with the Up and Down keys."""
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            super().keyPressEvent(event)
            event.accept()
            return
        super().keyPressEvent(event)


class MainWindow(QMainWindow):
    """Primary window for the MMU control application."""

    AUTOMATION_OUTPUT_LIMIT = AutomationRunner.OUTPUT_LIMIT
    MMU_SSH_AUTH_TIMEOUT_MS = 3000

    def __init__(
        self,
        ssh_manager: SSHManager | None = None,
        command_set_store: CommandSetStore | None = None,
        automation_store: AutomationStore | None = None,
        config_manager: ConfigManager | None = None,
        task_runner: TaskRunner | None = None,
    ) -> None:
        super().__init__()
        self._ssh_manager = ssh_manager or SSHManager()
        self._command_set_store = command_set_store or CommandSetStore.create_default()
        self._automation_store = automation_store or AutomationStore.create_default()
        self._config_manager = config_manager or ConfigManager.create_default()
        self._task_runner = task_runner or ThreadPoolTaskRunner(self)
        self._sftp_manager = SFTPManager()
        self._minicom_manager = MinicomManager()
        self._power_supply_manager = PowerSupplyManager()
        self._settings = AppSettings()
        self._command_sets: dict[str, CommandSet] = {}
        self._command_folders: dict[str, CommandFolder] = {}
        self._automation_scenarios: dict[str, AutomationScenario] = {}
        self._automation_runner: AutomationRunner | None = None
        self._automation_terminal: AutomationTerminal | None = None
        self._automation_progress: dict[str, AutomationProgressSnapshot] = {}
        self._automation_file_check_due = 0.0
        self._shell: InteractiveShell | None = None
        self._sftp_shell: InteractiveShell | None = None
        self._pending_echo: str | None = None
        self._echo_buffer = ""
        self._automation_output_filter = TerminalStreamFilter()
        self._recent_automation_output = ""
        self._sftp_pending_echo: str | None = None
        self._sftp_pending_listing = False
        self._sftp_pending_pwd: str | None = None
        self._sftp_echo_buffer = ""
        self._sftp_prompt_buffer = ""
        self._sftp_startup_pending = False
        self._sftp_transfer_progress_dialog: QProgressDialog | None = None
        self._sftp_transfer_refresh_target: str | None = None
        self._sftp_transfer_seen_progress = False
        self._active_sftp_settings: BoardSettings | None = None
        self._sftp_session_active = False
        self._minicom_session_active = False
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self._local_process: QProcess | None = None
        self._interactive_program = ""
        self._local_cwd = os.getcwd()
        self._server_sftp_directory = os.path.expanduser("~")
        self._mmu_sftp_directory = "/tmp"
        self._closing = False
        self.setWindowTitle("MMU Control")
        # Reserve enough room for the terminal, command list, and response
        # output.  The default width is 15% larger than the previous layout.
        self.resize(1840, 900)
        self.setMinimumSize(1196, 560)
        self.setCentralWidget(self._build_central_widget())
        self.setStatusBar(self._build_status_bar())
        self._shell_timer = QTimer(self)
        self._shell_timer.setInterval(50)
        self._shell_timer.timeout.connect(self._poll_shell)
        self._sftp_timer = QTimer(self)
        self._sftp_timer.setInterval(50)
        self._sftp_timer.timeout.connect(self._poll_sftp_shell)
        self._sftp_startup_timeout_timer = QTimer(self)
        self._sftp_startup_timeout_timer.setSingleShot(True)
        self._sftp_startup_timeout_timer.setInterval(3000)
        self._sftp_startup_timeout_timer.timeout.connect(self._handle_sftp_startup_timeout)
        self._mmu_ssh_auth_timeout_timer = QTimer(self)
        self._mmu_ssh_auth_timeout_timer.setSingleShot(True)
        self._mmu_ssh_auth_timeout_timer.setInterval(self.MMU_SSH_AUTH_TIMEOUT_MS)
        self._mmu_ssh_auth_timeout_timer.timeout.connect(self._handle_mmu_ssh_auth_timeout)
        self._automation_timer = QTimer(self)
        self._automation_timer.setInterval(100)
        self._automation_timer.timeout.connect(self._poll_automation)
        self._wire_events()
        self._load_command_sets()
        self._load_automation_scenarios()
        self._load_settings()

    def _wire_events(self) -> None:
        self.connect_button.clicked.connect(self._connect_ssh)
        self.disconnect_button.clicked.connect(self._disconnect_ssh)
        self.terminal_widget.commandSubmitted.connect(self._send_terminal_command)
        self.terminal_widget.rawInput.connect(self._send_terminal_raw)
        self.new_command_button.clicked.connect(self._create_command_set)
        self.new_folder_button.clicked.connect(self._create_command_folder)
        self.edit_command_button.clicked.connect(self._edit_command_set)
        self.delete_command_button.clicked.connect(self._delete_command_set)
        self.run_command_set_button.clicked.connect(self._run_command_set)
        self.new_automation_button.clicked.connect(self._create_automation_scenario)
        self.import_automation_button.clicked.connect(self._import_automation_scenario)
        self.copy_automation_button.clicked.connect(self._copy_automation_scenario)
        self.edit_automation_button.clicked.connect(self._edit_automation_scenario)
        self.delete_automation_button.clicked.connect(self._delete_automation_scenario)
        self.run_automation_button.clicked.connect(self._run_automation_scenario)
        self.stop_automation_button.clicked.connect(self._stop_automation)
        self.automation_list.currentItemChanged.connect(self._show_selected_automation_scenario)
        self.open_sftp_button.clicked.connect(self._open_sftp)
        self.close_sftp_button.clicked.connect(self._close_sftp_session)
        self.server_path_input.localFileDropped.connect(self._handle_sftp_file_drop)
        self.server_file_list.fileDropped.connect(self._handle_sftp_list_drop)
        self.mmu_file_list.fileDropped.connect(self._handle_sftp_list_drop)
        self.server_file_list.deleteRequested.connect(self._delete_sftp_files)
        self.mmu_file_list.deleteRequested.connect(self._delete_sftp_files)
        self.server_file_list.itemDoubleClicked.connect(self._open_server_list_item)
        self.mmu_file_list.itemDoubleClicked.connect(self._open_mmu_list_item)
        self.refresh_server_file_list_button.clicked.connect(self._refresh_server_file_list)
        self.refresh_mmu_file_list_button.clicked.connect(self._refresh_mmu_file_list)
        self.refresh_usb_button.clicked.connect(self._refresh_usb_ports)
        self.open_minicom_button.clicked.connect(self._open_minicom)
        self.close_minicom_button.clicked.connect(self._close_minicom)
        self.mmu_ssh_connect_button.clicked.connect(self._connect_mmu_ssh)
        self.mmu_ssh_disconnect_button.clicked.connect(self._disconnect_mmu_ssh)
        self.usb_port_combo.currentTextChanged.connect(self._update_minicom_button)
        self.command_set_list.currentItemChanged.connect(self._show_selected_command_set)
        self.command_set_list.commandSetDropped.connect(self._move_command_set)
        self.power_on_button.clicked.connect(lambda: self._run_power_supply_command("on"))
        self.power_off_button.clicked.connect(lambda: self._run_power_supply_command("off"))
        self.power_status_button.clicked.connect(lambda: self._run_power_supply_command("status"))
        self.power_all_status_button.clicked.connect(lambda: self._run_power_supply_command("all_status"))
        self.power_set_button.clicked.connect(lambda: self._run_power_supply_command("set"))

    def _ssh_settings(self) -> SSHSettings:
        return SSHSettings(
            host=self.ssh_host_input.text().strip(),
            port=self.ssh_port_input.value(),
            username=self.ssh_username_input.text().strip(),
            password=self.ssh_password_input.text(),
        )

    def _power_supply_settings(self) -> PowerSupplySettings:
        return PowerSupplySettings(
            ip_address=self.power_supply_ip_input.text().strip(),
            voltage=self.power_supply_voltage_input.text().strip(),
            current=self.power_supply_current_input.text().strip(),
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

    def _run_power_supply_command(self, action: str) -> None:
        settings = self._power_supply_settings()
        self._power_supply_manager.update_settings(settings)
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Not connected to an SSH shell.")
            return
        try:
            command = self._power_supply_manager.build_command(action)
            self._shell.send_line(command)
        except PowerSupplyCommandError as exc:
            self.terminal_widget.write_output(f"Power Supply error: {exc}")
            return
        self.statusBar().showMessage(f"Power Supply command sent: {command}")

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
        self.ssh_group.setChecked(settings.window.ssh_group_expanded)
        self.mmu_group.setChecked(settings.window.mmu_group_expanded)
        self.ssh_host_input.setText(settings.ssh.host)
        self.ssh_port_input.setValue(settings.ssh.port)
        self.ssh_username_input.setText(settings.ssh.username)
        self.ssh_password_input.setText(settings.ssh.password)
        self.power_supply_ip_input.setText(settings.power_supply.ip_address)
        self.power_supply_voltage_input.setText(settings.power_supply.voltage)
        self.power_supply_current_input.setText(settings.power_supply.current)
        self._power_supply_manager.update_settings(settings.power_supply)
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
        self._settings.power_supply = self._power_supply_settings()
        self._power_supply_manager.update_settings(self._settings.power_supply)
        self._settings.window = WindowSettings(
            width=geometry.width(),
            height=geometry.height(),
            is_maximized=self.isMaximized(),
            ssh_group_expanded=self.ssh_group.isChecked(),
            mmu_group_expanded=self.mmu_group.isChecked(),
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
        self._automation_output_filter.reset()
        self._recent_automation_output = ""
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
        self._set_server_sftp_directory_to_home()
        self._poll_shell()

    def _set_server_sftp_directory_to_home(self) -> None:
        """Use the Linux server user home directory as the server file-list root."""
        try:
            home = self._ssh_manager.execute_command("printf '%s\n' \"$HOME\"").strip().splitlines()[0]
        except Exception:
            return
        if home.startswith("/"):
            self._server_sftp_directory = home
            self.server_file_list.current_directory = home
            self.server_current_path_input.setText(home)

    def _send_terminal_command(self, command: str) -> None:
        if self._shell is None or not self._shell.is_open:
            self._run_local_terminal_command(command)
            return
        if command.strip().lower() in {"clear", "cls"}:
            self.terminal_widget.clear_terminal()
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
        self._sftp_session_active = False
        self._sftp_startup_pending = True
        self._sftp_pending_echo = command
        self._sftp_echo_buffer = ""
        self._sftp_pending_listing = False
        self._sftp_prompt_buffer = ""
        self._append_sftp_output("SFTP session opening. Waiting for the remote sftp prompt...")
        self._sftp_timer.start()
        self._sftp_startup_timeout_timer.start()
        self._set_sftp_actions_enabled(False)
        self.board_status_label.setText("MMU: SFTP opening")
        self.statusBar().showMessage("Opening SFTP session...")
        self._poll_sftp_shell()
        self._poll_sftp_shell()

    def _handle_sftp_list_drop(
        self, source_side: str, source_paths: list[str] | str, target_directory: str
    ) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
            self._append_sftp_output("Open an SFTP session first.")
            return
        paths = [source_paths] if isinstance(source_paths, str) else source_paths
        commands: list[str] = []
        try:
            for source_path in paths:
                destination = posixpath.join(target_directory, posixpath.basename(source_path))
                if source_side == "server":
                    command = self._sftp_manager.upload(self._sftp_shell, source_path, destination)
                else:
                    command = self._sftp_manager.download(self._sftp_shell, source_path, destination)
                commands.append(command)
        except SFTPError as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            return
        self._sftp_pending_echo = commands[-1] if commands else None
        self._sftp_echo_buffer = ""
        file_count = len(commands)
        action = "Uploading to MMU" if source_side == "server" else "Downloading to server"
        if file_count > 1:
            action = f"{action} ({file_count} files)"
        self._start_sftp_transfer_progress(
            action,
            "mmu" if source_side == "server" else "server",
        )
        for command in commands:
            self._append_sftp_output(f"Running: {command}")
        self.statusBar().showMessage("SFTP drag-and-drop transfer started")

    def _delete_sftp_files(self, side: str, paths: list[str]) -> None:
        if not paths:
            return
        file_word = "file" if len(paths) == 1 else "files"
        result = QMessageBox.question(
            self,
            "Delete SFTP Files",
            f"Delete {len(paths)} selected {file_word}?",
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            if side == "mmu":
                if self._sftp_shell is None or not self._sftp_shell.is_open or not self._sftp_session_active:
                    raise SFTPError("Open an SFTP session first.")
                commands = [self._sftp_manager.remove(self._sftp_shell, path) for path in paths]
                self._sftp_pending_echo = commands[-1] if commands else None
                self._sftp_echo_buffer = ""
                self._refresh_mmu_file_list()
            elif side == "server":
                command = "rm -f -- " + " ".join(shlex.quote(path) for path in paths)
                self._ssh_manager.execute_command(command)
                self._refresh_server_file_list()
            else:
                raise SFTPError("Unknown SFTP file list.")
        except Exception as exc:
            self._append_sftp_output(f"SFTP error: {exc}")
            return
        self._append_sftp_output(f"Deleted {len(paths)} selected {file_word}.")
        self.statusBar().showMessage("SFTP delete completed")

    def _start_sftp_transfer_progress(self, title: str, refresh_target: str) -> None:
        """Show transfer progress and remember which file list to refresh when done."""
        self._close_sftp_transfer_progress()
        dialog = QProgressDialog("Transfer progress: 0%", "", 0, 100, self)
        dialog.setCancelButton(None)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumDuration(0)
        dialog.setValue(0)
        dialog.show()
        self._sftp_transfer_progress_dialog = dialog
        self._sftp_transfer_refresh_target = refresh_target
        self._sftp_transfer_seen_progress = False

    def _update_sftp_transfer_progress(self, output: str) -> None:
        """Update and close the drag-and-drop transfer progress popup from SFTP output."""
        if self._sftp_transfer_progress_dialog is None:
            return
        percentages = [min(int(match), 100) for match in re.findall(r"(?<!\d)(\d{1,3})%", output)]
        if percentages:
            percent = max(percentages)
            self._sftp_transfer_seen_progress = True
            self._sftp_transfer_progress_dialog.setLabelText(f"Transfer progress: {percent}%")
            self._sftp_transfer_progress_dialog.setValue(percent)
        if "sftp>" in output and (self._sftp_transfer_seen_progress or not percentages):
            self._finish_sftp_transfer_progress()

    def _finish_sftp_transfer_progress(self) -> None:
        """Close the progress popup and refresh the side that received the file."""
        refresh_target = self._sftp_transfer_refresh_target
        if self._sftp_transfer_progress_dialog is not None:
            self._sftp_transfer_progress_dialog.setValue(100)
            self._close_sftp_transfer_progress()
        if refresh_target == "server":
            self._refresh_server_file_list()
        elif refresh_target == "mmu":
            self._refresh_mmu_file_list()

    def _close_sftp_transfer_progress(self) -> None:
        """Close and forget any active SFTP transfer progress popup."""
        if self._sftp_transfer_progress_dialog is not None:
            self._sftp_transfer_progress_dialog.close()
            self._sftp_transfer_progress_dialog.deleteLater()
        self._sftp_transfer_progress_dialog = None
        self._sftp_transfer_refresh_target = None
        self._sftp_transfer_seen_progress = False

    def _refresh_sftp_file_lists(self) -> None:
        self._refresh_server_file_list()
        self._refresh_mmu_file_list()

    def _refresh_server_file_list(self) -> None:
        self.server_file_list.current_directory = self._server_sftp_directory
        self.server_current_path_input.setText(self._server_sftp_directory)
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
        self.mmu_current_path_input.setText(self._mmu_sftp_directory)
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            self._populate_file_list(self.mmu_file_list, [])
            return
        command = f"ls -la {shlex.quote(self._mmu_sftp_directory)}"
        self._sftp_shell.send_line(command)
        self._sftp_pending_echo = command
        self._sftp_pending_listing = True
        self._sftp_echo_buffer = ""
        self._append_sftp_output(f"Listing MMU files: {command}")
        self._populate_file_list(self.mmu_file_list, [])

    def _parse_find_listing(self, output: str) -> list[SftpListEntry]:
        entries: list[SftpListEntry] = []
        for line in output.splitlines():
            if "\t" not in line:
                continue
            kind, path = line.split("\t", 1)
            entries.append(SftpListEntry(kind == "d", posixpath.basename(path.rstrip("/")), path))
        return entries

    def _parse_sftp_listing(self, output: str) -> list[SftpListEntry]:
        entries: list[SftpListEntry] = []
        for line in output.splitlines():
            line = self._normalize_sftp_listing_line(line)
            if not line:
                continue
            parts = line.split(maxsplit=8)
            if len(parts) < 9 or not parts[0] or parts[0][0] not in "-dl":
                continue
            raw_name = parts[8]
            is_link = parts[0].startswith("l")
            name, link_target = self._split_sftp_link_name(raw_name) if is_link else (raw_name, None)
            if name == ".":
                continue
            is_dir = parts[0].startswith("d")
            path = (
                posixpath.dirname(self._mmu_sftp_directory.rstrip("/")) or "/"
                if name == ".."
                else posixpath.join(self._mmu_sftp_directory, name)
            )
            navigate_path = self._sftp_link_navigation_path(path, link_target) if is_link else path
            if is_link:
                is_dir = bool(link_target)
            entries.append(SftpListEntry(is_dir, name, path, is_link, link_target, navigate_path))
        return entries


    def _normalize_sftp_listing_line(self, line: str) -> str:
        """Return a clean long-format SFTP listing row, without prompts or echoes."""
        line = line.strip()
        if not line or line.startswith("Listing MMU files:"):
            return ""
        if line.startswith("sftp>"):
            line = line.removeprefix("sftp>").strip()
        if line.startswith(("ls ", "dir ")):
            return ""
        return line

    def _split_sftp_link_name(self, raw_name: str) -> tuple[str, str | None]:
        name, separator, target = raw_name.partition(" -> ")
        if not separator:
            return raw_name, None
        return name, target or None

    def _sftp_link_navigation_path(self, link_path: str, link_target: str | None) -> str:
        if not link_target:
            return link_path
        if link_target.startswith("/"):
            return posixpath.normpath(link_target)
        return posixpath.normpath(posixpath.join(posixpath.dirname(link_path), link_target))

    def _sftp_link_points_to_directory(self, link_path: str) -> bool:
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            return False
        try:
            self._sftp_shell.send_line(f"ls -ldL {shlex.quote(link_path)}")
        except Exception:
            try:
                self._sftp_shell.send_line(f"cd {shlex.quote(link_path)}")
            except Exception:
                return False
        return True

    def _coerce_file_entry(self, entry: SftpListEntry | tuple[bool, str, str]) -> SftpListEntry:
        if isinstance(entry, SftpListEntry):
            return entry
        return SftpListEntry.from_tuple(entry)

    def _populate_file_list(
        self,
        file_list: SftpFileListWidget,
        entries: list[SftpListEntry | tuple[bool, str, str]],
    ) -> None:
        file_list.clear()
        coerced_entries = [self._coerce_file_entry(entry) for entry in entries]
        if not any(entry.name == ".." for entry in coerced_entries):
            parent = posixpath.dirname(file_list.current_directory.rstrip("/")) or "/"
            parent_item = QListWidgetItem("../")
            parent_item.setData(Qt.ItemDataRole.UserRole, parent)
            parent_item.setData(Qt.ItemDataRole.UserRole + 1, True)
            parent_item.setData(Qt.ItemDataRole.UserRole + 2, False)
            parent_item.setData(Qt.ItemDataRole.UserRole + 3, None)
            parent_item.setData(Qt.ItemDataRole.UserRole + 4, parent)
            file_list.addItem(parent_item)
        sorted_entries = sorted(
            coerced_entries,
            key=lambda entry: (entry.name != "..", not entry.is_dir, entry.name.lower()),
        )
        for entry in sorted_entries:
            if not entry.name or not entry.path:
                item = QListWidgetItem(entry.name)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            else:
                item = QListWidgetItem(f"{entry.name}/" if entry.is_dir else entry.name)
                item.setData(Qt.ItemDataRole.UserRole, entry.path)
                item.setData(Qt.ItemDataRole.UserRole + 1, entry.is_dir)
                item.setData(Qt.ItemDataRole.UserRole + 2, entry.is_link)
                item.setData(Qt.ItemDataRole.UserRole + 3, entry.link_target)
                item.setData(Qt.ItemDataRole.UserRole + 4, entry.navigate_path or entry.path)
            file_list.addItem(item)
        file_list.update_scroll_bars()

    def _open_server_list_item(self, item: QListWidgetItem) -> None:
        self._open_sftp_list_item(self.server_file_list, item)

    def _open_mmu_list_item(self, item: QListWidgetItem) -> None:
        self._open_sftp_list_item(self.mmu_file_list, item)

    def _open_sftp_list_item(self, file_list: SftpFileListWidget, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        navigate_path = item.data(Qt.ItemDataRole.UserRole + 4)
        is_dir = bool(item.data(Qt.ItemDataRole.UserRole + 1))
        is_link = bool(item.data(Qt.ItemDataRole.UserRole + 2))
        if not isinstance(path, str) or (not is_dir and not is_link):
            return
        if file_list.side == "mmu" and is_link:
            self._sftp_link_points_to_directory(path)
        destination = navigate_path if isinstance(navigate_path, str) and navigate_path else path
        if file_list.side == "server":
            self._change_sftp_directory("lcd", destination, send_command=True)
        else:
            self._change_sftp_directory("cd", destination, send_command=True)

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
        self._start_sftp_transfer_progress("Uploading to MMU", "mmu")
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
        if command.strip():
            self._echo_sftp_command(command)
        if self._handle_sftp_directory_command(command):
            return
        if self._handle_sftp_listing_command(command):
            return
        if self._handle_sftp_pwd_command(command):
            return
        try:
            self._sftp_shell.send_line(command)
            self._sftp_pending_echo = command
            self._sftp_echo_buffer = ""
        except Exception as exc:
            self._show_sftp_error(exc)

    def _echo_sftp_command(self, command: str) -> None:
        """Ensure programmatically submitted SFTP commands are visible once."""
        prompt = self.terminal_widget._prompt
        text = self.terminal_widget.toPlainText()
        if text.endswith(f"{prompt}{command}\n{prompt}"):
            return
        self.terminal_widget.write_stream(f"{prompt}{command}\r\n")

    def _run_sftp_local_command(self, command: str) -> None:
        """Run fallback commands in the SFTP pane without touching the Terminal tab."""
        command = command.strip()
        if not command:
            return
        if command.lower() in {"clear", "cls"}:
            self.terminal_widget.clear_terminal()
            return
        if command.lower() in {"pwd", "cd"}:
            self._append_sftp_output(self._local_cwd)
            return
        if command.lower().startswith("cd "):
            self._change_sftp_fallback_local_directory(command[3:].strip())
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
            self._append_sftp_output(str(exc))
            return
        output = f"{result.stdout}{result.stderr}"
        if output:
            self._append_sftp_output(output)
        self.terminal_widget.set_prompt(self._local_prompt())

    def _change_sftp_fallback_local_directory(self, path_text: str) -> None:
        if not path_text:
            self._append_sftp_output(self._local_cwd)
            return
        try:
            parts = shlex.split(path_text)
        except ValueError as exc:
            self._append_sftp_output(str(exc))
            return
        target_text = " ".join(parts) if parts else path_text
        target = os.path.expanduser(os.path.expandvars(target_text))
        if not os.path.isabs(target):
            target = os.path.join(self._local_cwd, target)
        target = os.path.abspath(target)
        if not os.path.isdir(target):
            self._append_sftp_output(f"cd: no such directory: {target_text}")
            return
        self._local_cwd = target

    def _handle_sftp_directory_command(self, command: str) -> bool:
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if not parts or parts[0] not in {"cd", "lcd"}:
            return False
        target = parts[1] if len(parts) > 1 else ""
        self._change_sftp_directory(parts[0], target, send_command=True)
        return True

    def _handle_sftp_listing_command(self, command: str) -> bool:
        try:
            parts = shlex.split(command)
        except ValueError:
            return False
        if not parts or parts[0] not in {"ls", "dir"}:
            return False
        target = (
            parts[-1]
            if len(parts) > 1 and not parts[-1].startswith("-")
            else self._mmu_sftp_directory
        )
        self._mmu_sftp_directory = self._resolve_sftp_path(self._mmu_sftp_directory, target)
        self._refresh_mmu_file_list()
        return True

    def _handle_sftp_pwd_command(self, command: str) -> bool:
        normalized = command.strip().lower()
        if normalized not in {"pwd", "lpwd"}:
            return False
        if normalized == "lpwd":
            self._append_sftp_output(f"Local working directory: {self._server_sftp_directory}")
            return True
        try:
            self._sftp_shell.send_line("pwd")
            self._sftp_pending_echo = "pwd"
            self._sftp_pending_pwd = "pwd"
            self._sftp_echo_buffer = ""
        except Exception as exc:
            self._show_sftp_error(exc)
        return True

    def _handle_sftp_pwd_output(self, output: str) -> bool:
        path = self._extract_sftp_pwd_path(output)
        if path is None:
            return False
        self._mmu_sftp_directory = path
        self.mmu_file_list.current_directory = path
        self.mmu_current_path_input.setText(path)
        self._refresh_mmu_file_list()
        return True

    def _extract_sftp_pwd_path(self, output: str) -> str | None:
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith("sftp>"):
                continue
            path = self._path_from_sftp_pwd_line(line)
            if path is not None:
                return path
        return None

    def _path_from_sftp_pwd_line(self, line: str) -> str | None:
        if ":" in line:
            label, path = line.split(":", 1)
            if "remote working directory" not in label.lower():
                return None
        else:
            path = line
        path = path.strip().strip('"')
        return posixpath.normpath(path) if path.startswith("/") else None

    def _change_sftp_directory(self, command: str, target: str, send_command: bool) -> None:
        current = self._mmu_sftp_directory if command == "cd" else self._server_sftp_directory
        destination = self._resolve_sftp_path(current, target)
        if send_command and self._sftp_shell is not None and self._sftp_shell.is_open:
            sftp_command = f"{command} {shlex.quote(destination)}"
            self._sftp_shell.send_line(sftp_command)
            self._sftp_pending_echo = sftp_command
            self._sftp_echo_buffer = ""
        if command == "cd":
            self._mmu_sftp_directory = destination
            self.mmu_file_list.current_directory = destination
            self.mmu_current_path_input.setText(destination)
            self._refresh_mmu_file_list()
        else:
            self._server_sftp_directory = destination
            self.server_file_list.current_directory = destination
            self.server_current_path_input.setText(destination)
            self._refresh_server_file_list()

    def _resolve_sftp_path(self, current: str, target: str) -> str:
        if not target:
            return current
        if target.startswith("/"):
            return posixpath.normpath(target)
        return posixpath.normpath(posixpath.join(current, target))

    def _send_sftp_raw(self, text: str) -> None:
        if self._sftp_shell is None or not self._sftp_shell.is_open:
            return
        try:
            self._sftp_shell.send(text)
        except Exception as exc:
            self._show_sftp_error(exc)

    def _set_sftp_actions_enabled(self, enabled: bool) -> None:
        self.close_sftp_button.setEnabled(enabled)
        self.refresh_server_file_list_button.setEnabled(enabled)
        self.refresh_mmu_file_list_button.setEnabled(enabled)

    def _refresh_usb_ports(self) -> None:
        if self._shell is None or not self._shell.is_open:
            self.statusBar().showMessage("USB serial console is available only through the SSH server")
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
        try:
            command = self._build_mmu_ssh_command(self._board_settings())
            if self._shell is None or not self._shell.is_open:
                self._start_local_mmu_ssh(command)
                return
            known_hosts_cleanup_command = SFTPManager.KNOWN_HOSTS_CLEANUP_COMMAND
            self.terminal_widget.write_output(f"$ {known_hosts_cleanup_command}")
            self._shell.send_line(known_hosts_cleanup_command)
            self.terminal_widget.write_output(f"$ {command}")
            self._shell.send_line(command)
        except ValueError as exc:
            self.terminal_widget.write_output(f"MMU SSH error: {exc}")
            self.board_status_label.setText("MMU: SSH failed")
            return
        # Both commands have already been rendered above.  Do not wait for an
        # assumed PTY echo before rendering output: some server shells do not
        # echo commands, which otherwise hides SSH connection prompts and
        # errors from the terminal completely.
        self._pending_echo = None
        self._echo_buffer = ""
        self._mmu_ssh_prompt_buffer = ""
        self._mmu_ssh_auth_pending = True
        self._mmu_ssh_session_active = True
        self._mmu_ssh_auth_timeout_timer.start()
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button.setEnabled(True)
        self.board_status_label.setText("MMU: SSH connecting")
        self.statusBar().showMessage("Opening MMU SSH session...")

    def _start_local_mmu_ssh(self, command: str) -> None:
        """Start a direct Client SSH session from the local Windows PC."""
        self._close_local_process()
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_local_process_output)
        process.errorOccurred.connect(self._handle_local_process_error)
        process.finished.connect(self._handle_local_mmu_ssh_finished)
        self._local_process = process
        self.terminal_widget.write_output(f"$ {command}")
        self.terminal_widget.set_interactive_mode(True)
        self._interactive_program = "ssh"
        self._mmu_ssh_session_active = True
        self.mmu_ssh_connect_button.setEnabled(False)
        self.mmu_ssh_disconnect_button.setEnabled(True)
        self.board_status_label.setText("MMU: local SSH connecting")
        self.statusBar().showMessage("Opening local SSH session...")
        parts = shlex.split(command)
        process.start(parts[0], parts[1:])

    def _read_local_process_output(self) -> None:
        """Render output from the local direct SSH process."""
        if self._local_process is None:
            return
        output = bytes(self._local_process.readAllStandardOutput()).decode("utf-8", errors="replace")
        if output:
            self.terminal_widget.write_stream(output)

    def _write_local_process_input(self, text: str) -> None:
        """Forward raw terminal input to an active local direct SSH process."""
        if self._local_process is None or self._local_process.state() == QProcess.ProcessState.NotRunning:
            return
        self._local_process.write(text.encode("utf-8"))

    def _handle_local_process_error(self, _error: QProcess.ProcessError) -> None:
        if self._local_process is None or not self._mmu_ssh_session_active:
            return
        self.terminal_widget.write_output(f"Local SSH error: {self._local_process.errorString()}")
        if self._local_process.state() == QProcess.ProcessState.NotRunning:
            self._handle_local_mmu_ssh_finished(1, QProcess.ExitStatus.CrashExit)

    def _handle_local_mmu_ssh_finished(self, _exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        if not self._mmu_ssh_session_active:
            return
        self._read_local_process_output()
        self._mmu_ssh_session_active = False
        self._local_process = None
        self._leave_interactive_mode()
        self.mmu_ssh_connect_button.setEnabled(self._shell is None or not self._shell.is_open)
        self.mmu_ssh_disconnect_button.setEnabled(False)
        self.board_status_label.setText("MMU: local SSH disconnected")
        self.statusBar().showMessage("Local SSH session closed")

    def _build_mmu_ssh_command(self, settings: BoardSettings) -> str:
        if not settings.ip_address.strip():
            raise ValueError("MMU IP address is required.")
        if not settings.username.strip():
            raise ValueError("MMU username is required.")
        if not 1 <= settings.ssh_port <= 65535:
            raise ValueError("MMU SSH port must be between 1 and 65535.")
        destination = settings.ip_address.strip()
        interface = settings.interface.strip()
        if ":" in destination and interface and "%" not in destination:
            destination = f"{destination}%{interface}"
        command = [
            "ssh",
            f"{settings.username.strip()}@{destination}",
            "-p",
            str(settings.ssh_port),
        ]
        return " ".join(shlex.quote(part) for part in command)

    def _handle_mmu_ssh_auth(self, output: str) -> None:
        self._mmu_ssh_prompt_buffer = f"{self._mmu_ssh_prompt_buffer}{output}"[-512:]
        lower = self._mmu_ssh_prompt_buffer.lower()
        if self._sftp_manager.connection_failed(lower):
            self._mark_mmu_ssh_failed()
        elif "password:" in lower and self._mmu_ssh_auth_pending:
            password = self.board_password_input.text()
            self._shell.send_line(password)
            self._mmu_ssh_auth_pending = False
            self._mmu_ssh_prompt_buffer = ""
            self._mmu_ssh_auth_timeout_timer.stop()
            self.terminal_widget.write_output("MMU SSH password sent.")
            self.board_status_label.setText("MMU: SSH connected")
            self.statusBar().showMessage("MMU SSH session opened")
        elif "are you sure you want to continue connecting" in lower:
            self._shell.send_line("yes")
            self._mmu_ssh_prompt_buffer = ""
        elif output:
            self._mmu_ssh_auth_timeout_timer.stop()
            self.board_status_label.setText("MMU: SSH connected")

    def _handle_mmu_ssh_auth_timeout(self) -> None:
        """Restore MMU SSH controls when its authentication prompt never appears."""
        if not self._mmu_ssh_session_active or not self._mmu_ssh_auth_pending:
            return
        timeout_seconds = self.MMU_SSH_AUTH_TIMEOUT_MS // 1000
        self.terminal_widget.write_output(
            f"MMU SSH connection failed: authentication prompt did not arrive within {timeout_seconds} seconds."
        )
        self._mark_mmu_ssh_failed()

    def _mark_mmu_ssh_failed(self) -> None:
        """Reset MMU SSH controls after the nested SSH command fails."""
        self._mmu_ssh_auth_timeout_timer.stop()
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self.mmu_ssh_connect_button.setEnabled(self._shell is not None and self._shell.is_open)
        self.mmu_ssh_disconnect_button.setEnabled(False)
        self.board_status_label.setText("MMU: SSH failed")
        self.statusBar().showMessage("MMU SSH failed")

    def _disconnect_mmu_ssh(self) -> None:
        if self._shell is not None and self._shell.is_open and self._mmu_ssh_session_active:
            self._shell.send_line("exit")
        elif self._local_process is not None:
            self._close_local_process()
        self._mmu_ssh_session_active = False
        self._mmu_ssh_auth_pending = False
        self._mmu_ssh_prompt_buffer = ""
        self._mmu_ssh_auth_timeout_timer.stop()
        self.mmu_ssh_connect_button.setEnabled(True)
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
        self.terminal_widget.set_backspace_sequence("\x7f")
        self.terminal_widget.set_interactive_mode(True)
        self.open_minicom_button.setEnabled(False)
        self.close_minicom_button.setEnabled(True)
        self.board_status_label.setText(f"MMU: minicom on {self._selected_usb_port()}")
        self.statusBar().showMessage("Opening minicom...")

    def _close_minicom(self) -> None:
        if self._automation_runner is not None and self._automation_runner.is_active:
            self._stop_automation()
        if self._shell is not None and self._shell.is_open and self._minicom_session_active:
            self._minicom_manager.close_session(self._shell)
        self._minicom_session_active = False
        self._leave_interactive_mode()
        self.close_minicom_button.setEnabled(False)
        self._update_minicom_button()
        self.board_status_label.setText("MMU: minicom closed")
        self.statusBar().showMessage("Closing minicom...")

    def _append_sftp_output(self, text: str) -> None:
        self.terminal_widget.write_output(f"[SFTP] {text.rstrip()}")

    def _load_command_sets(self) -> None:
        collection = self._command_set_store.load()
        self._command_sets = dict(collection.command_sets or {})
        self._command_folders = dict(collection.folders or {})
        self._refresh_command_set_list()

    def _refresh_command_set_list(self, selected_name: str | None = None) -> None:
        self.command_set_list.clear()
        items: dict[str, QTreeWidgetItem] = {"": self.command_set_list.invisibleRootItem()}
        for path, folder in sorted(self._command_folders.items(), key=lambda item: item[0]):
            parent = items.get(folder.parent_path, self.command_set_list.invisibleRootItem())
            item = QTreeWidgetItem(parent, [folder.name])
            item.setData(0, Qt.ItemDataRole.UserRole, ("folder", path))
            items[path] = item
        for name, command_set in sorted(self._command_sets.items()):
            parent = items.get(command_set.parent_path, self.command_set_list.invisibleRootItem())
            item = QTreeWidgetItem(parent, [name])
            item.setData(0, Qt.ItemDataRole.UserRole, ("group", name))
            if selected_name == name:
                self.command_set_list.setCurrentItem(item)
        self.command_set_list.expandAll()
        if self.command_set_list.currentItem() is None and self.command_set_list.topLevelItemCount():
            self.command_set_list.setCurrentItem(self.command_set_list.topLevelItem(0))
        if self.command_set_list.currentItem() is None:
            self._show_selected_command_set()

    def _folder_paths(self) -> list[str]:
        return sorted(self._command_folders)

    def _create_command_folder(self) -> None:
        name, accepted = QInputDialog.getText(self, "New Folder", "Folder name")
        if not accepted or not name.strip():
            return
        parent_path = self._selected_folder_path() or ""
        collection = self._command_set_store.create_folder(name, parent_path)
        self._command_folders = dict(collection.folders or {})
        self._command_sets = dict(collection.command_sets or {})
        self._refresh_command_set_list()

    def _create_command_set(self) -> None:
        dialog = CommandEditorDialog(parent=self, folder_paths=self._folder_paths())
        if dialog.exec() != CommandEditorDialog.DialogCode.Accepted:
            return
        self._save_command_set(dialog.command_set())

    def _edit_command_set(self) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            return
        dialog = CommandEditorDialog(command_set, self, self._folder_paths())
        if dialog.exec() != CommandEditorDialog.DialogCode.Accepted:
            return
        edited = dialog.command_set()
        if edited.name != command_set.name:
            self._command_set_store.delete(command_set.name)
        self._save_command_set(edited)

    def _delete_command_set(self) -> None:
        command_set = self._selected_command_set()
        folder_path = self._selected_folder_path()
        if command_set is not None:
            if QMessageBox.question(self, "Delete Command Set", f"Delete command set '{command_set.name}'?") != QMessageBox.StandardButton.Yes:
                return
            collection = self._command_set_store.delete(command_set.name)
        elif folder_path is not None:
            answer = QMessageBox.question(
                self, "Delete Folder",
                f"Delete '{folder_path}' and all of its contents? Choose No to move its contents to the top level.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            collection = self._command_set_store.delete_folder(folder_path, delete_contents=answer == QMessageBox.StandardButton.Yes)
        else:
            return
        self._command_sets, self._command_folders = dict(collection.command_sets or {}), dict(collection.folders or {})
        self._refresh_command_set_list()

    def _run_command_set(self) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            return
        if self._shell is None or not self._shell.is_open:
            self.terminal_widget.write_output("Not connected to an SSH shell.")
            return
        commands = self._commands_in(command_set)
        if not commands:
            return
        for command in commands:
            self._shell.send_line(command)
        self.statusBar().showMessage(f"Commands sent from group '{command_set.name}'.")

    def _save_command_set(self, command_set: CommandSet) -> None:
        collection = self._command_set_store.upsert(command_set)
        self._command_sets, self._command_folders = dict(collection.command_sets or {}), dict(collection.folders or {})
        self._refresh_command_set_list(command_set.name.strip())

    def _move_command_set(self, name: str, parent_path: str) -> None:
        """Move a command set when it is dropped on a command folder."""
        command_set = self._command_sets.get(name)
        if command_set is None or command_set.parent_path == parent_path:
            return
        try:
            collection = self._command_set_store.move_command_set(name, parent_path)
        except Exception as exc:
            self.statusBar().showMessage(f"Could not move command set: {exc}")
            return
        self._command_sets = dict(collection.command_sets or {})
        self._command_folders = dict(collection.folders or {})
        self._refresh_command_set_list(name)

    def _selected_folder_path(self) -> str | None:
        item = self.command_set_list.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return data[1] if isinstance(data, tuple) and data[0] == "folder" else None

    def _selected_command_set(self) -> CommandSet | None:
        item = self.command_set_list.currentItem()
        data = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        return self._command_sets.get(data[1]) if isinstance(data, tuple) and data[0] == "group" else None

    def _show_selected_command_set(self, *_items: QTreeWidgetItem | None) -> None:
        command_set = self._selected_command_set()
        if command_set is None:
            folder_path = self._selected_folder_path()
            self.command_set_output.setPlainText(f"Folder: {folder_path}" if folder_path else "")
            self._set_command_actions_enabled(False)
            self.delete_command_button.setEnabled(folder_path is not None)
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

    @staticmethod
    def _commands_in(command_set: CommandSet) -> list[str]:
        return [command.strip() for command in command_set.commands.splitlines() if command.strip()]

    def _load_automation_scenarios(self) -> None:
        """Load persisted automation scenarios without preventing app startup."""
        try:
            self._automation_scenarios = dict(self._automation_store.load().scenarios)
        except Exception as exc:
            self._automation_scenarios = {}
            self.terminal_widget.write_output(f"Could not load automation scenarios: {exc}")
        self._refresh_automation_list()

    def _refresh_automation_list(self, selected_name: str | None = None) -> None:
        self.automation_list.clear()
        for name in sorted(self._automation_scenarios):
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.automation_list.addItem(item)
            if name == selected_name:
                self.automation_list.setCurrentItem(item)
        if self.automation_list.currentItem() is None and self.automation_list.count():
            self.automation_list.setCurrentRow(0)
        self._set_automation_actions_enabled(self.automation_list.currentItem() is not None)

    def _selected_automation_scenario(self) -> AutomationScenario | None:
        item = self.automation_list.currentItem()
        name = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        return self._automation_scenarios.get(name) if isinstance(name, str) else None

    def _show_selected_automation_scenario(self, *_items: QListWidgetItem | None) -> None:
        self._remember_automation_progress()
        scenario = self._selected_automation_scenario()
        if scenario is None:
            self.automation_output.clear()
            self.automation_start_step_input.clear()
            self._set_automation_actions_enabled(False)
            return
        self._populate_automation_start_step_input(scenario)
        self._render_automation_progress(scenario)
        self._set_automation_actions_enabled(True)

    def _populate_automation_start_step_input(self, scenario: AutomationScenario) -> None:
        """Offer every step as a possible entry point for the selected scenario."""
        self.automation_start_step_input.blockSignals(True)
        try:
            self.automation_start_step_input.clear()
            for index, step in enumerate(scenario.steps):
                self.automation_start_step_input.addItem(
                    f"Step {index + 1}: {step.name or step.command or 'Unnamed step'}", index
                )
        finally:
            self.automation_start_step_input.blockSignals(False)

    def _render_automation_progress(self, scenario: AutomationScenario) -> None:
        """Render scenario steps and its most recently observed progress."""
        runner = self._automation_runner
        active_scenario = runner.scenario if runner is not None else None
        is_running_scenario = active_scenario is not None and active_scenario.name == scenario.name
        snapshot = self._automation_progress.get(scenario.name)
        if is_running_scenario and runner is not None:
            snapshot = AutomationProgressSnapshot(
                runner.status, runner.skipped_step_indices, runner.start_step_index,
                self._active_automation_terminal_display_name(),
            )
        status = snapshot.status if snapshot is not None else None
        current_index = status.step_index if status is not None else -1
        skipped_indices = snapshot.skipped_step_indices if snapshot is not None else frozenset()
        start_step_index = (
            runner.start_step_index
            if is_running_scenario and runner is not None
            else snapshot.start_step_index if snapshot is not None else 0
        )
        step_lines: list[str] = []
        for index, step in enumerate(scenario.steps):
            marker = "○"
            if index < start_step_index:
                marker = "↷ not run"
            elif index in skipped_indices:
                marker = "↷ skipped"
            elif status is not None and status.state.value == "succeeded" and index <= current_index:
                marker = "✓ completed"
            elif status is not None and status.state.value in {"failed", "cancelled"} and index == current_index:
                marker = f"✗ {status.state.value}"
            elif is_running_scenario and runner is not None and runner.is_active and index == current_index:
                marker = "▶ running"
            elif is_running_scenario and index < current_index:
                marker = "✓ completed"
            step_lines.append(
                f"{index + 1}. [{marker}] {step.name or step.command} — "
                f"{step.completion_type.value}: {step.completion_value}"
            )
        progress = status.message if status is not None else "Not running."
        terminal_name = (
            snapshot.terminal_display_name
            if snapshot is not None and snapshot.terminal_display_name
            else self._active_automation_terminal_display_name()
        )
        self.automation_output.setPlainText(
            f"Name: {scenario.name}\nConsole: {terminal_name}\nDescription: {scenario.description}\n\n"
            f"Execution progress: {progress}\n\n" + "\n".join(step_lines)
        )

    def _remember_automation_progress(self) -> None:
        """Keep progress visible after the user selects another scenario."""
        runner = self._automation_runner
        if runner is None or runner.scenario is None:
            return
        self._automation_progress[runner.scenario.name] = AutomationProgressSnapshot(
            runner.status, runner.skipped_step_indices, runner.start_step_index,
            self._active_automation_terminal_display_name(),
        )

    def _set_automation_actions_enabled(self, selected: bool) -> None:
        active = self._automation_runner is not None and self._automation_runner.is_active
        self.copy_automation_button.setEnabled(selected and not active)
        self.edit_automation_button.setEnabled(selected and not active)
        self.delete_automation_button.setEnabled(selected and not active)
        self.run_automation_button.setEnabled(selected and not active)
        self.automation_start_step_input.setEnabled(selected and bool(self.automation_start_step_input.count()) and not active)
        self.stop_automation_button.setEnabled(active)

    def _create_automation_scenario(self) -> None:
        dialog = AutomationEditorDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_automation_scenario(dialog.scenario())

    def _import_automation_scenario(self) -> None:
        """Import commands into a draft, then let the user review it before saving."""
        import_dialog = AutomationImportDialog(self)
        if import_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        scenario = import_dialog.scenario()
        if scenario is None:
            return
        editor = AutomationEditorDialog(scenario, self)
        if editor.exec() == QDialog.DialogCode.Accepted:
            self._save_automation_scenario(editor.scenario())

    def _copy_automation_scenario(self) -> None:
        """Open a copy of the selected scenario with a unique default name."""
        scenario = self._selected_automation_scenario()
        if scenario is None:
            return
        copied = AutomationScenario.from_dict(scenario.to_dict())
        copied.name = self._next_automation_copy_name(scenario.name)
        dialog = AutomationEditorDialog(copied, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._save_automation_scenario(dialog.scenario())

    def _next_automation_copy_name(self, name: str) -> str:
        """Return a scenario name that will not replace an existing scenario."""
        base_name = f"{name} (Copy)"
        candidate = base_name
        copy_number = 2
        while candidate in self._automation_scenarios:
            candidate = f"{base_name} {copy_number}"
            copy_number += 1
        return candidate

    def _edit_automation_scenario(self) -> None:
        scenario = self._selected_automation_scenario()
        if scenario is None:
            return
        dialog = AutomationEditorDialog(scenario, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            edited = dialog.scenario()
            if edited.name != scenario.name:
                try:
                    self._automation_store.delete(scenario.name)
                except Exception as exc:
                    self._show_automation_save_error("renaming scenario", exc)
                    return
            self._save_automation_scenario(edited)

    def _delete_automation_scenario(self) -> None:
        scenario = self._selected_automation_scenario()
        if scenario is None:
            return
        if QMessageBox.question(self, "Delete Automation", f"Delete automation '{scenario.name}'?") != QMessageBox.StandardButton.Yes:
            return
        self._automation_scenarios = dict(self._automation_store.delete(scenario.name).scenarios)
        self._automation_progress.pop(scenario.name, None)
        self._refresh_automation_list()

    def _save_automation_scenario(self, scenario: AutomationScenario) -> bool:
        """Persist a scenario, leaving the displayed scenarios unchanged on failure."""
        try:
            collection = self._automation_store.upsert(scenario)
        except Exception as exc:
            self._show_automation_save_error("saving scenario", exc)
            return False
        self._automation_scenarios = dict(collection.scenarios)
        self._refresh_automation_list(scenario.name)
        return True

    def _show_automation_save_error(self, action: str, error: Exception) -> None:
        """Expose a scenario persistence error without changing the current list state."""
        reason = str(error) or error.__class__.__name__
        message = (
            f"Automation save failed while {action}: {reason} "
            f"(storage: {self._automation_store.path})"
        )
        self.automation_status_label.setText(message)
        self.statusBar().showMessage(message)

    def _active_automation_terminal(self) -> AutomationTerminal | None:
        """Return the console that automation can use at this instant."""
        if self._shell is None or not self._shell.is_open:
            return None
        name = "Minicom" if self._minicom_session_active else "SSH shell"
        return _ShellAutomationTerminal(self._shell, name, self._recent_automation_output)

    def _active_automation_terminal_display_name(self) -> str:
        """Return a user-facing name for the current console, if any."""
        terminal = self._active_automation_terminal()
        return terminal.display_name if terminal is not None else "No active console"

    def _run_automation_scenario(self) -> None:
        scenario = self._selected_automation_scenario()
        if scenario is None:
            return
        try:
            self._automation_scenarios = dict(self._automation_store.load().scenarios)
        except Exception as exc:
            self.automation_status_label.setText(f"Automation: could not load scenarios: {exc}")
            return
        scenario = self._automation_scenarios.get(scenario.name)
        if scenario is None:
            self.automation_status_label.setText("Automation: selected scenario no longer exists")
            self._refresh_automation_list()
            return
        terminal = self._active_automation_terminal()
        if terminal is None:
            self.automation_status_label.setText("Automation: no active console is available")
            return
        self._automation_runner = AutomationRunner(terminal.send_line)
        self._automation_terminal = terminal
        try:
            start_step_index = self.automation_start_step_input.currentData()
            if not isinstance(start_step_index, int):
                self.automation_status_label.setText("Automation: selected scenario has no steps")
                return
            self._automation_runner.start(scenario, start_step_index)
            self._automation_runner.receive_initial_output(terminal.read_recent_output())
        except Exception as exc:
            self.automation_status_label.setText(f"Automation failed to start: {exc}")
            return
        self._remember_automation_progress()
        self._automation_file_check_due = 0.0
        self._automation_timer.start()
        self._update_automation_status()

    def _stop_automation(self) -> None:
        if self._automation_runner is not None:
            self._automation_runner.cancel()
        self._automation_timer.stop()
        self._update_automation_status()

    def _poll_automation(self) -> None:
        runner = self._automation_runner
        if runner is None:
            self._automation_timer.stop()
            return
        needs_file_check = runner.tick()
        if needs_file_check and time.monotonic() >= self._automation_file_check_due:
            command = runner.file_check_command()
            if command is not None:
                try:
                    terminal = self._automation_terminal
                    if terminal is None:
                        raise RuntimeError("No active automation console")
                    terminal.send_line(command)
                except Exception as exc:
                    runner.fail_current_step(f"Could not inspect device file: {exc}")
            self._automation_file_check_due = time.monotonic() + 1.0
        self._update_automation_status()
        if not runner.is_active:
            self._automation_timer.stop()

    def _update_automation_status(self) -> None:
        runner = self._automation_runner
        if runner is None:
            self.automation_status_label.setText("Automation: idle")
            self._set_automation_actions_enabled(self._selected_automation_scenario() is not None)
            return
        self._remember_automation_progress()
        status = runner.status
        state = status.state.value.replace("_", " ")
        self.automation_status_label.setText(f"Automation: {state} — {status.message}")
        scenario = self._selected_automation_scenario()
        if scenario is not None:
            self._render_automation_progress(scenario)
        self._set_automation_actions_enabled(self._selected_automation_scenario() is not None)

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
        output = self._automation_output_filter.feed(output)
        if self._automation_runner is not None and output:
            self._automation_runner.receive_output(output)
            self._update_automation_status()
        if output:
            self._recent_automation_output = (
                f"{self._recent_automation_output}{output}"[-self.AUTOMATION_OUTPUT_LIMIT :]
            )
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
        if self._sftp_manager.connection_failed(output):
            self._append_sftp_output("SFTP connection failed. Check the connection settings and terminal output below.")
            filtered_output = self._filter_sftp_echo(output)
            filtered_output = self._without_trailing_sftp_prompt(filtered_output)
            if filtered_output:
                self.terminal_widget.write_stream(filtered_output)
            self._show_sftp_error(Exception("connection failed"))
            return
        startup_reached = self._sftp_startup_pending and "sftp>" in output
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
        self._update_sftp_transfer_progress(output)
        pwd_response_complete = self._sftp_pending_pwd is not None and "sftp>" in output
        output = self._without_trailing_sftp_prompt(output)
        if startup_reached:
            self._mark_sftp_connected()
        if self._sftp_pending_listing and output.strip():
            self._populate_file_list(self.mmu_file_list, self._parse_sftp_listing(output))
            self._sftp_pending_listing = False
        if self._sftp_pending_pwd is not None and output.strip():
            handled_pwd = self._handle_sftp_pwd_output(output)
            if handled_pwd or pwd_response_complete:
                self._sftp_pending_pwd = None
        if output:
            self.terminal_widget.write_stream(output)

    def _mark_sftp_connected(self) -> None:
        """Enable SFTP controls only after the remote prompt confirms startup."""
        self._sftp_startup_timeout_timer.stop()
        self._sftp_startup_pending = False
        self._sftp_session_active = True
        self._append_sftp_output("SFTP session opened.")
        if self._sftp_shell is not None and self._sftp_shell.is_open:
            command = self._sftp_manager.change_directory(
                self._sftp_shell,
                self._mmu_sftp_directory,
            )
            self._sftp_pending_echo = command
            self._sftp_echo_buffer = ""
            self._append_sftp_output(f"Changed MMU SFTP directory: {command}")
        self._set_sftp_actions_enabled(True)
        self.board_status_label.setText("MMU: SFTP connected")
        self.statusBar().showMessage("SFTP session opened")
        self._refresh_sftp_file_lists()


    def _handle_sftp_startup_timeout(self) -> None:
        """Fail SFTP startup when the remote prompt does not appear quickly."""
        if not self._sftp_startup_pending:
            return
        self._append_sftp_output("SFTP connection failed: no response within 3 seconds.")
        self._show_sftp_error(Exception("connection timed out after 3 seconds"))

    def _without_trailing_sftp_prompt(self, output: str) -> str:
        """Drop remote SFTP prompts because the widget already shows one locally."""
        while output.endswith("sftp> "):
            output = output.removesuffix("sftp> ")
        return output

    def _filter_command_echo(self, output: str) -> str:
        """Remove the PTY echo because the widget already displays local input."""
        if self._pending_echo is None or not output:
            return output
        normalized_output = output.replace("\r\n", "\n").replace("\r", "\n")
        chunk_start = len(self._echo_buffer)
        self._echo_buffer += normalized_output
        echo = self._pending_echo

        # The initial shell banner, prompt, and command echo can each arrive
        # in a different read_available() result.  Keep accumulating until a
        # complete echo is present; releasing the pending state based on a
        # non-echo first line would render a later echo as duplicate input.
        echo_end = self._echo_buffer.find(f"{echo}\n")
        while echo_end != -1 and (
            echo_end not in {0, chunk_start}
            and self._echo_buffer[echo_end - 1] != "\n"
        ):
            echo_end = self._echo_buffer.find(f"{echo}\n", echo_end + 1)
        if echo_end == -1:
            return ""

        before_echo = self._echo_buffer[:echo_end]
        remainder = self._echo_buffer[echo_end + len(echo) + 1 :]
        # A line advance emitted immediately before the first echoed command
        # is not visible input.  Drop it only when it is the entire prefix,
        # so banner output received before the echo is retained.
        if before_echo == "\n":
            before_echo = ""
        result = before_echo + remainder
        if not echo:
            result = result.lstrip("\n")
        else:
            result = self._without_extra_echo_newline(result)
        self._pending_echo = None
        self._echo_buffer = ""
        return result

    def _without_extra_echo_newline(self, output: str) -> str:
        """Drop one blank line left behind after filtering a PTY echo."""
        return output[1:] if output.startswith("\n") else output

    def _filter_sftp_echo(self, output: str) -> str:
        if self._sftp_pending_echo is None or not output:
            return output
        self._sftp_echo_buffer += output.replace("\r\n", "\n")
        if "\n" not in self._sftp_echo_buffer:
            if "\r" not in self._sftp_echo_buffer:
                return ""
            normalized_echo_buffer = self._sftp_echo_buffer.replace("\r", "\n")
            first_line, remainder = normalized_echo_buffer.split("\n", 1)
            result = (
                remainder
                if first_line == self._sftp_pending_echo
                else self._sftp_echo_buffer
            )
            self._sftp_pending_echo = None
            self._sftp_echo_buffer = ""
            return result
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
        if self._automation_runner is not None and self._automation_runner.is_active:
            self._stop_automation()
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
        self._mmu_ssh_auth_timeout_timer.stop()
        self.mmu_ssh_connect_button.setEnabled(True)
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
        self._sftp_startup_timeout_timer.stop()
        if self._sftp_shell is not None:
            self._sftp_shell.close()
            self._sftp_shell = None
        self._sftp_session_active = False
        self._active_sftp_settings = None
        self._sftp_pending_echo = None
        self._sftp_pending_pwd = None
        self._sftp_echo_buffer = ""
        self._sftp_prompt_buffer = ""
        self._sftp_startup_pending = False
        self._close_sftp_transfer_progress()
        self._set_sftp_actions_enabled(False)
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
        self._mmu_ssh_auth_timeout_timer.stop()
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
        self.mmu_ssh_connect_button.setEnabled(True)
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
        layout = QHBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)

        self.main_response_splitter = QSplitter(Qt.Orientation.Horizontal, container)
        self.main_response_splitter.setChildrenCollapsible(False)

        self.main_content = QWidget(self.main_response_splitter)
        main_layout = QVBoxLayout(self.main_content)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(10)
        main_layout.addWidget(self._build_connection_panel())
        main_layout.addWidget(self._build_workspace(), stretch=1)

        self.response_panel = self._build_response_panel()
        self.main_response_splitter.addWidget(self.main_content)
        self.main_response_splitter.addWidget(self.response_panel)
        self.main_response_splitter.setStretchFactor(0, 1)
        self.main_response_splitter.setStretchFactor(1, 0)
        self.main_response_splitter.setSizes([1100, 460])
        self._response_panel_width = 460
        self.setMinimumWidth(
            1196 + self._response_panel_width + self.main_response_splitter.handleWidth()
        )

        layout.addWidget(self.main_response_splitter)
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
        # QScrollArea uses the platform's inactive-window colour by default on
        # some Windows themes.  Keep the connection inputs visually aligned
        # with the white workspace below them.
        panel.setStyleSheet("QFrame { background-color: white; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        header = QWidget(panel)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.connection_panel_toggle_button = QPushButton("Hide connection info", self)
        self.connection_panel_toggle_button.setCheckable(True)
        self.connection_panel_toggle_button.setChecked(True)
        header_layout.addWidget(self.connection_panel_toggle_button)
        header_layout.addStretch(1)
        # Keep the response control above the Client column so it remains
        # available after the response pane itself is folded away.
        self.response_panel_toggle_button = QPushButton("Hide", header)
        self.response_panel_toggle_button.setCheckable(True)
        self.response_panel_toggle_button.setChecked(True)
        header_layout.addWidget(self.response_panel_toggle_button)
        layout.addWidget(header)

        self.connection_panel_content = QWidget(panel)
        content_layout = QGridLayout(self.connection_panel_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setHorizontalSpacing(16)
        content_layout.setVerticalSpacing(10)
        content_layout.addWidget(self._build_ssh_group(), 0, 0)
        content_layout.addWidget(self._build_power_supply_group(), 0, 1)
        content_layout.addWidget(self._build_board_group(), 0, 2)
        content_layout.setColumnStretch(0, 1)
        content_layout.setColumnStretch(1, 1)
        content_layout.setColumnStretch(2, 1)
        self.connection_panel_scroll_area = QScrollArea(panel)
        self.connection_panel_scroll_area.setWidgetResizable(True)
        self.connection_panel_scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.connection_panel_scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.connection_panel_scroll_area.setStyleSheet(
            "QScrollArea, QScrollArea > QWidget > QWidget { background-color: white; }"
        )
        self.connection_panel_scroll_area.setWidget(self.connection_panel_content)
        layout.addWidget(self.connection_panel_scroll_area)

        self.connection_panel_toggle_button.toggled.connect(self._set_connection_panel_visible)
        self._set_connection_panel_visible(True)
        return panel

    def _set_connection_panel_visible(self, visible: bool) -> None:
        self.connection_panel_scroll_area.setVisible(visible)
        label = "Hide connection info" if visible else "Show connection info"
        self.connection_panel_toggle_button.setText(label)

    def _make_group(self, title: str, content: QWidget) -> QGroupBox:
        group = QGroupBox(title, self)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(content)
        return group

    def _build_ssh_group(self) -> QGroupBox:
        self.ssh_group_content = QWidget(self)
        layout = QFormLayout(self.ssh_group_content)
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
        self.ssh_group = self._make_group("SSH Server", self.ssh_group_content)
        return self.ssh_group

    def _build_power_supply_group(self) -> QGroupBox:
        self.power_supply_group_content = QWidget(self)
        layout = QFormLayout(self.power_supply_group_content)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.power_supply_ip_input = QLineEdit(self)
        self.power_supply_ip_input.setPlaceholderText("Power Supply IPv4")
        ipv4_pattern = (
            r"^(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1?\d?\d)$"
        )
        self.power_supply_ip_input.setValidator(
            QRegularExpressionValidator(QRegularExpression(ipv4_pattern), self)
        )

        decimal_pattern = r"^(?:\d+(?:\.\d*)?|\.\d+)$"
        decimal_validator = QRegularExpressionValidator(QRegularExpression(decimal_pattern), self)
        self.power_supply_voltage_input = QLineEdit(self)
        self.power_supply_voltage_input.setPlaceholderText("Voltage")
        self.power_supply_voltage_input.setValidator(decimal_validator)
        self.power_supply_current_input = QLineEdit(self)
        self.power_supply_current_input.setPlaceholderText("Current")
        self.power_supply_current_input.setValidator(decimal_validator)

        self.power_set_button = QPushButton("Set", self)
        self.power_on_button = QPushButton("ON", self)
        self.power_off_button = QPushButton("OFF", self)
        self.power_status_button = QPushButton("Status", self)
        self.power_all_status_button = QPushButton("All Status", self)

        button_row = QWidget(self)
        button_layout = QGridLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self.power_set_button, 0, 0)
        button_layout.addWidget(self.power_status_button, 0, 1)
        button_layout.addWidget(self.power_all_status_button, 0, 2)
        button_layout.addWidget(self.power_on_button, 1, 0)
        button_layout.addWidget(self.power_off_button, 1, 1)
        button_layout.setColumnStretch(3, 1)

        layout.addRow("IPv4", self.power_supply_ip_input)
        layout.addRow("Voltage", self.power_supply_voltage_input)
        layout.addRow("Current", self.power_supply_current_input)
        layout.addRow(button_row)
        self.power_supply_group = self._make_group("Power Supply", self.power_supply_group_content)
        return self.power_supply_group

    def _build_board_group(self) -> QGroupBox:
        self.mmu_group_content = QWidget(self)
        layout = QFormLayout(self.mmu_group_content)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self.board_ip_input = QLineEdit(self)
        self.board_ip_input.setPlaceholderText("IP address, e.g. 192.168.0.10 or fe80::1")
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

        self.board_console_tabs = QTabWidget(self)
        self.board_console_tabs.addTab(self._build_serial_console_tab(), "Serial Console")
        self.board_console_tabs.addTab(self._build_ssh_console_tab(), "SSH Console")
        layout.addRow(self.board_console_tabs)
        self.mmu_group = self._make_group("Client", self.mmu_group_content)
        return self.mmu_group

    def _build_serial_console_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QFormLayout(tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        usb_row = QWidget(tab)
        usb_layout = QHBoxLayout(usb_row)
        usb_layout.setContentsMargins(0, 0, 0, 0)
        usb_layout.addWidget(self.usb_port_combo, stretch=1)
        usb_layout.addWidget(self.refresh_usb_button)

        button_row = QWidget(tab)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self.open_minicom_button)
        button_layout.addWidget(self.close_minicom_button)
        button_layout.addStretch(1)

        layout.addRow("USB Port", usb_row)
        layout.addRow(button_row)
        return tab

    def _build_ssh_console_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QFormLayout(tab)
        layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        button_row = QWidget(tab)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addWidget(self.mmu_ssh_connect_button)
        button_layout.addWidget(self.mmu_ssh_disconnect_button)
        button_layout.addStretch(1)

        layout.addRow("IP", self.board_ip_input)
        layout.addRow("User", self.board_username_input)
        layout.addRow("Password", self.board_password_input)
        layout.addRow("Interface", self.board_interface_input)
        layout.addRow("SSH Port", self.board_ssh_port_input)
        layout.addRow(button_row)
        return tab

    def _build_workspace(self) -> QTabWidget:
        self.workspace_tabs = QTabWidget(self)
        self.workspace_tabs.addTab(self._build_terminal_tab(), "Terminal")
        self.workspace_tabs.addTab(self._build_transfer_tab(), "SFTP")
        return self.workspace_tabs

    def _build_terminal_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        terminal_splitter = QSplitter(Qt.Orientation.Horizontal, tab)
        terminal_splitter.setChildrenCollapsible(False)

        terminal_panel = QWidget(tab)
        terminal_layout = QVBoxLayout(terminal_panel)
        terminal_layout.setContentsMargins(0, 0, 0, 0)
        self.terminal_widget = TerminalWidget(prompt=self._local_prompt())
        self.terminal_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        terminal_layout.addWidget(self.terminal_widget, stretch=1)

        terminal_splitter.addWidget(terminal_panel)
        terminal_side_tabs = QTabWidget(tab)
        terminal_side_tabs.setSizePolicy(
            QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )
        terminal_side_tabs.addTab(self._build_commands_tab(), "Commands")
        terminal_side_tabs.addTab(self._build_scenarios_tab(), "Scenarios")
        terminal_splitter.addWidget(terminal_side_tabs)
        terminal_splitter.setStretchFactor(0, 3)
        terminal_splitter.setStretchFactor(1, 2)

        # Keep the Commands and Scenarios tabs at their minimum useful width
        # initially. The splitter remains resizable after this initial layout
        # is applied.
        QTimer.singleShot(
            0,
            lambda: terminal_splitter.setSizes(
                [
                    max(terminal_splitter.width() - terminal_side_tabs.minimumSizeHint().width(), 1),
                    terminal_side_tabs.minimumSizeHint().width(),
                ]
            ),
        )

        layout.addWidget(terminal_splitter, stretch=1)
        return tab

    def _build_response_panel(self) -> QWidget:
        """Build the collapsible pane reserved for command-response output."""
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)

        title = QLabel("Response", panel)

        self.response_panel_content = QPlainTextEdit(panel)
        self.response_panel_content.setReadOnly(True)
        self.response_panel_content.setPlaceholderText(
            "Results for configured terminal commands will appear here."
        )
        layout.addWidget(title)
        layout.addWidget(self.response_panel_content, stretch=1)
        self.response_panel_toggle_button.toggled.connect(self._set_response_panel_visible)
        return panel

    def _set_response_panel_visible(self, visible: bool) -> None:
        """Fold the response pane while preserving the main-content width."""
        self.response_panel_toggle_button.setText("Hide" if visible else "Show")
        if not hasattr(self, "main_response_splitter"):
            return
        if visible:
            self.response_panel.show()
            width_change = self._response_panel_width + self.main_response_splitter.handleWidth()
            target_width = self.width() + width_change
            self.setMinimumWidth(1196 + width_change)
            if not self.isMaximized():
                self.resize(max(target_width, self.minimumWidth()), self.height())
            self.main_response_splitter.setSizes(
                [max(self.main_content.width(), 1), self._response_panel_width]
            )
        else:
            self._response_panel_width = max(self.response_panel.width(), 1)
            width_change = self._response_panel_width + self.main_response_splitter.handleWidth()
            target_width = self.width() - width_change
            self.response_panel.hide()
            self.setMinimumWidth(1196)
            if not self.isMaximized():
                self.resize(max(self.minimumWidth(), target_width), self.height())

    def _build_commands_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        self.commands_group = QGroupBox("Commands", tab)
        commands_layout = QVBoxLayout(self.commands_group)

        button_row = QWidget(self.commands_group)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)

        self.new_command_button = QPushButton("New Command", self.commands_group)
        self.new_folder_button = QPushButton("New Folder", self.commands_group)
        self.edit_command_button = QPushButton("Edit", self.commands_group)
        self.delete_command_button = QPushButton("Delete", self.commands_group)
        self.run_command_set_button = QPushButton("Run", self.commands_group)
        self.edit_command_button.setEnabled(False)
        self.delete_command_button.setEnabled(False)
        self.run_command_set_button.setEnabled(False)

        button_layout.addWidget(self.new_folder_button)
        button_layout.addWidget(self.new_command_button)
        button_layout.addWidget(self.edit_command_button)
        button_layout.addWidget(self.delete_command_button)
        button_layout.addStretch(1)
        button_layout.addWidget(self.run_command_set_button)

        self.command_set_output = QPlainTextEdit(self.commands_group)
        self.command_set_output.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.command_set_output.setReadOnly(True)
        self.command_set_output.setPlaceholderText("Selected command group details appear here.")

        commands_layout.addWidget(button_row)
        self.command_set_list = CommandSetTreeWidget(self.commands_group)
        self.command_set_list.setHeaderHidden(True)
        self.command_set_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        command_splitter = QSplitter(Qt.Orientation.Vertical, self.commands_group)
        command_splitter.setChildrenCollapsible(False)
        command_splitter.addWidget(self.command_set_list)
        command_splitter.addWidget(self.command_set_output)
        command_splitter.setStretchFactor(0, 1)
        command_splitter.setStretchFactor(1, 1)
        commands_layout.addWidget(command_splitter, stretch=1)
        layout.addWidget(self.commands_group, stretch=1)
        return tab

    def _build_scenarios_tab(self) -> QWidget:
        """Build the dedicated workspace for automation scenarios."""
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)

        automation_group = QGroupBox("Automation Scenarios", tab)
        automation_layout = QVBoxLayout(automation_group)
        automation_actions = QHBoxLayout()
        self.new_automation_button = QPushButton("New Scenario", automation_group)
        self.import_automation_button = QPushButton("텍스트에서 가져오기", automation_group)
        self.copy_automation_button = QPushButton("Copy", automation_group)
        self.edit_automation_button = QPushButton("Edit", automation_group)
        self.delete_automation_button = QPushButton("Delete", automation_group)
        self.run_automation_button = QPushButton("Run Scenario", automation_group)
        self.automation_start_step_input = QComboBox(automation_group)
        self.automation_start_step_input.setToolTip("Choose the step at which to start the scenario.")
        self.stop_automation_button = QPushButton("Stop", automation_group)
        self.edit_automation_button.setEnabled(False)
        self.copy_automation_button.setEnabled(False)
        self.delete_automation_button.setEnabled(False)
        self.run_automation_button.setEnabled(False)
        self.stop_automation_button.setEnabled(False)
        for button in (
            self.new_automation_button,
            self.import_automation_button,
            self.copy_automation_button,
            self.edit_automation_button,
            self.delete_automation_button,
        ):
            automation_actions.addWidget(button)
        automation_actions.addStretch(1)
        automation_run_controls = QHBoxLayout()
        automation_run_controls.addWidget(self.automation_start_step_input)
        automation_run_controls.addWidget(self.run_automation_button)
        automation_run_controls.addWidget(self.stop_automation_button)
        automation_run_controls.addStretch(1)
        self.automation_list = QListWidget(automation_group)
        self.automation_output = QPlainTextEdit(automation_group)
        self.automation_output.setReadOnly(True)
        self.automation_output.setPlaceholderText("Scenario execution progress appears here.")
        self.automation_status_label = QLabel("Automation: idle", automation_group)
        automation_splitter = QSplitter(Qt.Orientation.Vertical, automation_group)
        automation_splitter.addWidget(self.automation_list)
        automation_splitter.addWidget(self.automation_output)
        automation_splitter.setStretchFactor(0, 1)
        automation_splitter.setStretchFactor(1, 1)
        automation_layout.addLayout(automation_actions)
        automation_layout.addLayout(automation_run_controls)
        automation_layout.addWidget(automation_splitter)
        automation_layout.addWidget(self.automation_status_label)
        layout.addWidget(automation_group, stretch=1)
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
        file_list_splitter = QSplitter(Qt.Orientation.Horizontal, file_lists)
        file_list_splitter.setChildrenCollapsible(False)
        server_column = QWidget(self)
        server_layout = QVBoxLayout(server_column)
        server_layout.setContentsMargins(0, 0, 0, 0)
        self.server_file_list = SftpFileListWidget("server", self)
        self.server_file_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.server_file_list.setToolTip("Linux server files. Drag a file to the MMU list to upload it.")
        server_header = QWidget(self)
        server_header_layout = QHBoxLayout(server_header)
        server_header_layout.setContentsMargins(0, 0, 0, 0)
        server_header_layout.addWidget(QLabel("Linux server files", self))
        server_header_layout.addStretch(1)
        self.refresh_server_file_list_button = QPushButton("Refresh", self)
        self.refresh_server_file_list_button.setEnabled(False)
        server_header_layout.addWidget(self.refresh_server_file_list_button)
        server_layout.addWidget(server_header)
        self.server_current_path_input = QLineEdit(self._server_sftp_directory, self)
        self.server_current_path_input.setReadOnly(True)
        self.server_current_path_input.setToolTip("Current directory on the connected Linux server.")
        server_layout.addWidget(self.server_current_path_input)
        server_layout.addWidget(self.server_file_list)
        mmu_column = QWidget(self)
        mmu_layout = QVBoxLayout(mmu_column)
        mmu_layout.setContentsMargins(0, 0, 0, 0)
        self.mmu_file_list = SftpFileListWidget("mmu", self)
        self.mmu_file_list.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.mmu_file_list.setToolTip("MMU files. Drag a file to the Linux server list to download it.")
        mmu_header = QWidget(self)
        mmu_header_layout = QHBoxLayout(mmu_header)
        mmu_header_layout.setContentsMargins(0, 0, 0, 0)
        mmu_header_layout.addWidget(QLabel("MMU files", self))
        mmu_header_layout.addStretch(1)
        self.refresh_mmu_file_list_button = QPushButton("Refresh", self)
        self.refresh_mmu_file_list_button.setEnabled(False)
        mmu_header_layout.addWidget(self.refresh_mmu_file_list_button)
        mmu_layout.addWidget(mmu_header)
        self.mmu_current_path_input = QLineEdit(self._mmu_sftp_directory, self)
        self.mmu_current_path_input.setReadOnly(True)
        self.mmu_current_path_input.setToolTip("Current directory on the connected MMU.")
        mmu_layout.addWidget(self.mmu_current_path_input)
        mmu_layout.addWidget(self.mmu_file_list)
        file_list_splitter.addWidget(server_column)
        file_list_splitter.addWidget(mmu_column)
        file_list_splitter.setStretchFactor(0, 1)
        file_list_splitter.setStretchFactor(1, 1)
        file_list_layout.addWidget(file_list_splitter)

        path_help = QLabel(
            "Drag a file from Linux server files to MMU files to upload, or drag a file "
            "from MMU files to Linux server files to download. Double-click a directory "
            "to browse into it.",
            self,
        )
        path_help.setWordWrap(True)

        layout.addWidget(transfer_actions)
        layout.addWidget(path_help)
        layout.addWidget(file_lists, stretch=1)
        return tab
