"""Interactive shell channel wrapper."""

from __future__ import annotations

from typing import Protocol


class ShellChannel(Protocol):
    """Protocol for Paramiko-like interactive shell channels."""

    closed: bool

    def recv_ready(self) -> bool:
        """Return whether output can be read without blocking."""

    def recv(self, nbytes: int) -> bytes:
        """Read bytes from the shell channel."""

    def send(self, data: str) -> int:
        """Send text to the shell channel."""

    def close(self) -> None:
        """Close the shell channel."""


class InteractiveShell:
    """Non-owning wrapper around an SSH interactive shell channel."""

    def __init__(self, channel: ShellChannel, encoding: str = "utf-8") -> None:
        self._channel = channel
        self._encoding = encoding

    @property
    def is_open(self) -> bool:
        """Return whether the shell channel is open."""
        return not self._channel.closed

    def send(self, text: str) -> int:
        """Send raw text to the shell channel."""
        self._ensure_open()
        return self._channel.send(text)

    def send_line(self, command: str) -> int:
        """Send a command followed by a newline."""
        return self.send(f"{command}\n")

    def read_available(self, max_bytes: int = 65535) -> str:
        """Read all immediately available output from the shell channel."""
        self._ensure_open()
        chunks: list[bytes] = []
        while self._channel.recv_ready():
            chunk = self._channel.recv(max_bytes)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks).decode(self._encoding, errors="replace")

    def respond_to_prompt(self, output: str, prompt: str, response: str) -> bool:
        """Send a response when output contains a prompt."""
        if prompt.lower() not in output.lower():
            return False
        self.send_line(response)
        return True

    def close(self) -> None:
        """Close the shell channel."""
        if not self._channel.closed:
            self._channel.close()

    def _ensure_open(self) -> None:
        if self._channel.closed:
            raise RuntimeError("Interactive shell is closed.")
