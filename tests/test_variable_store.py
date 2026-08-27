"""Tests for per-user command variable persistence."""

from __future__ import annotations

import json

import pytest

from mmu_control.storage.variable_store import VariableStore, VariableStoreError


def test_variable_store_round_trip(tmp_path) -> None:
    store = VariableStore(tmp_path / "variables.json")
    store.save({"MMU_USERNAME": "alice", "MMU_PASSWORD": "secret"})
    assert store.load() == {"MMU_USERNAME": "alice", "MMU_PASSWORD": "secret"}
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1


def test_variable_store_returns_empty_mapping_when_absent(tmp_path) -> None:
    assert VariableStore(tmp_path / "missing.json").load() == {}


def test_variable_store_rejects_invalid_names_without_showing_values(tmp_path) -> None:
    store = VariableStore(tmp_path / "variables.json")
    with pytest.raises(VariableStoreError) as error:
        store.save({"INVALID-NAME": "do-not-display"})
    assert "INVALID-NAME" in str(error.value)
    assert "do-not-display" not in str(error.value)


def test_default_store_uses_per_user_data_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert VariableStore.create_default().path == tmp_path / "MMUControl" / "variables.json"
