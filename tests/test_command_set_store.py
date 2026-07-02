"""Tests for command set persistence."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.models.command_set import CommandSet
from mmu_control.storage.command_set_store import CommandSetStore


class CommandSetStoreTest(unittest.TestCase):
    """Tests for JSON command set storage."""

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


if __name__ == "__main__":
    unittest.main()
