"""Application settings models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SSHSettings:
    """SSH connection settings for the Linux server."""

    host: str = ""
    port: int = 22
    username: str = ""
    password: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SSHSettings:
        """Create SSH settings from JSON-compatible data."""
        return cls(
            host=str(data.get("host", "")),
            port=int(data.get("port", 22)),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert SSH settings to JSON-compatible data."""
        return {
            "host": self.host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
        }


@dataclass(slots=True)
class BoardSettings:
    """Board connection settings used by SFTP and terminal workflows."""

    ip_address: str = ""
    username: str = ""
    password: str = ""
    interface: str = ""
    usb_port: str = ""
    ssh_port: int = 22
    ssh_key_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoardSettings:
        """Create board settings from JSON-compatible data."""
        return cls(
            ip_address=str(data.get("ip_address", "")),
            username=str(data.get("username", "")),
            password=str(data.get("password", "")),
            interface=str(data.get("interface", "")),
            usb_port=str(data.get("usb_port", "")),
            ssh_port=int(data.get("ssh_port", 22)),
            ssh_key_path=str(data.get("ssh_key_path", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert board settings to JSON-compatible data."""
        return {
            "ip_address": self.ip_address,
            "username": self.username,
            "password": self.password,
            "interface": self.interface,
            "usb_port": self.usb_port,
            "ssh_port": self.ssh_port,
            "ssh_key_path": self.ssh_key_path,
        }


@dataclass(slots=True)
class WindowSettings:
    """Persisted main window state."""

    width: int = 1180
    height: int = 760
    is_maximized: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WindowSettings:
        """Create window settings from JSON-compatible data."""
        return cls(
            width=int(data.get("width", 1180)),
            height=int(data.get("height", 760)),
            is_maximized=bool(data.get("is_maximized", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert window settings to JSON-compatible data."""
        return {
            "width": self.width,
            "height": self.height,
            "is_maximized": self.is_maximized,
        }


@dataclass(slots=True)
class AppSettings:
    """Top-level application settings."""

    schema_version: int = 1
    ssh: SSHSettings = field(default_factory=SSHSettings)
    board: BoardSettings = field(default_factory=BoardSettings)
    window: WindowSettings = field(default_factory=WindowSettings)
    active_profile: str = "default"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        """Create application settings from JSON-compatible data."""
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            ssh=SSHSettings.from_dict(data.get("ssh", {})),
            board=BoardSettings.from_dict(data.get("board", {})),
            window=WindowSettings.from_dict(data.get("window", {})),
            active_profile=str(data.get("active_profile", "default")),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert application settings to JSON-compatible data."""
        return {
            "schema_version": self.schema_version,
            "ssh": self.ssh.to_dict(),
            "board": self.board.to_dict(),
            "window": self.window.to_dict(),
            "active_profile": self.active_profile,
        }
