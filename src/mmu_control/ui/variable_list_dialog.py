"""Searchable, read-only command variable catalog for a client workspace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView,
)


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
    ) -> None:
        super().__init__(parent)
        self._provider = provider
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
        self.copy_button = buttons.addButton("Copy variable", QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.search_input.textChanged.connect(self._filter)
        self.show_values.toggled.connect(self._render)
        self.refresh_button.clicked.connect(self.refresh)
        self.table.cellClicked.connect(lambda *_: self.copy_variable())
        self.table.itemSelectionChanged.connect(self._update_copy_button)
        self.copy_button.clicked.connect(self.copy_variable)
        self.refresh()

    def refresh(self) -> None:
        """Reload from disk/current inputs and return to masked values."""
        self.show_values.blockSignals(True)
        self.show_values.setChecked(False)
        self.show_values.blockSignals(False)
        self._entries, error = self._provider()
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
        self.copy_button.setEnabled(
            bool(self.table.selectedItems()) and row >= 0 and not self.table.isRowHidden(row)
        )

    def copy_variable(self) -> None:
        """Copy syntax only, never the value, for the selected visible row."""
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row) or not self.table.selectedItems():
            return
        syntax = self.table.item(row, 0).text()
        QApplication.clipboard().setText(syntax)
        self.status_label.setText(f"Copied {syntax}")
