"""Shared pytest configuration for the Qt widget test suite."""

from __future__ import annotations

import os


# Select Qt's headless platform before pytest imports any test module that
# imports PySide6. This lets widget tests run in Linux CI containers without a
# display server.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
