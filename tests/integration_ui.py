"""Opt-in native GTK + REAL microphone/STT integration in a private Xvfb display."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voicelens.ui import VoiceLensWindow, Gdk, Gtk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--microphone', action='store_true')
    parser.add_argument('--output', required=True, type=Path, help='Local directory for the opt-in report')
    args = parser.parse_args()
    if not args.microphone:
        raise SystemExit('Explicit --microphone required: this check records for 3 seconds.')
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    window = VoiceLensWindow()
    window.show_all()
    def pump(condition, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            if condition():
                return
            time.sleep(.01)
        raise AssertionError('GTK integration timeout; status: '+window.status.get_text())
    try:
        pump(lambda: not window.devices_loading)
        assert window.record.get_sensitive(), window.status.get_text()
        window.record.clicked()
        pump(lambda: window.state == 'recording')
        began = time.monotonic()
        pump(lambda: time.monotonic()-began >= 3)
        window.record.clicked()
        pump(lambda: window.state == 'idle')
        status = window.status.get_text()
        assert 'Done' in status or 'No speech detected' in status or 'Fertig' in status or 'Keine Sprache erkannt' in status, status
        assert window.memory_status.get_text() in ('Model unloaded', 'Modell entladen')
        assert not window.controller.busy
        buffer = window.text.get_buffer()
        char_count = buffer.get_char_count()
        # Avoid retaining incidental room speech; capture the real empty ready state.
        buffer.set_text('')
        window.status.set_text('Ready. Press Record, speak, then stop.')
        window.elapsed.set_text('00:00')
        end = time.monotonic()+.2
        pump(lambda: time.monotonic() >= end)
        pixbuf = Gdk.pixbuf_get_from_window(window.get_window(), 0, 0, window.get_allocated_width(), window.get_allocated_height())
        assert pixbuf is not None
        image = output / 'voicelens.png'
        pixbuf.savev(str(image), 'png', [], [])
        report = {'native_gtk_real_record_stop_pipeline': True, 'hardware_capture_seconds': 3,
                  'status_after_transcription': status, 'transcript_char_count_only': char_count,
                  'model_status': window.memory_status.get_text(), 'controller_thread_finished': True,
                  'screenshot': str(image)}
        (output/'ui-integration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        window._close()
        pump(lambda: not window.controller.busy, timeout=20)
        window.destroy()


if __name__ == '__main__':
    main()
