"""Tests for terminal control sequence helpers."""

from __future__ import annotations

import unittest

from mmu_control.core.terminal_sequences import TerminalStreamFilter, strip_terminal_sequences


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

    def test_split_sequences_do_not_leak_fragments(self) -> None:
        """ANSI and character-set sequences may span SSH reads."""
        stream_filter = TerminalStreamFilter()

        first = stream_filter.feed("\x1b[01;")
        second = stream_filter.feed("34msrc\x1b(B\x0e\x0f")

        self.assertEqual(first, "")
        self.assertEqual(second, "src")

    def test_dec_graphics_are_rendered_as_box_characters(self) -> None:
        """Linux ncurses borders should not appear as stray q/x letters."""
        stream_filter = TerminalStreamFilter()

        cleaned = stream_filter.feed("\x1b(0lqqk\x1b(B text")

        self.assertEqual(cleaned, "┌──┐ text")

    def test_preserves_sgr_styles_across_chunks(self) -> None:
        """Split colour sequences produce styled fragments and reset cleanly."""
        stream_filter = TerminalStreamFilter()

        self.assertEqual(stream_filter.feed_styled("\x1b[38;2;10;"), [])
        fragments = stream_filter.feed_styled("20;30mRGB\x1b[0m plain")

        self.assertEqual([fragment.text for fragment in fragments], ["RGB", " plain"])
        self.assertEqual(fragments[0].style.foreground, (10, 20, 30))
        self.assertIsNone(fragments[1].style.foreground)

    def test_supports_standard_and_indexed_ansi_colors(self) -> None:
        """Linux shell 16-colour and 256-colour output retains its colours."""
        fragments = TerminalStreamFilter().feed_styled(
            "\x1b[1;34mblue\x1b[48;5;196m red-background"
        )

        self.assertEqual(fragments[0].style.foreground, (36, 114, 200))
        self.assertTrue(fragments[0].style.bold)
        self.assertEqual(fragments[1].style.background, (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
