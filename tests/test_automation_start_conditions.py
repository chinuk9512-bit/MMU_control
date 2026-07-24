"""Tests for start-condition support in automation steps."""

from __future__ import annotations

import os
import sys
import unittest

import pytest

from mmu_control.core.automation_runner import AutomationRunner, AutomationState
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType


class AutomationStartConditionModelTest(unittest.TestCase):
    """Persisted steps safely support optional start conditions."""

    def test_loads_legacy_step_without_start_condition(self) -> None:
        step = AutomationStep.from_dict({"name": "legacy", "command": "run", "completion_type": "none"})

        self.assertEqual(step.start_type, CompletionType.NONE)
        self.assertEqual(step.start_value, "")
        self.assertEqual(step.start_file_path, "")
        self.assertEqual(step.start_timeout_seconds, 60)
        self.assertFalse(step.skip_on_start_condition_failure)

    def test_round_trips_skip_on_start_condition_failure(self) -> None:
        step = AutomationStep.from_dict({
            "name": "optional",
            "command": "run",
            "skip_on_start_condition_failure": True,
        })

        self.assertTrue(step.skip_on_start_condition_failure)
        self.assertTrue(step.to_dict()["skip_on_start_condition_failure"])

    def test_false_string_does_not_enable_skipping(self) -> None:
        step = AutomationStep.from_dict({"skip_on_start_condition_failure": "false"})

        self.assertFalse(step.skip_on_start_condition_failure)


