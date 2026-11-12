"""Multi-client lifecycle and routing tests without network or real hardware."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from mmu_control.core.automation_runner import AutomationRunner
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType
from mmu_control.storage.automation_store import AutomationStore
from mmu_control.storage.command_set_store import CommandSetStore
from mmu_control.ui.client_tabs import ClientTabsWindow
from mmu_control.ui.main_window import MainWindow


class Shell:
    """Record writes and supply output independently for each client."""

    def __init__(self) -> None:
        self.is_open = True
        self.output = ""
        self.sent: list[str] = []

    def send_line(self, command: str) -> None:
        self.sent.append(command)

    def read_available(self) -> str:
        output, self.output = self.output, ""
        return output

    def close(self) -> None:
        self.is_open = False


class Manager:
    """Track whether this client's SSH manager was disconnected."""

    def __init__(self) -> None:
        self.disconnected = False

    def disconnect(self) -> None:
        self.disconnected = True


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, app):
    def factory(**kwargs):
        return MainWindow(
            ssh_manager=Manager(),
            command_set_store=CommandSetStore(tmp_path / "commands.json"),
            automation_store=AutomationStore(tmp_path / "scenarios.json"),
            **kwargs,
        )

    host = ClientTabsWindow(tmp_path / "data", factory)
    yield host
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        host.close()
    app.processEvents()


def test_independent_ssh_sftp_variables_and_background_output(window, app):
    first = window.client_tabs.widget(0)
    second = window.add_client("Board B")
    assert first._ssh_manager is not second._ssh_manager
    assert first._config_manager.config_path != second._config_manager.config_path
    assert first._variable_store.path != second._variable_store.path
    assert first._power_supply_manager is not second._power_supply_manager
    first._variable_store.save({"TARGET": "a"})
    second._variable_store.save({"TARGET": "b"})
    assert first._variable_store.load() == {"TARGET": "a"}
    assert second._variable_store.load() == {"TARGET": "b"}

    a, b = Shell(), Shell()
    first._shell, second._shell = a, b
    first._sftp_shell, second._sftp_shell = Shell(), Shell()
    first.terminal_widget.commandSubmitted.emit("echo first")
    second.terminal_widget.commandSubmitted.emit("echo second")
    assert a.sent == ["echo first"]
    assert b.sent == ["echo second"]
    first._pending_echo = second._pending_echo = None
    a.output, b.output = "first-only\r\n", "second-only\r\n"
    first._shell_timer.start()
    second._shell_timer.start()
    window.client_tabs.setCurrentIndex(1)
    # Exercise the real Qt timer path while the first client is hidden.
    from PySide6.QtTest import QTest
    QTest.qWait(120)
    assert "first-only" in first.terminal_widget.toPlainText()
    assert "second-only" not in first.terminal_widget.toPlainText()
    assert "second-only" in second.terminal_widget.toPlainText()
    assert first._shell_timer.isActive()
    window._refresh_status()
    assert "Board B" in window.client_tabs.tabText(1)
    assert window.client_tabs.tabText(1).endswith("— connected")


def test_closing_one_client_stops_only_its_resources(window):
    first = window.client_tabs.widget(0)
    second = window.add_client("Keep me")
    first._shell, second._shell = Shell(), Shell()
    first._sftp_shell, second._sftp_shell = Shell(), Shell()
    removed_sftp = first._sftp_shell
    first._automation_runner = AutomationRunner(first._shell.send_line)
    first._automation_runner.start(AutomationScenario(name="running", steps=[
        AutomationStep("wait", "run", CompletionType.DELAY, timeout_seconds=100)
    ]))
    for timer in first.findChildren(QTimer):
        timer.start(10000)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        window.close_client(0)
    assert window.client_tabs.count() == 2
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        window.close_client(0)
    assert window.client_tabs.count() == 1
    assert first._ssh_manager.disconnected
    assert not removed_sftp.is_open
    assert not first._automation_runner.is_active
    assert all(not timer.isActive() for timer in first.findChildren(QTimer))
    assert second._shell.is_open and second._sftp_shell.is_open
    assert not second._ssh_manager.disconnected


def test_busy_client_blocks_tab_and_application_close(window):
    session = window.client_tabs.widget(0)
    class BusyRunner:
        has_pending_tasks = True
    session._task_runner = BusyRunner()
    with patch.object(QMessageBox, "information") as message:
        window.close_client(0)
        assert not window.close()
    assert message.call_count == 2
    assert window.client_tabs.widget(0) is session
    assert not session._closing
    session._task_runner.has_pending_tasks = False


