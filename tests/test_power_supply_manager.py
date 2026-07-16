"""Tests for power supply command configuration."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.core.power_supply_manager import PowerSupplyCommandError, PowerSupplyManager
from mmu_control.models.settings import PowerSupplySettings


class PowerSupplyManagerTest(unittest.TestCase):
    """Power supply commands are loaded from JSON templates."""

    def test_builds_default_commands_from_json(self) -> None:
        manager = PowerSupplyManager(
            PowerSupplySettings(ip_address="192.168.0.50", voltage="12.5", current="1.25")
        )

        self.assertEqual(manager.build_command("set"), "psu 192.168.0.50 set 12.5 1.25")
        self.assertEqual(manager.build_command("on"), "psu 192.168.0.50 on")
        self.assertEqual(manager.build_command("off"), "psu 192.168.0.50 off")
        self.assertEqual(manager.build_command("status"), "psu 192.168.0.50 status")
        self.assertEqual(manager.build_command("all_status"), "psu all-status")

    def test_builds_custom_commands_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            commands_path = Path(temp_dir) / "power_supply_commands.json"
            commands_path.write_text(
                '{"commands": {"on": "custom --host {ip} --on"}}',
                encoding="utf-8",
            )
            manager = PowerSupplyManager(
                PowerSupplySettings(ip_address="10.0.0.2"),
                commands_path=commands_path,
            )

            self.assertEqual(manager.build_command("on"), "custom --host 10.0.0.2 --on")

    def test_ip_is_required_when_template_uses_ip(self) -> None:
        manager = PowerSupplyManager(PowerSupplySettings(ip_address=""))

        with self.assertRaisesRegex(PowerSupplyCommandError, "IP address is required"):
            manager.build_command("on")

    def test_voltage_and_current_are_required_for_set_command(self) -> None:
        manager = PowerSupplyManager(PowerSupplySettings(ip_address="192.168.0.50"))

        with self.assertRaisesRegex(PowerSupplyCommandError, "voltage is required"):
            manager.build_command("set")

        manager.update_settings(PowerSupplySettings(ip_address="192.168.0.50", voltage="12"))
        with self.assertRaisesRegex(PowerSupplyCommandError, "current is required"):
            manager.build_command("set")


if __name__ == "__main__":
    unittest.main()
