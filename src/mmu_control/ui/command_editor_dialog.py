"""Dialog for creating and editing command sets."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from mmu_control.models.command_set import CommandSet


class CommandEditorDialog(QDialog):
    """Modal editor for one command set."""

    def __init__(
        self,
        command_set: CommandSet | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Command Group")
        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color: #b00020;")

        self.name_input = QLineEdit(self)
        self.description_input = QLineEdit(self)
        self.commands_input = QPlainTextEdit(self)
        self.commands_input.setPlaceholderText("Enter one shell command per line. Each command can be selected and run separately.")

        if command_set is not None:
            self.name_input.setText(command_set.name)
            self.description_input.setText(command_set.description)
            self.commands_input.setPlainText(command_set.commands)

        form = QFormLayout()
        form.addRow("Group name", self.name_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Commands (one per line)", self))
        layout.addWidget(self.commands_input)
        layout.addWidget(QLabel("Description", self))
        layout.addWidget(self.description_input)
        layout.addWidget(self._error_label)
        layout.addWidget(buttons)
        self.resize(560, 420)

    def command_set(self) -> CommandSet:
        """Return the current dialog input as a command set."""
        return CommandSet(
            name=self.name_input.text().strip(),
            description=self.description_input.text().strip(),
            commands=self.commands_input.toPlainText().strip(),
        )

    def accept(self) -> None:
        """Validate inputs before closing the dialog."""
        command_set = self.command_set()
        if not command_set.name:
            self._error_label.setText("Name is required.")
            return
        if not command_set.commands:
            self._error_label.setText("At least one command is required.")
            return
        super().accept()