def test_restart_restores_names_order_fields_and_active_tab_without_connecting(window):
    first = window.client_tabs.widget(0)
    first.ssh_host_input.setText("gateway-a")
    second = window.add_client("Board B")
    second.board_ip_input.setText("192.0.2.5")
    second.power_supply_ip_input.setText("192.0.2.6")
    with patch("mmu_control.ui.client_tabs.QInputDialog.getText", return_value=("Board A", True)):
        window.rename_client(0)
    window.client_tabs.tabBar().moveTab(1, 0)
    window.client_tabs.setCurrentIndex(0)
    assert window.close()
    restored = ClientTabsWindow(window._data_directory, window._session_factory)
    try:
        assert restored.client_tabs.count() == 2
        b, a = restored.client_tabs.widget(0), restored.client_tabs.widget(1)
        assert b.property("client_name") == "Board B"
        assert a.property("client_name") == "Board A"
        assert a.ssh_host_input.text() == "gateway-a"
        assert b.board_ip_input.text() == "192.0.2.5"
        assert b.power_supply_ip_input.text() == "192.0.2.6"
        assert restored.client_tabs.currentIndex() == 0
        assert not a.has_active_session and not b.has_active_session
    finally:
        restored.close()


def test_last_tab_can_be_closed_and_replaced(window):
    old_id = window.client_tabs.widget(0).property("client_id")
    window.close_client(0)
    assert window.client_tabs.count() == 1
    assert window.client_tabs.widget(0).property("client_id") != old_id


def test_invalid_manifest_is_preserved_and_cannot_escape_data_directory(tmp_path, app):
    path = tmp_path / "client_tabs.json"
    raw = json.dumps({"clients": [{"id": "../../escape", "name": "bad"}]})
    path.write_text(raw)
    def factory(**kwargs):
        return MainWindow(command_set_store=CommandSetStore(tmp_path / "commands.json"),
                          automation_store=AutomationStore(tmp_path / "scenarios.json"), **kwargs)
    host = ClientTabsWindow(tmp_path, factory)
    assert host.client_tabs.count() == 1
    assert "Could not restore" in host.statusBar().currentMessage()
    host.close()
    assert path.read_text() == raw


def test_sftp_commands_and_simultaneous_scenarios_use_their_own_client(window):
    first = window.client_tabs.widget(0)
    second = window.add_client("Second")
    for session, target in ((first, "alpha"), (second, "beta")):
        session._shell = Shell()
        session._sftp_shell = Shell()
        session._variable_store.save({"TARGET": target})
    first._send_sftp_command("put alpha.bin")
    second._send_sftp_command("get beta.bin")
    assert first._sftp_shell.sent == ["put alpha.bin"]
    assert second._sftp_shell.sent == ["get beta.bin"]
    first._automation_store.upsert(AutomationScenario(name="shared", steps=[
        AutomationStep("run", "echo ${TARGET}", CompletionType.OUTPUT_CONTAINS,
                       completion_value="done", timeout_seconds=100)
    ]))
    for session in (first, second):
        session.refresh_shared_definitions()
        session._run_automation_scenario()
    assert first._shell.sent == ["echo alpha"]
    assert second._shell.sent == ["echo beta"]
    first_runner, second_runner = first._automation_runner, second._automation_runner
    window.client_tabs.setCurrentIndex(0)
    window.client_tabs.setCurrentIndex(1)
    assert first._automation_runner is first_runner
    assert second._automation_runner is second_runner
    first._shell.output = "done\n"
    first._poll_shell()
    assert first_runner.status.state.value == "succeeded"
    assert second_runner.is_active
    second._shell.output = "done\n"
    second._poll_shell()
    assert second_runner.status.state.value == "succeeded"


def test_real_worker_prevents_close_until_its_callback_completes(window, app):
    from threading import Event
    from PySide6.QtTest import QTest
    session = window.client_tabs.widget(0)
    release = Event()
    results = []
    session._task_runner.submit(lambda: release.wait(timeout=5), results.append, results.append)
    try:
        assert session.has_pending_tasks
        with patch.object(QMessageBox, "information"):
            window.close_client(0)
        assert window.client_tabs.widget(0) is session
    finally:
        release.set()
        for _ in range(100):
            QTest.qWait(10)
            if not session.has_pending_tasks:
                break
    assert not session.has_pending_tasks
    assert results == [True]
    window.close_client(0)
    assert window.client_tabs.widget(0) is not session


