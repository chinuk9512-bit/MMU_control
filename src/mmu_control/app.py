"""Application entry point."""

from __future__ import annotations

import sys

from mmu_control.core.logging_config import configure_logging, shutdown_logging


def main() -> int:
    """Start the GUI application."""
    from PySide6.QtWidgets import QApplication

    from mmu_control.ui.main_window import MainWindow
    from mmu_control.ui.theme import apply_dark_theme

    configure_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("MMU Control")
    app.setOrganizationName("MMU Control")
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    try:
        return app.exec()
    finally:
        shutdown_logging()


if __name__ == "__main__":
    raise SystemExit(main())
