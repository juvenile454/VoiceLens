"""Explicit local integration check; --microphone records 3 seconds, never saves audio."""
import argparse
import array
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from voicelens import backend


def pid_gone(pid):
    return not Path(f'/proc/{pid}').exists()


def measured_transcription(path, pass_fds=()):
    stop = threading.Event()
    peaks = {}
    worker_path = str(Path(backend.__file__).with_name('worker.py'))
    main_children = Path(f'/proc/{os.getpid()}/task/{threading.get_native_id()}/children')
    def monitor():
        while not stop.wait(0.025):
            for value in main_children.read_text().split():
                pid = int(value)
                try:
                    args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\x00')
                    if worker_path not in args:
                        continue
                    status = Path(f'/proc/{pid}/status').read_text()
                    rss = next(int(line.split()[1]) for line in status.splitlines() if line.startswith('VmRSS:'))
                    peaks[pid] = max(peaks.get(pid, 0), rss)
                except (FileNotFoundError, ProcessLookupError, StopIteration):
                    continue
    watcher = threading.Thread(target=monitor)
    watcher.start()
    began = time.monotonic()
    try:
        result = backend.transcribe_file(path, pass_fds=pass_fds, language='de')
        elapsed = time.monotonic() - began
    finally:
        stop.set()
        watcher.join()
    assert result['model_unloaded'] is True
    assert pid_gone(result['worker_pid']), 'Worker still exists after result'
    return result, {'elapsed_seconds': round(elapsed, 3), 'worker_pid': result['worker_pid'],
                    'worker_peak_rss_mib': round(peaks.get(result['worker_pid'], 0) / 1024, 2),
                    'worker_gone_before_result_handled': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--speech', required=True, help='Known local German speech fixture')
    parser.add_argument('--silence', required=True, help='Local silent WAV fixture')
    parser.add_argument('--microphone', action='store_true', help='Explicitly record 3s from current default microphone')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    report = {'speech_fixture': args.speech, 'checks': {}}
    text, measured = measured_transcription(args.speech)
    assert len(text['text'].split()) >= 8, text
    assert 'deutschen' in text['text'].lower() or 'spracherkennung' in text['text'].lower(), text
    report['checks']['real_whisper_synthetic_german'] = {**measured, 'transcript': text['text']}
    silence, measured = measured_transcription(args.silence)
    assert silence['text'] == '', silence
    report['checks']['real_whisper_silence'] = {**measured, 'transcript': silence['text']}
    if args.microphone:
        microphones = backend.list_microphones()
        selected = next(m for m in microphones if m['default'])
        recorder = backend.Recorder(selected['name'], max_seconds=5)
        captured_path = None
        try:
            recorder.start()
            pid = recorder.pid
            time.sleep(3)
            assert not recorder.finished, 'Recorder stopped prematurely'
            captured_path = recorder.stop()
            assert pid_gone(pid), 'Recorder still exists after stop'
            with wave.open(captured_path, 'rb') as stream:
                samples = array.array('h', stream.readframes(stream.getnframes()))
                duration = stream.getnframes() / stream.getframerate()
                assert stream.getframerate() == 16000 and stream.getnchannels() == 1
            assert duration > 1.0, duration
            rms = math.sqrt(sum(v*v for v in samples) / len(samples))
            result, measured = measured_transcription(captured_path, recorder.pass_fds)
            # Do not disclose any incidental room speech in the report.
            report['checks']['hardware_microphone'] = {
                'device': selected['description'], 'duration_seconds': round(duration, 3),
                'rms_pcm16': round(rms, 2), 'peak_pcm16': max(abs(v) for v in samples),
                'transcript_char_count_only': len(result['text']), **measured,
                'recorder_gone_after_stop': True,
            }
        finally:
            recorder.close()
        assert captured_path and not Path(captured_path).exists()
        report['checks']['hardware_microphone']['anonymous_audio_released'] = True
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
