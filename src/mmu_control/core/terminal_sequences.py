"""Helpers for terminal control sequences."""

from __future__ import annotations


class TerminalStreamFilter:
    """Remove ANSI/VT sequences while preserving state across output chunks."""

    DEC_SPECIAL_GRAPHICS = str.maketrans(
        {
            "j": "┘",
            "k": "┐",
            "l": "┌",
            "m": "└",
            "n": "┼",
            "q": "─",
            "t": "├",
            "u": "┤",
            "v": "┴",
            "w": "┬",
            "x": "│",
        }
    )

    def __init__(self) -> None:
        self._state = "text"
        self._charset_target = ""
        self._g0_dec_graphics = False
        self._g1_dec_graphics = False
        self._shift_g1 = False

    def reset(self) -> None:
        """Discard a pending partial control sequence."""
        self._state = "text"
        self._charset_target = ""
        self._g0_dec_graphics = False
        self._g1_dec_graphics = False
        self._shift_g1 = False

    def feed(self, text: str) -> str:
        """Return visible text from one terminal output chunk."""
        visible: list[str] = []
        for character in text:
            code = ord(character)

            if self._state == "text":
                if character == "\x1b":
                    self._state = "escape"
                elif character == "\x9b":
                    self._state = "csi"
                elif character == "\x9d":
                    self._state = "osc"
                elif character == "\x90":
                    self._state = "string"
                elif character == "\x0e":
                    self._shift_g1 = True
                elif character == "\x0f":
                    self._shift_g1 = False
                elif character in "\b\n\r\t":
                    visible.append(character)
                elif code >= 32 and code != 127 and not 0x80 <= code <= 0x9F:
                    dec_graphics = (
                        self._g1_dec_graphics if self._shift_g1 else self._g0_dec_graphics
                    )
                    visible.append(
                        character.translate(self.DEC_SPECIAL_GRAPHICS)
                        if dec_graphics
                        else character
                    )
                continue

            if self._state == "escape":
                if character == "[":
                    self._state = "csi"
                elif character == "]":
                    self._state = "osc"
                elif character in "PX^_":
                    self._state = "string"
                elif character in "()":
                    self._charset_target = character
                    self._state = "charset"
                elif 0x20 <= code <= 0x2F:
                    self._state = "escape_intermediate"
                else:
                    self._state = "text"
                continue

            if self._state == "charset":
                dec_graphics = character == "0"
                if self._charset_target == "(":
                    self._g0_dec_graphics = dec_graphics
                else:
                    self._g1_dec_graphics = dec_graphics
                self._charset_target = ""
                self._state = "text"
                continue

            if self._state == "escape_intermediate":
                if not 0x20 <= code <= 0x2F:
                    self._state = "text"
                continue

            if self._state == "csi":
                if 0x40 <= code <= 0x7E:
                    self._state = "text"
                continue

            if self._state in {"osc", "string"}:
                if character == "\x07" and self._state == "osc":
                    self._state = "text"
                elif character in {"\x1b", "\x9c"}:
                    self._state = "text" if character == "\x9c" else f"{self._state}_escape"
                continue

            if self._state in {"osc_escape", "string_escape"}:
                base_state = self._state.removesuffix("_escape")
                self._state = "text" if character == "\\" else base_state

        return "".join(visible)


def strip_terminal_sequences(text: str) -> str:
    """Remove terminal escape/control sequences from a complete string."""
    return TerminalStreamFilter().feed(text) if text else text
