"""Tests for application settings models."""

from __future__ import annotations

import unittest

from mmu_control.models.settings import AppSettings


class AppSettingsTest(unittest.TestCase):
    """Tests for top-level application settings."""

    def test_app_settings_round_trip(self) -> None:
        """Settings can be converted to dictionaries and restored."""
        settings = AppSettings.from_dict(
            {
                "ssh": {
                    "host": "192.0.2.10",
                    "port": 2200,
                    "username": "developer",
                    "password": "secret",
                },
                "board": {
                    "ip_address": "fe80::1",
                    "ip_version": "IPv4",
                    "username": "root",
                    "password": "board",
                    "interface": "eth0",
                    "usb_port": "/dev/ttyUSB0",
                    "ssh_port": 2222,
                    "ssh_key_path": "/home/user/.ssh/mmu",
                },
            }
        )

        self.assertEqual(
            settings.to_dict(),
            {
                "schema_version": 1,
                "ssh": {
                    "host": "192.0.2.10",
                    "port": 2200,
                    "username": "developer",
                    "password": "secret",
                },
                "board": {
                    "ip_address": "fe80::1",
                    "ip_version": "IPv4",
                    "username": "root",
                    "password": "board",
                    "interface": "eth0",
                    "usb_port": "/dev/ttyUSB0",
                    "ssh_port": 2222,
                    "ssh_key_path": "/home/user/.ssh/mmu",
                },
                "power_supply": {"ip_address": ""},
                "window": {
                    "width": 1180,
                    "height": 760,
                    "is_maximized": False,
                    "ssh_group_expanded": True,
                    "mmu_group_expanded": True,
                },
                "active_profile": "default",
            },
        )


if __name__ == "__main__":
    unittest.main()
