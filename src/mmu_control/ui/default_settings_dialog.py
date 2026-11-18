"""Choose which connection fields become defaults for new Clients."""

from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget


class DefaultSettingsDialog(QDialog):
    """Select complete groups; unchecked groups are omitted from saved defaults."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save connection defaults")
        layout = QVBoxLayout(self)
        description = QLabel("Select fields to reuse in new Client tabs. No connection or power command is run.", self)
        description.setWordWrap(True)
        layout.addWidget(description)
        self.resize(460, 220)
        self.groups: dict[str, QCheckBox] = {}
        for key, title in (("ssh", "SSH server"), ("power_supply", "Power supply"),
                           ("board", "Client (including IP, VLAN and MAC addresses)")):
            checkbox = QCheckBox(title, self)
            checkbox.setChecked(True)
            self.groups[key] = checkbox
            layout.addWidget(checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        for checkbox in self.groups.values():
            checkbox.toggled.connect(lambda *_: self.save_button.setEnabled(bool(self.selected_sections())))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sections(self) -> set[str]:
        """Return checked connection groups."""
        return {key for key, checkbox in self.groups.items() if checkbox.isChecked()}
