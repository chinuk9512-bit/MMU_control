"""Tests for terminal control sequence helpers."""

from __future__ import annotations

import unittest

from mmu_control.core.terminal_sequences import strip_terminal_sequences


class TerminalSequencesTest(unittest.TestCase):
    """Tests for ANSI/VT sequence cleanup."""

    def test_strips_bracketed_paste_and_color_sequences(self) -> None:
        """Bracketed paste and colored ls output are rendered as plain text."""
        raw_output = "\x1b[?2004huser@server:~$ \x1b[01;34msrc\x1b[0m\r\n"

        cleaned = strip_terminal_sequences(raw_output)

        self.assertEqual(cleaned, "user@server:~$ src\r\n")

    def test_strips_osc_sequences(self) -> None:
        """Window-title OSC sequences are removed."""
        raw_output = "\x1b]0;user@server:~\x07prompt$ "

        cleaned = strip_terminal_sequences(raw_output)

        self.assertEqual(cleaned, "prompt$ ")


if __name__ == "__main__":
    unittest.main()
