"""Tests for the Streamlit web interface helpers."""

from __future__ import annotations

from pathlib import Path

from mmu_control.models.command_set import CommandSet
from mmu_control.web_app import (
    command_lines,
    create_web_services,
    parse_find_listing,
    parse_sftp_listing,
    resolve_sftp_path,
    settings_from_form_values,
)


def test_create_web_services_uses_default_managers() -> None:
    services = create_web_services()

    assert services.ssh_manager is not None
    assert services.sftp_manager is not None
    assert services.minicom_manager is not None
    assert services.power_supply_manager is not None
    assert services.config_manager is not None
    assert services.command_set_store is not None
    assert services.automation_store is not None


def test_settings_from_form_values_builds_app_settings() -> None:
    settings = settings_from_form_values(
        ssh_host=" server.local ",
        ssh_port=2222,
        ssh_username=" user ",
        ssh_password="secret",
        board_ip=" fe80::1 ",
        board_username="root",
        board_password="mmu",
        board_interface=" eth0 ",
        board_usb_port="/dev/ttyUSB0",
        board_ssh_port=2200,
        power_ip="192.168.0.5",
        power_voltage="12",
        power_current="1.5",
    )

    assert settings.ssh.host == "server.local"
    assert settings.ssh.port == 2222
    assert settings.board.ip_address == "fe80::1"
    assert settings.board.interface == "eth0"
    assert settings.power_supply.current == "1.5"


def test_command_lines_ignores_blank_lines() -> None:
    command_set = CommandSet("Boot", commands="\n echo one \n\nreboot\n")

    assert command_lines(command_set) == ["echo one", "reboot"]


def test_parse_find_listing_matches_file_kinds() -> None:
    entries = parse_find_listing("d\t/tmp\nf\t/tmp/a.bin\nl\t/tmp/latest\nignored\n")

    assert [(entry.is_dir, entry.name, entry.path) for entry in entries] == [
        (True, "tmp", "/tmp"),
        (False, "a.bin", "/tmp/a.bin"),
        (False, "latest", "/tmp/latest"),
    ]


def test_parse_sftp_listing_handles_parent_and_symlink() -> None:
    output = """
sftp> ls -la /tmp
drwxr-xr-x    2 root root 4096 Jul 01 00:00 .
drwxr-xr-x    5 root root 4096 Jul 01 00:00 ..
-rw-r--r--    1 root root    4 Jul 01 00:00 data.bin
lrwxrwxrwx    1 root root    8 Jul 01 00:00 logs -> /var/log
"""

    entries = parse_sftp_listing(output, "/tmp")

    assert [(entry.name, entry.path, entry.is_dir) for entry in entries] == [
        ("..", "/", True),
        ("data.bin", "/tmp/data.bin", False),
        ("logs", "/tmp/logs", True),
    ]
    assert entries[-1].link_target == "/var/log"
    assert entries[-1].navigate_path == "/var/log"


def test_resolve_sftp_path() -> None:
    assert resolve_sftp_path("/tmp", "firmware") == "/tmp/firmware"
    assert resolve_sftp_path("/tmp/work", "..") == "/tmp"
    assert resolve_sftp_path("/tmp", "/var/log") == "/var/log"


def test_web_pyinstaller_spec_bundles_power_supply_commands_only_as_static_data() -> None:
    spec_text = Path("MMUControlWeb.spec").read_text(encoding="utf-8")

    assert r"src\\mmu_control\\resources\\power_supply_commands.json" in spec_text
    assert "mmu_control/resources" in spec_text
    assert "command_sets.json" not in spec_text
    assert "automation_scenarios.json" not in spec_text
