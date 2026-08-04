"""Dialog for turning a text file or pasted commands into an automation draft."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from mmu_control.core.automation_import_parser import parse_automation_commands
from mmu_control.models.automation import AutomationScenario


class AutomationImportDialog(QDialog):
    """Collect import metadata and create an unsaved automation scenario draft."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Scenario from Text")
        self._scenario: AutomationScenario | None = None

        self.name_input = QLineEdit(self)
        self.description_input = QLineEdit(self)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 86_400)
        self.timeout_input.setValue(60)
        self.timeout_input.setSuffix(" seconds")

        self.file_source_radio = QRadioButton("Choose file", self)
        self.text_source_radio = QRadioButton("Paste text", self)
        self.text_source_radio.setChecked(True)
        self.file_path_input = QLineEdit(self)
        self.file_path_input.setPlaceholderText(
            "Command text file (three /// separator lines split multi-line commands)"
        )
        self.file_browse_button = QPushButton("Browse...", self)
        self.file_browse_button.clicked.connect(self._choose_file)
        self.text_input = QPlainTextEdit(self)
        self.text_input.setPlaceholderText(
            "Paste commands here. Three consecutive lines containing at least two / "
            "characters are separators. Lines between separators become one command. "
            "Lines starting with # are comments."
        )
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #ff7b86;")

        self.file_source_radio.toggled.connect(self._update_source_controls)
        self.text_source_radio.toggled.connect(self._update_source_controls)
        self._build_layout()
        self._update_source_controls()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        metadata = QFormLayout()
        metadata.addRow("Scenario name", self.name_input)
        metadata.addRow("Description", self.description_input)
        metadata.addRow("Default timeout", self.timeout_input)
        layout.addLayout(metadata)

        layout.addWidget(self.file_source_radio)
        file_layout = QHBoxLayout()
        file_layout.addWidget(self.file_path_input)
        file_layout.addWidget(self.file_browse_button)
        layout.addLayout(file_layout)
        layout.addWidget(self.text_source_radio)
        layout.addWidget(self.text_input)
        layout.addWidget(self.error_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(680, 520)

    def _update_source_controls(self) -> None:
        file_source = self.file_source_radio.isChecked()
        self.file_path_input.setEnabled(file_source)
        self.file_browse_button.setEnabled(file_source)
        self.text_input.setEnabled(not file_source)

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose command text file", "", "Text files (*.txt);;All files (*)"
        )
        if path:
            self.file_path_input.setText(path)
            self.file_source_radio.setChecked(True)

    def _source_text(self) -> str | None:
        if not self.file_source_radio.isChecked():
            return self.text_input.toPlainText()
        path_text = self.file_path_input.text().strip()
        if not path_text:
            self.error_label.setText("Choose a text file to import.")
            return None
        try:
            return Path(path_text).read_text(encoding="utf-8")
        except OSError as exc:
            self.error_label.setText(f"Could not read the text file: {exc}")
            return None
        except UnicodeError:
            self.error_label.setText("The text file must be UTF-8 encoded.")
            return None

    def scenario(self) -> AutomationScenario | None:
        """Return the parsed draft after successful import validation."""
        return self._scenario

    def accept(self) -> None:
        """Validate input and create a draft without persisting it."""
        self.error_label.clear()
        name = self.name_input.text().strip()
        if not name:
            self.error_label.setText("Scenario name is required.")
            return
        text = self._source_text()
        if text is None:
            return
        steps = parse_automation_commands(text, self.timeout_input.value())
        if not steps:
            self.error_label.setText(
                "No commands were found to import. Enter commands other than blank lines "
                "and # comment lines."
            )
            return
        self._scenario = AutomationScenario(
            name=name,
            description=self.description_input.text().strip(),
            steps=steps,
        )
        super().accept()
