"""Tests for configuration persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.core.config_manager import ConfigError, ConfigManager
from mmu_control.models.settings import AppSettings, SSHSettings


class ConfigManagerTest(unittest.TestCase):
    """Tests for JSON configuration loading and saving."""

    def test_load_missing_file_returns_defaults(self) -> None:
        """Missing config files produce default settings."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ConfigManager(Path(temp_dir) / "settings.json")

            settings = manager.load()

            self.assertEqual(settings.ssh.port, 22)
            self.assertEqual(settings.window.width, 1840)

    def test_save_and_load_round_trip(self) -> None:
        """Saved settings can be loaded again."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "nested" / "settings.json"
            manager = ConfigManager(config_path)
            settings = AppSettings(ssh=SSHSettings(host="server", username="user"))

            manager.save(settings)
            loaded = manager.load()

            self.assertEqual(loaded.ssh.host, "server")
            self.assertEqual(loaded.ssh.username, "user")

    def test_invalid_json_raises_config_error(self) -> None:
        """Invalid config JSON is reported as a configuration error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            config_path.write_text("{not-json", encoding="utf-8")
            manager = ConfigManager(config_path)

            with self.assertRaises(ConfigError):
                manager.load()

    def test_invalid_setting_value_raises_config_error(self) -> None:
        """Malformed values are reported instead of crashing application startup."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "settings.json"
            config_path.write_text('{"ssh": {"port": "not-a-port"}}', encoding="utf-8")
            manager = ConfigManager(config_path)

            with self.assertRaises(ConfigError):
                manager.load()


if __name__ == "__main__":
    unittest.main()


def test_private_paths_ignore_working_directory_and_appdata(monkeypatch, tmp_path):
    from mmu_control.core import config_manager
    from mmu_control.core.logging_config import default_log_path
    root = tmp_path / "project"
    monkeypatch.setattr(config_manager, "__file__", str(root / "src/mmu_control/core/config_manager.py"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "old-appdata"))
    monkeypatch.chdir(tmp_path)
    expected = root / "local_data"
    assert config_manager.default_user_data_directory() == expected
    assert config_manager.default_config_path() == expected / "settings.json"
    assert default_log_path() == expected / "mmu_control.log"
    assert not expected.exists()  # Resolving paths neither creates nor migrates data.


def test_frozen_private_data_uses_project_above_dist(monkeypatch, tmp_path):
    from mmu_control.core import config_manager
    root = tmp_path / "project"
    (root / "src/mmu_control").mkdir(parents=True)
    monkeypatch.setattr(config_manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_manager.sys, "executable", str(root / "dist/MMUControl.exe"))
    monkeypatch.setattr(config_manager.sys, "_MEIPASS", str(tmp_path / "extraction"), raising=False)
    assert config_manager.default_user_data_directory() == root / "local_data"


def test_standalone_exe_uses_distribution_directory(monkeypatch, tmp_path):
    from mmu_control.core import config_manager
    monkeypatch.setattr(config_manager.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config_manager.sys, "executable", str(tmp_path / "distribution/MMUControl.exe"))
    assert config_manager.default_user_data_directory() == tmp_path / "distribution/local_data"


def test_launch_outside_project_does_not_migrate_old_appdata(monkeypatch, tmp_path):
    from mmu_control.core import config_manager
    from mmu_control.storage.variable_store import VariableStore
    root = tmp_path / "project"
    (root / "src/mmu_control").mkdir(parents=True)
    old = tmp_path / "appdata/MMUControl"
    old.mkdir(parents=True)
    original = '{"ssh": {"host": "old-host"}}'
    (old / "settings.json").write_text(original)
    monkeypatch.setenv("APPDATA", str(old.parent))
    monkeypatch.setattr(config_manager, "__file__", str(root / "src/mmu_control/core/config_manager.py"))
    monkeypatch.chdir(tmp_path)
    assert config_manager.project_storage_root() == root
    assert ConfigManager.create_default().load().ssh.host == ""
    assert VariableStore.create_default().load() == {}
    assert not (root / "local_data").exists()
    assert (old / "settings.json").read_text() == original
