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
