"""Isolated backend lifecycle tests; workers and ffmpeg are test doubles."""

from __future__ import annotations

import array
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
import wave
from pathlib import Path
from unittest import mock

from voicelens import backend
from voicelens.i18n import set_language


class BackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.audio = self.root / "audio.wav"
        self.audio.write_bytes(b"not used by fake workers")
        set_language("en")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def fake_worker(self, body: str) -> str:
        path = self.root / f"worker-{len(list(self.root.glob('worker-*')))}.py"
        path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(body), encoding="utf-8")
        return str(path)

    def transcribe_with(self, worker: str, **kwargs):
        real_module_path = backend._module_path
        with mock.patch.dict(os.environ, {"VOICELENS_STT_PYTHON": sys.executable}, clear=False), mock.patch.object(
            backend,
            "_module_path",
            side_effect=lambda name: worker if name == "worker.py" else real_module_path(name),
        ):
            return backend.transcribe_file(str(self.audio), **kwargs)

    def assert_process_gone(self, pid: int) -> None:
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)

    def test_transcription_success_is_reaped_before_return(self) -> None:
        worker = self.fake_worker(
            """
            import json, os
            print(json.dumps({"ok": True, "text": "Hallo Welt", "worker_pid": os.getpid()}))
            """
        )
        result = self.transcribe_with(worker)
        self.assertEqual(result["text"], "Hallo Welt")
        self.assertEqual(result["language"], "en")
        self.assertEqual(result["model"], "small")
        self.assertTrue(result["model_unloaded"])
        self.assert_process_gone(result["worker_pid"])

    def test_worker_error_is_user_facing(self) -> None:
        worker = self.fake_worker(
            """
            import json
            print(json.dumps({"ok": False, "error": "Testfehler"}))
            raise SystemExit(1)
            """
        )
        with self.assertRaisesRegex(backend.AppError, "Testfehler"):
            self.transcribe_with(worker)

    def test_setup_worker_is_reaped_without_loading_a_model(self):
        marker = self.root / 'check.pid'
        worker = self.fake_worker(f'''
            import json, os, sys
            assert sys.argv[1:] == ['--check']
            open({str(marker)!r}, 'w').write(str(os.getpid()))
            print(json.dumps({{'ok': True, 'version': 'double'}}))
        ''')
        original = backend._module_path
        with mock.patch.object(backend, '_stt_python', return_value=sys.executable), mock.patch.object(
            backend, '_module_path', side_effect=lambda name: worker if name == 'worker.py' else original(name)
        ):
            result = backend.check_runtime()
        self.assertEqual(result['version'], 'double')
        self.assert_process_gone(int(marker.read_text()))

    def test_setup_worker_timeout_reaps_child(self):
        marker = self.root / 'check-timeout.pid'
        worker = self.fake_worker(f'''
            import os, time
            open({str(marker)!r}, 'w').write(str(os.getpid()))
            time.sleep(30)
        ''')
        original = backend._module_path
        with mock.patch.object(backend, '_stt_python', return_value=sys.executable), mock.patch.object(
            backend, '_module_path', side_effect=lambda name: worker if name == 'worker.py' else original(name)
        ), self.assertRaises(backend.AppError):
            backend.check_runtime(timeout=1)
        self.assert_process_gone(int(marker.read_text()))

    def test_unplugged_ports_and_sink_monitors_are_not_microphones(self):
        sources = [
            {'name': 'unplugged', 'ports': [{'name': 'jack', 'availability': 'not available'}], 'active_port': 'jack'},
            {'name': 'sink_capture', 'monitor_of_sink': 0},
            {'name': 'mic', 'monitor_of_sink': 4294967295, 'properties': 'malformed', 'state': 'SUSPENDED'},
        ]
        with mock.patch.object(backend, '_run_pactl', side_effect=[
            subprocess.CompletedProcess([], 0, json.dumps(sources)), backend.AppError('unsupported')
        ]):
            microphones = backend.list_microphones()
        self.assertEqual([mic['name'] for mic in microphones], ['mic'])

    def test_timeout_stops_and_reaps_worker(self) -> None:
        pid_file = self.root / "timeout.pid"
        worker = self.fake_worker(
            f"""
            import os, time
            open({str(pid_file)!r}, "w").write(str(os.getpid()))
            time.sleep(30)
            """
        )
        with self.assertRaisesRegex(backend.AppError, "time limit"):
            self.transcribe_with(worker, timeout=2)
        pid = int(pid_file.read_text())
        self.assert_process_gone(pid)

    def test_cancel_stops_and_reaps_worker(self) -> None:
        pid_file = self.root / "cancel.pid"
        worker = self.fake_worker(
            f"""
            import os, time
            open({str(pid_file)!r}, "w").write(str(os.getpid()))
            time.sleep(30)
            """
        )
        cancelled = threading.Event()
        def cancel_after_start():
            deadline = time.monotonic() + 5
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            cancelled.set()
        timer = threading.Thread(target=cancel_after_start)
        timer.start()
        try:
            with self.assertRaises(backend.Cancelled):
                self.transcribe_with(worker, cancel=cancelled)
        finally:
            timer.join(6)
        pid = int(pid_file.read_text())
        self.assert_process_gone(pid)

    def test_already_cancelled_does_not_start_worker(self) -> None:
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(backend.Cancelled):
            backend.transcribe_file(str(self.audio), cancel=cancelled)

    def test_microphone_filtering_and_default(self) -> None:
        sources = [
            {"name": "real", "description": "USB Mikrofon", "mute": False},
            {"name": "real.monitor", "description": "Monitor", "mute": False},
            {"name": "other", "properties": {"monitor_source": "sink"}, "mute": False},
            {"name": "classed", "properties": {"device.class": "monitor"}, "mute": False},
            {"name": "muted", "mute": True},
        ]
        responses = [
            subprocess.CompletedProcess([], 0, json.dumps(sources), ""),
            subprocess.CompletedProcess([], 0, "real\n", ""),
        ]
        with mock.patch.object(backend.subprocess, "run", side_effect=responses) as run:
            microphones = backend.list_microphones()
        self.assertEqual(
            microphones,
            [
                {"name": "real", "description": "USB Mikrofon", "default": True, "muted": False},
                {"name": "muted", "description": "muted", "default": False, "muted": True},
            ],
        )
        self.assertEqual(run.call_args_list[0].args[0], [backend.PACTL_PATH, "--format=json", "list", "sources"])
        self.assertEqual(run.call_args_list[0].kwargs["env"]["LC_ALL"], "C.UTF-8")

    def test_transcribe_passes_model_and_language(self) -> None:
        worker = self.fake_worker(
            """
            import json, os, sys
            print(json.dumps({
                "ok": True,
                "text": " ".join(sys.argv[1:]),
                "worker_pid": os.getpid(),
                "language": "de",
                "model": "base",
            }))
            """
        )
        result = self.transcribe_with(worker, model="base", language="de")
        self.assertIn("--model", result["text"])
        self.assertIn("base", result["text"])
        self.assertIn("--language", result["text"])
        self.assertIn("de", result["text"])
        self.assertEqual(result["language"], "de")
        self.assertEqual(result["model"], "base")

    def test_result_falls_back_to_requested_language(self) -> None:
        worker = self.fake_worker(
            """
            import json, os
            print(json.dumps({"ok": True, "text": "hello", "worker_pid": os.getpid()}))
            """
        )
        result = self.transcribe_with(worker, model="small", language="de")
        self.assertEqual(result["language"], "de")
        self.assertEqual(result["model"], "small")

    def test_recorder_memfd_lifecycle_with_fake_ffmpeg(self) -> None:
        fake_ffmpeg = self.root / "fake-ffmpeg.py"
        fake_ffmpeg.write_text(
            textwrap.dedent(
                """
                #!/usr/bin/env python3
                import signal
                import sys
                import time
                import wave

                output = sys.argv[-1]
                with wave.open(output, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(16000)
                    wav.writeframes(b"\\0\\0" * 16000)
                signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
                while True:
                    time.sleep(1)
                """
            ).lstrip(),
            encoding="utf-8",
        )
        fake_ffmpeg.chmod(0o755)
        with mock.patch.object(backend, "FFMPEG_PATH", str(fake_ffmpeg)), mock.patch.object(
            backend, "list_microphones", return_value=[{"name": "mic", "muted": False}]
        ):
            recorder = backend.Recorder("mic", max_seconds=3)
            recorder.start()
            # The test double has to create its WAV header before SIGINT.
            deadline = time.monotonic() + 2
            while os.fstat(recorder.pass_fds[0]).st_size < 44 and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(recorder.pid)
            self.assertEqual(len(recorder.pass_fds), 1)
            path = recorder.stop()
            self.assertTrue(path.startswith("/proc/self/fd/"))
            self.assertGreater(recorder.elapsed, 0)
            self.assertTrue(recorder.finished)
            recorder.close()
            recorder.close()
            self.assertFalse(os.path.exists(path))

    def _wav_bytes(self, samples: list[int]) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(array.array("h", samples).tobytes())
        return buf.getvalue()

    def test_pcm16_level_gates_silence_and_follows_speech(self) -> None:
        self.assertEqual(backend._pcm16_level(b""), 0.0)
        quiet = array.array("h", [0] * 800).tobytes()
        loud = array.array("h", [18000] * 800).tobytes()
        self.assertEqual(backend._pcm16_level(quiet), 0.0)
        self.assertGreater(backend._pcm16_level(loud), 0.5)
        body = array.array("h", [4000] * 800).tobytes()
        plosive = array.array("h", [4000] * 760 + [22000] * 40).tobytes()
        self.assertGreater(backend._pcm16_level(plosive), backend._pcm16_level(body))

    def test_wav_data_offset_finds_pcm_after_fmt(self) -> None:
        payload = self._wav_bytes([0] * 100)
        offset = backend._wav_data_offset(payload[:256])
        self.assertIsNotNone(offset)
        self.assertGreaterEqual(offset, 44)

    def test_peek_level_reads_without_moving_file_offset(self) -> None:
        fd = backend._create_memfd("voicelens-level.wav")
        recorder = object.__new__(backend.Recorder)
        recorder._audio_fd = fd
        recorder._pcm_start = None
        try:
            os.write(fd, self._wav_bytes([0] * 4000))
            marker = os.lseek(fd, 12, os.SEEK_SET)
            quiet = recorder.peek_level()
            self.assertEqual(os.lseek(fd, 0, os.SEEK_CUR), marker)
            self.assertLess(quiet, 0.08)
            os.lseek(fd, 0, os.SEEK_SET)
            os.ftruncate(fd, 0)
            os.write(fd, self._wav_bytes([14000] * 4000))
            recorder._pcm_start = None
            loud = recorder.peek_level()
            self.assertGreater(loud, 0.4)
        finally:
            os.close(fd)

    def test_recorder_rejects_muted_or_missing_source(self) -> None:
        with mock.patch.object(backend, "list_microphones", return_value=[]):
            with self.assertRaisesRegex(backend.AppError, "no longer available"):
                backend.Recorder("gone").start()
        with mock.patch.object(backend, "list_microphones", return_value=[
            {"name": "muted", "description": "Desk microphone", "muted": True},
            {"name": "other", "muted": False},
        ]), mock.patch.object(backend.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(backend.AppError, "Desk microphone.*muted.*select another"):
                backend.Recorder("muted").start()
            spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
