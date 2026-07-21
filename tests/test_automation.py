"""Tests for persisted automation scenarios and sequential execution."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from mmu_control.core.automation_runner import AutomationRunner, AutomationState
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType
from mmu_control.storage.automation_store import AutomationStore


class AutomationStoreTest(unittest.TestCase):
    """Automation JSON data is persisted with its completion conditions."""

    def test_default_store_uses_persistent_user_data_path(self) -> None:
        """Default scenarios live outside PyInstaller's temporary bundle."""
        with patch.dict("os.environ", {"APPDATA": "C:/Users/test/AppData/Roaming"}):
            store = AutomationStore.create_default()

        self.assertEqual(
            store._path,
            Path("C:/Users/test/AppData/Roaming")
            / "MMUControl"
            / "automation_scenarios.json",
        )

    def test_upsert_load_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = AutomationStore(Path(directory) / "automation.json")
            scenario = AutomationScenario(
                name="boot",
                transport="minicom",
                steps=[
                    AutomationStep(
                        name="wait lock",
                        command="start",
                        completion_type=CompletionType.REMOTE_FILE_CONTAINS,
                        completion_value="lock",
                        file_path="/tmp/status",
                    )
                ],
            )
            store.upsert(scenario)
            self.assertEqual(store.load().scenarios, {"boot": scenario})
            self.assertEqual(store.delete("boot").scenarios, {})

    def test_upsert_loads_scenario_without_steps(self) -> None:
        """Newly named scenarios can be persisted before steps are configured."""
        with tempfile.TemporaryDirectory() as directory:
            store = AutomationStore(Path(directory) / "automation.json")
            scenario = AutomationScenario(name="new scenario")

            store.upsert(scenario)

            self.assertEqual(store.load().scenarios, {"new scenario": scenario})

    def test_upsert_serializes_legacy_string_completion_type(self) -> None:
        """Supported string completion types remain safe at the JSON boundary."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automation.json"
            store = AutomationStore(path)
            scenario = AutomationScenario(
                name="legacy completion",
                steps=[AutomationStep(name="run", command="run", completion_type="none")],
            )

            store.upsert(scenario)

            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["scenarios"]["legacy completion"]["steps"][0]["completion_type"], "none")
            self.assertEqual(store.load().scenarios["legacy completion"].steps[0].completion_type, CompletionType.NONE)


class AutomationEditorDialogTest(unittest.TestCase):
    """The editor stores completion conditions as CompletionType values."""

    def test_saved_step_serializes_completion_type_as_enum_value(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        dialog = AutomationEditorDialog(
            AutomationScenario(
                name="editor",
                steps=[AutomationStep(name="run", command="run")],
            )
        )
        none_index = dialog.condition_type_input.findData(CompletionType.NONE)
        dialog.condition_type_input.setItemData(none_index, "none")
        dialog.condition_type_input.setCurrentIndex(none_index)

        saved_step = dialog.scenario().steps[0]

        self.assertIs(saved_step.completion_type, CompletionType.NONE)
        self.assertEqual(saved_step.to_dict()["completion_type"], CompletionType.NONE.value)

    def test_add_step_keeps_edited_step_and_selects_a_default_step(self) -> None:
        """Adding a step saves only the current step and does not copy its values."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        dialog = AutomationEditorDialog(
            AutomationScenario(name="editor", steps=[AutomationStep(name="original", command="old")])
        )
        dialog.step_name_input.setText("edited step")
        dialog.command_input.setPlainText("edited command")
        dialog.condition_type_input.setCurrentIndex(
            dialog.condition_type_input.findData(CompletionType.REMOTE_FILE_CONTAINS)
        )
        dialog.condition_value_input.setText("complete")
        dialog.file_path_input.setText("/tmp/complete")
        dialog.timeout_input.setValue(15)

        dialog._add_step()

        self.assertEqual(dialog._steps[0], AutomationStep(
            name="edited step",
            command="edited command",
            completion_type=CompletionType.REMOTE_FILE_CONTAINS,
            completion_value="complete",
            file_path="/tmp/complete",
            timeout_seconds=15,
        ))
        self.assertEqual(dialog._steps[1], AutomationStep())
        self.assertEqual(dialog.step_list.currentRow(), 1)
        self.assertEqual(dialog.step_name_input.text(), "")
        self.assertEqual(dialog.command_input.toPlainText(), "")
        self.assertIs(dialog.condition_type_input.currentData(), CompletionType.NONE)
        self.assertEqual(dialog.condition_value_input.text(), "")
        self.assertEqual(dialog.file_path_input.text(), "")
        self.assertEqual(dialog.timeout_input.value(), 60)


