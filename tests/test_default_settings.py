"""Defaults persist selected connection groups without migration or geometry."""

import json

import pytest
from PySide6.QtWidgets import QApplication

from mmu_control.core.config_manager import ConfigError
from mmu_control.models.settings import AppSettings, SSHSettings, BoardSettings, PowerSupplySettings
from mmu_control.storage.default_settings_store import DefaultSettingsStore
from mmu_control.ui.default_settings_dialog import DefaultSettingsDialog


def test_only_selected_groups_are_saved_and_replaced(tmp_path):
    store = DefaultSettingsStore(tmp_path / "default_settings.json")
    settings = AppSettings(ssh=SSHSettings(host="server"), board=BoardSettings(ip_address="192.0.2.1"))
    assert store.load()[1] == frozenset()
    assert not store.path.exists()
    store.save(settings, {"ssh", "board"})
    assert set(json.loads(store.path.read_text())) == {"schema_version", "ssh", "board"}
    restored, groups = store.load()
    assert groups == {"ssh", "board"} and restored.board.ip_address == "192.0.2.1"
    store.save(settings, {"ssh"})
    assert store.load()[1] == {"ssh"}
    assert "board" not in json.loads(store.path.read_text())
    before = store.path.read_bytes()
    with pytest.raises(ConfigError):
        store.save(settings, set())
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("raw", ['[]', '{"ssh": "invalid"}', '{"ssh": {"port": "private-example"}}', '{broken'])
def test_invalid_defaults_are_reported_without_values(tmp_path, raw):
    store = DefaultSettingsStore(tmp_path / "default_settings.json")
    store.path.write_text(raw)
    with pytest.raises(ConfigError) as error:
        store.load()
    assert "private-example" not in str(error.value)
    assert store.path.read_text() == raw


def test_group_selection_requires_at_least_one_checkbox():
    app = QApplication.instance() or QApplication([])
    dialog = DefaultSettingsDialog()
    try:
        assert dialog.selected_sections() == {"ssh", "power_supply", "board"}
        for checkbox in dialog.groups.values():
            checkbox.setChecked(False)
        assert not dialog.save_button.isEnabled()
        dialog.groups["ssh"].setChecked(True)
        assert dialog.save_button.isEnabled() and dialog.selected_sections() == {"ssh"}
    finally:
        dialog.close()


@pytest.mark.parametrize("existing", [False, True])
def test_first_window_uses_defaults_only_without_saved_client_settings(tmp_path, existing):
    from mmu_control.core.config_manager import ConfigManager
    from mmu_control.ui.client_tabs import ClientTabsWindow
    from mmu_control.ui.main_window import MainWindow
    from mmu_control.storage.command_set_store import CommandSetStore
    from mmu_control.storage.automation_store import AutomationStore
    app = QApplication.instance() or QApplication([])
    root = tmp_path / "data"
    DefaultSettingsStore(root / "default_settings.json").save(AppSettings(ssh=SSHSettings(host="default-server")), {"ssh"})
    if existing:
        ConfigManager(root / "settings.json").save(AppSettings(ssh=SSHSettings(host="existing-server")))
    def factory(**kwargs):
        return MainWindow(command_set_store=CommandSetStore(tmp_path / "commands.json"),
                          automation_store=AutomationStore(tmp_path / "scenarios.json"), **kwargs)
    host = ClientTabsWindow(root, factory)
    try:
        session = host.client_tabs.widget(0)
        assert session.ssh_host_input.text() == ("existing-server" if existing else "default-server")
        assert not session.has_active_session and not session.has_pending_tasks
    finally:
        host.close()
