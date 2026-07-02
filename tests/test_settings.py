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
                    "username": "root",
                    "password": "board",
                    "interface": "eth0",
                    "usb_port": "/dev/ttyUSB0",
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
                    "username": "root",
                    "password": "board",
                    "interface": "eth0",
                    "usb_port": "/dev/ttyUSB0",
                },
                "window": {
                    "width": 1180,
                    "height": 760,
                    "is_maximized": False,
                },
                "active_profile": "default",
            },
        )


if __name__ == "__main__":
    unittest.main()
