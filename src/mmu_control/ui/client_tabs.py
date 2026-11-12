"""One application window containing independently connected client workspaces."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QInputDialog, QMainWindow, QMessageBox, QPushButton, QTabWidget,
)

from mmu_control.core.config_manager import ConfigManager, default_user_data_directory
from mmu_control.storage.variable_store import VariableStore
from mmu_control.ui.main_window import MainWindow


class ClientTabsWindow(QMainWindow):
    """Host complete, independent client sessions in movable, closable tabs."""

    def __init__(
        self,
        data_directory: Path | None = None,
        session_factory: Callable[..., MainWindow] = MainWindow,
    ) -> None:
        super().__init__()
        self._data_directory = data_directory or default_user_data_directory()
        self._manifest_path = self._data_directory / "client_tabs.json"
        self._session_factory = session_factory
        self._restoring = True
        self.setWindowTitle("MMU Control")
        self.resize(1840, 950)
        self.setMinimumSize(1196, 600)
        self.client_tabs = QTabWidget(self)
        self.client_tabs.setMovable(True)
        self.client_tabs.setTabsClosable(True)
        self.setCentralWidget(self.client_tabs)
        self.add_client_button = QPushButton("+", self)
        self.add_client_button.setToolTip("Add client")
        self.add_client_button.setAccessibleName("Add client")
        self.client_tabs.setCornerWidget(self.add_client_button, Qt.Corner.TopRightCorner)
        self.add_client_button.clicked.connect(lambda: self.add_client())
        self.client_tabs.tabCloseRequested.connect(self.close_client)
        self.client_tabs.tabBarDoubleClicked.connect(self.rename_client)
        self.client_tabs.tabBar().tabMoved.connect(lambda *_: self._save_tabs())
        self.client_tabs.currentChanged.connect(self._current_changed)
        self._restore_tabs()
        self._restoring = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(250)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()
        self._refresh_status()

    def add_client(
        self, name: str | None = None, client_id: str | None = None,
        *, fallback_name: str | None = None,
    ) -> MainWindow:
        """Create a disconnected client with its own managers, variables and settings."""
        client_id = client_id or uuid4().hex
        directory = self._data_directory if client_id == "default" else self._data_directory / "clients" / client_id
        session = self._session_factory(
            config_manager=ConfigManager(directory / "settings.json"),
            variable_store=VariableStore(directory / "variables.json"),
        )
        # QMainWindow is also a QWidget: keep the existing workspace and status
        # bar intact while embedding it instead of creating another OS window.
        session.setWindowState(Qt.WindowState.WindowNoState)
        session.setWindowFlags(Qt.WindowType.Widget)
        session.setProperty("client_id", client_id)
        default_name = f"Client {self.client_tabs.count() + 1}"
        generated_name = name if name and re.fullmatch(r"Client \d+", name) else None
        session.setProperty("client_fallback_name", fallback_name or generated_name or default_name)
        # Version-one manifests stored both generated labels and user names in
        # the same field. Migrate custom labels without masking the IP fallback.
        if name and not re.fullmatch(r"Client \d+", name) and not session.board_name_input.text().strip():
            session.board_name_input.setText(name)
        session.setProperty("client_name", self._client_label(session))
        session.board_name_input.textChanged.connect(self._identity_changed)
        session.board_ip_input.textChanged.connect(self._identity_changed)
        session.ssh_host_input.textChanged.connect(self._refresh_status)
        index = self.client_tabs.addTab(session, session.property("client_name"))
        self.client_tabs.setCurrentIndex(index)
        self._save_tabs()
        return session

    def rename_client(self, index: int) -> None:
        """Rename a client by double-clicking its tab."""
        if index < 0 or index >= self.client_tabs.count():
            return
        session = self.client_tabs.widget(index)
        name, accepted = QInputDialog.getText(
            self, "Rename client", "Device name (leave empty to use Client IP):",
            text=session.board_name_input.text(),
        )
        if accepted:
            session.board_name_input.setText(name.strip())

    def close_client(self, index: int) -> None:
        """Disconnect and remove only the selected client after confirming active work."""
        if index < 0 or index >= self.client_tabs.count():
            return
        session = self.client_tabs.widget(index)
        if not self._can_close([session]):
            return
        if not session.close():
            return
        self.client_tabs.removeTab(index)
        session.deleteLater()
        if not self.client_tabs.count():
            self.add_client()
        self._save_tabs()

    def _can_close(self, sessions: list[MainWindow]) -> bool:
        if any(session.has_pending_tasks for session in sessions):
            QMessageBox.information(
                self, "Client is busy",
                "A connection or file operation is still running. Wait for it to finish before closing.",
            )
            return False
        active = [session.property("client_name") for session in sessions if session.has_active_session]
        if active:
            return QMessageBox.question(
                self, "Close connected clients?",
                "Disconnect and stop running work for: " + ", ".join(active) + "?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            ) == QMessageBox.StandardButton.Yes
        return True

    def _current_changed(self, index: int) -> None:
        if index >= 0:
            # Definitions are shared, but executions and variable stores are not.
            session = self.client_tabs.widget(index)
            session.refresh_shared_definitions()
        self._save_tabs()

    @staticmethod
    def _client_label(session: MainWindow) -> str:
        return (
            session.board_name_input.text().strip()
            or session.board_ip_input.text().strip()
            or session.property("client_fallback_name")
        )

    def _identity_changed(self) -> None:
        self._refresh_status()
        self._save_tabs()

    def _refresh_status(self) -> None:
        for index in range(self.client_tabs.count()):
            session = self.client_tabs.widget(index)
            status = "connected" if session.has_active_session else "disconnected"
            if session.has_pending_tasks:
                status = "busy"
            name = self._client_label(session)
            session.setProperty("client_name", name)
            self.client_tabs.setTabText(index, f"{name} — {status}")
            self.client_tabs.setTabToolTip(index, "\n".join((
                f"Device: {session.board_name_input.text().strip() or '(unnamed)'}",
                f"Client IP: {session.board_ip_input.text().strip() or '(not set)'}",
                f"SSH server: {session.ssh_host_input.text().strip() or '(not set)'}",
                session.connection_status_label.text(),
                session.board_status_label.text(),
            )))
        current = self.client_tabs.currentWidget()
        if current is not None:
            self.setWindowTitle(f"MMU Control — {self._client_label(current)}")

    def _restore_tabs(self) -> None:
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("clients"), list) or not raw["clients"]:
                raise ValueError("Expected a nonempty client list")
            clients = raw["clients"]
            seen: set[str] = set()
            for entry in clients:
                if not isinstance(entry, dict):
                    raise ValueError("Invalid client entry")
                client_id, name = entry.get("id"), entry.get("name")
                if not isinstance(client_id, str) or not isinstance(name, str) or not name.strip():
                    raise ValueError("Invalid client identity")
                if client_id != "default" and UUID(client_id).hex != client_id:
                    raise ValueError("Invalid client ID")
                if client_id in seen:
                    raise ValueError("Duplicate client ID")
                seen.add(client_id)
        except FileNotFoundError:
            self.add_client("Client 1", "default")
            return
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            self.statusBar().showMessage(f"Could not restore client tabs: {exc}")
            # Never overwrite a malformed manifest automatically.
            self._manifest_invalid = True
            self.add_client("Client 1", "default")
            return
        for entry in clients:
            if raw.get("schema_version", 1) == 1:
                self.add_client(entry["name"], entry["id"])
            else:
                self.add_client(client_id=entry["id"], fallback_name=entry["name"])
        active_id = raw.get("active_client")
        for index in range(self.client_tabs.count()):
            if self.client_tabs.widget(index).property("client_id") == active_id:
                self.client_tabs.setCurrentIndex(index)
                break

    def _save_tabs(self) -> bool:
        if self._restoring or getattr(self, "_manifest_invalid", False):
            return True
        clients = [
            {"id": self.client_tabs.widget(i).property("client_id"),
             "name": self.client_tabs.widget(i).property("client_fallback_name")}
            for i in range(self.client_tabs.count())
        ]
        current = self.client_tabs.currentWidget()
        data = {"schema_version": 2, "clients": clients,
                "active_client": current.property("client_id") if current else None}
        try:
            self._data_directory.mkdir(parents=True, exist_ok=True)
            temporary = self._manifest_path.with_suffix(".json.tmp")
            temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self._manifest_path)
        except OSError as exc:
            self.statusBar().showMessage(f"Could not save client tabs: {exc}")
            return False
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """Persist the tab layout and clean up every client on application exit."""
        sessions = [self.client_tabs.widget(i) for i in range(self.client_tabs.count())]
        if not self._can_close(sessions) or not self._save_tabs():
            event.ignore()
            return
        for session in sessions:
            session.close()
        self._status_timer.stop()
        event.accept()
