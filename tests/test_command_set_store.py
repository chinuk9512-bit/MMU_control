"""Tests for command set persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.models.command_set import CommandSet
from mmu_control.storage.command_set_store import CommandSetStore


class CommandSetStoreTest(unittest.TestCase):
    """Tests for JSON command set storage."""

    def test_create_default_uses_package_command_data_path(self) -> None:
        """The default store persists command sets in the package data directory."""
        store = CommandSetStore.create_default()

        expected_path = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "mmu_control"
            / "user_command"
            / "command_sets.json"
        )
        self.assertEqual(store.command_sets_path, expected_path)

    def test_upsert_load_and_delete_command_set(self) -> None:
        """Command sets can be saved, loaded, replaced, and deleted."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CommandSetStore(Path(temp_dir) / "command_sets.json")
            command_set = CommandSet(
                name="boot-check",
                description="Check boot state",
                commands="uname -a\nls /dev/ttyUSB*",
            )

            saved = store.upsert(command_set)
            loaded = store.load()

            self.assertEqual(saved.command_sets, {"boot-check": command_set})
            self.assertEqual(loaded.command_sets, {"boot-check": command_set})

            replacement = CommandSet(name="boot-check", commands="pwd")
            store.upsert(replacement)
            self.assertEqual(store.load().command_sets, {"boot-check": replacement})

            deleted = store.delete("boot-check")
            self.assertEqual(deleted.command_sets, {})

    def test_legacy_flat_json_loads_at_top_level(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "command_sets.json"
            path.write_text('{"command_sets": {"legacy": {"commands": "pwd"}}}', encoding="utf-8")
            collection = CommandSetStore(path).load()
            self.assertEqual(collection.schema_version, 2)
            self.assertEqual(collection.command_sets["legacy"].parent_path, "")
            self.assertEqual(collection.folders, {})

    def test_folder_move_reload_and_delete_policies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CommandSetStore(Path(temp_dir) / "command_sets.json")
            store.create_folder("A")
            store.create_folder("B", "A")
            store.upsert(CommandSet("nested", commands="pwd", parent_path="A/B"))
            store.move_command_set("nested", "A")
            reloaded = store.load()
            self.assertEqual(reloaded.command_sets["nested"].parent_path, "A")
            self.assertIn("A/B", reloaded.folders)
            self.assertEqual(__import__("json").loads(store.command_sets_path.read_text())["schema_version"], 2)

            store.delete_folder("A", delete_contents=False)
            promoted = store.load()
            self.assertIn("B", promoted.folders)
            self.assertEqual(promoted.command_sets["nested"].parent_path, "")
            store.delete_folder("B", delete_contents=True)
            self.assertNotIn("B", store.load().folders)


if __name__ == "__main__":
    unittest.main()
