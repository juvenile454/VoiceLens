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

from .controller import KEEP_ALWAYS, KEEP_RELEASE, KEEP_TIMED, Controller
from .hotkey import HOLD_SECONDS, PushToTalk
from .visualizer import VoiceVisualizer
from .i18n import set_language, t
from .settings import (
    DEFAULT_MODEL,
    MAX_KEEP_MINUTES,
    MIN_KEEP_MINUTES,
    WHISPER_MODELS,
    get_model_spec,
    is_model_available,
    keep_policy,
    load_settings,
    normalize_keep_minutes,
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
    'loading': 'cancel',
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
_TONES = ('tone-ready', 'tone-busy', 'tone-recording', 'tone-warn')
_BUSY_STATES = frozenset({'starting', 'stopping', 'transcribing', 'loading', 'settling', 'closing'})
_ACTIVE_STATES = frozenset({'starting', 'recording', 'stopping', 'transcribing', 'loading', 'settling'})
_MEMORY_REFRESH_SECONDS = 1.0
_COPY_FEEDBACK_MS = 1600
_TIMER_WARN_SECONDS = 60


def _format_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


def _set_tone(widget, tone: str) -> None:
    style = widget.get_style_context()
    for name in _TONES:
        style.remove_class(name)
    style.add_class('tone-' + tone)


def show_setup_help(parent, model_id: str):
    """Setup instructions for local models; identical from settings and the app menu."""
    dialog = Gtk.MessageDialog(transient_for=parent, modal=True, destroy_with_parent=True,
                               message_type=Gtk.MessageType.INFO, buttons=Gtk.ButtonsType.CLOSE,
                               text=t('setup_title'))
    dialog.get_style_context().add_class('voicelens-settings')
    dialog.get_widget_for_response(Gtk.ResponseType.CLOSE).set_label(t('close'))
    dialog.format_secondary_text(t('setup_instructions', path=str(data_dir() / 'models'), model=model_id))
    for label in dialog.get_message_area().get_children():
        if isinstance(label, Gtk.Label):
            label.set_selectable(True)
            label.set_max_width_chars(65)
    dialog.connect('response', lambda widget, *_: widget.destroy())
    dialog.show_all()
    return dialog


class ShortcutsDialog(Gtk.Dialog):
    """Plain list of the few shortcuts VoiceLens honours; no search, no builder."""

    GROUPS = (
        ('shortcuts_group_dictation', (
            ('<Control>', 'shortcut_hold_control'),
            ('Escape', 'shortcut_escape'),
        )),
        ('shortcuts_group_transcript', (
            ('<Control><Shift>c', 'shortcut_copy'),
        )),
    )

    def __init__(self, parent):
        super().__init__(transient_for=parent, modal=True, destroy_with_parent=True, use_header_bar=True)
        self.get_style_context().add_class('voicelens-settings')
        self.set_title(t('shortcuts_title'))
        self.set_resizable(False)
        self.add_button(t('close'), Gtk.ResponseType.CLOSE)
        self.set_default_response(Gtk.ResponseType.CLOSE)
        body = self.get_content_area()
        body.set_spacing(14)
        body.set_border_width(18)
        for heading_key, rows in self.GROUPS:
            heading = Gtk.Label(label=t(heading_key), xalign=0)
            heading.get_style_context().add_class('heading')
            body.pack_start(heading, False, False, 0)
            grid = Gtk.Grid(column_spacing=16, row_spacing=10)
            for index, (accelerator, title_key) in enumerate(rows):
                keys = Gtk.ShortcutLabel(accelerator=accelerator)
                keys.set_valign(Gtk.Align.CENTER)
                keys.set_halign(Gtk.Align.START)
                title = Gtk.Label(label=t(title_key), xalign=0)
                title.set_line_wrap(True)
                title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
                title.set_max_width_chars(44)
                title.set_hexpand(True)
                grid.attach(keys, 0, index, 1, 1)
                grid.attach(title, 1, index, 1, 1)
            body.pack_start(grid, False, False, 0)


class SettingsDialog(Gtk.Dialog):
    """Two pages: language / dictation behaviour, and the local Whisper model."""

    def __init__(self, parent: 'VoiceLensWindow'):
        super().__init__(transient_for=parent, modal=True, destroy_with_parent=True, use_header_bar=True)
        self.app_window = parent
        self._filling = False
        self.get_style_context().add_class('voicelens-settings')
        self.set_default_size(520, 600)
        self.add_button(t('close'), Gtk.ResponseType.CLOSE)
        self.set_default_response(Gtk.ResponseType.CLOSE)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        self.switcher = Gtk.StackSwitcher()
        self.switcher.set_stack(self.stack)
        header = self.get_header_bar()
        if header is not None:
            header.set_custom_title(self.switcher)
        body = self.get_content_area()
        body.set_border_width(0)
        body.pack_start(self.stack, True, True, 0)

        # --- General ---------------------------------------------------------
        general = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        general.set_border_width(18)
        self.stack.add_titled(general, 'general', t('settings_page_general'))

        self.language_heading = self._heading()
        general.pack_start(self.language_heading, False, False, 0)
        languages = Gtk.Box(spacing=8)
        languages.get_style_context().add_class('linked')
        self.radio_en = Gtk.RadioButton.new_with_label(None, t('language_en'))
        self.radio_de = Gtk.RadioButton.new_with_label_from_widget(self.radio_en, t('language_de'))
        for radio, code in ((self.radio_en, 'en'), (self.radio_de, 'de')):
            radio.set_mode(False)
            radio.get_style_context().add_class('language-choice')
            radio.connect('toggled', self._language_toggled, code)
            languages.pack_start(radio, True, True, 0)
        general.pack_start(languages, False, False, 0)

        self.ptt_heading = self._heading(top=8)
        general.pack_start(self.ptt_heading, False, False, 0)
        ptt_list = self._switch_list()
        self.ptt_row, self.ptt_check, self.ptt_label, self.ptt_hint = self._switch_row(self._ptt_toggled)
        ptt_list.add(self.ptt_row)
        general.pack_start(ptt_list, False, False, 0)

        self.behavior_heading = self._heading(top=8)
        general.pack_start(self.behavior_heading, False, False, 0)
        behavior_list = self._switch_list()
        self.append_row, self.append_switch, self.append_label, self.append_hint = self._switch_row(self._append_toggled)
        self.auto_copy_row, self.auto_copy_switch, self.auto_copy_label, self.auto_copy_hint = self._switch_row(
            self._auto_copy_toggled)
        behavior_list.add(self.append_row)
        behavior_list.add(self.auto_copy_row)
        general.pack_start(behavior_list, False, False, 0)

        # --- Model -----------------------------------------------------------
        models = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        models.set_border_width(18)
        self.stack.add_titled(models, 'model', t('settings_page_model'))

        self.model_heading = self._heading()
        models.pack_start(self.model_heading, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_shadow_type(Gtk.ShadowType.NONE)
        scroll.set_min_content_height(300)
        scroll.get_style_context().add_class('model-scroller')
        self.model_list = Gtk.ListBox()
        self.model_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.model_list.get_style_context().add_class('model-list')
        self.model_list.connect('row-selected', self._model_selected)
        scroll.add(self.model_list)
        models.pack_start(scroll, True, True, 0)

        self.note = Gtk.Label(xalign=0)
        self.note.set_line_wrap(True)
        self.note.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.note.set_max_width_chars(52)
        self.note.get_style_context().add_class('dim-label')
        models.pack_start(self.note, False, False, 0)

        self.keep_heading = self._heading(top=8)
        models.pack_start(self.keep_heading, False, False, 0)
        keep_modes = Gtk.Box(spacing=8)
        keep_modes.get_style_context().add_class('linked')
        self.keep_release = Gtk.RadioButton.new_with_label(None, '')
        self.keep_timed = Gtk.RadioButton.new_with_label_from_widget(self.keep_release, '')
        self.keep_always = Gtk.RadioButton.new_with_label_from_widget(self.keep_release, '')
        for radio, mode in ((self.keep_release, KEEP_RELEASE), (self.keep_timed, KEEP_TIMED),
                            (self.keep_always, KEEP_ALWAYS)):
            radio.set_mode(False)
            radio.get_style_context().add_class('language-choice')
            radio.connect('toggled', self._keep_mode_toggled, mode)
            keep_modes.pack_start(radio, True, True, 0)
        models.pack_start(keep_modes, False, False, 0)
        minutes_row = Gtk.Box(spacing=10)
        self.keep_minutes = Gtk.SpinButton.new_with_range(MIN_KEEP_MINUTES, MAX_KEEP_MINUTES, 1)
        self.keep_minutes.set_numeric(True)
        self.keep_minutes.set_increments(1, 10)
        self.keep_minutes.set_valign(Gtk.Align.CENTER)
        self.keep_minutes.connect('value-changed', self._keep_minutes_changed)
        self.keep_minutes_label = Gtk.Label(xalign=0)
        self.keep_minutes_label.get_style_context().add_class('row-title')
        minutes_row.pack_start(self.keep_minutes, False, False, 0)
        minutes_row.pack_start(self.keep_minutes_label, True, True, 0)
        models.pack_start(minutes_row, False, False, 0)
        self.keep_hint = Gtk.Label(xalign=0)
        self.keep_hint.set_line_wrap(True)
        self.keep_hint.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.keep_hint.set_max_width_chars(52)
        self.keep_hint.get_style_context().add_class('dim-label')
        models.pack_start(self.keep_hint, False, False, 0)

        actions = Gtk.Box(spacing=8)
        self.setup_help = Gtk.Button()
        self.setup_help.set_image(Gtk.Image.new_from_icon_name('help-about-symbolic', Gtk.IconSize.BUTTON))
        self.setup_help.set_always_show_image(True)
        self.setup_help.connect('clicked', self._setup_help)
        self.open_folder = Gtk.Button()
        self.open_folder.set_image(Gtk.Image.new_from_icon_name('folder-open-symbolic', Gtk.IconSize.BUTTON))
        self.open_folder.set_always_show_image(True)
        self.open_folder.connect('clicked', self._open_models_folder)
        actions.pack_start(self.setup_help, True, True, 0)
        actions.pack_start(self.open_folder, True, True, 0)
        models.pack_start(actions, False, False, 0)

        self.refresh_strings()

    @staticmethod
    def _heading(top=0):
        label = Gtk.Label(xalign=0)
        label.get_style_context().add_class('heading')
        label.set_margin_top(top)
        return label

    @staticmethod
    def _switch_list():
        box = Gtk.ListBox()
        box.set_selection_mode(Gtk.SelectionMode.NONE)
        box.get_style_context().add_class('settings-list')
        return box

    @staticmethod
    def _switch_row(callback):
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        outer = Gtk.Box(spacing=14)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        texts.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(xalign=0)
        title.set_line_wrap(True)
        title.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        title.get_style_context().add_class('row-title')
        hint = Gtk.Label(xalign=0)
        hint.set_line_wrap(True)
        hint.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        hint.set_max_width_chars(46)
        hint.get_style_context().add_class('dim-label')
        texts.pack_start(title, False, False, 0)
        texts.pack_start(hint, False, False, 0)
        switch = Gtk.Switch()
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect('notify::active', callback)
        outer.pack_start(texts, True, True, 0)
        outer.pack_end(switch, False, False, 0)
        row.add(outer)
        return row, switch, title, hint

    def refresh_strings(self):
        self.set_title(t('settings_title'))
        self.stack.child_set_property(self.stack.get_child_by_name('general'), 'title', t('settings_page_general'))
        self.stack.child_set_property(self.stack.get_child_by_name('model'), 'title', t('settings_page_model'))
        self.language_heading.set_text(t('language_heading'))
        self.ptt_heading.set_text(t('ptt_heading'))
        self.ptt_label.set_text(t('ptt_label'))
        self.ptt_hint.set_text(t('ptt_hint'))
        self.behavior_heading.set_text(t('behavior_heading'))
        self.append_label.set_text(t('append_label'))
        self.append_hint.set_text(t('append_hint'))
        self.auto_copy_label.set_text(t('auto_copy_label'))
        self.auto_copy_hint.set_text(t('auto_copy_hint'))
        self.model_heading.set_text(t('model_heading'))
        self.note.set_text(t('offline_note'))
        self.keep_heading.set_text(t('keep_heading'))
        self.keep_release.set_label(t('keep_release_label'))
        self.keep_timed.set_label(t('keep_timed_label'))
        self.keep_always.set_label(t('keep_always_label'))
        self.keep_minutes_label.set_text(t('keep_minutes_label'))
        self.keep_hint.set_text(t('keep_hint'))
        self.setup_help.set_label(t('setup_help_button'))
        self.open_folder.set_label(t('open_models_folder'))
        self.open_folder.set_tooltip_text(t('open_models_folder_tooltip'))
        self.radio_en.set_label(t('language_en'))
        self.radio_de.set_label(t('language_de'))
        close = self.get_widget_for_response(Gtk.ResponseType.CLOSE)
        if close is not None:
            close.set_label(t('close'))
        prefs = self.app_window.prefs
        self._filling = True
        if prefs.language == 'de':
            self.radio_de.set_active(True)
        else:
            self.radio_en.set_active(True)
        self.ptt_check.set_active(bool(prefs.push_to_talk))
        self.append_switch.set_active(bool(prefs.append_transcript))
        self.auto_copy_switch.set_active(bool(prefs.auto_copy))
        mode, _seconds = keep_policy(prefs)
        {KEEP_RELEASE: self.keep_release, KEEP_TIMED: self.keep_timed, KEEP_ALWAYS: self.keep_always}[mode].set_active(True)
        self.keep_minutes.set_value(normalize_keep_minutes(prefs.keep_minutes))
        self.keep_minutes.set_sensitive(mode == KEEP_TIMED)
        for child in list(self.model_list.get_children()):
            self.model_list.remove(child)
        selected = None
        for spec in WHISPER_MODELS:
            row = self._model_row(spec, spec.id == prefs.model)
            self.model_list.add(row)
            if spec.id == prefs.model:
                selected = row
        self.model_list.show_all()
        if selected is not None:
            self.model_list.select_row(selected)
        self._filling = False

    @staticmethod
    def _chip(text, style):
        chip = Gtk.Label(label=text)
        chip.get_style_context().add_class('chip')
        chip.get_style_context().add_class(style)
        chip.set_valign(Gtk.Align.CENTER)
        return chip

    def _model_row(self, spec, selected):
        row = Gtk.ListBoxRow()
        row.model_id = spec.id
        available = is_model_available(spec.id)
        row.get_style_context().add_class('model-row')
        if not available:
            row.get_style_context().add_class('model-missing')
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        outer.set_margin_top(10)
        outer.set_margin_bottom(10)
        outer.set_margin_start(12)
        outer.set_margin_end(12)
        title = Gtk.Box(spacing=8)
        name = Gtk.Label(label=t(spec.name_key), xalign=0)
        name.get_style_context().add_class('row-title')
        title.pack_start(name, False, False, 0)
        if spec.id == DEFAULT_MODEL:
            title.pack_start(self._chip(t('recommended'), 'chip-accent'), False, False, 0)
        ram = Gtk.Label(label=t('ram_caption', ram=spec.ram), xalign=1)
        ram.get_style_context().add_class('dim-label')
        title.pack_end(ram, False, False, 0)
        detail = Gtk.Box(spacing=8)
        hint = Gtk.Label(label=t(spec.hint_key), xalign=0)
        hint.get_style_context().add_class('dim-label')
        hint.set_line_wrap(True)
        detail.pack_start(hint, True, True, 0)
        badge = self._chip(t('installed') if available else t('not_installed'),
                           'chip-ok' if available else 'chip-muted')
        detail.pack_end(badge, False, False, 0)
        outer.pack_start(title, False, False, 0)
        outer.pack_start(detail, False, False, 0)
        row.add(outer)
        row.set_tooltip_text(t('selected') if selected else None)
        return row

    def _language_toggled(self, button, language):
        if self._filling or not button.get_active():
            return
        self.app_window.set_language(language)

    def _ptt_toggled(self, switch, *_):
        if self._filling:
            return
        self.app_window.set_push_to_talk(switch.get_active())

    def _append_toggled(self, switch, *_):
        if self._filling:
            return
        self.app_window.set_append_transcript(switch.get_active())

    def _auto_copy_toggled(self, switch, *_):
        if self._filling:
            return
        self.app_window.set_auto_copy(switch.get_active())

    def _keep_mode_toggled(self, button, mode):
        if self._filling or not button.get_active():
            return
        self.keep_minutes.set_sensitive(mode == KEEP_TIMED)
        self.app_window.set_keep_model(mode)

    def _keep_minutes_changed(self, spin, *_):
        if self._filling:
            return
        self.app_window.set_keep_minutes(spin.get_value_as_int())

    def _model_selected(self, _list, row):
        if self._filling or row is None:
            return
        self.app_window.set_model(row.model_id)

    def _setup_help(self, *_):
        return show_setup_help(self, self.app_window.prefs.model)

    def _open_models_folder(self, *_):
        folder = data_dir() / 'models'
        try:
            folder.mkdir(parents=True, exist_ok=True)
            Gtk.show_uri_on_window(self, folder.as_uri(), Gdk.CURRENT_TIME)
        except (OSError, GLib.Error) as error:
            detail = getattr(error, 'message', None) or str(error)
            self.note.set_text(t('models_folder_failed', detail=detail))


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
        self.shortcuts_window = None
        self.ptt_inject = False
        self._ptt = PushToTalk()
        self._ptt_timer = None
        self._ptt_target = None
        self._delivery = None
        self._delivery_timer = None
        self._delivery_call = None
        self._copy_feedback = None
        self._status_transcribing = ''
        self._memory_after_outcome = ''
        self._loading_from = None
        self._memory_refreshed = 0.0
        self._preload_pending = True
        self.prefs = prefs if prefs is not None else load_settings()
        set_language(self.prefs.language)
        self.controller.set_keep_policy(*keep_policy(self.prefs))
        self.set_default_size(680, 720)
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
        self.connect('key-press-event', self._on_shortcut)
        self.connect('key-press-event', self._on_key_event)
        self.connect('key-release-event', self._on_key_event)
        self._build()
        self.timer_id = GLib.timeout_add(33, self._tick)
        self._refresh()

    # ------------------------------------------------------------------ build
    def _build(self):
        self.header = Gtk.HeaderBar(title='VoiceLens')
        self.header.set_show_close_button(True)
        self.set_titlebar(self.header)
        self.menu_button = Gtk.MenuButton()
        self.menu_button.set_image(Gtk.Image.new_from_icon_name('open-menu-symbolic', Gtk.IconSize.BUTTON))
        self.menu_button.get_style_context().add_class('header-icon')
        self.menu_button.set_popover(self._build_menu())
        self.header.pack_end(self.menu_button)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        body.set_border_width(24)
        self.add(body)

        hero = Gtk.Box(spacing=18)
        self.visualizer = VoiceVisualizer()
        hero.pack_start(self.visualizer, False, False, 0)
        intro = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        intro.set_valign(Gtk.Align.CENTER)
        self.eyebrow = self._label('eyebrow')
        self.hero_title = self._label('hero-title')
        self.hero_title.set_line_wrap(True)
        self.hero_title.set_max_width_chars(24)
        self.hero_hint = self._label('hero-hint')
        self.hero_hint.set_line_wrap(True)
        phase = Gtk.Box(spacing=8)
        self.phase_dot = self._label('phase-dot', '●')
        self.phase_title = self._label('phase-title')
        phase.pack_start(self.phase_dot, False, False, 0)
        phase.pack_start(self.phase_title, False, False, 0)
        for widget in (self.eyebrow, self.hero_title, self.hero_hint, phase):
            intro.pack_start(widget, False, False, 0)
        hero.pack_start(intro, True, True, 0)
        body.pack_start(hero, False, False, 0)

        capture = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        capture.get_style_context().add_class('card')
        capture_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        capture_inner.set_border_width(16)
        capture.pack_start(capture_inner, True, True, 0)
        capture_head = Gtk.Box(spacing=8)
        self.input_caption = self._label('caption')
        capture_head.pack_start(self.input_caption, False, False, 0)
        capture_inner.pack_start(capture_head, False, False, 0)
        devices = Gtk.Box(spacing=8)
        self.source = Gtk.ComboBoxText()
        self.source.set_hexpand(True)
        renderer = self.source.get_cells()[0]
        renderer.set_property('ellipsize', Pango.EllipsizeMode.END)
        renderer.set_property('width-chars', 28)
        self.refresh = Gtk.Button.new_from_icon_name('view-refresh-symbolic', Gtk.IconSize.BUTTON)
        self.refresh.get_style_context().add_class('icon-button')
        self.refresh.connect('clicked', self._refresh)
        devices.pack_start(self.source, True, True, 0)
        devices.pack_start(self.refresh, False, False, 0)
        capture_inner.pack_start(devices, False, False, 0)

        self.level_bar = Gtk.LevelBar.new_for_interval(0.0, 1.0)
        self.level_bar.set_mode(Gtk.LevelBarMode.CONTINUOUS)
        self.level_bar.get_style_context().add_class('level-meter')
        self.level_bar.set_size_request(-1, 6)
        capture_inner.pack_start(self.level_bar, False, False, 0)

        controls = Gtk.Box(spacing=18)
        self.record = Gtk.Button()
        self.record.set_size_request(180, 48)
        self.record.get_style_context().add_class('record-button')
        self.record.connect('clicked', self._record)
        clock = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        clock.set_valign(Gtk.Align.CENTER)
        self.elapsed = self._label('timer', '00:00')
        self.elapsed.set_xalign(1)
        self.limit = self._label('timer-limit', t('limit_caption', limit=_format_clock(self.controller.max_seconds)))
        self.limit.set_xalign(1)
        clock.pack_start(self.elapsed, False, False, 0)
        clock.pack_start(self.limit, False, False, 0)
        self.spinner = Gtk.Spinner()
        controls.pack_start(self.record, True, True, 0)
        controls.pack_start(clock, False, False, 0)
        controls.pack_end(self.spinner, False, False, 0)
        capture_inner.pack_start(controls, False, False, 0)

        status_row = Gtk.Box(spacing=8)
        self.status_dot = self._label('status-dot', '●')
        self.status_dot.set_valign(Gtk.Align.START)
        self.status = self._label('status-detail')
        self.status.set_line_wrap(True)
        self.status.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.status.set_max_width_chars(55)
        status_row.pack_start(self.status_dot, False, False, 0)
        status_row.pack_start(self.status, True, True, 0)
        capture_inner.pack_start(status_row, False, False, 0)
        self.settings_button = Gtk.Button()
        self.settings_button.set_image(Gtk.Image.new_from_icon_name('preferences-system-symbolic', Gtk.IconSize.MENU))
        self.settings_button.set_always_show_image(True)
        self.settings_button.set_halign(Gtk.Align.START)
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
        self.clear = Gtk.Button.new_from_icon_name('user-trash-symbolic', Gtk.IconSize.BUTTON)
        self.clear.get_style_context().add_class('icon-button')
        self.clear.set_sensitive(False)
        self.clear.connect('clicked', self._clear)
        self.copy = Gtk.Button()
        self.copy.set_image(Gtk.Image.new_from_icon_name('edit-copy-symbolic', Gtk.IconSize.BUTTON))
        self.copy.set_always_show_image(True)
        self.copy.set_sensitive(False)
        self.copy.connect('clicked', self._copy)
        transcript_header.pack_start(self.transcript_caption, False, False, 0)
        transcript_header.pack_start(self.text_count, True, True, 0)
        transcript_header.pack_end(self.copy, False, False, 0)
        transcript_header.pack_end(self.clear, False, False, 0)
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

    def _build_menu(self):
        popover = Gtk.Popover()
        popover.get_style_context().add_class('voicelens-menu')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.set_border_width(6)
        self.menu_settings = Gtk.ModelButton()
        self.menu_settings.connect('clicked', self._open_settings)
        self.menu_setup_help = Gtk.ModelButton()
        self.menu_setup_help.connect('clicked', self._open_setup_help)
        self.menu_shortcuts = Gtk.ModelButton()
        self.menu_shortcuts.connect('clicked', self._open_shortcuts)
        self.menu_preload = Gtk.ModelButton()
        self.menu_preload.connect('clicked', self._preload_model)
        self.menu_release = Gtk.ModelButton()
        self.menu_release.connect('clicked', self._release_model)
        for item in (self.menu_settings, self.menu_setup_help, self.menu_shortcuts,
                     Gtk.Separator(), self.menu_preload, self.menu_release):
            box.pack_start(item, False, False, 0)
        box.show_all()
        popover.add(box)
        return popover

    @staticmethod
    def _label(style, text=''):
        label = Gtk.Label(label=text, xalign=0)
        label.get_style_context().add_class(style)
        return label

    # ---------------------------------------------------------------- strings
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
        self.level_bar.set_tooltip_text(t('level_tooltip'))
        self.limit.set_text(t('limit_caption', limit=_format_clock(self.controller.max_seconds)))
        self._end_copy_feedback()
        self.copy.set_label(t('copy'))
        self.copy.set_tooltip_text(t('copy_tooltip'))
        self.clear.set_tooltip_text(t('clear_tooltip'))
        self.clear.get_accessible().set_name(t('clear'))
        self.menu_button.set_tooltip_text(t('menu_tooltip'))
        self.menu_settings.set_property('text', t('menu_settings'))
        self.menu_setup_help.set_property('text', t('menu_setup_help'))
        self.menu_shortcuts.set_property('text', t('menu_shortcuts'))
        self.menu_preload.set_property('text', t('menu_preload'))
        self.menu_release.set_property('text', t('menu_release'))
        self._update_settings_button()
        if self.state == 'idle' and not self.devices_loading:
            if self.microphones:
                self.status.set_text(self._idle_status())
            elif self.devices_loaded:
                self.status.set_text(t('status_no_mic'))
            else:
                self.status.set_text(t('status_discovering'))
        elif self.devices_loading:
            self.status.set_text(t('status_discovering'))
        self._update_memory_status(force=True)
        self._controls()
        if self.settings_dialog is not None:
            self.settings_dialog.refresh_strings()
        if self.shortcuts_window is not None:
            self.shortcuts_window.destroy()

    # --------------------------------------------------------------- settings
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
        resident = self.controller.resident_model
        if resident is not None and resident != spec.id:
            self.controller.release_model('replaced')
            self._preload_pending = True
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

    def set_append_transcript(self, enabled):
        self.prefs.append_transcript = bool(enabled)
        save_settings(self.prefs)

    def set_auto_copy(self, enabled):
        self.prefs.auto_copy = bool(enabled)
        save_settings(self.prefs)

    def set_keep_model(self, mode):
        """Release now / keep for the chosen minutes / keep loaded (loads at start-up)."""
        self.prefs.keep_model = mode if mode in (KEEP_RELEASE, KEEP_TIMED, KEEP_ALWAYS) else KEEP_RELEASE
        save_settings(self.prefs)
        self.controller.set_keep_policy(*keep_policy(self.prefs))
        self._preload_pending = self.prefs.keep_model == KEEP_ALWAYS
        self._update_memory_status(force=True)
        self._controls()

    def set_keep_minutes(self, minutes):
        self.prefs.keep_minutes = normalize_keep_minutes(minutes)
        save_settings(self.prefs)
        self.controller.set_keep_policy(*keep_policy(self.prefs))
        self._update_memory_status(force=True)

    def _preload_model(self, *_):
        """Load the model ahead of the first take (menu, or automatically for “keep loaded”)."""
        self._preload_pending = False
        if self.state != 'idle' or self.controller.busy or self.closing or self.devices_loading:
            return False
        if self.setup_error or not is_model_available(self.prefs.model) or self.prefs.keep_model == KEEP_RELEASE:
            return False
        if self.controller.resident_model == self.prefs.model:
            return False
        self._dismiss_settings()
        self.ptt_inject = False
        self.state = 'loading'
        self._loading_from = 'idle'
        self.pending_outcome = None
        if not self.controller.preload(self.prefs.model, self.prefs.language):
            self.state = 'idle'
            self._loading_from = None
            self._controls()
            return False
        self.status.set_text(t('status_loading_model', model=t(get_model_spec(self.prefs.model).name_key)))
        self._update_memory_status(force=True)
        self._controls()
        return True

    def _release_model(self, *_):
        if self.state != 'idle' or self.controller.busy or self.closing:
            return False
        self._preload_pending = False
        released = self.controller.release_model('manual')
        self._update_memory_status(force=True)
        self._controls()
        return released

    def _update_memory_status(self, force=False):
        """Footer line: what the worker holds right now; refreshed about once a second."""
        now = time.monotonic()
        if not force and now - self._memory_refreshed < _MEMORY_REFRESH_SECONDS:
            return
        self._memory_refreshed = now
        resident = self.controller.resident_model
        if self.state == 'loading':
            text = t('memory_loading')
        elif resident is not None:
            name = t(get_model_spec(resident).name_key)
            release_at = self.controller.release_at
            if self.controller.keep_mode == KEEP_TIMED and release_at is not None:
                remaining = max(0.0, release_at - now)
                if remaining < 60:
                    text = t('memory_resident_soon', model=name)
                else:
                    text = t('memory_resident_timed', model=name, minutes=int(remaining // 60) + (1 if remaining % 60 else 0))
            else:
                text = t('memory_resident_always', model=name)
        elif self.state in ('transcribing', 'stopping'):
            text = t('memory_working')
        elif self.state in ('idle', 'settling') and self.pending_outcome is None and self._memory_after_outcome:
            text = self._memory_after_outcome
        else:
            text = t('memory_idle')
        self.memory_status.set_text(text)
        style = self.memory_status.get_style_context()
        if resident is not None and self.state != 'loading':
            style.add_class('memory-resident')
        else:
            style.remove_class('memory-resident')

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
        if self.shortcuts_window is not None:
            self.shortcuts_window.destroy()

    def _open_setup_help(self, *_):
        if self.closing:
            return None
        return show_setup_help(self, self.prefs.model)

    def _open_shortcuts(self, *_):
        if self.closing:
            return None
        if self.shortcuts_window is not None:
            self.shortcuts_window.present()
            return self.shortcuts_window
        window = ShortcutsDialog(self)
        window.connect('response', lambda dialog, *_: dialog.destroy())
        window.connect('destroy', self._shortcuts_destroyed)
        self.shortcuts_window = window
        window.show_all()
        return window

    def _shortcuts_destroyed(self, *_):
        self.shortcuts_window = None

    # --------------------------------------------------------------- controls
    def _tone(self):
        if self.state == 'recording':
            return 'recording'
        if self.state in _BUSY_STATES or self.devices_loading:
            return 'busy'
        if self.setup_error or not self.microphones or not is_model_available(self.prefs.model):
            return 'warn'
        return 'ready'

    def _controls(self):
        idle = self.state == 'idle' and not self.closing
        self.source.set_sensitive(idle and not self.devices_loading)
        self.refresh.set_sensitive(idle and not self.devices_loading)
        self.settings_button.set_sensitive(idle and not self.devices_loading)
        self.menu_settings.set_sensitive(idle and not self.devices_loading)
        resident = self.controller.resident_model
        self.menu_preload.set_sensitive(
            idle and not self.devices_loading and not self.setup_error and self.prefs.keep_model != KEEP_RELEASE
            and is_model_available(self.prefs.model) and resident != self.prefs.model)
        self.menu_release.set_sensitive(idle and resident is not None)
        self.record.set_sensitive(not self.closing and (
            self.state in ('recording', 'transcribing', 'loading', 'settling') or (
                idle and not self.devices_loading and bool(self.microphones)
                and not self.setup_error and is_model_available(self.prefs.model)
            )
        ))
        self.record.set_label(t(_RECORD_KEYS.get(self.state, 'please_wait')))
        self.visualizer.set_phase(self.state)
        self.phase_title.set_text(t('phase_' + self.state))
        tone = self._tone()
        for widget in (self.phase_dot, self.status_dot, self.phase_title):
            _set_tone(widget, tone)
        style = self.record.get_style_context()
        style.remove_class('suggested-action')
        style.remove_class('destructive-action')
        style.add_class('destructive-action' if self.state == 'recording' else 'suggested-action')
        if self.state in ('starting', 'stopping', 'transcribing', 'loading', 'closing'):
            self.spinner.start()
        else:
            self.spinner.stop()
        if self.state != 'recording':
            self.level_bar.set_value(0.0)
            self.elapsed.get_style_context().remove_class('timer-warn')
        self.level_bar.set_sensitive(self.state == 'recording')
        # Avoid silently overwriting edits made while a new transcript is processing.
        self.text.set_editable(idle)
        self.clear.set_sensitive(idle and self.text.get_buffer().get_char_count() > 0)

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

    # -------------------------------------------------------------- recording
    def _record(self, *_):
        if self.state == 'recording':
            self.controller.stop()
            self.state = 'stopping'
            self.status.set_text(t('status_ending'))
        elif self.state == 'settling':
            self._cancel_delivery()
            self.status.set_text(t('status_cancelled'))
        elif self.state in ('transcribing', 'loading'):
            self._ptt_osd_hide()
            self.controller.cancel()
            self.ptt_inject = False
            self.state = 'stopping'
            self.status.set_text(t('status_canceling'))
        elif self.state == 'idle' and not self.controller.busy:
            self._start_recording(inject=False)
        self._controls()

    def cancel_operation(self):
        """Abort whatever is running and keep the previous transcript (Escape)."""
        if self.closing or self.state not in _ACTIVE_STATES:
            return False
        if self.ptt_inject:
            self.cancel_push_to_talk()
            return True
        if self.state == 'settling':
            self._cancel_delivery()
            self.status.set_text(t('status_cancelled'))
        else:
            self.controller.cancel()
            self.state = 'stopping'
            self.status.set_text(t('status_canceling'))
        self._controls()
        return True

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
                self.controller.release_model('closing')
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
                level = max(0.0, min(1.0, float(data)))
                self.visualizer.level = level
                if self.state == 'recording':
                    self.level_bar.set_value(level)
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
                self.elapsed.set_text(_format_clock(seconds))
                style = self.elapsed.get_style_context()
                if self.controller.max_seconds - seconds <= _TIMER_WARN_SECONDS:
                    style.add_class('timer-warn')
                else:
                    style.remove_class('timer-warn')
            elif kind == 'transcribing':
                self.state = 'transcribing'
                self._status_transcribing = (t('status_limit') if data['automatic'] else '') + t(
                    'status_transcribing',
                    language=t('language_' + self.prefs.language),
                )
                self.status.set_text(self._status_transcribing)
                if self.ptt_inject:
                    self._ptt_osd('notify_transcribing')
            elif kind == 'loading':
                if self.state == 'transcribing':
                    self._loading_from = 'transcribing'
                    self.state = 'loading'
                    self.status.set_text(t('status_loading_model', model=t(get_model_spec(data['model']).name_key)))
            elif kind == 'model_loaded':
                if self.state == 'loading' and self._loading_from == 'transcribing':
                    self.state = 'transcribing'
                    self.status.set_text(self._status_transcribing)
                self._loading_from = None
            elif kind == 'model_released':
                self._memory_after_outcome = t('memory_unloaded')
                if self.state == 'idle' and data.get('reason') in ('idle', 'manual', 'policy'):
                    self.status.set_text(t('status_model_released'))
            else:
                self.pending_outcome = (kind, data)
            self._update_memory_status(force=True)
            self._controls()
        # Re-enable only after the lifecycle thread has also completed cleanup.
        if self.pending_outcome and not self.controller.busy:
            kind, data = self.pending_outcome
            self.pending_outcome = None
            if kind in ('result', 'preloaded') and self.controller.cancel_requested.is_set():
                kind, data = 'cancelled', None
            self._loading_from = None
            self._memory_after_outcome = t('memory_unloaded')
            if kind == 'result' and data['result']['text'].strip():
                self._begin_delivery(data['result']['text'].strip())
            else:
                self.state = 'idle'
                self.ptt_inject = False
                self._ptt_osd_hide()
                self._ptt_target = None
                if kind == 'preloaded':
                    self.status.set_text(t('status_model_loaded', model=t(get_model_spec(data['model']).name_key)))
                elif kind == 'result':
                    self.status.set_text(t('status_no_speech'))
                elif kind == 'cancelled':
                    self.status.set_text(t('status_cancelled'))
                else:
                    self.status.set_text(t('status_error', error=data))
                    self._memory_after_outcome = t('memory_none')
            self._update_memory_status(force=True)
            self._controls()
        elif (self._preload_pending and self.state == 'idle' and self.devices_loaded
              and not self.devices_loading and self.settings_dialog is None):
            if self.prefs.keep_model == KEEP_ALWAYS and not self.controller.busy:
                self._preload_model()
            else:
                self._preload_pending = False
        self._update_memory_status()
        if time.monotonic() - self._last_discovery >= 5:
            self._refresh(automatic=True)
        return GLib.SOURCE_CONTINUE

    # --------------------------------------------------------------- delivery
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

    def _place_result(self, text):
        """Replace the transcript, or append below the existing text when enabled."""
        buffer = self.text.get_buffer()
        existing = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        appended = bool(self.prefs.append_transcript and existing.strip())
        if appended:
            buffer.set_text(existing.rstrip() + '\n' + text)
        else:
            buffer.set_text(text)
        buffer.place_cursor(buffer.get_end_iter())
        self.text.scroll_mark_onscreen(buffer.get_insert())
        return appended

    def _complete_delivery(self, token):
        if self.closing or self._delivery is None or self._delivery[0] is not token:
            return GLib.SOURCE_REMOVE
        _, text, inject = self._delivery
        self._delivery = None
        self._delivery_call = self._delivery_timer = None
        appended = self._place_result(text)
        if self.prefs.auto_copy:
            self._clipboard(text)
        if inject:
            status = self._finish_inject(text)
        elif self.prefs.auto_copy:
            status = t('status_auto_copied')
        elif appended:
            status = t('status_appended')
        else:
            status = t('status_done')
        self.status.set_text(status)
        self.ptt_inject = False
        self._ptt_target = None
        self._ptt_osd_hide()
        self.state = 'idle'
        self._update_memory_status(force=True)
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

    # ------------------------------------------------------------- transcript
    def _text_changed(self, buffer):
        count = buffer.get_char_count()
        self.copy.set_sensitive(count > 0)
        self.clear.set_sensitive(count > 0 and self.text.get_editable())
        self.placeholder.set_visible(count == 0)
        if count:
            text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
            self.text_count.set_text(t('word_count', words=len(text.split()), count=count))
        else:
            self.text_count.set_text('')

    @staticmethod
    def _clipboard(text):
        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(text, -1)
        clipboard.store()

    def _copy(self, *_):
        buffer = self.text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        if not text:
            return
        self._clipboard(text)
        if self.state == 'idle':
            self.status.set_text(t('status_copied'))
        self._end_copy_feedback()
        self.copy.set_label(t('copied_label'))
        self.copy.get_style_context().add_class('copied')
        self._copy_feedback = GLib.timeout_add(_COPY_FEEDBACK_MS, self._copy_feedback_done)

    def _copy_feedback_done(self):
        self._copy_feedback = None
        self.copy.set_label(t('copy'))
        self.copy.get_style_context().remove_class('copied')
        return GLib.SOURCE_REMOVE

    def _end_copy_feedback(self):
        if self._copy_feedback is not None:
            GLib.source_remove(self._copy_feedback)
            self._copy_feedback = None
        self.copy.get_style_context().remove_class('copied')

    def _clear(self, *_):
        if not self.text.get_editable():
            return
        self.text.get_buffer().set_text('')
        if self.state == 'idle':
            self.status.set_text(t('status_cleared'))

    # -------------------------------------------------------------- shortcuts
    def _on_shortcut(self, _widget, event):
        """Escape cancels; Ctrl+Shift+C copies. Everything else propagates."""
        if self.closing or event is None:
            return False
        try:
            keyval = int(event.keyval)
            state = int(event.state) & int(Gtk.accelerator_get_default_mod_mask())
        except (AttributeError, TypeError, ValueError):
            return False
        if keyval == Gdk.KEY_Escape and not state:
            return bool(self.cancel_operation())
        copy_mask = int(Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK)
        if keyval in (Gdk.KEY_c, Gdk.KEY_C) and state == copy_mask and self.copy.get_sensitive():
            self._copy()
            return True
        return False

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
        if self.state in ('starting', 'recording', 'stopping', 'transcribing', 'loading'):
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

    # -------------------------------------------------------------- lifecycle
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
        self._end_copy_feedback()
        Gtk.StyleContext.remove_provider_for_screen(self.get_screen(), self._css)
        self.controller.cancel()
        self.controller.release_model('closing')
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
