"""Tests for PyInstaller packaging configuration."""

from __future__ import annotations

from pathlib import Path


def test_power_supply_commands_are_bundled_in_pyinstaller_spec() -> None:
    """The one-file executable must include the default power supply JSON."""
    spec_text = Path("MMUControl.spec").read_text(encoding="utf-8")

    assert r"src\\mmu_control\\resources\\power_supply_commands.json" in spec_text
    assert "mmu_control/resources" in spec_text


def test_command_sets_are_bundled_in_pyinstaller_spec() -> None:
    """The one-file executable must include the default command-set JSON."""
    spec_text = Path("MMUControl.spec").read_text(encoding="utf-8")

    assert r"src\\mmu_control\\user_command\\command_sets.json" in spec_text
    assert "mmu_control/user_command" in spec_text
