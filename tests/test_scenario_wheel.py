"""Wheel input scrolls scenario details without silently editing conditions."""

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea

from mmu_control.ui.automation_editor_dialog import AutomationEditorDialog


@pytest.fixture
def editor():
    app = QApplication.instance() or QApplication([])
    dialog = AutomationEditorDialog()
    dialog.show()
    app.processEvents()
    yield app, dialog
    dialog.close()


def wheel(widget, delta):
    local = QPointF(widget.rect().center())
    event = QWheelEvent(local, QPointF(widget.mapToGlobal(local.toPoint())),
                        QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


@pytest.mark.parametrize("field_name", ["start_type_input", "condition_type_input", "start_timeout_input", "timeout_input"])
@pytest.mark.parametrize("focused", [False, True])
@pytest.mark.parametrize("delta", [-120, 120])
def test_wheel_never_changes_condition_or_timeout(editor, field_name, focused, delta):
    app, dialog = editor
    field = getattr(dialog, field_name)
    is_combo = hasattr(field, "currentIndex")
    if is_combo:
        field.setCurrentIndex(2)
        before = field.currentIndex()
    else:
        field.setValue(120)
        before = field.value()
    (field if focused else dialog.step_name_input).setFocus()
    app.processEvents()
    wheel(field, delta)
    assert (field.currentIndex() if is_combo else field.value()) == before
    if not is_combo:
        wheel(field.lineEdit(), delta)
        assert field.value() == before


def test_keyboard_selection_and_timeout_typing_still_work(editor):
    app, dialog = editor
    combo = dialog.start_type_input
    combo.setCurrentIndex(1)
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Down)
    assert combo.currentIndex() == 2
    spin = dialog.timeout_input
    spin.setFocus()
    spin.selectAll()
    QTest.keyClicks(spin, "250")
    QTest.keyClick(spin, Qt.Key.Key_Return)
    assert spin.value() == 250
    QTest.keyClick(spin, Qt.Key.Key_Up)
    assert spin.value() == 251


def test_wheel_over_control_scrolls_the_details_pane(editor):
    app, dialog = editor
    scroll = dialog.findChild(QScrollArea)
    scroll.widget().setMinimumHeight(1600)
    app.processEvents()
    bar = scroll.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    before = bar.value()
    wheel(dialog.start_type_input, -120)
    app.processEvents()
    assert bar.value() > before
