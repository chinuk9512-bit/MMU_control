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

    def test_loads_legacy_transport_but_does_not_write_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "automation.json"
            path.write_text(json.dumps({"scenarios": {"legacy": {"transport": "minicom", "steps": []}}}), encoding="utf-8")
            store = AutomationStore(path)

            scenario = store.load().scenarios["legacy"]
            self.assertEqual(scenario.name, "legacy")
            self.assertNotIn("transport", scenario.to_dict())
            store.upsert(scenario)
            self.assertNotIn("transport", json.loads(path.read_text(encoding="utf-8"))["scenarios"]["legacy"])


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

    def test_editor_defaults_to_eight_visible_steps_with_resizable_panes(self) -> None:
        """The list starts at eight rows and can be resized independently of details."""
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        scenario = AutomationScenario(
            name="editor",
            steps=[AutomationStep(name=str(index), command="run") for index in range(8)],
        )
        dialog = AutomationEditorDialog(scenario)
        dialog.show()
        qt_widgets.QApplication.processEvents()

        self.assertEqual(dialog.minimumHeight(), 600)
        self.assertEqual(dialog.height(), 900)
        self.assertEqual(dialog.step_list.minimumHeight(), 45)
        self.assertEqual(dialog.DEFAULT_VISIBLE_STEP_COUNT, 8)
        self.assertEqual(dialog.step_editor_splitter.count(), 2)
        eighth_step = dialog.step_list.visualItemRect(dialog.step_list.item(7))
        self.assertTrue(dialog.step_list.viewport().rect().contains(eighth_step))
        self.assertEqual(dialog.command_input.minimumHeight(), 144)
        dialog.close()


class AutomationRunnerTest(unittest.TestCase):
    """Only one current step is sent and retried when it fails."""

    def setUp(self) -> None:
        self.sent: list[str] = []
        self.runner = AutomationRunner(self.sent.append)

    def test_console_condition_output_buffer_is_limited_to_300_characters(self) -> None:
        """Console contains and regex conditions only retain the newest 300 characters."""
        scenario = AutomationScenario(
            name="bounded output",
            steps=[AutomationStep("wait", "command", CompletionType.OUTPUT_CONTAINS, "ready")],
        )

        self.runner.start(scenario)
        self.runner.receive_output("x" * 350)

        self.assertEqual(len(self.runner._output), 300)

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

    def test_starts_at_the_requested_intermediate_step(self) -> None:
        """A run can begin without sending any preceding scenario commands."""
        scenario = AutomationScenario(
            name="resume",
            steps=[
                AutomationStep("first", "one"),
                AutomationStep("middle", "two", CompletionType.OUTPUT_CONTAINS, "done"),
                AutomationStep("last", "three"),
            ],
        )

        self.runner.start(scenario, start_step_index=1)

        self.assertEqual(self.sent, ["two"])
        self.assertEqual(self.runner.start_step_index, 1)
        self.assertEqual(self.runner.status.step_index, 1)
        self.runner.receive_output("done")
        self.assertEqual(self.sent, ["two", "three"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_rejects_an_out_of_range_start_step(self) -> None:
        scenario = AutomationScenario(name="one", steps=[AutomationStep("only", "one")])

        with self.assertRaises(ValueError):
            self.runner.start(scenario, start_step_index=1)

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