def test_local_process_is_killed_only_for_closed_client(window):
    import sys
    from PySide6.QtCore import QProcess
    first = window.client_tabs.widget(0)
    second = window.add_client("Other process")
    processes = []
    try:
        for session in (first, second):
            process = QProcess(session)
            process.start(sys.executable, ["-c", "import time; time.sleep(60)"])
            assert process.waitForStarted(1000)
            session._local_process = process
            processes.append(process)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            window.close_client(0)
        assert processes[0].state() == QProcess.ProcessState.NotRunning
        assert processes[1].state() == QProcess.ProcessState.Running
    finally:
        second._close_local_process()


def test_cancelling_application_close_preserves_every_connected_client(window):
    first = window.client_tabs.widget(0)
    second = window.add_client("Second")
    first._shell, second._shell = Shell(), Shell()
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.No):
        assert not window.close()
    assert not first._closing and not second._closing
    assert first._shell.is_open and second._shell.is_open
    assert window._status_timer.isActive()


def test_client_label_uses_device_name_then_client_ip_then_default(window):
    session = window.client_tabs.widget(0)
    assert session.property("client_name") == "Client 1"
    session.ssh_host_input.setText("gateway.example")
    assert session.property("client_name") == "Client 1"
    session.board_ip_input.setText("192.0.2.42")
    assert window.client_tabs.tabText(0) == "192.0.2.42 — disconnected"
    session.board_name_input.setText(" MMU-A ")
    assert window.client_tabs.tabText(0) == "MMU-A — disconnected"
    assert window.windowTitle() == "MMU Control — MMU-A"
    tooltip = window.client_tabs.tabToolTip(0)
    assert "Client IP: 192.0.2.42" in tooltip
    assert "SSH server: gateway.example" in tooltip
    session._shell = Shell()
    window._refresh_status()
    assert window.client_tabs.tabText(0) == "MMU-A — connected"
    session._shell.close()
    window._refresh_status()
    assert window.client_tabs.tabText(0) == "MMU-A — disconnected"
    session.board_name_input.clear()
    assert session.property("client_name") == "192.0.2.42"
    session.board_ip_input.clear()
    assert session.property("client_name") == "Client 1"


def test_double_click_rename_updates_device_field_and_can_clear_override(window):
    session = window.client_tabs.widget(0)
    session.board_ip_input.setText("192.0.2.42")
    with patch("mmu_control.ui.client_tabs.QInputDialog.getText", return_value=("MMU-A", True)):
        window.rename_client(0)
    assert session.board_name_input.text() == "MMU-A"
    with patch("mmu_control.ui.client_tabs.QInputDialog.getText", return_value=("", False)):
        window.rename_client(0)
    assert session.property("client_name") == "MMU-A"
    with patch("mmu_control.ui.client_tabs.QInputDialog.getText", return_value=("", True)):
        window.rename_client(0)
    assert session.board_name_input.text() == ""
    assert session.property("client_name") == "192.0.2.42"


def test_ip_fallback_stays_automatic_after_restart(window):
    session = window.client_tabs.widget(0)
    session.board_ip_input.setText("192.0.2.42")
    assert window.close()
    restored = ClientTabsWindow(window._data_directory, window._session_factory)
    try:
        session = restored.client_tabs.widget(0)
        assert session.board_name_input.text() == ""
        assert session.property("client_name") == "192.0.2.42"
        session.board_ip_input.setText("192.0.2.43")
        assert session.property("client_name") == "192.0.2.43"
        session.board_ip_input.clear()
        assert session.property("client_name") == "Client 1"
    finally:
        restored.close()


def test_legacy_tab_names_migrate_to_device_names_without_overriding_defaults(window):
    assert window.close()
    path = window._manifest_path
    path.write_text(json.dumps({"schema_version": 1, "clients": [
        {"id": "default", "name": "Legacy board"},
        {"id": "a" * 32, "name": "Client 7"},
    ]}))
    restored = ClientTabsWindow(window._data_directory, window._session_factory)
    try:
        first, second = restored.client_tabs.widget(0), restored.client_tabs.widget(1)
        assert first.board_name_input.text() == "Legacy board"
        assert first.property("client_name") == "Legacy board"
        assert second.board_name_input.text() == ""
        assert second.property("client_name") == "Client 7"
        second.board_ip_input.setText("192.0.2.7")
        assert second.property("client_name") == "192.0.2.7"
    finally:
        restored.close()
