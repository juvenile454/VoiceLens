"""Small native GTK3 window, no model imports or microphone access at startup."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
import queue
import signal
import threading
import time

import gi

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .controller import Controller
from .hotkey import HOLD_SECONDS, PushToTalk
from .visualizer import VoiceVisualizer
from .i18n import set_language, t
from .settings import (
    WHISPER_MODELS,
    get_model_spec,
    is_model_available,
    load_settings,
    save_settings,
    data_dir,
)

APP_ID = 'org.voicelens.VoiceLens'
ROOT = Path(__file__).resolve().parent.parent
_RECORD_KEYS = {
    'idle': 'record',
    'starting': 'starting',
    'recording': 'stop',
    'stopping': 'stopping',
    'transcribing': 'cancel',
    'closing': 'closing',
    'settling': 'cancel',
}
_CONTROL_KEYS = frozenset({Gdk.KEY_Control_L, Gdk.KEY_Control_R})
_MODIFIER_KEYS = _CONTROL_KEYS | {
    Gdk.KEY_Shift_L,
    Gdk.KEY_Shift_R,
    Gdk.KEY_Alt_L,
    Gdk.KEY_Alt_R,
    Gdk.KEY_Meta_L,
    Gdk.KEY_Meta_R,
    Gdk.KEY_Super_L,
    Gdk.KEY_Super_R,
    Gdk.KEY_Hyper_L,
    Gdk.KEY_Hyper_R,
    Gdk.KEY_Caps_Lock,
    Gdk.KEY_Num_Lock,
    Gdk.KEY_Scroll_Lock,
    Gdk.KEY_ISO_Level3_Shift,
    Gdk.KEY_ISO_Level5_Shift,
}


class SettingsDialog(Gtk.Dialog):
    """Chooser for UI/transcription language and the local Whisper model."""

    def __init__(self, parent: 'VoiceLensWindow'):
        super().__init__(transient_for=parent, modal=True, destroy_with_parent=True, use_header_bar=True)
        self.app_window = parent
        self._filling = False
        self.get_style_context().add_class('voicelens-settings')
        self.set_default_size(480, 620)
        self.add_button(t('close'), Gtk.ResponseType.CLOSE)
        self.set_default_response(Gtk.ResponseType.CLOSE)

        body = self.get_content_area()
        body.set_spacing(12)
        body.set_border_width(18)

        self.language_heading = Gtk.Label(xalign=0)
        self.language_heading.get_style_context().add_class('heading')
        body.pack_start(self.language_heading, False, False, 0)

        languages = Gtk.Box(spacing=16)
        self.radio_en = Gtk.RadioButton.new_with_label(None, t('language_en'))
        self.radio_de = Gtk.RadioButton.new_with_label_from_widget(self.radio_en, t('language_de'))
        self.radio_en.connect('toggled', self._language_toggled, 'en')
        self.radio_de.connect('toggled', self._language_toggled, 'de')
        languages.pack_start(self.radio_en, False, False, 0)
        languages.pack_start(self.radio_de, False, False, 0)
        body.pack_start(languages, False, False, 0)

        self.ptt_heading = Gtk.Label(xalign=0)
        self.ptt_heading.get_style_context().add_class('heading')
        body.pack_start(self.ptt_heading, False, False, 0)
        self.ptt_check = Gtk.CheckButton()
        self.ptt_check.connect('toggled', self._ptt_toggled)
        body.pack_start(self.ptt_check, False, False, 0)
        self.ptt_hint = Gtk.Label(xalign=0)
        self.ptt_hint.set_line_wrap(True)
        self.ptt_hint.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.ptt_hint.set_max_width_chars(48)
        self.ptt_hint.get_style_context().add_class('dim-label')
        body.pack_start(self.ptt_hint, False, False, 0)

        self.model_heading = Gtk.Label(xalign=0)
        self.model_heading.get_style_context().add_class('heading')
        body.pack_start(self.model_heading, False, False, 0)

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.IN)
        scroll.set_min_content_height(220)
        self.model_list = Gtk.ListBox()
        self.model_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.model_list.connect('row-selected', self._model_selected)
        scroll.add(self.model_list)
        body.pack_start(scroll, True, True, 0)

        self.note = Gtk.Label(xalign=0)
        self.note.set_line_wrap(True)
        self.note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.note.set_max_width_chars(48)
        self.note.get_style_context().add_class('dim-label')
        body.pack_start(self.note, False, False, 0)

        self.setup_help = Gtk.Button()
        self.setup_help.connect('clicked', self._setup_help)
        body.pack_start(self.setup_help, False, False, 0)

        self.refresh_strings()

    def refresh_strings(self):
        self.set_title(t('settings_title'))
        self.language_heading.set_text(t('language_heading'))
        self.ptt_heading.set_text(t('ptt_heading'))
        self.ptt_check.set_label(t('ptt_label'))
        self.ptt_hint.set_text(t('ptt_hint'))
        self.model_heading.set_text(t('model_heading'))
        self.note.set_text(t('offline_note'))
        self.setup_help.set_label(t('setup_help_button'))
        self.radio_en.set_label(t('language_en'))
        self.radio_de.set_label(t('language_de'))
        close = self.get_widget_for_response(Gtk.ResponseType.CLOSE)
        if close is not None:
            close.set_label(t('close'))
        self._filling = True
        if self.app_window.prefs.language == 'de':
            self.radio_de.set_active(True)
        else:
            self.radio_en.set_active(True)
        self.ptt_check.set_active(bool(self.app_window.prefs.push_to_talk))
        for child in list(self.model_list.get_children()):
            self.model_list.remove(child)
        selected = None
        for spec in WHISPER_MODELS:
            row = self._model_row(spec)
            self.model_list.add(row)
            if spec.id == self.app_window.prefs.model:
                selected = row
        self.model_list.show_all()
        if selected is not None:
            self.model_list.select_row(selected)
        self._filling = False

    def _model_row(self, spec):
        row = Gtk.ListBoxRow()
        row.model_id = spec.id
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        outer.set_margin_top(8)
        outer.set_margin_bottom(8)
        outer.set_margin_start(10)
        outer.set_margin_end(10)
        title = Gtk.Box(spacing=8)
        name = Gtk.Label(label=t(spec.name_key), xalign=0)
        name.set_hexpand(True)
        ram = Gtk.Label(label=t('ram_caption', ram=spec.ram), xalign=1)
        ram.get_style_context().add_class('dim-label')
        title.pack_start(name, True, True, 0)
        title.pack_end(ram, False, False, 0)
        available = is_model_available(spec.id)
        badge = t('installed') if available else t('not_installed')
        hint = Gtk.Label(label=f"{t(spec.hint_key)} · {badge}", xalign=0)
        hint.get_style_context().add_class('dim-label')
        hint.set_line_wrap(True)
        outer.pack_start(title, False, False, 0)
        outer.pack_start(hint, False, False, 0)
        row.add(outer)
        return row

    def _language_toggled(self, button, language):
        if self._filling or not button.get_active():
            return
        self.app_window.set_language(language)

    def _ptt_toggled(self, button):
        if self._filling:
            return
        self.app_window.set_push_to_talk(button.get_active())

    def _model_selected(self, _list, row):
        if self._filling or row is None:
            return
        self.app_window.set_model(row.model_id)

    def _setup_help(self, *_):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, destroy_with_parent=True,
                                   message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.CLOSE,
                                   text=t('setup_title'))
        dialog.get_style_context().add_class('voicelens-settings')
        dialog.get_widget_for_response(Gtk.ResponseType.CLOSE).set_label(t('close'))
        dialog.format_secondary_text(t('setup_instructions', path=str(data_dir() / 'models'),
                                       model=self.app_window.prefs.model))
        for label in dialog.get_message_area().get_children():
            if isinstance(label, Gtk.Label):
                label.set_selectable(True)
                label.set_max_width_chars(65)
        dialog.connect('response', lambda widget, *_: widget.destroy())
        dialog.show_all()
        return dialog


class VoiceLensWindow(Gtk.ApplicationWindow):
    def __init__(self, application=None, backend_api=None, prefs=None):
        super().__init__(application=application, title='VoiceLens')
        self.api = backend_api or importlib.import_module('.backend', __package__)
        self.controller = Controller(self.api)
        self.device_events = queue.Queue()
        self.state = 'idle'
        self.closing = False
        self.devices_loading = False
        self.pending_outcome = None
        self.microphones = []
        self.devices_loaded = False
        self.setup_error = ''
        self._last_discovery = time.monotonic()
        self._discovery_cancel = threading.Event()
        self._discovery_thread = None
        self.settings_dialog = None
        self.ptt_inject = False
        self._ptt = PushToTalk()
        self._ptt_timer = None
        self._ptt_target = None
        self._delivery = None
        self._delivery_timer = None
        self._delivery_call = None
        self.prefs = prefs if prefs is not None else load_settings()
        set_language(self.prefs.language)
        self.set_default_size(660, 660)
        self.set_size_request(560, 620)
        self.get_settings().set_property('gtk-application-prefer-dark-theme', True)
        self.get_style_context().add_class('voicelens-window')
        self._css = Gtk.CssProvider()
        try:
            self._css.load_from_path(str(ROOT / 'assets/ui.css'))
        except GLib.Error as error:
            logging.getLogger(__name__).warning(t('asset_unreadable', path=ROOT / 'assets/ui.css', detail=error.message))
        else:
            Gtk.StyleContext.add_provider_for_screen(self.get_screen(), self._css,
                                                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        try:
            self.set_icon_from_file(str(ROOT / 'assets/voicelens.svg'))
        except GLib.Error as error:
            logging.getLogger(__name__).warning(t('asset_unreadable', path=ROOT / 'assets/voicelens.svg', detail=error.message))
            self.set_icon_name('audio-input-microphone')
        self.connect('delete-event', self._close)
        self.connect('destroy', self._destroyed)
        self.connect('key-press-event', self._on_key_event)
        self.connect('key-release-event', self._on_key_event)
        self._build()
        self.timer_id = GLib.timeout_add(33, self._tick)
        self._refresh()

    def _build(self):
        self.header = Gtk.HeaderBar(title='VoiceLens')
        self.header.set_show_close_button(True)
        self.set_titlebar(self.header)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.set_border_width(24)
        self.add(body)

        hero = Gtk.Box(spacing=18)
        self.visualizer = VoiceVisualizer()
        hero.pack_start(self.visualizer, False, False, 0)
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        intro.set_valign(Gtk.Align.CENTER)
        self.eyebrow = self._label('eyebrow')
        self.hero_title = self._label('hero-title')
        self.hero_title.set_line_wrap(True)
        self.hero_title.set_max_width_chars(24)
        self.hero_hint = self._label('hero-hint')
        self.hero_hint.set_line_wrap(True)
        self.phase_title = self._label('phase-title')
        for label in (self.eyebrow, self.hero_title, self.hero_hint, self.phase_title):
            intro.pack_start(label, False, False, 0)
        hero.pack_start(intro, True, True, 0)
        body.pack_start(hero, False, False, 0)

        capture = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        capture.get_style_context().add_class('card')
        capture_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        capture_inner.set_border_width(16)
        capture.pack_start(capture_inner, True, True, 0)
        self.input_caption = self._label('caption')
        capture_inner.pack_start(self.input_caption, False, False, 0)
        devices = Gtk.Box(spacing=8)
        self.source = Gtk.ComboBoxText()
        self.source.set_hexpand(True)
        renderer = self.source.get_cells()[0]
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        renderer.set_property('width-chars', 28)
        self.refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        self.refresh.connect('clicked', self._refresh)
        devices.pack_start(self.source, True, True, 0)
        devices.pack_start(self.refresh, False, False, 0)
        capture_inner.pack_start(devices, False, False, 0)

        controls = Gtk.Box(spacing=18)
        self.record = Gtk.Button()
        self.record.set_size_request(180, 46)
        self.record.connect('clicked', self._record)
        self.elapsed = self._label('timer', '00:00')
        self.spinner = Gtk.Spinner()
        controls.pack_start(self.record, True, True, 0)
        controls.pack_start(self.elapsed, False, False, 0)
        controls.pack_end(self.spinner, False, False, 0)
        capture_inner.pack_start(controls, False, False, 0)

        self.status = self._label('status-detail')
        self.status.set_line_wrap(True)
        self.status.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(55)
        capture_inner.pack_start(self.status, False, False, 0)
        self.settings_button = Gtk.Button()
        self.settings_button.set_image(Gtk.Image.new_from_icon_name('preferences-system-symbolic', Gtk.IconSize.MENU))
        self.settings_button.set_always_show_image(True)
        self.settings_button.get_style_context().add_class('settings-summary')
        self.settings_button.connect('clicked', self._open_settings)
        capture_inner.pack_start(self.settings_button, False, False, 0)
        body.pack_start(capture, False, False, 0)

        transcript = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        transcript.get_style_context().add_class('card')
        transcript_header = Gtk.Box(spacing=10)
        transcript_header.set_border_width(12)
        self.transcript_caption = self._label('caption')
        self.text_count = self._label('dim-label')
        self.copy = Gtk.Button()
        self.copy.set_sensitive(False)
        self.copy.connect('clicked', self._copy)
        transcript_header.pack_start(self.transcript_caption, False, False, 0)
        transcript_header.pack_start(self.text_count, True, True, 0)
        transcript_header.pack_end(self.copy, False, False, 0)
        transcript.pack_start(transcript_header, False, False, 0)
        overlay = Gtk.Overlay()
        overlay.set_margin_start(8)
        overlay.set_margin_end(8)
        overlay.set_margin_bottom(8)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.text = Gtk.TextView()
        self.text.get_style_context().add_class('transcript')
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.set_left_margin(18)
        self.text.set_right_margin(18)
        self.text.set_top_margin(12)
        self.text.set_bottom_margin(18)
        self.text.set_pixels_below_lines(6)
        self.text.get_buffer().connect('changed', self._text_changed)
        self.text.connect('key-press-event', self._on_key_event)
        self.text.connect('key-release-event', self._on_key_event)
        scroll.add(self.text)
        overlay.add(scroll)
        self.placeholder = self._label('placeholder')
        self.placeholder.set_halign(Gtk.Align.CENTER)
        self.placeholder.set_valign(Gtk.Align.CENTER)
        self.placeholder.set_line_wrap(True)
        self.placeholder.set_justify(Gtk.Justification.CENTER)
        self.placeholder.set_no_show_all(True)
        self.placeholder.show()
        overlay.add_overlay(self.placeholder)
        overlay.set_overlay_pass_through(self.placeholder, True)
        transcript.pack_start(overlay, True, True, 0)
        body.pack_start(transcript, True, True, 0)

        footer = Gtk.Box(spacing=8)
        self.privacy = self._label('privacy')
        self.memory_status = self._label('dim-label')
        footer.pack_start(self.privacy, True, True, 0)
        footer.pack_end(self.memory_status, False, False, 0)
        body.pack_start(footer, False, False, 0)
        self._apply_strings()
        self._controls()

    @staticmethod
    def _label(style, text=''):
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class(style)
        return label

    def _settings_summary(self):
        spec = get_model_spec(self.prefs.model)
        return t(
            'settings_button',
            language=t('language_' + self.prefs.language),
            model=t(spec.name_key),
            ram=t('ram_caption', ram=spec.ram),
        )

    def _update_settings_button(self):
        self.settings_button.set_label(self._settings_summary())
        self.settings_button.set_tooltip_text(t('settings_tooltip'))
        self.settings_button.get_accessible().set_name(t('settings_title'))
        spec = get_model_spec(self.prefs.model)
        self.header.set_subtitle(t(
            'header_subtitle',
            language=t('language_' + self.prefs.language),
            model=t(spec.name_key),
        ))

    def _apply_strings(self):
        for widget, key in ((self.eyebrow, 'hero_eyebrow'), (self.hero_title, 'hero_title'),
                            (self.hero_hint, 'hero_hint'), (self.input_caption, 'input_caption'),
                            (self.transcript_caption, 'transcript_caption'),
                            (self.privacy, 'privacy_caption'), (self.placeholder, 'empty_transcript')):
            widget.set_text(t(key))
        self._text_changed(self.text.get_buffer())
        self.source.set_tooltip_text(t('mic_tooltip'))
        self.source.get_accessible().set_name(t('mic_accessible'))
        self.refresh.set_tooltip_text(t('refresh_tooltip'))
        self.refresh.get_accessible().set_name(t('refresh_accessible'))
        self.text.get_accessible().set_name(t('transcript_accessible'))
        self.text.set_tooltip_text(t('transcript_tooltip'))
        self.copy.set_label(t('copy'))
        self._update_settings_button()
        if self.state == 'idle' and not self.devices_loading:
            if self.microphones:
                self.status.set_text(self._idle_status())
            elif self.devices_loaded:
                self.status.set_text(t('status_no_mic'))
            else:
                self.status.set_text(t('status_discovering'))
            self.memory_status.set_text(t('memory_idle'))
        elif self.devices_loading:
            self.status.set_text(t('status_discovering'))
        self._controls()
        if self.settings_dialog is not None:
            self.settings_dialog.refresh_strings()

    def set_language(self, language):
        language = set_language(language)
        self.prefs.language = language
        save_settings(self.prefs)
        self._apply_strings()
        if self.microphones:
            self._apply_devices(self.microphones)

    def set_model(self, model_id):
        spec = get_model_spec(model_id)
        self.prefs.model = spec.id
        save_settings(self.prefs)
        self._update_settings_button()
        if self.state == 'idle' and not self.devices_loading:
            if not is_model_available(spec.id):
                self.status.set_text(t('model_not_local'))
            elif self.microphones:
                self.status.set_text(self._idle_status())
        self._controls()

    def set_push_to_talk(self, enabled):
        self.prefs.push_to_talk = bool(enabled)
        save_settings(self.prefs)
        if not self.prefs.push_to_talk:
            self._clear_ptt_timer()
            self._ptt.reset()
        if self.state == 'idle' and not self.devices_loading and self.microphones:
            self.status.set_text(self._idle_status())

    def _idle_status(self):
        if self.setup_error:
            return self.setup_error
        if not is_model_available(self.prefs.model):
            return t('model_not_local')
        if self.prefs.push_to_talk and self._ptt_needs_extension():
            return t('ptt_unavailable')
        return t('status_ready')

    def _ptt_needs_extension(self):
        from .inject import helper_available, wayland_session
        return wayland_session() and not helper_available()

    def _open_settings(self, *_):
        if self.state != 'idle' or self.closing or self.devices_loading:
            return
        if self.settings_dialog is not None:
            self.settings_dialog.present()
            return
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.connect('response', self._settings_closed)
        dialog.connect('destroy', self._settings_destroyed)
        dialog.show_all()

    def _settings_closed(self, dialog, *_):
        dialog.destroy()

    def _settings_destroyed(self, *_):
        self.settings_dialog = None

    def _dismiss_settings(self):
        if self.settings_dialog is not None:
            self.settings_dialog.destroy()
            self.settings_dialog = None

    def _controls(self):
        idle = self.state == 'idle' and not self.closing
        self.source.set_sensitive(idle and not self.devices_loading)
        self.refresh.set_sensitive(idle and not self.devices_loading)
        self.settings_button.set_sensitive(idle and not self.devices_loading)
        self.record.set_sensitive(not self.closing and (
            self.state in ('recording', 'transcribing', 'settling') or (
                idle and not self.devices_loading and bool(self.microphones)
                and not self.setup_error and is_model_available(self.prefs.model)
            )
        ))
        self.record.set_label(t(_RECORD_KEYS.get(self.state, 'please_wait')))
        self.visualizer.set_phase(self.state)
        self.phase_title.set_text(t('phase_' + self.state))
        style = self.record.get_style_context()
        style.remove_class('suggested-action')
        style.remove_class('destructive-action')
        style.add_class('destructive-action' if self.state == 'recording' else 'suggested-action')
        if self.state in ('starting', 'stopping', 'transcribing', 'closing'):
            self.spinner.start()
        else:
            self.spinner.stop()
        # Avoid silently overwriting edits made while a new transcript is processing.
        self.text.set_editable(idle)

    def _refresh(self, *_, automatic=False):
        if self.state != 'idle' or self.controller.busy or self.devices_loading or self.closing:
            return
        self.devices_loading = True
        self._last_discovery = time.monotonic()
        if not automatic:
            self.status.set_text(t('status_discovering'))
        self._controls()
        def discover():
            setup_error = self.setup_error
            if not automatic:
                try:
                    self.api.check_capture_dependencies()
                    self.api.check_runtime(cancel=self._discovery_cancel)
                    setup_error = ''
                except Exception as error:
                    setup_error = str(error)
            try:
                if self._discovery_cancel.is_set():
                    return
                self.device_events.put(('devices', (self.api.list_microphones(), setup_error, automatic)))
            except Exception as error:
                self.device_events.put(('error', (setup_error, str(error))))
        self._discovery_thread = threading.Thread(target=discover, name='voicelens-devices')
        self._discovery_thread.start()

    def _apply_devices(self, microphones):
        previous = self.source.get_active_id()
        self.source.remove_all()
        self.microphones = microphones
        if microphones:
            default = next((m for m in microphones if m['default']), microphones[0])
            suffix = t('muted_suffix') if default['muted'] else ''
            self.source.append('automatic', t('automatic', description=default['description']) + suffix)
            for microphone in microphones:
                suffix = t('muted_suffix') if microphone['muted'] else ''
                self.source.append(microphone['name'], microphone['description'] + suffix)
            names = {m['name'] for m in microphones}
            self.source.set_active_id(previous if previous in names else 'automatic')
            self.status.set_text(self._idle_status())
        else:
            self.status.set_text(self.setup_error or t('status_no_mic'))

    def _record(self, *_):
        if self.state == 'recording':
            self.controller.stop()
            self.state = 'stopping'
            self.status.set_text(t('status_ending'))
        elif self.state == 'settling':
            self._cancel_delivery()
            self.status.set_text(t('status_cancelled'))
        elif self.state == 'transcribing':
            self._ptt_osd_hide()
            self.controller.cancel()
            self.ptt_inject = False
            self.state = 'stopping'
            self.status.set_text(t('status_canceling'))
        elif self.state == 'idle' and not self.controller.busy:
            self._start_recording(inject=False)
        self._controls()

    def _start_recording(self, *, inject=False):
        if self.state != 'idle' or self.controller.busy or self.closing:
            return False
        if self.devices_loading or not self.microphones:
            return False
        if self.setup_error:
            self.status.set_text(self.setup_error)
            return False
        if not is_model_available(self.prefs.model):
            self.status.set_text(t('model_not_local'))
            self._controls()
            return False
        self._dismiss_settings()
        self.ptt_inject = inject
        self._ptt_target = self._snapshot_focus() if inject else None
        self.state = 'starting'
        self.pending_outcome = None
        self.elapsed.set_text('00:00')
        self.status.set_text(t('status_listening') if inject else t('status_opening'))
        source = self.source.get_active_id()
        self.controller.start(
            None if source == 'automatic' else source,
            model=self.prefs.model,
            language=self.prefs.language,
        )
        self._controls()
        if inject:
            self._ptt_osd('notify_listening')
        return True

    def _snapshot_focus(self):
        try:
            from .inject import snapshot_focus
            return snapshot_focus()
        except Exception:
            return None

    def _tick(self):
        if self.closing:
            if not self.controller.busy and not (self._discovery_thread and self._discovery_thread.is_alive()):
                self.timer_id = None
                self.destroy()
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        try:
            kind, data = self.device_events.get_nowait()
            self.devices_loading = False
            self.devices_loaded = True
            if kind == 'devices':
                microphones, self.setup_error, automatic = data
                if not automatic or microphones != self.microphones:
                    self._apply_devices(microphones)
            else:
                self.setup_error, device_error = data
                self.microphones = []
                self.source.remove_all()
                self.status.set_text(self.setup_error or device_error)
            self._controls()
        except queue.Empty:
            pass
        for kind, data in self.controller.drain():
            if kind == 'level':
                self.visualizer.level = max(0.0, min(1.0, float(data)))
                if self.ptt_inject:
                    self._ptt_osd_level(data)
                continue
            if kind == 'recording':
                if self.state != 'stopping':
                    self.state = 'recording'
                    self.status.set_text(
                        t('status_listening') if self.ptt_inject else t('status_recording')
                    )
            elif kind == 'elapsed':
                seconds = int(data)
                self.elapsed.set_text(f'{seconds // 60:02d}:{seconds % 60:02d}')
            elif kind == 'transcribing':
                self.state = 'transcribing'
                prefix = t('status_limit') if data['automatic'] else ''
                self.status.set_text(prefix + t(
                    'status_transcribing',
                    language=t('language_' + self.prefs.language),
                ))
                self.memory_status.set_text(t('memory_working'))
                if self.ptt_inject:
                    self._ptt_osd('notify_transcribing')
            else:
                self.pending_outcome = (kind, data)
            self._controls()
        # Re-enable only after the lifecycle thread has also completed cleanup.
        if self.pending_outcome and not self.controller.busy:
            kind, data = self.pending_outcome
            self.pending_outcome = None
            if kind == 'result' and self.controller.cancel_requested.is_set():
                kind, data = 'cancelled', None
            self.memory_status.set_text(t('memory_unloaded'))
            if kind == 'result' and data['result']['text'].strip():
                self._begin_delivery(data['result']['text'].strip())
            else:
                self.state = 'idle'
                self.ptt_inject = False
                self._ptt_osd_hide()
                self._ptt_target = None
                if kind == 'result':
                    self.status.set_text(t('status_no_speech'))
                elif kind == 'cancelled':
                    self.status.set_text(t('status_cancelled'))
                else:
                    self.status.set_text(t('status_error', error=data))
                    self.memory_status.set_text(t('memory_none'))
            self._controls()
        if time.monotonic() - self._last_discovery >= 5:
            self._refresh(automatic=True)
        return GLib.SOURCE_CONTINUE

    def _begin_delivery(self, text):
        # Controller cleanup has finished. Keep one operation until the visual
        # return is acknowledged; no UI thread sleep and no early text insertion.
        self.state = 'settling'
        token = object()
        self._delivery = (token, text, self.ptt_inject)
        self.status.set_text(t('status_inserting'))
        if self.ptt_inject:
            from .inject import finish_helper_status
            self._delivery_call = finish_helper_status(lambda ok: self._return_finished(token, ok))
        else:
            delay = 420 if self.get_settings().get_property('gtk-enable-animations') else 80
            self._delivery_timer = GLib.timeout_add(delay, self._complete_delivery, token)

    def _return_finished(self, token, ok):
        if self.closing or self._delivery is None or self._delivery[0] is not token:
            return
        if ok is False:
            # A known Shell cancellation (focus change/lock) is different from
            # an unavailable method on an older installed extension.
            self._cancel_delivery()
            self.status.set_text(t('status_cancelled'))
            self._controls()
        else:
            self._complete_delivery(token)

    def _complete_delivery(self, token):
        if self.closing or self._delivery is None or self._delivery[0] is not token:
            return GLib.SOURCE_REMOVE
        _, text, inject = self._delivery
        self._delivery = None
        self._delivery_call = self._delivery_timer = None
        self.text.get_buffer().set_text(text)
        self.status.set_text(self._finish_inject(text) if inject else t('status_done'))
        self.ptt_inject = False
        self._ptt_target = None
        self._ptt_osd_hide()
        self.state = 'idle'
        self._controls()
        return GLib.SOURCE_REMOVE

    def _cancel_delivery(self):
        self._delivery = None
        if self._delivery_timer is not None:
            GLib.source_remove(self._delivery_timer)
            self._delivery_timer = None
        if self._delivery_call is not None:
            self._delivery_call.cancel()
            self._delivery_call = None
        self.ptt_inject = False
        self._ptt_target = None
        self._ptt_osd_hide()
        if not self.closing and self.state == 'settling':
            self.state = 'idle'

    def _text_changed(self, buffer):
        count = buffer.get_char_count()
        self.copy.set_sensitive(count > 0)
        self.placeholder.set_visible(count == 0)
        self.text_count.set_text(t('character_count', count=count) if count else '')

    def _copy(self, *_):
        buffer = self.text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()
        if self.state == 'idle':
            self.status.set_text(t('status_copied'))

    def _clear_ptt_timer(self):
        if self._ptt_timer is not None:
            GLib.source_remove(self._ptt_timer)
            self._ptt_timer = None

    def _on_key_event(self, _widget, event):
        """Hold-Control fallback while this window is focused. Never consumes the key."""
        if not self.prefs.push_to_talk or self.closing or event is None:
            return False
        try:
            etype = event.type
            keyval = int(event.keyval)
        except (AttributeError, TypeError, ValueError):
            return False
        if etype == Gdk.EventType.KEY_PRESS:
            if keyval in _CONTROL_KEYS:
                self.on_ptt_ctrl(True)
            elif self._ptt.ctrl and keyval not in _MODIFIER_KEYS:
                self.on_ptt_chord()
        elif etype == Gdk.EventType.KEY_RELEASE and keyval in _CONTROL_KEYS:
            self.on_ptt_ctrl(False)
        return False

    def on_ptt_ctrl(self, pressed):
        if not self.prefs.push_to_talk or self.closing:
            return
        now = time.monotonic()
        command = self._ptt.down(now) if pressed else self._ptt.up(now)
        self._handle_ptt_command(command)

    def on_ptt_chord(self):
        if not self.prefs.push_to_talk or self.closing:
            return
        self._handle_ptt_command(self._ptt.other_key())

    def _handle_ptt_command(self, command):
        if command == 'arm':
            self._clear_ptt_timer()
            self._ptt_timer = GLib.timeout_add(int(HOLD_SECONDS * 1000) + 20, self._ptt_hold_ready)
        elif command in ('disarm', 'cancel', 'stop'):
            self._clear_ptt_timer()
            if command == 'stop':
                self.end_push_to_talk()
            elif command == 'cancel':
                self.cancel_push_to_talk()

    def _ptt_hold_ready(self):
        self._ptt_timer = None
        command = self._ptt.tick(time.monotonic())
        if command == 'start':
            self.begin_push_to_talk()
        return GLib.SOURCE_REMOVE

    def begin_push_to_talk(self):
        if not self.prefs.push_to_talk or self.closing:
            return False
        started = self._start_recording(inject=True)
        if not started:
            self._ptt.live = False
        return started

    def end_push_to_talk(self):
        if not self.ptt_inject:
            return
        if self.state == 'recording':
            self.controller.stop()
            self.state = 'stopping'
            self.status.set_text(t('status_ending'))
            self._controls()
            self._ptt_osd('notify_transcribing')
        elif self.state == 'starting':
            self.cancel_push_to_talk()

    def cancel_push_to_talk(self):
        if not self.ptt_inject:
            return
        if self.state == 'settling':
            self._cancel_delivery()
            self.status.set_text(t('status_cancelled'))
            self._controls()
            return
        self.ptt_inject = False
        self._ptt_target = None
        self._ptt_osd_hide()
        if self.state in ('starting', 'recording', 'stopping', 'transcribing'):
            self.controller.cancel()
            self.state = 'stopping'
            self.status.set_text(t('status_canceling'))
            self._controls()

    def _ptt_osd(self, key):
        from .inject import show_helper_status
        phase = 'listening' if key == 'notify_listening' else 'transcribing'
        if show_helper_status(t(key), phase=phase, target=self._ptt_target):
            return
        app = self.get_application()
        if app is None:
            return
        notification = Gio.Notification.new('VoiceLens')
        notification.set_body(t(key))
        app.send_notification('voicelens-ptt', notification)

    def _ptt_osd_level(self, level):
        from .inject import set_helper_level
        set_helper_level(level)

    def _ptt_osd_hide(self):
        from .inject import hide_helper_status
        hide_helper_status()
        app = self.get_application()
        if app is not None:
            app.withdraw_notification('voicelens-ptt')

    def _finish_inject(self, text):
        from .inject import inject_text
        how = inject_text(text, target=self._ptt_target)
        if how in ('own', 'accessible', 'paste'):
            return t('status_inserted')
        return t('status_copied_not_inserted')

    def start_background_helpers(self):
        if self.closing:
            return False
        def work():
            from .inject import wayland_session
            from .shell_ext import ensure
            if wayland_session() and self.prefs.push_to_talk:
                ensure()
            GLib.idle_add(self._ptt_helper_ready)
        threading.Thread(target=work, name='voicelens-ptt-helper', daemon=True).start()
        return False

    def _ptt_helper_ready(self):
        if self.closing:
            return False
        if self.state == 'idle' and self.microphones and not self.devices_loading:
            self.status.set_text(self._idle_status())
        return False

    def _close(self, *_):
        self._discovery_cancel.set()
        self.closing = True
        self.state = 'closing'
        self._cancel_delivery()
        self._clear_ptt_timer()
        self._ptt.reset()
        self.ptt_inject = False
        self._ptt_osd_hide()
        self._dismiss_settings()
        self.controller.cancel()
        self.status.set_text(t('status_closing'))
        self._controls()
        return True

    def _destroyed(self, *_):
        self._discovery_cancel.set()
        self.closing = True
        self._cancel_delivery()
        Gtk.StyleContext.remove_provider_for_screen(self.get_screen(), self._css)
        self.controller.cancel()
        self._clear_ptt_timer()
        self._dismiss_settings()
        if self.timer_id is not None:
            GLib.source_remove(self.timer_id)
            self.timer_id = None


class VoiceLensApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.window = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        for name, handler in (
            ('ptt-down', self._on_ptt_down),
            ('ptt-up', self._on_ptt_up),
            ('ptt-chord', self._on_ptt_chord),
            ('ptt-cancel', self._on_ptt_cancel),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', handler)
            self.add_action(action)

    def do_activate(self):
        first = self.window is None
        if first:
            self.window = VoiceLensWindow(self)
            self.window.connect('destroy', self._window_destroyed)
            self.window.show_all()
            GLib.idle_add(self.window.start_background_helpers)
        self.window.present()

    def _on_ptt_down(self, *_):
        if self.window:
            self.window.on_ptt_ctrl(True)

    def _on_ptt_up(self, *_):
        if self.window:
            self.window.on_ptt_ctrl(False)

    def _on_ptt_chord(self, *_):
        if self.window:
            self.window.on_ptt_chord()

    def _on_ptt_cancel(self, *_):
        if self.window:
            self.window._clear_ptt_timer()
            self.window._ptt.reset()
            self.window.cancel_push_to_talk()

    def _window_destroyed(self, *_):
        self.window = None


def run():
    GLib.set_application_name('VoiceLens')
    GLib.set_prgname(APP_ID)
    app = VoiceLensApplication()
    def close_signal():
        if app.window:
            app.window._close()
        else:
            app.quit()
        return GLib.SOURCE_CONTINUE
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, close_signal)
    return app.run([])
