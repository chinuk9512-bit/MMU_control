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
        assert dialog.table.columnCount() == 2
        assert [dialog.table.horizontalHeaderItem(i).text() for i in range(2)] == ["Variable", "Value"]
        assert dialog.table.item(0, 1).text() == "Hidden"
        assert dialog.table.item(0, 1).data(Qt.ItemDataRole.UserRole) is None
        assert dialog.table.item(0, 1).toolTip() == ""
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
        assert dialog.table.item(0, 1).text() == "secret-example"
        dialog.refresh()
        assert not dialog.show_values.isChecked()
        assert dialog.table.item(0, 1).text() == "Hidden"
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
        assert dialog.table.item(0, 1).text() == "Unavailable"
        assert dialog.error_label.text() == "Invalid config JSON"
        assert not dialog.show_values.isChecked()
    finally:
        dialog.close()


def _editable_dialog(tmp_path):
    from mmu_control.storage.variable_store import VariableStore, VariableStoreError
    store = VariableStore(tmp_path / "variables.json")
    store.save({"EXISTING": "original-value"})
    def provider():
        error = ""
        try:
            common = store.load()
        except VariableStoreError as exc:
            common, error = {}, str(exc)
        entries = [VariableEntry(name, "Common variables.json", "User-defined", value)
                   for name, value in sorted(common.items())]
        entries.append(VariableEntry("MMU_VLAN", "Client input", "Client VLAN", "100"))
        return entries, error
    return VariableListDialog(provider, variable_store=store), store


def test_add_common_variable_persists_masked_value_and_preserves_latest_file(tmp_path):
    from unittest.mock import patch
    app = QApplication.instance() or QApplication([])
    dialog, store = _editable_dialog(tmp_path)
    try:
        store.save({"EXISTING": "original-value", "OUTSIDE": "added-elsewhere"})
        with patch("mmu_control.ui.variable_list_dialog.QInputDialog.getText",
                   side_effect=[("MMU_PW_2", True), ("  private-example  ", True)]) as prompts:
            dialog.add_button.click()
        assert prompts.call_args.kwargs["echo"].name == "Password"
        assert store.load() == {"EXISTING": "original-value", "OUTSIDE": "added-elsewhere",
                                "MMU_PW_2": "  private-example  "}
        assert not dialog.show_values.isChecked()
        row = next(i for i in range(dialog.table.rowCount()) if dialog.table.item(i, 0).text() == "${MMU_PW_2}")
        assert dialog.table.item(row, 1).text() == "Hidden"
        assert "private-example" not in dialog.status_label.text()
    finally:
        dialog.close()


def test_add_rejects_invalid_duplicate_and_client_variable_names(tmp_path):
    from unittest.mock import patch
    app = QApplication.instance() or QApplication([])
    dialog, store = _editable_dialog(tmp_path)
    original = store.path.read_bytes()
    try:
        for name in ("${BAD}", "1BAD", "EXISTING", "MMU_VLAN"):
            with patch("mmu_control.ui.variable_list_dialog.QInputDialog.getText",
                       return_value=(name, True)) as prompt, patch(
                       "mmu_control.ui.variable_list_dialog.QMessageBox.warning") as warning:
                dialog.add_variable()
            prompt.assert_called_once()
            warning.assert_called_once()
            assert store.path.read_bytes() == original
        with patch("mmu_control.ui.variable_list_dialog.QInputDialog.getText",
                   side_effect=[("NEW", True), ("cancelled-value", False)]):
            dialog.add_variable()
        assert store.path.read_bytes() == original
    finally:
        dialog.close()


def test_remove_common_variable_confirms_and_protects_client_inputs(tmp_path):
    from unittest.mock import patch
    from PySide6.QtWidgets import QMessageBox
    app = QApplication.instance() or QApplication([])
    dialog, store = _editable_dialog(tmp_path)
    try:
        dialog.table.setCurrentCell(1, 0)
        assert not dialog.remove_button.isEnabled()
        with patch("mmu_control.ui.variable_list_dialog.QMessageBox.question") as question:
            dialog.remove_variable()
        question.assert_not_called()
        dialog.table.setCurrentCell(0, 0)
        assert dialog.remove_button.isEnabled()
        with patch("mmu_control.ui.variable_list_dialog.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
            dialog.remove_button.click()
        assert "EXISTING" in store.load()
        store.save({"EXISTING": "original-value", "OUTSIDE": "retained"})
        with patch("mmu_control.ui.variable_list_dialog.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
            dialog.remove_button.click()
        assert store.load() == {"OUTSIDE": "retained"}
        assert not dialog.show_values.isChecked()
    finally:
        dialog.close()


def test_unreadable_file_and_failed_save_preserve_existing_data(tmp_path):
    from unittest.mock import patch
    from mmu_control.storage.variable_store import VariableStoreError
    app = QApplication.instance() or QApplication([])
    dialog, store = _editable_dialog(tmp_path)
    original = store.path.read_bytes()
    try:
        with patch("mmu_control.ui.variable_list_dialog.QInputDialog.getText",
                   side_effect=[("NEW", True), ("secret-example", True)]), patch.object(
                   store, "save", side_effect=VariableStoreError("Unable to write variable file")):
            dialog.add_variable()
        assert store.path.read_bytes() == original
        assert "Unable to write" in dialog.error_label.text()
        assert "secret-example" not in dialog.error_label.text()
        assert not dialog.add_button.isEnabled()
        store.path.write_text('{"invalid":')
        dialog.refresh()
        assert not dialog.add_button.isEnabled() and not dialog.remove_button.isEnabled()
        dialog.add_variable()
        assert store.path.read_text() == '{"invalid":'
    finally:
        dialog.close()
