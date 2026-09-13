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
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    icon = GdkPixbuf.Pixbuf.new_from_file_at_scale(
        str(Path(__file__).resolve().parent.parent / 'assets/voicelens.svg'), 256, 256, True)
    icon.savev(str(args.output / 'app-icon.png'), 'png', [], [])
    window = VoiceLensWindow(backend_api=FakeBackend(), prefs=Settings(language='de'))
    window._ptt_needs_extension = lambda: False
    window._ptt_osd_hide = lambda: None
    window.show_all()
    capture(window, args.output / 'voicelens-de.png')
    window.settings_button.clicked()
    capture(window.settings_dialog, args.output / 'settings-de.png')
    with mock.patch('voicelens.ui.data_dir', return_value=Path('/home/user/.local/share/voicelens')):
        help_dialog = window.settings_dialog._setup_help()
        capture(help_dialog, args.output / 'setup-help-de.png')
        help_dialog.destroy()
    window.settings_dialog.destroy()
    for phase in ('recording', 'transcribing'):
        window.state = phase
        window.status.set_text(t('status_listening') if phase == 'recording' else t('status_transcribing', language='Deutsch'))
        window.elapsed.set_text('00:12')
        window._controls()
        window.visualizer.level = 0.65
        capture(window, args.output / f'{phase}-de.png')
    window.state = 'idle'
    window.elapsed.set_text('00:00')
    window.prefs.language = 'en'
    set_language('en')
    window._apply_strings()
    window._apply_devices(window.microphones)
    capture(window, args.output / 'voicelens-en.png')
    window.resize(560, 620)
    capture(window, args.output / 'compact-en.png')
    window.destroy()
    print(f'Synthetic GTK previews: {args.output.resolve()}')


if __name__ == '__main__':
    main()
