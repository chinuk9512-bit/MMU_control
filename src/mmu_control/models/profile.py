"""Connection profile models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mmu_control.models.settings import BoardSettings, SSHSettings


@dataclass(slots=True)
class ConnectionProfile:
    """Saved SSH and board connection settings."""

    name: str
    description: str = ""
    ssh: SSHSettings = field(default_factory=SSHSettings)
    board: BoardSettings = field(default_factory=BoardSettings)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionProfile:
        """Create a connection profile from JSON-compatible data."""
        return cls(
            name=str(data.get("name", "default")),
            description=str(data.get("description", "")),
            ssh=SSHSettings.from_dict(data.get("ssh", {})),
            board=BoardSettings.from_dict(data.get("board", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert this profile to JSON-compatible data."""
        return {
            "name": self.name,
            "description": self.description,
            "ssh": self.ssh.to_dict(),
            "board": self.board.to_dict(),
        }


@dataclass(slots=True)
class ProfileCollection:
    """Named connection profiles and the active selection."""

    active_profile: str = "default"
    profiles: dict[str, ConnectionProfile] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProfileCollection:
        """Create a profile collection from JSON-compatible data."""
        raw_profiles = data.get("profiles", {})
        profiles: dict[str, ConnectionProfile] = {}
        if isinstance(raw_profiles, dict):
            for name, profile_data in raw_profiles.items():
                if isinstance(profile_data, dict):
                    profile = ConnectionProfile.from_dict({"name": name, **profile_data})
                    profiles[profile.name] = profile
        return cls(
            active_profile=str(data.get("active_profile", "default")),
            profiles=profiles,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert this collection to JSON-compatible data."""
        return {
            "active_profile": self.active_profile,
            "profiles": {
                name: profile.to_dict()
                for name, profile in sorted(self.profiles.items())
            },
        }

    def get_active(self) -> ConnectionProfile | None:
        """Return the active profile when it exists."""
        return self.profiles.get(self.active_profile)
