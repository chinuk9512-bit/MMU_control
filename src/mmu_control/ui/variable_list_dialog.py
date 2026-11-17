"""Searchable command variable catalog and common variable manager for a client workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView, QInputDialog, QMessageBox,
)


from mmu_control.storage.variable_store import VariableStore, VariableStoreError


@dataclass(frozen=True)
class VariableEntry:
    """One variable's name, origin, purpose and optional current value."""

    name: str
    source: str
    description: str
    value: str | None


class VariableListDialog(QDialog):
    """Display variable names without exposing their values by default."""

    def __init__(
        self, provider: Callable[[], tuple[list[VariableEntry], str]],
        parent: QWidget | None = None, client_name: str = "Current client",
        *, variable_store: VariableStore | None = None,
    ) -> None:
        super().__init__(parent)
        self._provider = provider
        self._variable_store = variable_store
        self._load_error = ""
        self._entries: list[VariableEntry] = []
        self.setWindowTitle(f"Variables — {client_name}")
        self.resize(640, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Click a variable to copy its ${NAME} command syntax.", self))
        controls = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("Search variable names")
        controls.addWidget(self.search_input, stretch=1)
        self.show_values = QCheckBox("Show values", self)
        controls.addWidget(self.show_values)
        self.refresh_button = QPushButton("Refresh", self)
        controls.addWidget(self.refresh_button)
        layout.addLayout(controls)
        self.error_label = QLabel(self)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Variable", "Value"])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.status_label = QLabel(self)
        layout.addWidget(self.status_label)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        self.add_button = buttons.addButton("Add variable", QDialogButtonBox.ButtonRole.ActionRole)
        self.remove_button = buttons.addButton("Remove variable", QDialogButtonBox.ButtonRole.ActionRole)
        self.copy_button = buttons.addButton("Copy variable", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search_input.textChanged.connect(self._filter)
        self.show_values.toggled.connect(self._render)
        self.refresh_button.clicked.connect(self.refresh)
        self.table.cellClicked.connect(lambda *_: self.copy_variable())
        self.table.itemSelectionChanged.connect(self._update_copy_button)
        self.copy_button.clicked.connect(self.copy_variable)
        self.add_button.clicked.connect(self.add_variable)
        self.remove_button.clicked.connect(self.remove_variable)
        self.refresh()

    def refresh(self) -> None:
        """Reload from disk/current inputs and return to masked values."""
        self.show_values.blockSignals(True)
        self.show_values.setChecked(False)
        self.show_values.blockSignals(False)
        self._entries, error = self._provider()
        self._load_error = error
        self.error_label.setText(error)
        self.error_label.setVisible(bool(error))
        self.status_label.clear()
        self._render()

    def _render(self) -> None:
        self.table.clearContents()
        self.table.setRowCount(len(self._entries))
        for row, entry in enumerate(self._entries):
            value = "Unavailable" if entry.value is None else (
                entry.value if self.show_values.isChecked() else "Hidden"
            )
            for column, text in enumerate((f"${{{entry.name}}}", value)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.table.clearSelection()
        self._filter()

    def _filter(self) -> None:
        query = self.search_input.text().strip().casefold()
        for row, entry in enumerate(self._entries):
            # Values are never searched, even when shown: a hidden password
            # must not be discoverable by trying search strings.
            searchable = entry.name.casefold()
            self.table.setRowHidden(row, query not in searchable)
        self._update_copy_button()

    def _update_copy_button(self) -> None:
        row = self.table.currentRow()
        selected = bool(self.table.selectedItems()) and row >= 0 and not self.table.isRowHidden(row)
        self.copy_button.setEnabled(selected)
        writable = self._variable_store is not None and not self._load_error
        self.add_button.setEnabled(writable)
        self.remove_button.setEnabled(
            writable and selected and self._entries[row].source == "Common variables.json"
        )

    def copy_variable(self) -> None:
        """Copy syntax only, never the value, for the selected visible row."""
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row) or not self.table.selectedItems():
            return
        syntax = self.table.item(row, 0).text()
        QApplication.clipboard().setText(syntax)
        self.status_label.setText(f"Copied {syntax}")

    def _save_error(self, error: VariableStoreError) -> None:
        self._load_error = str(error)
        self.error_label.setText(self._load_error)
        self.error_label.show()
        self._update_copy_button()

    def add_variable(self) -> None:
        """Add a new common variable without overwriting an existing name."""
        if self._variable_store is None or self._load_error:
            return
        name, accepted = QInputDialog.getText(
            self, "Add common variable", "Variable name (without ${}):"
        )
        if not accepted:
            return
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            QMessageBox.warning(self, "Invalid name", "Use letters, digits and underscores; start with a letter or underscore.")
            return
        if any(entry.name == name for entry in self._entries):
            QMessageBox.warning(self, "Name already exists", "This variable already exists or is provided by Client inputs.")
            return
        value, accepted = QInputDialog.getText(
            self, "Add common variable", f"Value for ${{{name}}} (shared by all clients):",
            echo=QLineEdit.EchoMode.Password,
        )
        if not accepted:
            return
        try:
            # Read after prompting so additions made outside this dialog are
            # retained and names added during the prompt are checked again.
            variables = self._variable_store.load()
            if name in variables:
                QMessageBox.warning(self, "Name already exists", "This variable was added elsewhere. Refresh the list.")
                return
            variables[name] = value
            self._variable_store.save(variables)
        except VariableStoreError as exc:
            self._save_error(exc)
            return
        self.search_input.clear()
        self.refresh()
        self.status_label.setText(f"Added ${{{name}}} for all clients")

    def remove_variable(self) -> None:
        """Remove only user-defined common variables after confirmation."""
        row = self.table.currentRow()
        if (self._variable_store is None or self._load_error or row < 0
                or not self.table.selectedItems() or self.table.isRowHidden(row)):
            return
        entry = self._entries[row]
        if entry.source != "Common variables.json":
            return
        if QMessageBox.question(
            self, "Remove common variable?",
            f"Remove ${{{entry.name}}} from the common variables for all clients?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            return
        try:
            variables = self._variable_store.load()
            variables.pop(entry.name, None)
            self._variable_store.save(variables)
        except VariableStoreError as exc:
            self._save_error(exc)
            return
        self.refresh()
        self.status_label.setText(f"Removed ${{{entry.name}}} from common variables")
