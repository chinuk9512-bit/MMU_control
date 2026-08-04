"""Helpers for terminal control sequences and ANSI text styling."""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class TerminalStyle:
    """Display attributes selected by ANSI SGR control sequences."""

    foreground: tuple[int, int, int] | None = None
    background: tuple[int, int, int] | None = None
    bold: bool = False
    dim: bool = False


@dataclass(frozen=True, slots=True)
class TerminalText:
    """A visible terminal text fragment and the style used to display it."""

    text: str
    style: TerminalStyle


_ANSI_COLORS = (
    (0, 0, 0),
    (205, 49, 49),
    (13, 188, 121),
    (229, 229, 16),
    (36, 114, 200),
    (188, 63, 188),
    (17, 168, 205),
    (229, 229, 229),
    (102, 102, 102),
    (241, 76, 76),
    (35, 209, 139),
    (245, 245, 67),
    (59, 142, 234),
    (214, 112, 214),
    (41, 184, 219),
    (255, 255, 255),
)


def _indexed_color(index: int) -> tuple[int, int, int]:
    """Translate an ANSI 256-colour index into an RGB value."""
    index = max(0, min(255, index))
    if index < 16:
        return _ANSI_COLORS[index]
    if index < 232:
        value = index - 16
        levels = (0, 95, 135, 175, 215, 255)
        return levels[value // 36], levels[(value // 6) % 6], levels[value % 6]
    grey = 8 + (index - 232) * 10
    return grey, grey, grey


class TerminalStreamFilter:
    """Parse ANSI/VT output while preserving state across output chunks."""

    DEC_SPECIAL_GRAPHICS = str.maketrans(
        {"j": "┘", "k": "┐", "l": "┌", "m": "└", "n": "┼", "q": "─",
         "t": "├", "u": "┤", "v": "┴", "w": "┬", "x": "│"}
    )

    def __init__(self) -> None:
        self.reset()

    @property
    def style(self) -> TerminalStyle:
        """Return the style active at the end of the latest output chunk."""
        return self._style

    def reset(self) -> None:
        """Discard pending sequences and restore the default display style."""
        self._state = "text"
        self._charset_target = ""
        self._g0_dec_graphics = False
        self._g1_dec_graphics = False
        self._shift_g1 = False
        self._csi_buffer = ""
        self._style = TerminalStyle()

    def feed(self, text: str) -> str:
        """Return visible plain text from one terminal output chunk."""
        return "".join(fragment.text for fragment in self.feed_styled(text))

    def feed_styled(self, text: str) -> list[TerminalText]:
        """Return visible text fragments with their ANSI display attributes."""
        fragments: list[TerminalText] = []

        def append(character: str) -> None:
            if fragments and fragments[-1].style == self._style:
                previous = fragments[-1]
                fragments[-1] = TerminalText(previous.text + character, previous.style)
            else:
                fragments.append(TerminalText(character, self._style))

        for character in text:
            code = ord(character)
            if self._state == "text":
                if character == "\x1b":
                    self._state = "escape"
                elif character == "\x9b":
                    self._state, self._csi_buffer = "csi", ""
                elif character == "\x9d":
                    self._state = "osc"
                elif character == "\x90":
                    self._state = "string"
                elif character == "\x0e":
                    self._shift_g1 = True
                elif character == "\x0f":
                    self._shift_g1 = False
                elif character in "\b\n\r\t":
                    append(character)
                elif code >= 32 and code != 127 and not 0x80 <= code <= 0x9F:
                    graphics = (
                        self._g1_dec_graphics
                        if self._shift_g1
                        else self._g0_dec_graphics
                    )
                    append(
                        character.translate(self.DEC_SPECIAL_GRAPHICS)
                        if graphics
                        else character
                    )
                continue
            if self._state == "escape":
                if character == "[":
                    self._state, self._csi_buffer = "csi", ""
                elif character == "]":
                    self._state = "osc"
                elif character in "PX^_":
                    self._state = "string"
                elif character in "()":
                    self._charset_target, self._state = character, "charset"
                elif 0x20 <= code <= 0x2F:
                    self._state = "escape_intermediate"
                else:
                    self._state = "text"
                continue
            if self._state == "charset":
                graphics = character == "0"
                if self._charset_target == "(":
                    self._g0_dec_graphics = graphics
                else:
                    self._g1_dec_graphics = graphics
                self._charset_target, self._state = "", "text"
                continue
            if self._state == "escape_intermediate":
                if not 0x20 <= code <= 0x2F:
                    self._state = "text"
                continue
            if self._state == "csi":
                if 0x40 <= code <= 0x7E:
                    if character == "m":
                        self._apply_sgr(self._csi_buffer)
                    self._csi_buffer, self._state = "", "text"
                else:
                    self._csi_buffer += character
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
        return fragments

    def _apply_sgr(self, parameters: str) -> None:
        values = [int(value) if value.isdigit() else 0 for value in parameters.split(";")]
        if not parameters:
            values = [0]
        index = 0
        while index < len(values):
            value = values[index]
            if value == 0:
                self._style = TerminalStyle()
            elif value == 1:
                self._style = replace(self._style, bold=True)
            elif value == 2:
                self._style = replace(self._style, dim=True)
            elif value == 22:
                self._style = replace(self._style, bold=False, dim=False)
            elif 30 <= value <= 37 or 90 <= value <= 97:
                color_index = value - 30 if value <= 37 else value - 90 + 8
                self._style = replace(self._style, foreground=_ANSI_COLORS[color_index])
            elif value == 39:
                self._style = replace(self._style, foreground=None)
            elif 40 <= value <= 47 or 100 <= value <= 107:
                color_index = value - 40 if value <= 47 else value - 100 + 8
                self._style = replace(self._style, background=_ANSI_COLORS[color_index])
            elif value == 49:
                self._style = replace(self._style, background=None)
            elif value in {38, 48} and index + 2 < len(values):
                color: tuple[int, int, int] | None = None
                if values[index + 1] == 5:
                    color = _indexed_color(values[index + 2])
                    index += 2
                elif values[index + 1] == 2 and index + 4 < len(values):
                    color = tuple(
                        max(0, min(255, part))
                        for part in values[index + 2 : index + 5]
                    )
                    index += 4
                if color is not None:
                    field = "foreground" if value == 38 else "background"
                    self._style = replace(self._style, **{field: color})
            index += 1


def strip_terminal_sequences(text: str) -> str:
    """Remove terminal escape/control sequences from a complete string."""
    return TerminalStreamFilter().feed(text) if text else text
