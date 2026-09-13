"""Push-to-talk hold detection. Control alone starts dictation; chords cancel it."""
from __future__ import annotations

HOLD_SECONDS = 0.28


class PushToTalk:
    """Observe Control hold without consuming shortcuts such as Ctrl+C."""

    def __init__(self) -> None:
        self.ctrl = False
        self.live = False
        self.chord = False
        self.armed_at: float | None = None

    def reset(self) -> None:
        self.ctrl = False
        self.live = False
        self.chord = False
        self.armed_at = None

    def down(self, now: float) -> str | None:
        if self.ctrl:
            return None
        self.ctrl = True
        self.chord = False
        self.live = False
        self.armed_at = now
        return "arm"

    def up(self, _now: float) -> str | None:
        if not self.ctrl:
            return None
        self.ctrl = False
        self.armed_at = None
        if self.live:
            self.live = False
            self.chord = False
            return "stop"
        self.chord = False
        return "disarm"

    def other_key(self) -> str | None:
        if not self.ctrl:
            return None
        self.chord = True
        self.armed_at = None
        if self.live:
            self.live = False
            return "cancel"
        return "disarm"

    def tick(self, now: float) -> str | None:
        if (
            self.ctrl
            and not self.chord
            and not self.live
            and self.armed_at is not None
            and now - self.armed_at >= HOLD_SECONDS
        ):
            self.live = True
            return "start"
        return None
