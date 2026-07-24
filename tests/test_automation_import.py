"""Tests for importing line-oriented automation commands."""

from __future__ import annotations

import os
import sys
import unittest

import pytest


pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from mmu_control.ui.automation_import_dialog import AutomationImportDialog  # noqa: E402


class AutomationImportDialogTest(unittest.TestCase):
    """The dialog validates source content before it creates a draft."""

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_pasted_commands_create_a_draft(self) -> None:
        dialog = AutomationImportDialog()
        dialog.name_input.setText("Imported boot")
        dialog.description_input.setText("From terminal notes")
        dialog.timeout_input.setValue(12)
        dialog.text_input.setPlainText("# start board\necho boot\nstatus")

        dialog.accept()

        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNotNone(dialog.scenario())
        assert dialog.scenario() is not None
        self.assertEqual(dialog.scenario().name, "Imported boot")
        self.assertEqual([step.command for step in dialog.scenario().steps], ["echo boot", "status"])
        self.assertEqual([step.timeout_seconds for step in dialog.scenario().steps], [12, 12])

    def test_empty_or_comment_only_text_stays_open_and_displays_an_error(self) -> None:
        dialog = AutomationImportDialog()
        dialog.name_input.setText("Empty import")
        dialog.text_input.setPlainText("\n# no commands\n")

        dialog.accept()

        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertIsNone(dialog.scenario())
        self.assertIn("가져올 명령이 없습니다", dialog.error_label.text())
