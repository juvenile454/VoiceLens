"""Insert transcribed text at the focused caret. Never downloads or grabs keys."""
from __future__ import annotations

from dataclasses import dataclass
import os
import time

from gi.repository import Gio, GLib

HELPER_NAME = "org.voicelens.VoiceLens.PttHelper"
HELPER_PATH = "/org/voicelens/VoiceLens/PttHelper"
HELPER_IFACE = "org.voicelens.VoiceLens.PttHelper"
OWN_APP_NAMES = frozenset(
    {
        "org.voicelens.VoiceLens",
        "VoiceLens",
        "voicelens",
    }
)
_WALK_LIMIT = 900
_FOCUS_BUDGET_SECONDS = 0.25


@dataclass
class FocusTarget:
    app_name: str = ""
    own_app: bool = False
    accessible: object | None = None
    caret: tuple[int, int, int] | None = None
    terminal: bool = False


def _atspi():
    try:
        import gi

        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi

        Atspi.init()
        Atspi.set_timeout(80, 200)
        return Atspi
    except Exception:
        return None


def _safe_name(acc) -> str:
    try:
        return str(acc.get_name() or "")
    except Exception:
        return ""


def _safe_role(acc) -> str:
    try:
        return str(acc.get_role_name() or "")
    except Exception:
        return ""


def _has_state(acc, state) -> bool:
    try:
        return bool(acc.get_state_set().contains(state))
    except Exception:
        return False


def _children(acc, deadline=None):
    try:
        count = acc.get_child_count()
    except Exception:
        return
    for index in range(min(count, _WALK_LIMIT)):
        if deadline is not None and time.monotonic() >= deadline:
            return
        try:
            child = acc.get_child_at_index(index)
        except Exception:
            continue
        if child is not None:
            yield child


def _is_own_app(name: str) -> bool:
    lowered = name.lower()
    return name in OWN_APP_NAMES or lowered in OWN_APP_NAMES or "voicelens" in lowered


def snapshot_focus() -> FocusTarget:
    """Remember the active application so insert does not follow a later focus change."""
    atspi = _atspi()
    if atspi is None:
        return FocusTarget()
    deadline = time.monotonic() + _FOCUS_BUDGET_SECONDS
    try:
        desktop = atspi.get_desktop(0)
    except Exception:
        return FocusTarget()
    active_app = None
    active_win = None
    for app in _children(desktop, deadline):
        app_name = _safe_name(app)
        if app_name == "gnome-shell":
            continue
        for window in _children(app, deadline):
            if _has_state(window, atspi.StateType.ACTIVE):
                active_app, active_win = app, window
                break
        if active_win is not None:
            break
    app_name = _safe_name(active_app) if active_app is not None else ""
    own = _is_own_app(app_name)
    focused = None
    if active_win is not None:
        focused = _find_focused(atspi, active_win, deadline)
    if focused is None and active_app is not None and not own:
        focused = _find_focused(atspi, active_app, deadline)
    return FocusTarget(app_name=app_name, own_app=own, accessible=focused,
                       caret=caret_position(focused, atspi),
                       terminal=_safe_role(focused) == 'terminal')


def caret_position(acc, atspi=None) -> tuple[int, int, int] | None:
    """Read only caret geometry, never the contents of the focused document.

    End-of-text geometry is not implemented by every toolkit. Do not guess
    from the previous character (wrong for wrapped lines, newlines and RTL).
    The Shell can use its native input-method rectangle or a window fallback.
    """
    if acc is None:
        return None
    atspi = atspi or _atspi()
    if atspi is None:
        return None
    try:
        offset = acc.get_caret_offset()
        if offset is None or offset < 0:
            return None
        rect = acc.get_character_extents(offset, atspi.CoordType.SCREEN)
        x, y, height = int(rect.x), int(rect.y), int(rect.height)
        if height <= 0 or height > 256 or abs(x) > 100000 or abs(y) > 100000:
            return None
        return x, y, height
    except Exception:
        return None


