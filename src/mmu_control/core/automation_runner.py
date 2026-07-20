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

    def __init__(self, send_line: Callable[[str], None]) -> None:
        self._send_line = send_line
        self._scenario: AutomationScenario | None = None
        self._step_index = -1
        self._state = AutomationState.IDLE
        self._deadline = 0.0
        self._retry_at = 0.0
        self._retried = False
        self._output = ""
        self._message = ""

    @property
    def is_active(self) -> bool:
        """Return whether a scenario is still running."""
        return self._state in {AutomationState.WAITING, AutomationState.RETRY_WAITING}

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

    def start(self, scenario: AutomationScenario) -> None:
        """Start a scenario by sending its first command."""
        if self.is_active:
            raise RuntimeError("An automation scenario is already running.")
        if not scenario.steps:
            raise ValueError("Automation scenario must have at least one step.")
        self._scenario = scenario
        self._step_index = 0
        self._retried = False
        self._start_current_step()

    def receive_output(self, output: str) -> None:
        """Evaluate new terminal output against the current completion condition."""
        if self._state != AutomationState.WAITING or not output:
            return
        step = self.current_step
        if step is None:
            return
        self._output = f"{self._output}{output}"[-16_384:]
        if step.completion_type in {
            CompletionType.OUTPUT_CONTAINS,
            CompletionType.OUTPUT_REGEX,
            CompletionType.PROMPT_REGEX,
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        } and self._output_matches(step):
            self._advance()

    def receive_file_result(self, matched: bool, error: Exception | None = None) -> None:
        """Accept an asynchronous remote-file condition result."""
        if self._state != AutomationState.WAITING:
            return
        step = self.current_step
        if step is None or step.completion_type not in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }:
            return
        if error is not None:
            self.fail_current_step(f"File condition failed: {error}")
        elif matched:
            self._advance()

    def file_check_command(self) -> str | None:
        """Return a safe command that checks the current device file condition.

        The command is sent through the scenario's selected terminal.  This
        works for both a device SSH shell and a minicom device shell.
        """
        step = self.current_step
        if step is None or step.completion_type not in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }:
            return None
        grep_option = "-Fq" if step.completion_type == CompletionType.REMOTE_FILE_CONTAINS else "-Eq"
        return (
            f"grep {grep_option} -- {shlex.quote(step.completion_value)} {shlex.quote(step.file_path)} "
            "&& printf '__MMU_AUTOMATION_FILE_MATCH__\\n'"
        )

    def tick(self, now: float | None = None) -> bool:
        """Advance time-based states and return whether a file check is needed."""
        now = time.monotonic() if now is None else now
        if self._state == AutomationState.RETRY_WAITING and now >= self._retry_at:
            self._start_current_step()
            return False
        if self._state != AutomationState.WAITING:
            return False
        step = self.current_step
        if step is None:
            return False
        if step.completion_type == CompletionType.DELAY and now >= self._deadline:
            self._advance()
            return False
        if now >= self._deadline:
            self.fail_current_step(f"Timed out after {step.timeout_seconds} seconds.")
            return False
        return step.completion_type in {
            CompletionType.REMOTE_FILE_CONTAINS,
            CompletionType.REMOTE_FILE_REGEX,
        }

    def fail_current_step(self, message: str) -> None:
        """Retry the current step once, then mark the scenario as failed."""
        if not self.is_active:
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
        step = self.current_step
        if step is None:
            self._state = AutomationState.FAILED
            self._message = "Automation has no current step."
            return
        self._output = ""
        self._state = AutomationState.WAITING
        self._deadline = time.monotonic() + step.timeout_seconds
        self._message = f"Running step {self._step_index + 1}: {step.name or step.command}"
        try:
            self._send_line(step.command)
        except Exception as exc:
            self.fail_current_step(f"Could not send command: {exc}")

    def _advance(self) -> None:
        assert self._scenario is not None
        if self._step_index + 1 >= len(self._scenario.steps):
            self._state = AutomationState.SUCCEEDED
            self._message = "Automation completed successfully."
            return
        self._step_index += 1
        self._retried = False
        self._start_current_step()

    def _output_matches(self, step: AutomationStep) -> bool:
        if step.completion_type == CompletionType.OUTPUT_CONTAINS:
            return step.completion_value in self._output
        if step.completion_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX}:
            return "__MMU_AUTOMATION_FILE_MATCH__" in self._output
        flags = re.MULTILINE
        try:
            pattern = re.compile(step.completion_value, flags)
        except re.error as exc:
            self.fail_current_step(f"Invalid completion regular expression: {exc}")
            return False
        if step.completion_type == CompletionType.PROMPT_REGEX:
            latest_line = self._output.replace("\r", "\n").split("\n")[-1]
            return bool(pattern.fullmatch(latest_line.strip()))
        return bool(pattern.search(self._output))