class AutomationRunnerTest(unittest.TestCase):
    """Only one current step is sent and retried when it fails."""

    def setUp(self) -> None:
        self.sent: list[str] = []
        self.runner = AutomationRunner(self.sent.append)

    def test_waits_for_each_condition_before_sending_next_step(self) -> None:
        scenario = AutomationScenario(
            name="sequential",
            steps=[
                AutomationStep("first", "one", CompletionType.OUTPUT_CONTAINS, "ready"),
                AutomationStep("second", "two", CompletionType.PROMPT_REGEX, r"ushell>"),
            ],
        )
        self.runner.start(scenario)
        self.assertEqual(self.sent, ["one"])
        self.runner.receive_output("still booting")
        self.assertEqual(self.sent, ["one"])
        self.runner.receive_output(" ready")
        self.assertEqual(self.sent, ["one", "two"])
        self.runner.receive_output("\r\nushell>")
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_prompt_completion_matches_newline_terminated_last_line(self) -> None:
        scenario = AutomationScenario(
            name="prompt-last-line",
            steps=[AutomationStep("first", "one", CompletionType.PROMPT_REGEX, r"ushell>")],
        )

        self.runner.start(scenario)
        self.runner.receive_output("command output\r\nushell>\r\n")

        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_output_completion_matches_newline_terminated_last_line(self) -> None:
        scenario = AutomationScenario(
            name="output-last-line",
            steps=[AutomationStep("first", "one", CompletionType.OUTPUT_CONTAINS, "complete")],
        )

        self.runner.start(scenario)
        self.runner.receive_output("command output\r\ncomplete\r\n")

        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_step_without_completion_condition_advances_immediately(self) -> None:
        scenario = AutomationScenario(
            name="no-condition",
            steps=[
                AutomationStep("prepare", "prepare", CompletionType.NONE),
                AutomationStep("wait", "wait", CompletionType.DELAY, timeout_seconds=1),
            ],
        )

        self.runner.start(scenario)

        self.assertEqual(self.sent, ["prepare", "wait"])
        self.assertEqual(self.runner.status.state, AutomationState.WAITING)
        self.assertEqual(self.runner.status.step_index, 1)

    def test_file_condition_uses_safe_terminal_command_and_marker(self) -> None:
        scenario = AutomationScenario(
            name="file",
            steps=[AutomationStep("check", "start", CompletionType.REMOTE_FILE_CONTAINS, "lock", "/tmp/state")],
        )
        self.runner.start(scenario)
        self.assertTrue(self.runner.tick())
        command = self.runner.file_check_command()
        self.assertIn("grep -Fq", command or "")
        self.assertIn("__MMU_AUTOMATION_FILE_MATCH__", command or "")
        self.runner.receive_output("__MMU_AUTOMATION_FILE_MATCH__\n")
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_retries_only_current_step_once_after_two_seconds(self) -> None:
        scenario = AutomationScenario(
            name="retry",
            steps=[AutomationStep("one", "one", CompletionType.DELAY, timeout_seconds=10)],
        )
        self.runner.start(scenario)
        self.runner.fail_current_step("connection lost")
        self.assertEqual(self.runner.status.state, AutomationState.RETRY_WAITING)
        self.assertEqual(self.sent, ["one"])
        self.runner.tick(now=0.0)
        self.assertEqual(self.sent, ["one"])
        self.runner._retry_at = 0.0  # Exercise elapsed retry time without sleeping in the test.
        self.runner.tick(now=0.0)
        self.assertEqual(self.sent, ["one", "one"])
        self.runner.fail_current_step("connection lost again")
        self.assertEqual(self.runner.status.state, AutomationState.FAILED)


if __name__ == "__main__":
    unittest.main()
