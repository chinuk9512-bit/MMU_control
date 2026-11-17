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


def test_independent_connections_with_common_variables_and_background_output(window, app):
    first = window.client_tabs.widget(0)
    second = window.add_client("Board B")
    assert first._ssh_manager is not second._ssh_manager
    assert first._config_manager.config_path != second._config_manager.config_path
    assert first._variable_store.path == second._variable_store.path
    assert first._power_supply_manager is not second._power_supply_manager
    first._variable_store.save({"TARGET": "a"})
    assert first._variable_store.load() == {"TARGET": "a"}
    assert second._variable_store.load() == {"TARGET": "a"}

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
    for session, vlan in ((first, "100"), (second, "200")):
        session._shell = Shell()
        session._sftp_shell = Shell()
        session.board_vlan_input.setText(vlan)
    first._send_sftp_command("put alpha.bin")
    second._send_sftp_command("get beta.bin")
    assert first._sftp_shell.sent == ["put alpha.bin"]
    assert second._sftp_shell.sent == ["get beta.bin"]
    first._automation_store.upsert(AutomationScenario(name="shared", steps=[
        AutomationStep("run", "echo ${MMU_VLAN}", CompletionType.OUTPUT_CONTAINS,
                       completion_value="done", timeout_seconds=100)
    ]))
    for session in (first, second):
        session.refresh_shared_definitions()
        session._run_automation_scenario()
    assert first._shell.sent == ["echo 100"]
    assert second._shell.sent == ["echo 200"]
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


def test_vlan_mac_values_are_per_client_and_restored(window):
    first = window.client_tabs.widget(0)
    second = window.add_client("MMU-B")
    template = "configure --vlan ${MMU_VLAN} --du-mac ${DU_MAC}"
    first.board_vlan_input.setText("100")
    first.du_mac_input.setText("aa:bb:cc:dd:ee:01")
    second.board_vlan_input.setText("200")
    second.du_mac_input.setText("aa-bb-cc-dd-ee-02")
    assert first._resolve_commands([template]) == ["configure --vlan 100 --du-mac AA:BB:CC:DD:EE:01"]
    assert second._resolve_commands([template]) == ["configure --vlan 200 --du-mac AA:BB:CC:DD:EE:02"]
    assert window.close()
    restored = ClientTabsWindow(window._data_directory, window._session_factory)
    try:
        a, b = restored.client_tabs.widget(0), restored.client_tabs.widget(1)
        assert (a.board_vlan_input.text(), a.du_mac_input.text()) == ("100", "aa:bb:cc:dd:ee:01")
        assert (b.board_vlan_input.text(), b.du_mac_input.text()) == ("200", "aa-bb-cc-dd-ee-02")
        assert a._resolve_commands([template]) != b._resolve_commands([template])
    finally:
        restored.close()


@pytest.mark.parametrize("vlan", ["", "0", "4095", "12; reboot", "1.5"])
def test_invalid_vlan_blocks_entire_command_group(window, vlan):
    from mmu_control.models.command_set import CommandSet
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    session.board_vlan_input.setText(vlan)
    session._command_set_store.upsert(CommandSet(name="config", commands="echo start\nset-vlan ${MMU_VLAN}"))
    session.refresh_shared_definitions()
    session._run_command_set()
    assert session._shell.sent == []
    assert "MMU_VLAN" in session.terminal_widget.toPlainText()


