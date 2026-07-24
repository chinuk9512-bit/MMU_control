"""Dialog for editing a sequential terminal automation scenario."""

from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
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
    QScrollArea,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from mmu_control.models.automation import AutomationScenario, AutomationStep, CompletionType


class ScenarioStepListWidget(QListWidget):
    """Step list with explicit keyboard navigation between scenario steps."""

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        """Select the preceding or following step with the arrow keys."""
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            offset = -1 if event.key() == Qt.Key.Key_Up else 1
            target = max(0, min(self.count() - 1, self.currentRow() + offset))
            self.setCurrentRow(target)
            event.accept()
            return
        super().keyPressEvent(event)


class AutomationEditorDialog(QDialog):
    """Edit any number of commands and their individual completion conditions."""

    # The details pane scrolls, so the editor remains usable on smaller displays.
    MINIMUM_HEIGHT = 600
    DEFAULT_HEIGHT = 900
    STEP_LIST_MINIMUM_HEIGHT = 45
    DEFAULT_VISIBLE_STEP_COUNT = 8
    COMMAND_MINIMUM_HEIGHT = 144

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
        self._updating_step_selection = False
        self.name_input = QLineEdit(scenario.name if scenario else "", self)
        self.description_input = QLineEdit(scenario.description if scenario else "", self)
        self.step_list = ScenarioStepListWidget(self)
        self.step_list.setMinimumHeight(self.STEP_LIST_MINIMUM_HEIGHT)
        self.step_list.currentRowChanged.connect(self._select_step)
        self.step_name_input = QLineEdit(self)
        self.command_input = QPlainTextEdit(self)
        self.command_input.setMinimumHeight(self.COMMAND_MINIMUM_HEIGHT)
        self.command_input.setPlaceholderText("Command to send to the currently active console")
        self.start_type_input = QComboBox(self)
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
            self.start_type_input.addItem(label, completion_type)
            self.condition_type_input.addItem(label, completion_type)
        self.start_type_input.currentIndexChanged.connect(self._update_condition_labels)
        self.condition_type_input.currentIndexChanged.connect(self._update_condition_labels)
        self.start_value_input = QLineEdit(self)
        self.start_file_path_input = QLineEdit(self)
        self.start_timeout_input = QSpinBox(self)
        self.start_timeout_input.setRange(1, 86_400)
        self.start_timeout_input.setSuffix(" seconds")
        self.skip_on_start_condition_failure_input = QCheckBox(
            "Skip this step and continue when the start condition times out or fails", self
        )
        self.condition_value_input = QLineEdit(self)
        self.file_path_input = QLineEdit(self)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 86_400)
        self.timeout_input.setSuffix(" seconds")
        self.save_step_button = QPushButton("Save Step", self)
        self.save_step_button.clicked.connect(self._save_current_step)
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #b00020;")
        self._build_layout()
        self._refresh_step_list()
        self.step_list.setCurrentRow(0)
        self._step_splitter_initialized = False

    def _build_layout(self) -> None:
        form = QFormLayout()
        form.addRow("Name", self.name_input)
        form.addRow("Description", self.description_input)

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
        step_form.addRow("Start condition", self.start_type_input)
        step_form.addRow("Start text / regular expression", self.start_value_input)
        step_form.addRow("Start device file path", self.start_file_path_input)
        step_form.addRow("Start timeout", self.start_timeout_input)
        step_form.addRow("Start condition failure", self.skip_on_start_condition_failure_input)
        step_form.addRow("Completion condition", self.condition_type_input)
        step_form.addRow("Completion text / regular expression", self.condition_value_input)
        step_form.addRow("Completion device file path", self.file_path_input)
        step_form.addRow("Completion timeout", self.timeout_input)
        step_form.addRow(self.save_step_button)
        details = QWidget(self)
        details.setLayout(step_form)
        details_scroll_area = QScrollArea(self)
        details_scroll_area.setWidgetResizable(True)
        details_scroll_area.setWidget(details)

        # Both panes remain independently scrollable.  The splitter lets users
        # give the list less or more space without hiding the step details.
        self.step_editor_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.step_editor_splitter.setChildrenCollapsible(False)
        self.step_editor_splitter.addWidget(self.step_list)
        self.step_editor_splitter.addWidget(details_scroll_area)
        self.step_editor_splitter.setStretchFactor(0, 0)
        self.step_editor_splitter.setStretchFactor(1, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(actions)
        layout.addWidget(self.step_editor_splitter, 1)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)
        self.setMinimumHeight(self.MINIMUM_HEIGHT)
        self.resize(760, self.DEFAULT_HEIGHT)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        """Give the step list room for eight rows when the dialog first opens."""
        super().showEvent(event)
        if not self._step_splitter_initialized:
            QTimer.singleShot(0, self._set_initial_step_list_height)

    def _set_initial_step_list_height(self) -> None:
        """Set the initial splitter position after Qt has laid out the dialog."""
        if self._step_splitter_initialized or self.step_editor_splitter.height() <= 0:
            return
        row_height = self.step_list.sizeHintForRow(0)
        if row_height <= 0:
            row_height = self.step_list.fontMetrics().height()
        list_height = (row_height * self.DEFAULT_VISIBLE_STEP_COUNT) + (self.step_list.frameWidth() * 2)
        remaining_height = max(1, self.step_editor_splitter.height() - list_height)
        self.step_editor_splitter.setSizes([list_height, remaining_height])
        self._step_splitter_initialized = True

    def scenario(self) -> AutomationScenario:
        """Return the current, validated dialog data as a scenario."""
        self._store_current_step()
        return AutomationScenario(
            name=self.name_input.text().strip(),
            description=self.description_input.text().strip(),
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
            for label, condition_type, value, file_path in (
                ("start", step.start_type, step.start_value, step.start_file_path),
                ("completion", step.completion_type, step.completion_value, step.file_path),
            ):
                if condition_type in {CompletionType.NONE, CompletionType.DELAY}:
                    continue
                if not value:
                    self.error_label.setText(f"Step {index}: {label} value is required.")
                    return
                if condition_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX} and not file_path:
                    self.error_label.setText(f"Step {index}: {label} device file path is required.")
                    return
                if condition_type in {CompletionType.OUTPUT_REGEX, CompletionType.PROMPT_REGEX, CompletionType.REMOTE_FILE_REGEX}:
                    try:
                        re.compile(value)
                    except re.error as exc:
                        self.error_label.setText(f"Step {index}: invalid {label} regular expression: {exc}")
                        return
        super().accept()

    def _refresh_step_list(self) -> None:
        selected = self._current_index
        self._updating_step_selection = True
        try:
            self.step_list.clear()
            for index, step in enumerate(self._steps, start=1):
                self.step_list.addItem(f"{index}. {step.name or step.command or 'Unnamed step'}")
            if self._steps:
                self.step_list.setCurrentRow(max(0, min(selected, len(self._steps) - 1)))
        finally:
            self._updating_step_selection = False

    def _select_step(self, index: int) -> None:
        if not self._updating_step_selection:
            self._store_current_step()
        self._current_index = index
        if not 0 <= index < len(self._steps):
            return
        step = self._steps[index]
        self.step_name_input.setText(step.name)
        self.command_input.setPlainText(step.command)
        self.start_type_input.setCurrentIndex(self.start_type_input.findData(step.start_type))
        self.start_value_input.setText(step.start_value)
        self.start_file_path_input.setText(step.start_file_path)
        self.start_timeout_input.setValue(step.start_timeout_seconds)
        self.skip_on_start_condition_failure_input.setChecked(step.skip_on_start_condition_failure)
        self.condition_type_input.setCurrentIndex(self.condition_type_input.findData(step.completion_type))
        self.condition_value_input.setText(step.completion_value)
        self.file_path_input.setText(step.file_path)
        self.timeout_input.setValue(step.timeout_seconds)
        self._update_condition_labels()

    def _store_current_step(self) -> None:
        if not 0 <= self._current_index < len(self._steps):
            return
        start_type = self.start_type_input.currentData()
        start_value, start_file_path = self._condition_inputs(start_type, self.start_value_input, self.start_file_path_input)
        completion_type = self.condition_type_input.currentData()
        completion_value, file_path = self._condition_inputs(completion_type, self.condition_value_input, self.file_path_input)
        self._steps[self._current_index] = AutomationStep(
            name=self.step_name_input.text().strip(),
            command=self.command_input.toPlainText().strip(),
            completion_type=completion_type,
            completion_value=completion_value,
            file_path=file_path,
            timeout_seconds=self.timeout_input.value(),
            start_type=start_type,
            start_value=start_value,
            start_file_path=start_file_path,
            start_timeout_seconds=self.start_timeout_input.value(),
            skip_on_start_condition_failure=self.skip_on_start_condition_failure_input.isChecked(),
        )

    def _save_current_step(self) -> None:
        """Save the selected step without closing the scenario editor."""
        if not 0 <= self._current_index < len(self._steps):
            self.error_label.setStyleSheet("color: #b00020;")
            self.error_label.setText("Select a step to save.")
            return
        if not self.command_input.toPlainText().strip():
            self.error_label.setStyleSheet("color: #b00020;")
            self.error_label.setText("Step command is required.")
            return

        self._store_current_step()
        step = self._steps[self._current_index]
        self.step_list.item(self._current_index).setText(
            f"{self._current_index + 1}. {step.name or step.command or 'Unnamed step'}"
        )
        self.error_label.setStyleSheet("color: #006400;")
        self.error_label.setText("Step saved.")

    def _update_condition_labels(self) -> None:
        self._update_condition_widgets(self.start_type_input.currentData(), self.start_value_input, self.start_file_path_input, "start")
        self._update_condition_widgets(self.condition_type_input.currentData(), self.condition_value_input, self.file_path_input, "completion")

    @staticmethod
    def _condition_inputs(condition_type: CompletionType, value_input: QLineEdit, file_path_input: QLineEdit) -> tuple[str, str]:
        value = value_input.text()
        file_path = file_path_input.text().strip()
        if condition_type in {CompletionType.NONE, CompletionType.DELAY}:
            value = ""
        if condition_type not in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX}:
            file_path = ""
        return value, file_path

    @staticmethod
    def _update_condition_widgets(condition_type: CompletionType, value_input: QLineEdit, file_path_input: QLineEdit, label: str) -> None:
        file_condition = condition_type in {CompletionType.REMOTE_FILE_CONTAINS, CompletionType.REMOTE_FILE_REGEX}
        unused_value = condition_type in {CompletionType.NONE, CompletionType.DELAY}
        value_input.setEnabled(not unused_value)
        file_path_input.setEnabled(file_condition)
        file_path_input.setPlaceholderText("Absolute device path" if file_condition else "Not used for this condition")
        value_input.setPlaceholderText(f"Not used for this {label} type" if unused_value else "Text or regular expression")

    def _add_step(self) -> None:
        self._store_current_step()
        self._steps.append(AutomationStep())
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
            start_type=step.start_type, start_value=step.start_value, start_file_path=step.start_file_path,
            start_timeout_seconds=step.start_timeout_seconds,
            skip_on_start_condition_failure=step.skip_on_start_condition_failure,
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
