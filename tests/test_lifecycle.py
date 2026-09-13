"""Regression: a recorder must not outlive a crashed app. No real microphone."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from voicelens import backend
from voicelens.i18n import set_language


class LifecycleTests(unittest.TestCase):
    def test_guard_errors_use_selected_language_and_do_not_launch_command(self):
        command = [sys.executable, backend._module_path('guard.py'), '--parent-pid',
                   str(os.getpid() + 1000000), '--', '/usr/bin/true']
        try:
            for language, expected in (('en', 'The calling process has exited.'),
                                       ('de', 'Der aufrufende Prozess wurde beendet.')):
                with self.subTest(language=language):
                    set_language(language)
                    result = subprocess.run(command, env=backend._pactl_environment(),
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 125)
                    self.assertEqual(result.stdout, '')
                    self.assertEqual(result.stderr.strip(), expected)
        finally:
            set_language('en')

    def test_unreaped_child_is_never_reported_as_stopped(self):
        process = mock.Mock(pid=123)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired('explicit-test-double', 2)
        with mock.patch.object(backend, '_signal_process_group'):
            with self.assertRaisesRegex(backend.AppError, 'could not be stopped'):
                backend._stop_process(process)

    def test_anonymous_audio_fd_is_not_inheritable_by_default(self):
        fd = backend._create_memfd('explicit-test-memfd')
        try:
            self.assertFalse(os.get_inheritable(fd))
        finally:
            os.close(fd)

    def test_crashed_parent_cannot_leave_recorder_running(self):
        project = Path(backend.__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_capture = root / 'fake_capture'
            fake_capture.write_text(
                f'#!{sys.executable}\n'
                'import sys,time,wave\n'
                'with wave.open(sys.argv[-1], "wb") as w:\n'
                ' w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b"\\0\\0"*16000)\n'
                'time.sleep(30)\n'
            )
            fake_capture.chmod(0o755)
            pid_file = root / 'child.pid'
            parent_file = root / 'parent.py'
            parent_file.write_text(
                'import os,sys,time\n'
                f'sys.path.insert(0, {str(project)!r})\n'
                'from voicelens import backend\n'
                f'backend.FFMPEG_PATH={str(fake_capture)!r}\n'
                'backend.list_microphones=lambda:[{"name":"test", "muted":False}]\n'
                'recorder=backend.Recorder("test")\n'
                'recorder.start()\n'
                'while os.fstat(recorder.pass_fds[0]).st_size<44: time.sleep(.01)\n'
                f'open({str(pid_file)!r},"w").write(str(recorder.pid))\n'
                'time.sleep(30)\n'
            )
            parent = subprocess.Popen([sys.executable, str(parent_file)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            child = None
            try:
                deadline = time.monotonic() + 5
                while not pid_file.exists() and time.monotonic() < deadline and parent.poll() is None:
                    time.sleep(.02)
                self.assertTrue(pid_file.exists(), 'Test child did not start')
                child = int(pid_file.read_text())
                self.assertTrue(Path(f'/proc/{child}').exists())
                parent.kill()
                parent.communicate(timeout=3)
                deadline = time.monotonic() + 5
                while Path(f'/proc/{child}').exists() and time.monotonic() < deadline:
                    status = Path(f'/proc/{child}/status').read_text()
                    if '\nState:\tZ' in status:
                        self.assertNotIn('VmRSS:', status)
                        break  # A reparented zombie has already released all memory/descriptors.
                    time.sleep(.02)
                else:
                    self.assertFalse(Path(f'/proc/{child}').exists(), 'Recorder survived parent death')
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.communicate(timeout=3)
                if child and Path(f'/proc/{child}').exists():
                    try:
                        os.kill(child, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_audio_environment_does_not_inherit_api_tokens(self):
        with mock.patch.dict(os.environ, {'EXAMPLE_API_KEY': 'not-a-real-key', 'HF_TOKEN': 'not-a-real-token'}):
            for environment in (backend._pactl_environment(), backend._sanitized_worker_environment()):
                self.assertNotIn('EXAMPLE_API_KEY', environment)
                self.assertNotIn('HF_TOKEN', environment)
