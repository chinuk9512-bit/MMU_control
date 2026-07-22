"""Sequential, condition-driven execution for automation scenarios."""

from __future__ import annotations

import re
import shlex
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType


class AutomationState(StrEnum):
    """Observable state of an automation run."""

    IDLE = "idle"
    WAITING_START = "waiting_start"
    WAITING = "waiting"
    RETRY_WAITING = "retry_waiting"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AutomationStatus:
    """A snapshot intended for UI status rendering."""

    state: AutomationState
    step_index: int = -1
    message: str = ""


class AutomationRunner:
    """Run one scenario, retrying only its failing current step once."""

    RETRY_DELAY_SECONDS = 2.0
    # Output-based conditions intentionally inspect only the most recent
    # console text, so stale output cannot satisfy a later condition.
    OUTPUT_LIMIT = 300

    def __init__(self, send_line: Callable[[str], None]) -> None:
        self._send_line = send_line
        self._scenario: AutomationScenario | None = None
        self._step_index = -1
        self._start_step_index = 0
        self._state = AutomationState.IDLE
        self._deadline = 0.0
        self._retry_at = 0.0
        self._retried = False
        self._output = ""
        self._message = ""
        self._skipped_step_indices: set[int] = set()

    @property
    def is_active(self) -> bool:
        """Return whether a scenario is still running."""
        return self._state in {AutomationState.WAITING_START, AutomationState.WAITING, AutomationState.RETRY_WAITING}

    @property
    def status(self) -> AutomationStatus:
        """Return the current runner status."""
        return AutomationStatus(self._state, self._step_index, self._message)

    @property
    def current_step(self) -> AutomationStep | None:
        """Return the step currently being evaluated."""
        if self._scenario is None or not 0 <= self._step_index < len(self._scenario.steps):
            return None
        return self._scenario.steps[self._step_index]

    @property
    def scenario(self) -> AutomationScenario | None:
        """Return the scenario associated with this run."""
        return self._scenario

    @property
    def start_step_index(self) -> int:
        """Return the zero-based step at which the current run began."""
        return self._start_step_index

    @property
    def skipped_step_indices(self) -> frozenset[int]:
        """Return zero-based indices of steps skipped after a start-condition failure."""
        return frozenset(self._skipped_step_indices)

    def start(self, scenario: AutomationScenario, start_step_index: int = 0) -> None:
        """Start a scenario at a chosen step by evaluating its start condition."""
        if self.is_active:
            raise RuntimeError("An automation scenario is already running.")
        if not scenario.steps:
            raise ValueError("Automation scenario must have at least one step.")
        if not 0 <= start_step_index < len(scenario.steps):
            raise ValueError("Automation start step must be within the scenario.")
        self._scenario = scenario
        self._start_step_index = start_step_index
        self._step_index = start_step_index
        self._retried = False
        self._skipped_step_indices.clear()
        self._start_current_step()

    def receive_initial_output(self, output: str) -> None:
        """Evaluate the first step's start condition against a terminal snapshot.

        A snapshot belongs only to the scenario boundary: later steps must
        evaluate their start conditions using output received after the prior
        step completed.
        """
        if self._step_index != self._start_step_index or self._state != AutomationState.WAITING_START:
            return
        self.receive_output(output)

    def receive_output(self, output: str) -> None:
        """Evaluate new terminal output against the active start or completion condition."""
        if self._state not in {AutomationState.WAITING_START, AutomationState.WAITING} or not output:
            return
        step = self.current_step
        if step is None:
            return
        self._output = f"{self._output}{output}"[-self.OUTPUT_LIMIT :]
        condition_type = self._condition_type(step)
        if condition_type in {
            CompletionType.OUTPUT_CONTAINS,
            CompletionType.OUTPUT_REGEX,
            CompletionType.PROMPT_REGEX,
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        } and self._output_matches():
            self._condition_satisfied()

    def receive_file_result(self, matched: bool, error: Exception | None = None) -> None:
        """Accept an asynchronous remote-file condition result."""
        if self._state not in {AutomationState.WAITING_START, AutomationState.WAITING}:
            return
        step = self.current_step
        if step is None or self._condition_type(step) not in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }:
            return
        if error is not None:
            self.fail_current_step(f"File condition failed: {error}")
        elif matched:
            self._condition_satisfied()

    def file_check_command(self) -> str | None:
        """Return a safe command that checks the current device file condition.

        The command is sent through the scenario's selected terminal.  This
        works for both a device SSH shell and a minicom device shell.
        """
        step = self.current_step
        if self._state not in {AutomationState.WAITING_START, AutomationState.WAITING} or step is None or self._condition_type(step) not in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }:
            return None
        grep_option = "-Fq" if self._condition_type(step) == CompletionType.REMOTE_FILE_CONTAINS else "-Eq"
        return (
            f"grep {grep_option} -- {shlex.quote(self._condition_value(step))} {shlex.quote(self._condition_file_path(step))} "
            "&& printf '__MMU_AUTOMATION_FILE_MATCH__\\n'"
        )

    def tick(self, now: float | None = None) -> bool:
        """Advance time-based states and return whether a file check is needed."""
        now = time.monotonic() if now is None else now
        if self._state == AutomationState.RETRY_WAITING and now >= self._retry_at:
            self._start_current_step()
            return False
        if self._state not in {AutomationState.WAITING_START, AutomationState.WAITING}:
            return False
        step = self.current_step
        if step is None:
            return False
        if self._condition_type(step) == CompletionType.DELAY and now >= self._deadline:
            self._condition_satisfied()
            return False
        if now >= self._deadline:
            self.fail_current_step(f"Timed out waiting for {self._condition_name()} after {self._timeout_seconds(step)} seconds.")
            return False
        return self._condition_type(step) in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }

    def fail_current_step(self, message: str) -> None:
        """Retry the current step once, then mark the scenario as failed."""
        if not self.is_active:
            return
        step = self.current_step
        if (
            self._state == AutomationState.WAITING_START
            and step is not None
            and step.skip_on_start_condition_failure
        ):
            self._skipped_step_indices.add(self._step_index)
            self._advance()
            return
        if not self._retried:
            self._retried = True
            self._state = AutomationState.RETRY_WAITING
            self._retry_at = time.monotonic() + self.RETRY_DELAY_SECONDS
            self._message = f"{message} Retrying this step once in 2 seconds."
            return
        self._state = AutomationState.FAILED
        self._message = message

    def cancel(self) -> None:
        """Cancel the active run without sending another command."""
        if self.is_active:
            self._state = AutomationState.CANCELLED
            self._message = "Automation stopped by user."

    def _start_current_step(self) -> None:
        """Begin a step from its start condition on every retry."""
        step = self.current_step
        if step is None:
            self._state = AutomationState.FAILED
            self._message = "Automation has no current step."
            return
        self._output = ""
        self._state = AutomationState.WAITING_START
        self._deadline = time.monotonic() + step.start_timeout_seconds
        self._message = f"Waiting to start step {self._step_index + 1}: {step.name or step.command}"
        if step.start_type == CompletionType.NONE:
            self._send_current_command()

    def _send_current_command(self) -> None:
        step = self.current_step
        if step is None:
            return
        self._output = ""
        self._state = AutomationState.WAITING
        self._deadline = time.monotonic() + step.timeout_seconds
        self._message = f"Running step {self._step_index + 1}: {step.name or step.command}"
        try:
            self._send_line(step.command)
        except Exception as exc:
            self.fail_current_step(f"Could not send command: {exc}")
            return
        if step.completion_type == CompletionType.NONE:
            self._advance()

    def _condition_satisfied(self) -> None:
        if self._state == AutomationState.WAITING_START:
            self._send_current_command()
        else:
            self._advance()

    def _condition_type(self, step: AutomationStep) -> CompletionType:
        return step.start_type if self._state == AutomationState.WAITING_START else step.completion_type

    def _condition_value(self, step: AutomationStep) -> str:
        return step.start_value if self._state == AutomationState.WAITING_START else step.completion_value

    def _condition_file_path(self, step: AutomationStep) -> str:
        return step.start_file_path if self._state == AutomationState.WAITING_START else step.file_path

    def _timeout_seconds(self, step: AutomationStep) -> int:
        return step.start_timeout_seconds if self._state == AutomationState.WAITING_START else step.timeout_seconds

    def _condition_name(self) -> str:
        return "start condition" if self._state == AutomationState.WAITING_START else "completion condition"

    def _advance(self) -> None:
        assert self._scenario is not None
        if self._step_index + 1 >= len(self._scenario.steps):
            self._state = AutomationState.SUCCEEDED
            self._message = "Automation completed successfully."
            return
        self._step_index += 1
        self._retried = False
        self._start_current_step()

    def _output_matches(self) -> bool:
        step = self.current_step
        assert step is not None
        condition_type = self._condition_type(step)
        condition_value = self._condition_value(step)
        if condition_type == CompletionType.OUTPUT_CONTAINS:
            return self._output_contains(condition_value)
        if condition_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX}:
            return "__MMU_AUTOMATION_FILE_MATCH__" in self._output
        flags = re.MULTILINE
        try:
            pattern = re.compile(condition_value, flags)
        except re.error as exc:
            self.fail_current_step(f"Invalid {self._condition_name()} regular expression: {exc}")
            return False
        if condition_type == CompletionType.PROMPT_REGEX:
            latest_line = self._latest_output_line()
            return bool(pattern.fullmatch(latest_line.strip()))
        return bool(pattern.search(self._output))

    def _latest_output_line(self) -> str:
        """Return the final terminal line, including one ended by a newline."""
        normalized_output = self._output.replace("\r\n", "\n").replace("\r", "\n")
        lines = normalized_output.splitlines()
        return lines[-1] if lines else ""

    def _output_contains(self, condition_value: str) -> bool:
        """Match displayed text in the latest terminal line or prior output."""
        return condition_value in self._latest_output_line() or condition_value in self._output
