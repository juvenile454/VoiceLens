#!/usr/bin/env python3
"""Small Linux exec guard: kill the child if its expected parent dies."""

from __future__ import annotations

import ctypes
import os
import signal
import sys

if __package__:
    from .i18n import set_language, t
else:
    from i18n import set_language, t

_PR_SET_PDEATHSIG = 1


def _set_parent_death_signal() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def main(argv: list[str] | None = None) -> int:
    set_language(os.environ.get("VOICELENS_LANGUAGE"))
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        marker = args.index("--")
        if marker != 2 or args[0] != "--parent-pid":
            raise ValueError
        expected_parent = int(args[1])
        command = args[marker + 1 :]
        if expected_parent <= 1 or not command:
            raise ValueError
    except (ValueError, IndexError):
        print(t("guard_invalid_call"), file=sys.stderr)
        return 125

    # Check before and after prctl: the parent may die in between those calls.
    if os.getppid() != expected_parent:
        print(t("guard_parent_gone"), file=sys.stderr)
        return 125
    try:
        _set_parent_death_signal()
    except OSError as exc:
        print(t("guard_setup_failed", detail=exc), file=sys.stderr)
        return 125
    if os.getppid() != expected_parent:
        print(t("guard_parent_gone"), file=sys.stderr)
        return 125

    try:
        os.execvpe(command[0], command, os.environ.copy())
    except OSError as exc:
        print(t("guard_exec_failed", detail=exc), file=sys.stderr)
        return 126


if __name__ == "__main__":
    raise SystemExit(main())
