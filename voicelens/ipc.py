"""Newline-delimited JSON over a Unix socket, with file descriptors via SCM_RIGHTS.

Shared by the GTK process and the resident worker; standard library only so the
STT interpreter can import it without extra packages.
"""
from __future__ import annotations

import array
import json
import socket
import time
from typing import Callable

_CHUNK = 65536
_MAX_FDS = 16
_POLL_SECONDS = 0.2


class ChannelClosed(Exception):
    """The peer closed its end of the channel."""


class ChannelTimeout(Exception):
    """No complete message arrived before the deadline."""


class Channel:
    """One message at a time in each direction; not thread-safe by design."""

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self._buffer = b""
        self._fds: list[int] = []

    def fileno(self) -> int:
        return self.sock.fileno()

    def send(self, payload: dict, fds: tuple[int, ...] | list[int] = ()) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        self.sock.settimeout(None)
        sent = 0
        if fds:
            ancillary = [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", list(fds)).tobytes())]
            sent = self.sock.sendmsg([data], ancillary)
        if sent < len(data):
            self.sock.sendall(data[sent:])

    def receive(
        self,
        timeout: float | None = None,
        *,
        poll: Callable[[], None] | None = None,
    ) -> tuple[dict, list[int]]:
        """Return the next message and the descriptors that arrived with it.

        ``poll`` runs every few hundred milliseconds while waiting and may raise
        to abort (cancellation, a dead peer). Descriptors are owned by the caller.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while b"\n" not in self._buffer:
            if poll is not None:
                poll()
            wait = _POLL_SECONDS
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ChannelTimeout()
                wait = min(wait, remaining)
            self.sock.settimeout(wait)
            try:
                data, ancillary, _flags, _address = self.sock.recvmsg(
                    _CHUNK, socket.CMSG_SPACE(_MAX_FDS * array.array("i").itemsize))
            except socket.timeout:
                continue
            except OSError as error:
                raise ChannelClosed() from error
            for level, kind, blob in ancillary:
                if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                    received = array.array("i")
                    received.frombytes(blob[: len(blob) - (len(blob) % received.itemsize)])
                    self._fds.extend(received)
            if not data:
                raise ChannelClosed()
            self._buffer += data
        line, _, self._buffer = self._buffer.partition(b"\n")
        fds, self._fds = self._fds, []
        try:
            payload = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if not isinstance(payload, dict):
            payload = {"ok": False, "error": "invalid message"}
        return payload, fds

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def pair() -> tuple[Channel, socket.socket]:
    """A parent channel plus the raw child socket to hand to a spawned process."""
    parent, child = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    return Channel(parent), child
