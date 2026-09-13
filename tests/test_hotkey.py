"""PTT and injection contracts with accessibility/D-Bus doubles; no desktop input or audio."""
import unittest
from unittest import mock
from gi.repository import Gio, GLib

from voicelens.hotkey import HOLD_SECONDS, PushToTalk
from voicelens.inject import FocusTarget, caret_position, inject_text
from voicelens import inject


class PushToTalkTests(unittest.TestCase):
    def setUp(self):
        self.ptt = PushToTalk()

    def test_quick_ctrl_does_not_start(self):
        self.assertEqual(self.ptt.down(0.0), "arm")
        self.assertIsNone(self.ptt.tick(HOLD_SECONDS / 2))
        self.assertEqual(self.ptt.up(HOLD_SECONDS / 2), "disarm")
        self.assertIsNone(self.ptt.tick(1.0))

    def test_hold_starts_and_release_stops(self):
        self.assertEqual(self.ptt.down(1.0), "arm")
        self.assertEqual(self.ptt.tick(1.0 + HOLD_SECONDS), "start")
        self.assertIsNone(self.ptt.tick(1.0 + HOLD_SECONDS + 0.1))
        self.assertEqual(self.ptt.up(2.0), "stop")

    def test_chord_before_hold_never_starts(self):
        self.ptt.down(0.0)
        self.assertEqual(self.ptt.other_key(), "disarm")
        self.assertIsNone(self.ptt.tick(HOLD_SECONDS + 1))
        self.assertEqual(self.ptt.up(2.0), "disarm")

    def test_chord_during_recording_cancels(self):
        self.ptt.down(0.0)
        self.assertEqual(self.ptt.tick(HOLD_SECONDS), "start")
        self.assertEqual(self.ptt.other_key(), "cancel")
        self.assertEqual(self.ptt.up(1.0), "disarm")

    def test_repeated_ctrl_down_is_ignored(self):
        self.assertEqual(self.ptt.down(0.0), "arm")
        self.assertIsNone(self.ptt.down(0.05))

    def test_reset_clears_live_hold(self):
        self.ptt.down(0.0)
        self.ptt.tick(HOLD_SECONDS)
        self.ptt.reset()
        self.assertFalse(self.ptt.ctrl)
        self.assertFalse(self.ptt.live)
        self.assertIsNone(self.ptt.up(9.0))

    def test_inject_into_own_window_is_not_pasted_again(self):
        target = FocusTarget(app_name="org.voicelens.VoiceLens", own_app=True)
        self.assertEqual(inject_text("hello", target=target), "own")
        self.assertEqual(inject_text(""), "empty")

    def test_caret_geometry_uses_exact_offset_and_accepts_negative_monitor(self):
        acc = mock.Mock()
        acc.get_caret_offset.return_value = 24
        acc.get_character_extents.return_value = mock.Mock(x=-900, y=410, height=22)
        atspi = mock.Mock()
        self.assertEqual(caret_position(acc, atspi), (-900, 410, 22))
        acc.get_character_extents.assert_called_once_with(24, atspi.CoordType.SCREEN)
        acc.get_text.assert_not_called()

    def test_missing_end_of_line_geometry_is_not_guessed(self):
        acc = mock.Mock()
        acc.get_caret_offset.return_value = 20
        acc.get_character_extents.return_value = mock.Mock(x=0, y=0, height=0)
        self.assertIsNone(caret_position(acc, mock.Mock()))
        self.assertEqual(acc.get_character_extents.call_count, 1)
        acc.get_character_extents.side_effect = RuntimeError('defunct accessible')
        self.assertIsNone(caret_position(acc, mock.Mock()))

    def test_accessibility_children_and_expired_walk_are_bounded(self):
        acc = mock.Mock()
        acc.get_child_count.return_value = 100000
        list(inject._children(acc))
        self.assertEqual(acc.get_child_at_index.call_count, inject._WALK_LIMIT)
        acc.reset_mock()
        self.assertIsNone(inject._find_focused(mock.Mock(), acc, deadline=0))
        acc.get_state_set.assert_not_called()

    def test_large_tree_visits_focused_child_before_fetching_siblings(self):
        atspi = mock.Mock()
        root, focused = mock.Mock(), mock.Mock()
        root.get_child_count.return_value = 100000
        root.get_child_at_index.return_value = focused
        with mock.patch.object(inject, '_has_state', side_effect=lambda node, state:
                node is focused and state is atspi.StateType.FOCUSED), mock.patch.object(
                inject, '_safe_role', return_value='text'):
            self.assertIs(inject._find_focused(atspi, root), focused)
        root.get_child_at_index.assert_called_once_with(0)


