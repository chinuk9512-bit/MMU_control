"""Tests for persisted automation scenarios and sequential execution."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mmu_control.core.automation_runner import AutomationRunner, AutomationState
from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType
from mmu_control.storage.automation_store import AutomationStore


class AutomationStoreTest(unittest.TestCase):
    """Automation JSON data is persisted with its completion conditions."""

    def test_default_store_uses_package_user_scenario_directory(self) -> None:
        """Default scenarios live beside the application package, not in APPDATA."""
        store = AutomationStore.create_default()

        self.assertEqual(
            store._path,
            Path(__file__).resolve().parents[1]
            / "src"
            / "mmu_control"
            / "user_scenario"
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