class AutomationStartConditionEditorDialogTest(unittest.TestCase):
    """The editor saves start-condition fields independently of completion fields."""

    def test_editor_does_not_store_or_select_an_execution_transport(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        dialog = AutomationEditorDialog(AutomationScenario(name="editor", steps=[AutomationStep(name="run", command="run")]))

        self.assertFalse(hasattr(dialog, "transport_input"))
        self.assertEqual(dialog.command_input.placeholderText(), "Command to send to the currently active console")

    def test_saved_step_includes_start_condition_fields(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        dialog = AutomationEditorDialog(AutomationScenario(name="editor", steps=[AutomationStep(name="run", command="run")]))
        dialog.start_type_input.setCurrentIndex(dialog.start_type_input.findData(CompletionType.REMOTE_FILE_CONTAINS))
        dialog.start_value_input.setText("ready")
        dialog.start_file_path_input.setText("/tmp/state")
        dialog.start_timeout_input.setValue(42)

        saved_step = dialog.scenario().steps[0]

        self.assertEqual(saved_step.start_type, CompletionType.REMOTE_FILE_CONTAINS)
        self.assertEqual(saved_step.start_value, "ready")
        self.assertEqual(saved_step.start_file_path, "/tmp/state")
        self.assertEqual(saved_step.start_timeout_seconds, 42)

    def test_saved_step_includes_skip_on_start_condition_failure(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_widgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
        qt_widgets.QApplication.instance() or qt_widgets.QApplication(sys.argv)
        from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog

        dialog = AutomationEditorDialog(AutomationScenario(name="editor", steps=[AutomationStep(name="run", command="run")]))
        dialog.skip_on_start_condition_failure_input.setChecked(True)

        self.assertTrue(dialog.scenario().steps[0].skip_on_start_condition_failure)


class AutomationStartConditionRunnerTest(unittest.TestCase):
    """Commands are deferred until the current step's start condition is met."""

    def setUp(self) -> None:
        self.sent: list[str] = []
        self.runner = AutomationRunner(self.sent.append)

    def test_does_not_send_command_before_output_start_condition_matches(self) -> None:
        scenario = AutomationScenario(
            name="start-output",
            steps=[AutomationStep("run", "command", start_type=CompletionType.OUTPUT_CONTAINS, start_value="ready")],
        )

        self.runner.start(scenario)
        self.assertEqual(self.runner.status.state, AutomationState.WAITING_START)
        self.assertEqual(self.sent, [])
        self.runner.receive_output("not yet")
        self.assertEqual(self.sent, [])
        self.runner.receive_output(" ready")
        self.assertEqual(self.sent, ["command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_initial_output_snapshot_starts_command_when_it_contains_start_text(self) -> None:
        start_marker = "service-ready"
        scenario = AutomationScenario(
            name="initial-output-match",
            steps=[AutomationStep("start", "command", start_type=CompletionType.OUTPUT_CONTAINS, start_value=start_marker)],
        )

        self.runner.start(scenario)
        self.runner.receive_initial_output(f"device state: {start_marker}")

        self.assertEqual(self.sent, ["command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_initial_output_snapshot_without_match_keeps_waiting_for_new_output(self) -> None:
        start_marker = "service-ready"
        scenario = AutomationScenario(
            name="initial-output-no-match",
            steps=[AutomationStep("start", "command", start_type=CompletionType.OUTPUT_CONTAINS, start_value=start_marker)],
        )

        self.runner.start(scenario)
        self.runner.receive_initial_output("device state: booting")

        self.assertEqual(self.sent, [])
        self.assertEqual(self.runner.status.state, AutomationState.WAITING_START)
        self.runner.receive_output(f"\r\ndevice state: {start_marker}")
        self.assertEqual(self.sent, ["command"])

    def test_previous_step_output_is_reused_for_a_later_step_start_condition(self) -> None:
        scenario = AutomationScenario(
            name="shared-output-history",
            steps=[
                AutomationStep("first", "one", start_type=CompletionType.OUTPUT_CONTAINS, start_value="ready"),
                AutomationStep("second", "two", start_type=CompletionType.OUTPUT_CONTAINS, start_value="ready"),
            ],
        )

        self.runner.start(scenario)
        self.runner.receive_initial_output("ready")

        self.assertEqual(self.sent, ["one", "two"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_completion_output_starts_next_step_with_regex_start_condition(self) -> None:
        scenario = AutomationScenario(
            name="completion-start-regex",
            steps=[
                AutomationStep(
                    "first",
                    "one",
                    completion_type=CompletionType.OUTPUT_CONTAINS,
                    completion_value="complete",
                ),
                AutomationStep(
                    "second",
                    "two",
                    start_type=CompletionType.OUTPUT_REGEX,
                    start_value=r"result [0-9]+",
                ),
            ],
        )

        self.runner.start(scenario)
        self.runner.receive_output("complete: result 61")

        self.assertEqual(self.sent, ["one", "two"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_completion_output_starts_next_step_when_it_contains_start_text(self) -> None:
        """The completion chunk may also satisfy the immediate next start condition."""
        scenario = AutomationScenario(
            name="completion-start-output",
            steps=[
                AutomationStep(
                    "first",
                    "one",
                    completion_type=CompletionType.OUTPUT_CONTAINS,
                    completion_value="complete",
                ),
                AutomationStep(
                    "second",
                    "two",
                    start_type=CompletionType.OUTPUT_CONTAINS,
                    start_value="61",
                ),
            ],
        )

        self.runner.start(scenario)
        self.runner.receive_output("complete: result 61")

        self.assertEqual(self.sent, ["one", "two"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_sends_command_when_prompt_start_condition_matches_newline_terminated_last_line(self) -> None:
        scenario = AutomationScenario(
            name="start-prompt",
            steps=[AutomationStep("run", "command", start_type=CompletionType.PROMPT_REGEX, start_value=r"ready>")],
        )

        self.runner.start(scenario)
        self.runner.receive_output("booting\r\nready>\r\n")

        self.assertEqual(self.sent, ["command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_sends_command_when_output_start_condition_matches_newline_terminated_last_line(self) -> None:
        scenario = AutomationScenario(
            name="start-output-last-line",
            steps=[AutomationStep("run", "command", start_type=CompletionType.OUTPUT_CONTAINS, start_value="ready")],
        )

        self.runner.start(scenario)
        self.runner.receive_output("booting\r\nready\r\n")

        self.assertEqual(self.sent, ["command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_file_start_condition_sends_command_only_after_match(self) -> None:
        scenario = AutomationScenario(
            name="start-file",
            steps=[
                AutomationStep(
                    "run",
                    "command",
                    start_type=CompletionType.REMOTE_FILE_REGEX,
                    start_value=r"ready-[0-9]+",
                    start_file_path="/tmp/state",
                )
            ],
        )

        self.runner.start(scenario)
        self.assertTrue(self.runner.tick())
        command = self.runner.file_check_command()
        self.assertIn("grep -Eq", command or "")
        self.assertIn("/tmp/state", command or "")
        self.assertEqual(self.sent, [])
        self.runner.receive_file_result(True)
        self.assertEqual(self.sent, ["command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)

    def test_delay_start_condition_sends_command_after_timeout(self) -> None:
        scenario = AutomationScenario(
            name="start-delay",
            steps=[AutomationStep("run", "command", start_type=CompletionType.DELAY, start_timeout_seconds=3)],
        )

        self.runner.start(scenario)
        self.assertEqual(self.sent, [])
        self.runner._deadline = 3.0
        self.runner.tick(now=2.0)
        self.assertEqual(self.sent, [])
        self.runner.tick(now=3.0)
        self.assertEqual(self.sent, ["command"])

    def test_start_condition_timeout_retries_from_start_condition(self) -> None:
        scenario = AutomationScenario(
            name="start-timeout",
            steps=[
                AutomationStep(
                    "run",
                    "command",
                    start_type=CompletionType.OUTPUT_CONTAINS,
                    start_value="ready",
                    start_timeout_seconds=1,
                )
            ],
        )

        self.runner.start(scenario)
        self.runner._deadline = 0.0
        self.runner.tick(now=0.0)
        self.assertEqual(self.runner.status.state, AutomationState.RETRY_WAITING)
        self.assertEqual(self.sent, [])
        self.runner._retry_at = 0.0
        self.runner.tick(now=0.0)
        self.assertEqual(self.runner.status.state, AutomationState.WAITING_START)
        self.runner.receive_output("ready")
        self.assertEqual(self.sent, ["command"])

    def test_failed_optional_start_condition_skips_to_the_next_step(self) -> None:
        scenario = AutomationScenario(
            name="skip-unmet-start",
            steps=[
                AutomationStep(
                    "optional",
                    "must-not-send",
                    start_type=CompletionType.OUTPUT_CONTAINS,
                    start_value="ready",
                    skip_on_start_condition_failure=True,
                ),
                AutomationStep("next", "next-command"),
            ],
        )

        self.runner.start(scenario)
        self.runner.fail_current_step("Timed out waiting for start condition")

        self.assertEqual(self.sent, ["next-command"])
        self.assertEqual(self.runner.status.state, AutomationState.SUCCEEDED)
        self.assertEqual(self.runner.skipped_step_indices, frozenset({0}))
