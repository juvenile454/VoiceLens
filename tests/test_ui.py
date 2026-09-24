"""Native GTK actions using an explicit backend double; no desktop/audio I/O."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GLib, Gtk
from voicelens.i18n import set_language
from voicelens.settings import Settings, WHISPER_MODELS
from voicelens.ui import VoiceLensWindow
from test_controller import FakeBackend


def iter_labels(widget):
    if isinstance(widget, Gtk.Label):
        text = widget.get_text()
        if text:
            yield text
    if isinstance(widget, Gtk.Button):
        label = widget.get_label()
        if label:
            yield label
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from iter_labels(child)


class WindowTests(unittest.TestCase):
    def setUp(self):
        if not Gtk.init_check(None)[0]:
            self.skipTest('Use GDK_BACKEND=x11 xvfb-run for isolated GTK tests')
        self._xdg = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get('XDG_CONFIG_HOME')
        os.environ['XDG_CONFIG_HOME'] = self._xdg.name
        set_language('en')
        self.model_available = mock.patch('voicelens.ui.is_model_available', return_value=True)
        self.model_available.start()
        self.api = FakeBackend()
        self.finish_callbacks = []
        self.defer_finish = False
        def finish(callback):
            if self.defer_finish:
                self.finish_callbacks.append(callback)
            else:
                GLib.idle_add(lambda: callback(True) or GLib.SOURCE_REMOVE)
            return mock.Mock()
        self.finish_mock = mock.patch('voicelens.inject.finish_helper_status', side_effect=finish)
        self.finish_mock.start()
        self.window = VoiceLensWindow(backend_api=self.api, prefs=Settings())
        self.window._ptt_needs_extension = lambda: False
        self.window._ptt_osd = lambda *_: None
        self.window._ptt_osd_hide = lambda *_: None
        self.window._ptt_osd_level = lambda *_: None
        self.window._snapshot_focus = lambda: None
        self.window._finish_inject = lambda _text: 'Inserted at the caret.'
        self.window.show_all()
        self.pump(lambda: not self.window.devices_loading)

    def tearDown(self):
        self.window._close()
        self.pump(lambda: not self.window.controller.busy)
        self.window.destroy()
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        set_language('en')
        if self._old_xdg is None:
            os.environ.pop('XDG_CONFIG_HOME', None)
        else:
            os.environ['XDG_CONFIG_HOME'] = self._old_xdg
        self._xdg.cleanup()
        self.finish_mock.stop()
        self.model_available.stop()

    def pump(self, condition, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if condition():
                return
            time.sleep(0.01)
        self.fail('GTK condition timed out')

    def text(self):
        b = self.window.text.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), True)

    def record_and_stop(self):
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'recording')
        self.assertEqual(self.window.record.get_label(), '■  Stop')
        self.window.record.clicked()

    def test_startup_never_records_or_loads_model(self):
        self.assertEqual(self.api.created, [])
        self.assertEqual(self.api.calls, 0)
        self.assertTrue(self.window.record.get_sensitive())
        self.assertEqual(self.window.source.get_active_id(), 'automatic')
        self.assertFalse(self.window.copy.get_sensitive())
        self.assertEqual(self.window.prefs.language, 'en')
        self.assertEqual(self.window.prefs.model, 'small')
        self.assertEqual(self.window.record.get_label(), '●  Record')
        self.assertIn('English', self.window.settings_button.get_label())
        self.assertIn('Small', self.window.settings_button.get_label())
        self.assertIn('2 GB', self.window.settings_button.get_label())

    def test_window_starts_with_missing_or_invalid_appearance_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            assets = root / 'assets'
            assets.mkdir()
            for invalid in (False, True):
                if invalid:
                    (assets / 'ui.css').write_text('invalid stylesheet')
                    (assets / 'voicelens.svg').write_text('invalid icon')
                window = None
                try:
                    with self.subTest(invalid=invalid), mock.patch('voicelens.ui.ROOT', root), self.assertLogs('voicelens.ui', level='WARNING'):
                        window = VoiceLensWindow(backend_api=self.api, prefs=Settings())
                    window.show_all()
                    self.pump(lambda: not window.devices_loading)
                    self.assertTrue(window.get_visible())
                    self.assertTrue(window.record.get_sensitive())
                    self.assertEqual(window.get_icon_name(), 'audio-input-microphone')
                    self.assertEqual(self.api.created, [])
                finally:
                    if window is not None:
                        window._close()
                        self.pump(lambda: not (window._discovery_thread and window._discovery_thread.is_alive()))
                        window.destroy()

    def test_dependency_hint_survives_device_error_and_refresh_recovers(self):
        hint = 'Missing dependency: pulseaudio-utils. See README.md.'
        with mock.patch.object(self.api, 'check_capture_dependencies', side_effect=RuntimeError(hint)), mock.patch.object(
            self.api, 'list_microphones', side_effect=RuntimeError('The microphone manager is not available.')
        ):
            self.window._refresh()
            self.pump(lambda: not self.window.devices_loading)
            self.assertEqual(self.window.setup_error, hint)
            self.assertEqual(self.window.status.get_text(), hint)
            self.assertFalse(self.window.record.get_sensitive())
            self.window._refresh(automatic=True)
            self.pump(lambda: not self.window.devices_loading)
            self.assertEqual(self.window.status.get_text(), hint)
        self.window._refresh()
        self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.setup_error, '')
        self.assertTrue(self.window.record.get_sensitive())
        self.assertEqual(self.api.created, [])

    def test_dependency_hint_survives_empty_device_list(self):
        with mock.patch.object(self.api, 'check_runtime', side_effect=RuntimeError('Runtime missing')), mock.patch.object(
            self.api, 'list_microphones', return_value=[]
        ):
            self.window._refresh()
            self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.status.get_text(), 'Runtime missing')
        self.assertFalse(self.window.record.get_sensitive())

    def test_missing_runtime_blocks_recording_and_refresh_recovers(self):
        self.window.text.get_buffer().set_text('Keep me')
        with mock.patch.object(self.api, 'check_runtime', side_effect=RuntimeError('Runtime missing')):
            self.window._refresh()
            self.pump(lambda: not self.window.devices_loading)
        self.assertFalse(self.window.record.get_sensitive())
        self.assertFalse(self.window._start_recording())
        self.assertEqual(self.api.created, [])
        self.assertIn('Runtime missing', self.window.status.get_text())
        self.window._refresh()
        self.pump(lambda: not self.window.devices_loading)
        self.assertTrue(self.window.record.get_sensitive())
        self.assertEqual(self.text(), 'Keep me')

    def test_hotplug_preserves_selection_and_transcript(self):
        self.window.source.set_active_id('test-source')
        self.window.text.get_buffer().set_text('Keep me')
        inputs = self.api.list_microphones() + [dict(name='usb', description='USB mic', default=False, muted=False)]
        with mock.patch.object(self.api, 'list_microphones', return_value=inputs), mock.patch.object(self.api, 'check_runtime') as runtime:
            self.window._last_discovery = 0
            self.window._tick()
            self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.source.get_active_id(), 'test-source')
        self.assertEqual(len(self.window.microphones), 2)
        self.assertEqual(self.text(), 'Keep me')
        runtime.assert_not_called()
        with mock.patch.object(self.api, 'list_microphones', return_value=inputs[1:]):
            self.window._refresh(automatic=True)
            self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.source.get_active_id(), 'automatic')
        self.assertEqual(self.api.created, [])

    def test_audio_server_failure_clears_stale_devices(self):
        with mock.patch.object(self.api, 'list_microphones', side_effect=RuntimeError('No audio server')):
            self.window._refresh(automatic=True)
            self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.microphones, [])
        self.assertFalse(self.window.record.get_sensitive())
        self.assertIn('No audio server', self.window.status.get_text())
        self.window._refresh(automatic=True)
        self.pump(lambda: not self.window.devices_loading)
        self.assertTrue(self.window.record.get_sensitive())

    def test_model_missing_disables_record_but_keeps_settings_accessible(self):
        with mock.patch('voicelens.ui.is_model_available', return_value=False):
            self.window.set_model('tiny')
            self.assertFalse(self.window.record.get_sensitive())
            self.assertTrue(self.window.settings_button.get_sensitive())
            self.assertFalse(self.window._start_recording())
        self.assertEqual(self.api.created, [])

    def test_unchanged_hotplug_poll_keeps_outcome_status(self):
        self.window.status.set_text('Done. Keep this message.')
        self.window._refresh(automatic=True)
        self.pump(lambda: not self.window.devices_loading)
        self.assertEqual(self.window.status.get_text(), 'Done. Keep this message.')

    def test_record_stop_edit_copy(self):
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), self.api.result_text)
        self.assertEqual(self.window.memory_status.get_text(), 'Model unloaded')
        self.assertTrue(self.api.created[0].closed)
        self.window.text.get_buffer().set_text('Corrected test text – äöü.')
        self.window.copy.clicked()
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.assertEqual(clipboard.wait_for_text(), 'Corrected test text – äöü.')

    def test_silence_preserves_previous_text(self):
        self.window.text.get_buffer().set_text('Previous text')
        self.api.result_text = ''
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), 'Previous text')
        self.assertIn('No speech', self.window.status.get_text())

    def test_failure_preserves_previous_text(self):
        self.window.text.get_buffer().set_text('Previous text')
        self.api.fail = True
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), 'Previous text')
        self.assertIn('Error', self.window.status.get_text())

    def test_cancel_button_releases_and_allows_new_recording(self):
        self.api.allow_result.clear()
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'transcribing')
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'idle')
        self.assertIn('Canceled', self.window.status.get_text())
        self.assertTrue(self.api.created[0].closed)
        self.assertTrue(self.window.record.get_sensitive())

    def test_close_while_recording(self):
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'recording')
        self.window._close()
        self.pump(lambda: not self.window.controller.busy)
        self.assertEqual(self.api.calls, 0)
        self.assertTrue(self.api.created[0].closed)

    def test_settings_dialog_lists_models_with_estimated_ram(self):
        self.window.settings_button.clicked()
        self.pump(lambda: self.window.settings_dialog is not None)
        dialog = self.window.settings_dialog
        labels = ' '.join(iter_labels(dialog))
        self.assertIn('Language', labels)
        self.assertIn('English', labels)
        self.assertIn('German', labels)
        for spec in WHISPER_MODELS:
            self.assertIn(spec.ram, labels)
        self.assertIn('Tiny', labels)
        self.assertIn('Base', labels)
        self.assertIn('Small', labels)
        self.assertIn('Medium', labels)
        self.assertIn('Large v2', labels)
        self.assertIn('Large v3', labels)
        self.assertIn('Est. RAM', labels)
        self.assertIn('Push-to-talk', labels)
        self.assertIn('Control', labels)
        self.assertTrue(dialog.ptt_check.get_active())
        dialog.response(Gtk.ResponseType.CLOSE)
        self.pump(lambda: self.window.settings_dialog is None)

    def test_language_switch_updates_ui(self):
        self.window.set_language('de')
        self.assertEqual(self.window.record.get_label(), '●  Aufnehmen')
        self.assertIn('Deutsch', self.window.settings_button.get_label())
        self.assertIn('Kopieren', self.window.copy.get_label())
        self.assertIn('Deutsch', self.window.header.get_subtitle())
        self.window.set_language('en')
        self.assertEqual(self.window.record.get_label(), '●  Record')
        self.assertIn('English', self.window.settings_button.get_label())
        self.assertIn('English', self.window.header.get_subtitle())

    def test_selected_model_and_language_reach_backend(self):
        self.window.set_model('base')
        self.window.set_language('de')
        with mock.patch('voicelens.ui.is_model_available', return_value=True):
            self.window.record.clicked()
            self.pump(lambda: self.window.state == 'recording')
        self.assertIn('Stoppen', self.window.record.get_label())
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.api.last_model, 'base')
        self.assertEqual(self.api.last_language, 'de')

    def test_push_to_talk_hold_records_and_injects(self):
        delivered = []
        self.window._snapshot_focus = lambda: None
        self.window._ptt_osd = lambda *_: None
        self.window._finish_inject = lambda text: delivered.append(text) or 'Inserted at the caret.'
        self.window.on_ptt_ctrl(True)
        self.assertEqual(self.window.state, 'idle')
        self.pump(lambda: self.window.state == 'recording', timeout=2)
        self.assertTrue(self.window.ptt_inject)
        self.assertIn('Listening', self.window.status.get_text())
        self.window.on_ptt_ctrl(False)
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), self.api.result_text)
        self.assertEqual(delivered, [self.api.result_text])
        self.assertIn('Inserted', self.window.status.get_text())

    def test_push_to_talk_chord_does_not_open_microphone(self):
        self.window.on_ptt_ctrl(True)
        self.window.on_ptt_chord()
        self.window.on_ptt_ctrl(False)
        end = time.monotonic() + 0.5
        self.pump(lambda: time.monotonic() >= end)
        self.assertEqual(self.window.state, 'idle')
        self.assertEqual(self.api.created, [])

    def test_push_to_talk_can_be_disabled(self):
        self.window.set_push_to_talk(False)
        self.assertFalse(self.window.begin_push_to_talk())
        self.assertEqual(self.window.state, 'idle')
        self.assertEqual(self.api.created, [])

    def _key(self, keyval, press=True):
        event = Gdk.Event.new(Gdk.EventType.KEY_PRESS if press else Gdk.EventType.KEY_RELEASE)
        event.keyval = keyval
        return event

    def test_control_key_event_in_window_records_and_injects(self):
        delivered = []
        self.window._finish_inject = lambda text: delivered.append(text) or 'Inserted at the caret.'
        self.assertFalse(self.window._on_key_event(self.window, self._key(Gdk.KEY_Control_L, True)))
        self.assertEqual(self.window.state, 'idle')
        self.pump(lambda: self.window.state == 'recording', timeout=2)
        self.assertTrue(self.window.ptt_inject)
        self.assertFalse(self.window._on_key_event(self.window, self._key(Gdk.KEY_Control_L, False)))
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(delivered, [self.api.result_text])

    def test_control_chord_key_event_does_not_open_microphone(self):
        self.assertFalse(self.window._on_key_event(self.window, self._key(Gdk.KEY_Control_L, True)))
        self.assertFalse(self.window._on_key_event(self.window, self._key(Gdk.KEY_c, True)))
        self.assertFalse(self.window._on_key_event(self.window, self._key(Gdk.KEY_Control_L, False)))
        end = time.monotonic() + 0.5
        self.pump(lambda: time.monotonic() >= end)
        self.assertEqual(self.window.state, 'idle')
        self.assertEqual(self.api.created, [])

    def test_push_to_talk_osd_stays_through_transcription(self):
        events = []
        self.window._ptt_osd = lambda key: events.append(key)
        self.window._ptt_osd_hide = lambda: events.append('hide')
        self.window._finish_inject = lambda text: 'Inserted at the caret.'
        self.window.on_ptt_ctrl(True)
        self.pump(lambda: self.window.state == 'recording', timeout=2)
        self.assertEqual(events, ['notify_listening'])
        self.window.on_ptt_ctrl(False)
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(events[0], 'notify_listening')
        self.assertIn('hide', events)
        self.assertIn('notify_transcribing', events)
        listen = events.index('notify_listening')
        transcribe = events.index('notify_transcribing')
        hide = events.index('hide')
        self.assertLess(listen, transcribe)
        self.assertLess(transcribe, hide)
        self.assertNotIn('hide', events[:transcribe])

    def test_push_to_talk_forwards_microphone_level(self):
        levels = []
        original = self.api.Recorder

        def make(source, max_seconds=900):
            rec = original(source, max_seconds)
            rec.peek_level = lambda: 0.42
            return rec

        self.api.Recorder = make
        self.window._ptt_osd_level = lambda value: levels.append(value)
        self.window.on_ptt_ctrl(True)
        self.pump(lambda: self.window.state == 'recording' and levels, timeout=2)
        self.assertTrue(levels)
        self.assertTrue(all(value == 0.42 for value in levels))
        self.window.on_ptt_ctrl(False)
        self.pump(lambda: self.window.state == 'idle')

    def test_push_to_talk_chord_hides_osd(self):
        events = []
        self.window._ptt_osd = lambda key: events.append(key)
        self.window._ptt_osd_hide = lambda: events.append('hide')
        self.window.on_ptt_ctrl(True)
        self.pump(lambda: self.window.state == 'recording', timeout=2)
        self.assertEqual(events, ['notify_listening'])
        self.window.on_ptt_chord()
        self.window.on_ptt_ctrl(False)
        self.pump(lambda: self.window.state == 'idle')
        self.assertIn('hide', events)
        self.assertNotIn('notify_transcribing', events)

    def test_record_button_does_not_inject(self):
        self.window._finish_inject = lambda text: (_ for _ in ()).throw(AssertionError('button path must not inject'))
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), self.api.result_text)
        self.assertIn('Done', self.window.status.get_text())

    def test_return_animation_precedes_text_and_blocks_next_operation(self):
        self.defer_finish = True
        self.window.text.get_buffer().set_text('Previous text')
        deliveries = []
        self.window._finish_inject = lambda text: deliveries.append(text) or 'Inserted'
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.pump(lambda: self.window.state == 'settling')
        self.assertFalse(self.window.controller.busy)
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(self.text(), 'Previous text')
        self.assertFalse(self.window.begin_push_to_talk())
        self.assertFalse(self.window.text.get_editable())
        self.assertEqual(deliveries, [])
        self.finish_callbacks[0](True)
        self.assertEqual(deliveries, [self.api.result_text])
        self.assertEqual(self.window.state, 'idle')

    def test_cancel_return_ignores_late_ack_and_preserves_text(self):
        self.defer_finish = True
        self.window.text.get_buffer().set_text('Previous text')
        self.window._finish_inject = mock.Mock()
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.pump(lambda: self.window.state == 'settling')
        self.window.record.clicked()
        self.finish_callbacks[0](True)
        self.assertEqual(self.text(), 'Previous text')
        self.window._finish_inject.assert_not_called()
        self.assertEqual(self.window.state, 'idle')

    def test_close_return_ignores_late_ack_and_stops_animation(self):
        self.defer_finish = True
        self.window._finish_inject = mock.Mock()
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.pump(lambda: self.window.state == 'settling')
        self.window._close()
        self.finish_callbacks[0](True)
        self.window._finish_inject.assert_not_called()
        self.window.destroy()
        self.assertIsNone(self.window.visualizer._source)

    def test_old_extension_failure_still_delivers_and_hides_after_insert(self):
        self.defer_finish = True
        events = []
        self.window._ptt_osd_hide = lambda: events.append('hide')
        self.window._finish_inject = lambda _: events.append('insert') or 'Inserted'
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.pump(lambda: self.window.state == 'settling')
        self.finish_callbacks[0](None)
        self.assertEqual(events, ['insert', 'hide'])
        self.assertEqual(self.window.state, 'idle')

    def test_shell_cancellation_during_return_never_inserts(self):
        self.defer_finish = True
        self.window.text.get_buffer().set_text('Previous text')
        self.window._finish_inject = mock.Mock()
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.pump(lambda: self.window.state == 'settling')
        self.finish_callbacks[0](False)
        self.assertEqual(self.text(), 'Previous text')
        self.window._finish_inject.assert_not_called()
        self.assertEqual(self.window.state, 'idle')

    def test_cancel_between_stop_and_transcription_preserves_text(self):
        self.api.allow_result.clear()
        self.window.text.get_buffer().set_text('Previous text')
        self.window.begin_push_to_talk()
        self.pump(lambda: self.window.state == 'recording')
        self.window.end_push_to_talk()
        self.assertEqual(self.window.state, 'stopping')
        self.window.cancel_push_to_talk()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), 'Previous text')
        self.assertTrue(self.api.created[0].closed)

    def test_cancel_after_result_queued_preserves_text(self):
        self.window.text.get_buffer().set_text('Previous text')
        self.window.state = 'transcribing'
        self.window.controller.events.put(('result', {'result': {'text': 'New text'}}))
        self.window._record()
        self.window._tick()
        self.assertEqual(self.text(), 'Previous text')
        self.assertEqual(self.window.state, 'idle')

    def test_append_mode_keeps_previous_text_below_new_result(self):
        self.window.text.get_buffer().set_text('Previous text')
        self.window.set_append_transcript(True)
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), 'Previous text\n' + self.api.result_text)
        self.assertIn('appended', self.window.status.get_text())
        self.window.set_append_transcript(False)
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), self.api.result_text)

    def test_auto_copy_places_result_in_clipboard(self):
        self.window.set_auto_copy(True)
        self.record_and_stop()
        self.pump(lambda: self.window.state == 'idle')
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.assertEqual(clipboard.wait_for_text(), self.api.result_text)
        self.assertIn('copied', self.window.status.get_text())

    def test_clear_button_empties_transcript_only_when_idle(self):
        self.assertFalse(self.window.clear.get_sensitive())
        self.window.text.get_buffer().set_text('Some words here')
        self.assertTrue(self.window.clear.get_sensitive())
        self.assertIn('3 words', self.window.text_count.get_text())
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'recording')
        self.assertFalse(self.window.clear.get_sensitive())
        self.window._clear()
        self.assertEqual(self.text(), 'Some words here')
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'idle')
        self.window.clear.clicked()
        self.assertEqual(self.text(), '')
        self.assertFalse(self.window.copy.get_sensitive())
        self.assertIn('cleared', self.window.status.get_text())

    def test_copy_shows_transient_feedback_and_restores_label(self):
        self.window.text.get_buffer().set_text('Copy me')
        self.window.copy.clicked()
        self.assertEqual(self.window.copy.get_label(), 'Copied ✓')
        self.pump(lambda: self.window.copy.get_label() == 'Copy')
        self.window.copy.clicked()
        self.window.set_language('de')
        self.assertEqual(self.window.copy.get_label(), 'Kopieren')

    def test_escape_cancels_recording_and_keeps_previous_text(self):
        self.window.text.get_buffer().set_text('Previous text')
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'recording')
        self.assertTrue(self.window._on_shortcut(self.window, self._key(Gdk.KEY_Escape, True)))
        self.pump(lambda: self.window.state == 'idle')
        self.assertEqual(self.text(), 'Previous text')
        self.assertIn('Canceled', self.window.status.get_text())
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(self.api.calls, 0)
        self.assertFalse(self.window._on_shortcut(self.window, self._key(Gdk.KEY_Escape, True)))

    def test_control_shift_c_copies_transcript(self):
        self.window.text.get_buffer().set_text('Shortcut text')
        event = self._key(Gdk.KEY_C, True)
        event.state = Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK
        self.assertTrue(self.window._on_shortcut(self.window, event))
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        self.assertEqual(clipboard.wait_for_text(), 'Shortcut text')
        plain = self._key(Gdk.KEY_c, True)
        plain.state = Gdk.ModifierType.CONTROL_MASK
        self.assertFalse(self.window._on_shortcut(self.window, plain))

    def test_settings_switches_persist_behaviour_flags(self):
        self.window.settings_button.clicked()
        self.pump(lambda: self.window.settings_dialog is not None)
        dialog = self.window.settings_dialog
        labels = ' '.join(iter_labels(dialog))
        self.assertIn('Append to the transcript', labels)
        self.assertIn('Copy the text automatically', labels)
        self.assertIn('Recommended', labels)
        self.assertFalse(dialog.append_switch.get_active())
        dialog.append_switch.set_active(True)
        dialog.auto_copy_switch.set_active(True)
        dialog.ptt_check.set_active(False)
        self.assertTrue(self.window.prefs.append_transcript)
        self.assertTrue(self.window.prefs.auto_copy)
        self.assertFalse(self.window.prefs.push_to_talk)
        saved = json.loads((Path(self._xdg.name) / 'voicelens/settings.json').read_text())
        self.assertEqual(saved['append_transcript'], True)
        self.assertEqual(saved['auto_copy'], True)
        self.assertEqual(saved['push_to_talk'], False)
        dialog.response(Gtk.ResponseType.CLOSE)
        self.pump(lambda: self.window.settings_dialog is None)

    def test_menu_opens_shortcuts_and_setup_help(self):
        self.assertEqual(self.window.menu_shortcuts.get_property('text'), 'Keyboard shortcuts')
        window = self.window._open_shortcuts()
        self.assertIsNotNone(self.window.shortcuts_window)
        self.assertIs(self.window._open_shortcuts(), window)
        window.destroy()
        self.assertIsNone(self.window.shortcuts_window)
        help_dialog = self.window._open_setup_help()
        self.assertTrue(help_dialog.get_visible())
        help_dialog.destroy()
        self.assertEqual(self.api.created, [])

    def test_visualizer_is_static_at_rest_and_when_unmapped(self):
        visual = self.window.visualizer
        self.assertIsNone(visual._source)
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'recording')
        self.assertIsNotNone(visual._source)
        self.window.hide()
        self.assertIsNone(visual._source)
        self.window.show_all()
        self.assertIsNotNone(visual._source)
        self.window.record.clicked()
        self.pump(lambda: self.window.state == 'idle')
        self.assertIsNone(visual._source)
