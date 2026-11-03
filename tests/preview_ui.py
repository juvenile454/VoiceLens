"""Opt-in screenshots with a synthetic backend. No recording or desktop helper."""
import argparse
from pathlib import Path
import sys
import time
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gdk, GdkPixbuf, Gtk
from voicelens.i18n import set_language, t
from voicelens.settings import Settings
from voicelens.ui import VoiceLensWindow
from test_controller import FakeBackend


class PreviewBackend(FakeBackend):
    mic_description = {'en': 'Built-in microphone', 'de': 'Eingebautes Mikrofon'}
    language = 'de'

    def list_microphones(self):
        return [dict(name='test-source', description=self.mic_description[self.language], default=True, muted=False)]


SAMPLE_TEXT = {
    'en': 'This is a sample transcript from the synthetic backend. '
          'It shows how finished text looks in the window and can be edited.',
    'de': 'Das ist ein Beispieltranskript aus dem synthetischen Backend. '
          'Es zeigt, wie ein fertiger Text im Fenster aussieht und bearbeitet werden kann.',
}


def pump():
    end = time.monotonic() + 0.25
    while time.monotonic() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def capture(widget, path):
    pump()
    native = widget.get_window()
    width, height = native.get_width(), native.get_height()
    image = Gdk.pixbuf_get_from_window(native, 0, 0, width, height)
    image.savev(str(path), 'png', [], [])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--language', choices=('en', 'de'), default='de')
    args = parser.parse_args()
    lang = args.language
    set_language(lang)
    backend = PreviewBackend()
    backend.language = lang
    args.output.mkdir(parents=True, exist_ok=True)
    icon = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(Path(__file__).resolve().parent.parent / 'assets/voicelens.svg'), 256, 256, True)
    icon.savev(str(args.output / 'app-icon.png'), 'png', [], [])
    model_available = mock.patch('voicelens.ui.is_model_available', return_value=True)
    model_available.start()
    window = VoiceLensWindow(backend_api=backend, prefs=Settings(language=lang, keep_model='timed', keep_minutes=10))
    window._ptt_needs_extension = lambda: False
    window._ptt_osd_hide = lambda: None
    window.show_all()
    capture(window, args.output / f'voicelens-{lang}.png')
    window.settings_button.clicked()
    capture(window.settings_dialog, args.output / f'settings-{lang}.png')
    window.settings_dialog.stack.set_visible_child_name('model')
    capture(window.settings_dialog, args.output / f'settings-model-{lang}.png')
    with mock.patch('voicelens.ui.data_dir', return_value=Path('/home/user/.local/share/voicelens')):
        help_dialog = window.settings_dialog._setup_help()
        capture(help_dialog, args.output / f'setup-help-{lang}.png')
        help_dialog.destroy()
    window.settings_dialog.destroy()
    shortcuts = window._open_shortcuts()
    capture(shortcuts, args.output / f'shortcuts-{lang}.png')
    shortcuts.destroy()
    for phase in ('recording', 'transcribing'):
        window.state = phase
        window.status.set_text(t('status_listening') if phase == 'recording' else t('status_transcribing', language=t('language_' + lang)))
        window.elapsed.set_text('00:12')
        window._controls()
        window.visualizer.level = 0.65
        if phase == 'recording':
            window.level_bar.set_value(0.65)
        capture(window, args.output / f'{phase}-{lang}.png')
    window.state = 'idle'
    window._controls()
    window.text.get_buffer().set_text(SAMPLE_TEXT[lang])
    window.status.set_text(t('status_done'))
    capture(window, args.output / f'result-{lang}.png')
    window.memory_status.set_text(t('memory_resident_timed', model='Small', minutes=9))
    window.memory_status.get_style_context().add_class('memory-resident')
    capture(window, args.output / f'resident-{lang}.png')
    window.memory_status.get_style_context().remove_class('memory-resident')
    window.text.get_buffer().set_text('')
    window.state = 'idle'
    window.elapsed.set_text('00:00')
    window.resize(560, 620)
    capture(window, args.output / f'compact-{lang}.png')
    window.destroy()
    model_available.stop()
    print(f'Synthetic GTK previews: {args.output.resolve()}')


if __name__ == '__main__':
    main()