def _find_focused(atspi, root, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + _FOCUS_BUDGET_SECONDS
    # Lazy depth-first traversal avoids fetching every sibling in a huge tree
    # before visiting the first focused text field.
    stack = [iter((root,))]
    seen = 0
    focused = None
    while stack and seen < _WALK_LIMIT and time.monotonic() < deadline:
        try:
            node = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        seen += 1
        if _has_state(node, atspi.StateType.DEFUNCT):
            continue
        if _has_state(node, atspi.StateType.FOCUSED):
            focused = node
            role = _safe_role(node)
            if role in {"text", "entry", "password text", "document text", "editbar", "paragraph", "terminal"}:
                return node
        stack.append(_children(node, deadline))
    return focused


def _insert_accessible(acc, text: str) -> bool:
    if acc is None or not text:
        return False
    try:
        offset = acc.get_caret_offset()
    except Exception:
        offset = 0
    if offset is None or offset < 0:
        offset = 0
        try:
            offset = acc.get_character_count()
        except Exception:
            offset = 0
    try:
        return bool(acc.insert_text(int(offset), text, len(text)))
    except Exception:
        return False


def _copy_clipboard(text: str) -> None:
    from gi.repository import Gdk, Gtk

    clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
    clipboard.set_text(text, -1)
    clipboard.store()


def paste_via_helper(text: str, *, terminal: bool = False) -> bool:
    if not text:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        try:
            result = bus.call_sync(
                HELPER_NAME, HELPER_PATH, HELPER_IFACE, 'PasteWithOptions',
                GLib.Variant('(sb)', (text, terminal)), GLib.VariantType('(b)'),
                Gio.DBusCallFlags.NONE, 2500, None,
            )
            return bool(result.unpack()[0])
        except GLib.Error as error:
            # Retry only when the method is absent, never after an uncertain
            # timeout (the first call may already have scheduled the paste).
            if not error.matches(Gio.dbus_error_quark(), Gio.DBusError.UNKNOWN_METHOD):
                return False
            if terminal:
                # The old helper only sends Ctrl+V, which is not terminal paste.
                return False
        result = bus.call_sync(
            HELPER_NAME,
            HELPER_PATH,
            HELPER_IFACE,
            "Paste",
            GLib.Variant("(s)", (text,)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            2500,
            None,
        )
        return bool(result.unpack()[0])
    except Exception:
        return False


def show_helper_status(label: str, *, phase='listening', target=None) -> bool:
    if not label:
        return False
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        caret = getattr(target, 'caret', None)
        try:
            result = bus.call_sync(
                HELPER_NAME, HELPER_PATH, HELPER_IFACE, 'ShowSession',
                GLib.Variant('(ssiiib)', (phase, label, *(caret or (0, 0, 0)), caret is not None)),
                GLib.VariantType('(b)'), Gio.DBusCallFlags.NONE, 500, None,
            )
            return bool(result.unpack()[0])
        except GLib.Error:
            # The installed extension may still contain the previous version.
            pass
        result = bus.call_sync(
            HELPER_NAME,
            HELPER_PATH,
            HELPER_IFACE,
            "ShowStatus",
            GLib.Variant("(s)", (label,)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            800,
            None,
        )
        return bool(result.unpack()[0])
    except Exception:
        return False


def finish_helper_status(callback):
    """Acknowledge return: True=ready, False=canceled, None=older/no helper."""
    cancellable = Gio.Cancellable()

    def finished(connection, result):
        try:
            ok = bool(connection.call_finish(result).unpack()[0])
        except Exception:
            ok = None
        callback(ok)

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call(HELPER_NAME, HELPER_PATH, HELPER_IFACE, 'FinishSession', None,
                 GLib.VariantType('(b)'), Gio.DBusCallFlags.NONE, 1200,
                 cancellable, finished)
    except Exception:
        GLib.idle_add(lambda: callback(None) or GLib.SOURCE_REMOVE)
    return cancellable


def set_helper_level(level: float) -> None:
    """Tell the GNOME overlay the current microphone loudness. Fire-and-forget."""
    try:
        value = max(0.0, min(1.0, float(level)))
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        bus.call(
            HELPER_NAME,
            HELPER_PATH,
            HELPER_IFACE,
            "SetLevel",
            GLib.Variant("(d)", (value,)),
            None,
            Gio.DBusCallFlags.NONE,
            200,
            None,
            _ignore_helper_reply,
        )
    except Exception:
        return


def _ignore_helper_reply(connection, result) -> None:
    try:
        connection.call_finish(result)
    except Exception:
        return


def hide_helper_status() -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        result = bus.call_sync(
            HELPER_NAME,
            HELPER_PATH,
            HELPER_IFACE,
            "HideStatus",
            None,
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            800,
            None,
        )
        return bool(result.unpack()[0])
    except Exception:
        return False


def helper_available() -> bool:
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return bool(bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (HELPER_NAME,)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            400,
            None,
        ).unpack()[0])
    except Exception:
        return False


def inject_text(text: str, target: FocusTarget | None = None) -> str:
    """Insert *text* at the caret. Returns how it was delivered."""
    if not text:
        return "empty"
    target = target if target is not None else snapshot_focus()
    if target.own_app:
        return "own"
    if _insert_accessible(target.accessible, text):
        return "accessible"
    _copy_clipboard(text)
    if paste_via_helper(text, terminal=target.terminal):
        return "paste"
    return "clipboard"


def wayland_session() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY"))
