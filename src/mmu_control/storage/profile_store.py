"""JSON storage for connection profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mmu_control.models.profile import ConnectionProfile, ProfileCollection


class ProfileStoreError(RuntimeError):
    """Raised when connection profiles cannot be loaded or saved."""


class ProfileStore:
    """Persist named connection profiles in JSON."""

    def __init__(self, profiles_path: Path) -> None:
        self._profiles_path = profiles_path

    @property
    def profiles_path(self) -> Path:
        """Return the JSON profiles file path."""
        return self._profiles_path

    def load(self) -> ProfileCollection:
        """Load profiles from disk, returning an empty collection when missing."""
        if not self._profiles_path.exists():
            return ProfileCollection()

        try:
            raw_data: Any = json.loads(self._profiles_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ProfileStoreError(f"Unable to read profiles: {self._profiles_path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileStoreError(f"Invalid profiles JSON: {self._profiles_path}") from exc

        if not isinstance(raw_data, dict):
            raise ProfileStoreError("Profiles JSON must contain an object.")
        return ProfileCollection.from_dict(raw_data)

    def save(self, collection: ProfileCollection) -> None:
        """Save profiles to disk."""
        try:
            self._profiles_path.parent.mkdir(parents=True, exist_ok=True)
            self._profiles_path.write_text(
                json.dumps(collection.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            raise ProfileStoreError(f"Unable to write profiles: {self._profiles_path}") from exc

    def upsert(self, profile: ConnectionProfile) -> ProfileCollection:
        """Insert or replace a profile and make it active."""
        collection = self.load()
        collection.profiles[profile.name] = profile
        collection.active_profile = profile.name
        self.save(collection)
        return collection

    def delete(self, name: str) -> ProfileCollection:
        """Delete a profile by name."""
        collection = self.load()
        collection.profiles.pop(name, None)
        if collection.active_profile == name:
            collection.active_profile = next(iter(collection.profiles), "default")
        self.save(collection)
        return collection
