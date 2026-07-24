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
        self.setWindowTitle("텍스트에서 시나리오 가져오기")
        self._scenario: AutomationScenario | None = None

        self.name_input = QLineEdit(self)
        self.description_input = QLineEdit(self)
        self.timeout_input = QSpinBox(self)
        self.timeout_input.setRange(1, 86_400)
        self.timeout_input.setValue(60)
        self.timeout_input.setSuffix(" seconds")

        self.file_source_radio = QRadioButton("파일 선택", self)
        self.text_source_radio = QRadioButton("직접 붙여넣기", self)
        self.text_source_radio.setChecked(True)
        self.file_path_input = QLineEdit(self)
        self.file_path_input.setPlaceholderText("명령 텍스트 파일 (/// 구분선 3줄로 여러 줄 명령 구분)")
        self.file_browse_button = QPushButton("찾아보기…", self)
        self.file_browse_button.clicked.connect(self._choose_file)
        self.text_input = QPlainTextEdit(self)
        self.text_input.setPlaceholderText(
            "명령을 붙여넣으세요. /가 2개 이상인 줄 3줄 연속은 구분선이며, "
            "구분선 사이의 여러 줄은 하나의 명령입니다. #으로 시작하는 줄은 주석입니다."
        )
        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color: #b00020;")

        self.file_source_radio.toggled.connect(self._update_source_controls)
        self.text_source_radio.toggled.connect(self._update_source_controls)
        self._build_layout()
        self._update_source_controls()

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        metadata = QFormLayout()
        metadata.addRow("시나리오 이름", self.name_input)
        metadata.addRow("설명", self.description_input)
        metadata.addRow("기본 timeout", self.timeout_input)
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
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("가져오기")
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
        path, _ = QFileDialog.getOpenFileName(self, "명령 텍스트 파일 선택", "", "Text files (*.txt);;All files (*)")
        if path:
            self.file_path_input.setText(path)
            self.file_source_radio.setChecked(True)

    def _source_text(self) -> str | None:
        if not self.file_source_radio.isChecked():
            return self.text_input.toPlainText()
        path_text = self.file_path_input.text().strip()
        if not path_text:
            self.error_label.setText("가져올 텍스트 파일을 선택하세요.")
            return None
        try:
            return Path(path_text).read_text(encoding="utf-8")
        except OSError as exc:
            self.error_label.setText(f"텍스트 파일을 읽을 수 없습니다: {exc}")
            return None
        except UnicodeError:
            self.error_label.setText("텍스트 파일은 UTF-8 인코딩이어야 합니다.")
            return None

    def scenario(self) -> AutomationScenario | None:
        """Return the parsed draft after successful import validation."""
        return self._scenario

    def accept(self) -> None:
        """Validate input and create a draft without persisting it."""
        self.error_label.clear()
        name = self.name_input.text().strip()
        if not name:
            self.error_label.setText("시나리오 이름은 필수입니다.")
            return
        text = self._source_text()
        if text is None:
            return
        steps = parse_automation_commands(text, self.timeout_input.value())
        if not steps:
            self.error_label.setText("가져올 명령이 없습니다. 빈 줄과 # 주석 줄을 제외한 명령을 입력하세요.")
            return
        self._scenario = AutomationScenario(
            name=name,
            description=self.description_input.text().strip(),
            steps=steps,
        )
        super().accept()
