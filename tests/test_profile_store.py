"""Tests for connection profile persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.models.profile import ConnectionProfile
from mmu_control.models.settings import BoardSettings, SSHSettings
from mmu_control.storage.profile_store import ProfileStore


class ProfileStoreTest(unittest.TestCase):
    """Tests for JSON profile storage."""

    def test_upsert_load_and_delete_profile(self) -> None:
        """Profiles can be saved, selected, loaded, and deleted."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = ProfileStore(Path(temp_dir) / "profiles.json")
            profile = ConnectionProfile(
                name="lab",
                description="Lab server",
                ssh=SSHSettings(host="server", username="developer"),
                board=BoardSettings(ip_address="fe80::1", username="root"),
            )

            saved = store.upsert(profile)
            loaded = store.load()

            self.assertEqual(saved.active_profile, "lab")
            self.assertEqual(loaded.get_active(), profile)

            deleted = store.delete("lab")
            self.assertIsNone(deleted.get_active())


if __name__ == "__main__":
    unittest.main()
