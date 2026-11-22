"""Parent-folder selection cannot change accidentally while scrolling."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from mmu_control.models.command_set import CommandSet
from mmu_control.ui.command_editor_dialog import CommandEditorDialog


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    dialog = CommandEditorDialog(CommandSet("example", commands="echo ok", parent_path="alpha"),
                                 folder_paths=["alpha", "beta"])
    dialog.show()
    app.processEvents()
    yield app, dialog
    dialog.close()


@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("delta", [-120, 120])
def test_wheel_preserves_selected_parent_folder(editor, focused, delta):
    app, dialog = editor
    field = dialog.parent_folder_input
    (field if focused else dialog.name_input).setFocus()
    app.processEvents()
    point = QPointF(field.rect().center())
    event = QWheelEvent(point, QPointF(field.mapToGlobal(point.toPoint())),
                        QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(field, event)
    assert field.currentData() == "alpha"
    assert dialog.command_set().parent_path == "alpha"


def test_keyboard_and_popup_click_can_still_select_folder(editor):
    app, dialog = editor
    field = dialog.parent_folder_input
    field.setFocus()
    QTest.keyClick(field, Qt.Key.Key_Down)
    assert field.currentData() == "beta"
    field.showPopup()
    app.processEvents()
    index = field.model().index(1, 0)
    QTest.mouseClick(field.view().viewport(), Qt.MouseButton.LeftButton,
                     pos=field.view().visualRect(index).center())
    assert dialog.command_set().parent_path == "alpha"