@pytest.mark.parametrize("mac", ["", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:GG", "AA:BB-CC:DD:EE:FF"])
def test_invalid_du_mac_blocks_scenario_before_first_command(window, mac):
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    session.du_mac_input.setText(mac)
    session._automation_store.upsert(AutomationScenario(name="config", steps=[
        AutomationStep("first", "echo start"),
        AutomationStep("mac", "set-mac ${DU_MAC}"),
    ]))
    session.refresh_shared_definitions()
    session._run_automation_scenario()
    assert session._shell.sent == []
    assert "DU_MAC" in session.automation_status_label.text()


def test_scenario_keeps_initial_vlan_mac_snapshot(window):
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    session.board_vlan_input.setText("100")
    session.du_mac_input.setText("AA:BB:CC:DD:EE:01")
    session._automation_store.upsert(AutomationScenario(name="snapshot", steps=[
        AutomationStep("wait", "set-vlan ${MMU_VLAN}", CompletionType.OUTPUT_CONTAINS,
                       completion_value="continue", timeout_seconds=100),
        AutomationStep("apply", "apply ${MMU_VLAN} ${DU_MAC}"),
    ]))
    session.refresh_shared_definitions()
    session._run_automation_scenario()
    session.board_vlan_input.setText("200")
    session.du_mac_input.setText("AA:BB:CC:DD:EE:02")
    session._automation_runner.receive_output("continue")
    assert session._shell.sent == ["set-vlan 100", "apply 100 AA:BB:CC:DD:EE:01"]


def test_unreferenced_inputs_and_escaped_placeholders_do_not_require_values(window):
    session = window.client_tabs.widget(0)
    session.board_vlan_input.setText("not configured")
    assert session._resolve_commands(["echo hello", "echo $${MMU_VLAN}"]) == [
        "echo hello", "echo ${MMU_VLAN}"
    ]


def test_input_fields_override_variable_file_and_vlan_boundaries(window):
    from mmu_control.storage.variable_store import VariableStoreError
    session = window.client_tabs.widget(0)
    session._variable_store.save({"MMU_VLAN": "999", "DU_MAC": "stale", "OTHER": "retained"})
    for vlan in ("1", "4094"):
        session.board_vlan_input.setText(vlan)
        session.du_mac_input.setText("AA:BB:CC:DD:EE:FF")
        assert session._resolve_commands(["${MMU_VLAN} ${DU_MAC} ${OTHER}"]) == [
            f"{vlan} AA:BB:CC:DD:EE:FF retained"
        ]
    session.board_vlan_input.clear()
    with pytest.raises(VariableStoreError, match="MMU_VLAN"):
        session._resolve_commands(["${MMU_VLAN}"])


def test_starting_at_later_step_does_not_require_skipped_input(window):
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    session._automation_store.upsert(AutomationScenario(name="partial", steps=[
        AutomationStep("skipped", "set-vlan ${MMU_VLAN}"),
        AutomationStep("run", "echo later"),
    ]))
    session.refresh_shared_definitions()
    session.automation_start_step_input.setCurrentIndex(1)
    session._run_automation_scenario()
    assert session._shell.sent == ["echo later"]


def test_all_clients_ignore_legacy_local_files_and_use_only_common_variables(window):
    from mmu_control.storage.variable_store import VariableStore
    shared = VariableStore(window._data_directory / "variables.json")
    shared.save({"MMU_PW_2": "shared-example"})
    first = window.client_tabs.widget(0)
    second = window.add_client("Second")
    third = window.add_client("Third")
    command = "example --password ${MMU_PW_2}"
    for session in (first, second, third):
        assert session._resolve_commands([command]) == ["example --password shared-example"]
    legacy = VariableStore(second._config_manager.config_path.parent / "variables.json")
    legacy.save({"MMU_PW_2": "ignored-client-example"})
    original_legacy = legacy.path.read_bytes()
    assert second._resolve_commands([command]) == ["example --password shared-example"]
    assert third._resolve_commands([command]) == ["example --password shared-example"]
    assert first._resolve_commands([command]) == ["example --password shared-example"]
    second._shell = Shell()
    second._automation_store.upsert(AutomationScenario(name="shared-vars", steps=[
        AutomationStep("run", command),
    ]))
    second.refresh_shared_definitions()
    second._run_automation_scenario()
    assert second._shell.sent == ["example --password shared-example"]
    shared.save({"MMU_PW_2": "updated-example"})
    for session in (first, second, third):
        assert session._resolve_commands([command]) == ["example --password updated-example"]
    assert legacy.path.read_bytes() == original_legacy
    shared.save({})
    from mmu_control.core.variable_resolver import MissingVariablesError
    with pytest.raises(MissingVariablesError, match="MMU_PW_2"):
        second._resolve_commands([command])


def test_mmu_mac_is_per_client_restored_and_shares_network_row(window, app):
    from PySide6.QtCore import QPoint
    first = window.client_tabs.widget(0)
    second = window.add_client("Second")
    first.mmu_mac_input.setText("aa-bb-cc-dd-ee-01")
    second.mmu_mac_input.setText("aa:bb:cc:dd:ee:02")
    assert first._resolve_commands(["set ${MMU_MAC}"]) == ["set AA:BB:CC:DD:EE:01"]
    assert second._resolve_commands(["set ${MMU_MAC}"]) == ["set AA:BB:CC:DD:EE:02"]
    window.show()
    app.processEvents()
    fields = (second.board_vlan_input, second.du_mac_input, second.mmu_mac_input)
    positions = [field.mapTo(window, QPoint()) for field in fields]
    assert len({point.y() for point in positions}) == 1
    assert positions[0].x() < positions[1].x() < positions[2].x()
    assert window.close()
    restored = ClientTabsWindow(window._data_directory, window._session_factory)
    try:
        assert restored.client_tabs.widget(0).mmu_mac_input.text() == "aa-bb-cc-dd-ee-01"
        assert restored.client_tabs.widget(1).mmu_mac_input.text() == "aa:bb:cc:dd:ee:02"
    finally:
        restored.close()


@pytest.mark.parametrize("mac", ["", "AA:BB:CC:DD:EE", "AA:BB:CC:DD:EE:GG", "AA:BB-CC:DD:EE:FF"])
def test_invalid_mmu_mac_blocks_scenario_before_first_command(window, mac):
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    session.mmu_mac_input.setText(mac)
    session._automation_store.upsert(AutomationScenario(name="config", steps=[
        AutomationStep("first", "echo start"),
        AutomationStep("mac", "set-mac ${MMU_MAC}"),
    ]))
    session.refresh_shared_definitions()
    session._run_automation_scenario()
    assert session._shell.sent == []
    assert "MMU_MAC" in session.automation_status_label.text()


def test_mmu_mac_snapshot_and_input_precedence(window):
    session = window.client_tabs.widget(0)
    session._variable_store.save({"MMU_MAC": "stale-file-value"})
    assert session._resolve_commands(["echo unused"]) == ["echo unused"]
    session._shell = Shell()
    session.mmu_mac_input.setText("AA:BB:CC:DD:EE:01")
    session._automation_store.upsert(AutomationScenario(name="snapshot", steps=[
        AutomationStep("wait", "echo waiting", CompletionType.OUTPUT_CONTAINS,
                       completion_value="continue", timeout_seconds=100),
        AutomationStep("apply", "set ${MMU_MAC}"),
    ]))
    session.refresh_shared_definitions()
    session._run_automation_scenario()
    session.mmu_mac_input.setText("AA:BB:CC:DD:EE:02")
    session._automation_runner.receive_output("continue")
    assert session._shell.sent == ["echo waiting", "set AA:BB:CC:DD:EE:01"]


@pytest.mark.parametrize("base,attribute", [("DU_MAC", "du_mac_input"), ("MMU_MAC", "mmu_mac_input")])
@pytest.mark.parametrize("mac,full,head,tail", [
    ("12:34:56:78:90:12", "12:34:56:78:90:12", "1234", "56789012"),
    ("00-01-00-02-0a-bc", "00:01:00:02:0A:BC", "0001", "00020ABC"),
])
def test_mac_parts_preserve_hex_digits(window, base, attribute, mac, full, head, tail):
    session = window.client_tabs.widget(0)
    getattr(session, attribute).setText(mac)
    template = "${" + base + "} 0x${" + base + "_HEAD} 0x${" + base + "_TAIL}"
    assert session._resolve_commands([template]) == [f"{full} 0x{head} 0x{tail}"]


@pytest.mark.parametrize("base,attribute", [("DU_MAC", "du_mac_input"), ("MMU_MAC", "mmu_mac_input")])
@pytest.mark.parametrize("suffix", ["HEAD", "TAIL"])
def test_mac_part_requires_valid_client_input_even_with_common_override(window, base, attribute, suffix):
    from mmu_control.models.command_set import CommandSet
    session = window.client_tabs.widget(0)
    session._shell = Shell()
    name = f"{base}_{suffix}"
    session._variable_store.save({name: "stale-file-value"})
    session._command_set_store.upsert(CommandSet(name="parts", commands="echo start\nset ${" + name + "}"))
    session.refresh_shared_definitions()
    for mac in ("", "invalid"):
        getattr(session, attribute).setText(mac)
        session._run_command_set()
        assert session._shell.sent == []
        assert base in session.terminal_widget.toPlainText()


@pytest.mark.parametrize("base,attribute", [("DU_MAC", "du_mac_input"), ("MMU_MAC", "mmu_mac_input")])
def test_mac_parts_are_client_specific_and_scenario_snapshot_is_stable(window, base, attribute):
    first = window.client_tabs.widget(0)
    second = window.add_client("Second")
    getattr(first, attribute).setText("00:01:00:02:0A:BC")
    getattr(second, attribute).setText("12:34:56:78:90:12")
    command = "set ${" + base + "_HEAD} ${" + base + "_TAIL}"
    assert first._resolve_commands([command]) == ["set 0001 00020ABC"]
    assert second._resolve_commands([command]) == ["set 1234 56789012"]
    first._shell = Shell()
    first._automation_store.upsert(AutomationScenario(name="parts", steps=[
        AutomationStep("wait", "echo waiting", CompletionType.OUTPUT_CONTAINS,
                       completion_value="continue", timeout_seconds=100),
        AutomationStep("apply", command),
    ]))
    first.refresh_shared_definitions()
    first._run_automation_scenario()
    getattr(first, attribute).setText("FF:FF:FF:FF:FF:FF")
    first._automation_runner.receive_output("continue")
    assert first._shell.sent == ["echo waiting", "set 0001 00020ABC"]


def test_mac_tooltips_follow_click_and_tab_without_expanding_layout(window, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    session = window.client_tabs.widget(0)
    window.show()
    app.processEvents()
    session.ssh_host_input.setFocus()
    app.processEvents()
    assert not hasattr(session, "mac_variable_hint")
    with patch("mmu_control.ui.main_window.QToolTip.showText") as show, patch(
        "mmu_control.ui.main_window.QToolTip.hideText"
    ) as hide:
        QTest.mouseClick(session.du_mac_input, Qt.MouseButton.LeftButton)
        app.processEvents()
        text = show.call_args.args[1]
        assert show.call_args.args[2] is session.du_mac_input
        for name in ("${DU_MAC}", "${DU_MAC_HEAD}", "${DU_MAC_TAIL}"):
            assert name in text
        assert "${MMU_MAC}" not in text
        show.reset_mock()
        # Clicking an already-focused input should show its tooltip again.
        QTest.mouseClick(session.du_mac_input, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert show.called
        QTest.keyClicks(session.du_mac_input, "12:34:56:78:90:12")
        assert session.du_mac_input.text() == "12:34:56:78:90:12"
        QTest.keyClick(session.du_mac_input, Qt.Key.Key_Tab)
        app.processEvents()
        assert session.mmu_mac_input.hasFocus()
        text = show.call_args.args[1]
        assert show.call_args.args[2] is session.mmu_mac_input
        for name in ("${MMU_MAC}", "${MMU_MAC_HEAD}", "${MMU_MAC_TAIL}"):
            assert name in text
        assert "${DU_MAC}" not in text
        show.reset_mock()
        hide.reset_mock()
        session.ssh_host_input.setFocus()
        app.processEvents()
        hide.assert_called()
        show.assert_not_called()


def test_variable_catalog_uses_current_client_and_reserved_input_precedence(window):
    first = window.client_tabs.widget(0)
    second = window.add_client("Other")
    first.board_vlan_input.setText("100")
    second.board_vlan_input.setText("200")
    first.du_mac_input.setText("00:01:00:02:0A:BC")
    first._variable_store.save({"MMU_PW_2": "shared-example", "MMU_VLAN": "stale"})
    entries, error = first._variable_catalog()
    assert not error
    by_name = {entry.name: entry for entry in entries}
    assert len(by_name) == 8
    assert by_name["MMU_PW_2"].source == "Common variables.json"
    assert by_name["MMU_PW_2"].value == "shared-example"
    assert by_name["MMU_VLAN"].value == "100"
    assert by_name["DU_MAC_HEAD"].value == "0001"
    assert by_name["DU_MAC_TAIL"].value == "00020ABC"
    assert by_name["MMU_MAC"].value is None
    assert {entry.name: entry.value for entry in second._variable_catalog()[0]}["MMU_VLAN"] == "200"
    first._variable_store.save({"NEW_NAME": "updated-example"})
    assert "NEW_NAME" in {entry.name for entry in first._variable_catalog()[0]}
    # Malformed files must still leave the built-in names discoverable.
    first._variable_store.path.write_text('{"broken":')
    entries, error = first._variable_catalog()
    assert error and len(entries) == 7
    assert all(entry.value is None for entry in entries)


def test_variables_button_opens_catalog_even_when_connection_fields_are_hidden(window):
    session = window.client_tabs.widget(0)
    session.connection_panel_toggle_button.setChecked(False)
    assert not session.variable_list_button.isHidden()
    with patch("mmu_control.ui.main_window.VariableListDialog.exec", return_value=0) as opened:
        session.variable_list_button.click()
    opened.assert_called_once()


def test_vlan_variable_tooltip_on_click_repeated_click_and_tab(window, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    session = window.client_tabs.widget(0)
    window.show()
    app.processEvents()
    session.board_name_input.setFocus()
    app.processEvents()
    assert "${MMU_VLAN}" in session.board_vlan_input.toolTip()
    with patch("mmu_control.ui.main_window.QToolTip.showText") as show:
        QTest.mouseClick(session.board_vlan_input, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert show.call_args.args[2] is session.board_vlan_input
        assert "${MMU_VLAN}" in show.call_args.args[1]
        show.reset_mock()
        QTest.mouseClick(session.board_vlan_input, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert show.called
        session.board_name_input.setFocus()
        app.processEvents()
        show.reset_mock()
        QTest.keyClick(session.board_name_input, Qt.Key.Key_Tab)
        app.processEvents()
        assert session.board_vlan_input.hasFocus()
        assert show.call_args.args[2] is session.board_vlan_input
        assert "${MMU_VLAN}" in show.call_args.args[1]
