"""Dialog for editing a sequential terminal automation scenario."""

from __future__ import annotations

import re

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType


class AutomationEditorDialog(QDialog):
    """Edit any number of commands and their individual completion conditions."""

    def __init__(
        self,
        scenario: AutomationScenario | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Automation Scenario")
        # A scenario can be saved before its steps are configured.  This lets
        # users create a named scenario and fill in its commands later.
        self._steps = list(scenario.steps) if scenario is not None else []
        self._current_index = -1
        self.name_input = QLineEdit(scenario.name if scenario else "", self)
        self.description_input = QLineEdit(scenario.description if scenario else "", self)
        self.transport_input = QComboBox(self)
        self.transport_input.addItem("SSH shell", "ssh")
        self.transport_input.addItem("Minicom", "minicom")
        self.transport_input.setCurrentIndex(1 if scenario and scenario.transport == "minicom" else 0)
        self.step_list = QListWidget(self)
        self.step_list.currentRowChanged.connect(self._select_step)
        self.step_name_input = QLineEdit(self)
        self.command_input = QPlainTextEdit(self)
        self.command_input.setPlaceholderText("Command to send to the selected SSH shell or minicom session")
        self.condition_type_input = QComboBox(self)
        for completion_type, label in (
            (CompletionType.NONE, "No completion condition required"),
            (CompletionType.OUTPUT_CONTAINS, "Console contains text"),
            (CompletionType.OUTPUT_REGEX, "Console matches regular expression"),
            (CompletionType.PROMPT_REGEX, "Latest prompt matches regular expression"),
            (CompletionType.REMOTE_FILE_CONTAINS, "Device file contains text"),
            (CompletionType.REMOTE_FILE_REGEX, "Device file matches regular expression"),
            (CompletionType.DELAY, "Wait for duration"),
        ):
            self.condition_type_input.addItem(label, completion_type)
        self.condition_type_input.currentIndexChanged.connect(self._update_condition_labels)
        self.condition_value_input = QLineEdit(self)
        self.file_path_input = QLineEdit(self)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 86_400)
        self.timeout_input.setSuffix(" seconds")
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #b00020;")
        self._build_layout()
        self._refresh_step_list()
        self.step_list.setCurrentRow(0)

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Name", self.name_input)
        form.addRow("Description", self.description_input)
        form.addRow("Run on", self.transport_input)

        add_button = QPushButton("Add Step", self)
        duplicate_button = QPushButton("Duplicate", self)
        delete_button = QPushButton("Delete", self)
        up_button = QPushButton("Up", self)
        down_button = QPushButton("Down", self)
        add_button.clicked.connect(self._add_step)
        duplicate_button.clicked.connect(self._duplicate_step)
        delete_button.clicked.connect(self._delete_step)
        up_button.clicked.connect(lambda: self._move_step(-1))
        down_button.clicked.connect(lambda: self._move_step(1))
        actions = QHBoxLayout()
        for button in (add_button, duplicate_button, delete_button, up_button, down_button):
            actions.addWidget(button)

        step_form = QFormLayout()
        step_form.addRow("Step name", self.step_name_input)
        step_form.addRow("Command", self.command_input)
        step_form.addRow("Completion", self.condition_type_input)
        step_form.addRow("Text / regular expression", self.condition_value_input)
        step_form.addRow("Device file path", self.file_path_input)
        step_form.addRow("Timeout", self.timeout_input)
        details = QWidget(self)
        details.setLayout(step_form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.step_list)
        layout.addWidget(details)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.resize(760, 720)

    def scenario(self) -> AutomationScenario:
        """Return the current, validated dialog data as a scenario."""
        self._store_current_step()
        return AutomationScenario(
            name=self.name_input.text().strip(),
            description=self.description_input.text().strip(),
            transport=str(self.transport_input.currentData()),
            steps=self._steps,
        )

    def accept(self) -> None:
        """Validate scenario data before accepting the dialog."""
        scenario = self.scenario()
        if not scenario.name:
            self.error_label.setText("Scenario name is required.")
            return
        for index, step in enumerate(scenario.steps, start=1):
            if not step.command.strip():
                self.error_label.setText(f"Step {index}: command is required.")
                return
            if step.completion_type in {CompletionType.NONE, CompletionType.DELAY}:
                continue
            if not step.completion_value:
                self.error_label.setText(f"Step {index}: completion value is required.")
                return
            if step.completion_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX} and not step.file_path:
                self.error_label.setText(f"Step {index}: device file path is required.")
                return
            if step.completion_type in {CompletionType.OUTPUT_REGEX, CompletionType.PROMPT_REGEX, CompletionType.REMOTE_FILE_REGEX}:
                try:
                    re.compile(step.completion_value)
                except re.error as exc:
                    self.error_label.setText(f"Step {index}: invalid regular expression: {exc}")
                    return
        super().accept()

    def _refresh_step_list(self) -> None:
        selected = self._current_index
        self.step_list.clear()
        for index, step in enumerate(self._steps, start=1):
            self.step_list.addItem(f"{index}. {step.name or step.command or 'Unnamed step'}")
        if self._steps:
            self.step_list.setCurrentRow(max(0, min(selected, len(self._steps) - 1)))

    def _select_step(self, index: int) -> None:
        self._store_current_step()
        self._current_index = index
        if not 0 <= index < len(self._steps):
            return
        step = self._steps[index]
        self.step_name_input.setText(step.name)
        self.command_input.setPlainText(step.command)
        self.condition_type_input.setCurrentIndex(self.condition_type_input.findData(step.completion_type))
        self.condition_value_input.setText(step.completion_value)
        self.file_path_input.setText(step.file_path)
        self.timeout_input.setValue(step.timeout_seconds)
        self._update_condition_labels()

    def _store_current_step(self) -> None:
        if not 0 <= self._current_index < len(self._steps):
            return
        self._steps[self._current_index] = AutomationStep(
            name=self.step_name_input.text().strip(),
            command=self.command_input.toPlainText().strip(),
            completion_type=self.condition_type_input.currentData(),
            completion_value=self.condition_value_input.text(),
            file_path=self.file_path_input.text().strip(),
            timeout_seconds=self.timeout_input.value(),
        )

    def _update_condition_labels(self) -> None:
        completion_type = self.condition_type_input.currentData()
        file_condition = completion_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX}
        delay = completion_type == CompletionType.DELAY
        no_completion_condition = completion_type == CompletionType.NONE
        self.condition_value_input.setEnabled(not delay and not no_completion_condition)
        self.file_path_input.setEnabled(file_condition)
        self.file_path_input.setPlaceholderText("Absolute device path" if file_condition else "Not used for this condition")
        self.condition_value_input.setPlaceholderText(
            "Not used for this completion type" if no_completion_condition or delay else "Text or regular expression"
        )

    def _add_step(self) -> None:
        self._store_current_step()
        self._steps.append(AutomationStep(name=f"Step {len(self._steps) + 1}"))
        self._current_index = len(self._steps) - 1
        self._refresh_step_list()

    def _duplicate_step(self) -> None:
        self._store_current_step()
        if not 0 <= self._current_index < len(self._steps):
            return
        step = self._steps[self._current_index]
        self._steps.insert(self._current_index + 1, AutomationStep(
            name=f"{step.name} copy", command=step.command, completion_type=step.completion_type,
            completion_value=step.completion_value, file_path=step.file_path, timeout_seconds=step.timeout_seconds,
        ))
        self._current_index += 1
        self._refresh_step_list()

    def _delete_step(self) -> None:
        if len(self._steps) <= 1 or not 0 <= self._current_index < len(self._steps):
            return
        self._steps.pop(self._current_index)
        self._current_index = min(self._current_index, len(self._steps) - 1)
        self._refresh_step_list()

    def _move_step(self, offset: int) -> None:
        self._store_current_step()
        target = self._current_index + offset
        if not 0 <= self._current_index < len(self._steps) or not 0 <= target < len(self._steps):
            return
        self._steps[self._current_index], self._steps[target] = self._steps[target], self._steps[self._current_index]
        self._current_index = target
        self._refresh_step_list()
