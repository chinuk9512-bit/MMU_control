"""Variable discovery without accidental value disclosure."""

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mmu_control.ui.variable_list_dialog import VariableEntry, VariableListDialog


def test_values_hidden_search_excludes_values_and_click_copies_syntax():
    app = QApplication.instance() or QApplication([])
    entries = [
        VariableEntry("MMU_PW_2", "Common variables.json", "User-defined variable", "secret-example"),
        VariableEntry("DU_MAC_HEAD", "Client input", "First 4 hexadecimal digits", "0001"),
    ]
    dialog = VariableListDialog(lambda: (entries, ""), client_name="MMU-A")
    try:
        dialog.show()
        app.processEvents()
        assert "MMU-A" in dialog.windowTitle()
        assert not dialog.show_values.isChecked()
        assert dialog.table.item(0, 3).text() == "Hidden"
        assert dialog.table.item(0, 3).data(Qt.ItemDataRole.UserRole) is None
        assert dialog.table.item(0, 3).toolTip() == ""
        dialog.search_input.setText("secret-example")
        assert all(dialog.table.isRowHidden(row) for row in range(2))
        dialog.search_input.setText("pw_2")
        assert not dialog.table.isRowHidden(0) and dialog.table.isRowHidden(1)
        QTest.mouseClick(dialog.table.viewport(), Qt.MouseButton.LeftButton,
                         pos=dialog.table.visualItemRect(dialog.table.item(0, 0)).center())
        assert QApplication.clipboard().text() == "${MMU_PW_2}"
        assert "secret-example" not in dialog.status_label.text()
        dialog.search_input.setText("du_mac_head")
        assert not dialog.copy_button.isEnabled()
        dialog.show_values.setChecked(True)
        assert dialog.table.item(0, 3).text() == "secret-example"
        dialog.refresh()
        assert not dialog.show_values.isChecked()
        assert dialog.table.item(0, 3).text() == "Hidden"
    finally:
        dialog.close()


def test_refresh_reloads_provider_and_displays_errors_without_stale_values():
    app = QApplication.instance() or QApplication([])
    snapshot = ([VariableEntry("FIRST", "Common variables.json", "User-defined", "first-value")], "")
    dialog = VariableListDialog(lambda: snapshot)
    try:
        dialog.show_values.setChecked(True)
        snapshot = ([VariableEntry("SECOND", "Client input", "Input missing", None)], "Invalid config JSON")
        dialog.refresh_button.click()
        assert dialog.table.rowCount() == 1
        assert dialog.table.item(0, 0).text() == "${SECOND}"
        assert dialog.table.item(0, 3).text() == "Unavailable"
        assert dialog.error_label.text() == "Invalid config JSON"
        assert not dialog.show_values.isChecked()
    finally:
        dialog.close()