class InjectionTests(unittest.TestCase):
    def test_terminal_focus_is_remembered_without_scanning_scrollback(self):
        desktop, app, win, terminal = (mock.Mock() for _ in range(4))
        atspi = mock.Mock()
        atspi.get_desktop.return_value = desktop
        children = {desktop: [app], app: [win], win: [terminal]}
        with mock.patch.object(inject, '_atspi', return_value=atspi), mock.patch.object(
                inject, '_children', side_effect=lambda node, *args: iter(children.get(node, []))), mock.patch.object(
                inject, '_safe_name', return_value='gnome-terminal-server'), mock.patch.object(
                inject, '_safe_role', side_effect=lambda node: 'terminal' if node is terminal else 'frame'), mock.patch.object(
                inject, 'caret_position', return_value=(300, 450, 22)), mock.patch.object(
                inject, '_has_state', side_effect=lambda node, state:
                    (node is win and state is atspi.StateType.ACTIVE) or
                    (node is terminal and state is atspi.StateType.FOCUSED)):
            target = inject.snapshot_focus()
        self.assertTrue(target.terminal)
        self.assertIs(target.accessible, terminal)
        self.assertEqual(target.caret, (300, 450, 22))
        terminal.get_child_count.assert_not_called()

    def test_terminal_role_reaches_helper_after_accessibility_fallback(self):
        target = FocusTarget(terminal=True, accessible=mock.Mock())
        with mock.patch.object(inject, '_insert_accessible', return_value=False), mock.patch.object(
                inject, '_copy_clipboard') as copy, mock.patch.object(inject, 'paste_via_helper', return_value=True) as paste:
            self.assertEqual(inject_text('Ein Test', target), 'paste')
        copy.assert_called_once_with('Ein Test')
        paste.assert_called_once_with('Ein Test', terminal=True)

    def test_successful_accessibility_insert_does_not_duplicate_paste(self):
        with mock.patch.object(inject, '_insert_accessible', return_value=True), mock.patch.object(
                inject, 'paste_via_helper') as paste, mock.patch.object(inject, '_copy_clipboard') as copy:
            self.assertEqual(inject_text('Test', FocusTarget()), 'accessible')
        paste.assert_not_called()
        copy.assert_not_called()

    def test_helper_transports_terminal_hint_without_changing_text(self):
        bus = mock.Mock()
        bus.call_sync.return_value = GLib.Variant('(b)', (True,))
        with mock.patch.object(Gio, 'bus_get_sync', return_value=bus):
            self.assertTrue(inject.paste_via_helper('hello world', terminal=True))
        args = bus.call_sync.call_args.args
        self.assertEqual(args[3], 'PasteWithOptions')
        self.assertEqual(args[4].unpack(), ('hello world', True))

    def test_older_helper_fallback_only_for_regular_apps(self):
        missing = GLib.Error.new_literal(Gio.dbus_error_quark(), 'old helper', Gio.DBusError.UNKNOWN_METHOD)
        for terminal in (False, True):
            with self.subTest(terminal=terminal):
                bus = mock.Mock()
                bus.call_sync.side_effect = [missing, GLib.Variant('(b)', (True,))]
                with mock.patch.object(Gio, 'bus_get_sync', return_value=bus):
                    self.assertEqual(inject.paste_via_helper('test', terminal=terminal), not terminal)
                self.assertEqual(bus.call_sync.call_count, 1 if terminal else 2)
                if not terminal:
                    self.assertEqual(bus.call_sync.call_args.args[3], 'Paste')

    def test_timed_out_paste_is_not_retried_and_duplicated(self):
        bus = mock.Mock()
        bus.call_sync.side_effect = GLib.Error.new_literal(
            Gio.dbus_error_quark(), 'uncertain delivery', Gio.DBusError.NO_REPLY)
        with mock.patch.object(Gio, 'bus_get_sync', return_value=bus):
            self.assertFalse(inject.paste_via_helper('test'))
        self.assertEqual(bus.call_sync.call_count, 1)


if __name__ == "__main__":
    unittest.main()
