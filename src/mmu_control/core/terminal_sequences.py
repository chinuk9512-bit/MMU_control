"""Helpers for terminal control sequences."""

from __future__ import annotations

import re


ANSI_ESCAPE_PATTERN = re.compile(
    r"""
    \x1b
    (?:
        \[[0-?]*[ -/]*[@-~]   # CSI sequences, including colors and bracketed paste.
        | \][^\x07]*(?:\x07|\x1b\\)  # OSC title/hyperlink sequences.
        | [PX^_].*?\x1b\\      # DCS/PM/APC string sequences.
        | [@-_]                 # Single-character ESC sequences.
    )
    """,
    re.VERBOSE | re.DOTALL,
)


def strip_terminal_sequences(text: str) -> str:
    """Remove terminal escape/control sequences that a text widget cannot render."""
    if not text:
        return text
    return ANSI_ESCAPE_PATTERN.sub("", text)
