"""Resident model worker: IPC channel, serve loop and backend session lifecycle.

Workers below are explicit test doubles that speak the real protocol; no model
is loaded and no audio is recorded.
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from voicelens import backend, ipc, worker
from voicelens.i18n import set_language

ROOT = Path(__file__).resolve().parent.parent


class ChannelTests(unittest.TestCase):
    def setUp(self):
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.left = ipc.Channel(left)
        self.right = ipc.Channel(right)

    def tearDown(self):
        self.left.close()
        self.right.close()

    def test_messages_and_descriptors_cross_the_channel(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, b'payload')
            self.left.send({'op': 'transcribe', 'language': 'de'}, (read_fd,))
            self.left.send({'op': 'second'})
            payload, fds = self.right.receive(timeout=2)
            self.assertEqual(payload, {'op': 'transcribe', 'language': 'de'})
            self.assertEqual(len(fds), 1)
            self.assertNotEqual(fds[0], read_fd)
            self.assertEqual(os.read(fds[0], 16), b'payload')
            os.close(fds[0])
            payload, fds = self.right.receive(timeout=2)
            self.assertEqual((payload, fds), ({'op': 'second'}, []))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_large_message_is_reassembled(self):
        text = 'x' * 200_000
        self.left.send({'text': text})
        payload, _ = self.right.receive(timeout=5)
        self.assertEqual(payload['text'], text)

    def test_closed_peer_timeout_and_poll_abort(self):
        with self.assertRaises(ipc.ChannelTimeout):
            self.right.receive(timeout=0.3)

        def abort():
            raise RuntimeError('abort')

        with self.assertRaisesRegex(RuntimeError, 'abort'):
            self.right.receive(timeout=5, poll=abort)
        self.left.close()
        with self.assertRaises(ipc.ChannelClosed):
            self.right.receive(timeout=2)

    def test_malformed_line_is_reported_not_raised(self):
        self.left.sock.sendall(b'not json\n')
        payload, fds = self.right.receive(timeout=2)
        self.assertFalse(payload['ok'])
        self.assertEqual(fds, [])


class ServeLoopTests(unittest.TestCase):
    """worker.serve with an in-process transcribe double."""

    def setUp(self):
        set_language('en')
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.client = ipc.Channel(left)
        self.server = ipc.Channel(right)
        self.seen = []

        def transcribe(path, language):
            with open(path, 'rb') as handle:
                data = handle.read()
            if data == b'boom':
                raise ValueError('bad audio')
            self.seen.append((data, language))
            return data.decode('utf-8') + '!'

        self.thread = threading.Thread(target=lambda: worker.serve(self.server, 'base', transcribe))
        self.thread.start()

    def tearDown(self):
        self.client.close()
        self.thread.join(4)
        self.server.close()
        self.assertFalse(self.thread.is_alive())
        set_language('en')

    def test_handshake_descriptor_requests_errors_and_quit(self):
        payload, _ = self.client.receive(timeout=2)
        self.assertEqual(payload['event'], 'loaded')
        self.assertEqual(payload['model'], 'base')
        self.assertEqual(payload['worker_pid'], os.getpid())
        with tempfile.NamedTemporaryFile() as audio:
            audio.write(b'hello')
            audio.flush()
            self.client.send({'op': 'transcribe', 'language': 'de'}, (audio.fileno(),))
            payload, _ = self.client.receive(timeout=2)
            self.assertEqual(payload['text'], 'hello!')
            self.assertEqual(payload['language'], 'de')
            self.assertEqual(payload['model'], 'base')
            self.client.send({'op': 'transcribe', 'language': 'xx', 'path': audio.name})
            payload, _ = self.client.receive(timeout=2)
            self.assertEqual(payload['text'], 'hello!')
            self.assertEqual(payload['language'], 'en')
            audio.seek(0)
            audio.truncate()
            audio.write(b'boom')
            audio.flush()
            self.client.send({'op': 'transcribe'}, (audio.fileno(),))
            payload, _ = self.client.receive(timeout=2)
            self.assertFalse(payload['ok'])
            self.assertIn('ValueError', payload['error'])
        self.client.send({'op': 'transcribe', 'path': '/nonexistent/voicelens-audio'})
        self.assertFalse(self.client.receive(timeout=2)[0]['ok'])
        self.client.send({'op': 'transcribe'})
        self.assertFalse(self.client.receive(timeout=2)[0]['ok'])
        self.client.send({'op': 'dance'})
        self.assertFalse(self.client.receive(timeout=2)[0]['ok'])
        self.client.send({'op': 'quit'})
        payload, _ = self.client.receive(timeout=2)
        self.assertEqual(payload['event'], 'bye')
        self.assertEqual([entry[0] for entry in self.seen], [b'hello', b'hello'])

    def test_peer_going_away_ends_the_loop(self):
        self.client.receive(timeout=2)
        self.client.close()
        self.thread.join(4)
        self.assertFalse(self.thread.is_alive())


_WORKER_PRELUDE = f'''
import os, sys, time, socket
sys.path.insert(0, {str(ROOT)!r})
from voicelens.ipc import Channel, ChannelClosed

def control():
    index = sys.argv.index('--control-fd')
    return Channel(socket.socket(fileno=int(sys.argv[index + 1])))

def loop(channel, transcribe):
    channel.send({{"ok": True, "event": "loaded", "model": "small", "worker_pid": os.getpid()}})
    while True:
        try:
            request, fds = channel.receive()
        except ChannelClosed:
            return 0
        if request.get("op") == "quit":
            channel.send({{"ok": True, "event": "bye"}})
            return 0
        try:
            channel.send(transcribe(request, fds))
        finally:
            for fd in fds:
                os.close(fd)
'''


class ModelSessionTests(unittest.TestCase):
    """backend.ModelSession against guarded fake workers (real processes, no model)."""

    def setUp(self):
        set_language('en')
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.audio = self.root / 'audio.wav'
        self.audio.write_bytes(b'fake audio bytes')

    def tearDown(self):
        self.tempdir.cleanup()

    def fake_worker(self, body):
        path = self.root / f'worker-{len(list(self.root.glob("worker-*")))}.py'
        path.write_text(_WORKER_PRELUDE + textwrap.dedent(body), encoding='utf-8')
        return str(path)

    def session_with(self, script, **kwargs):
        real_module_path = backend._module_path
        with mock.patch.dict(os.environ, {'VOICELENS_STT_PYTHON': sys.executable}), mock.patch.object(
            backend, '_module_path',
            side_effect=lambda name: script if name == 'worker.py' else real_module_path(name),
        ):
            return backend.ModelSession('small', language='en', **kwargs)

    def assert_process_gone(self, pid):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.02)
        self.fail(f'process {pid} still exists')

    def test_session_reuses_one_worker_and_close_reaps_it(self):
        script = self.fake_worker('''
            def transcribe(request, fds):
                data = os.read(fds[0], 64) if fds else b''
                return {"ok": True, "text": data.decode() + " / " + request["language"], "language": request["language"],
                        "model": "small", "worker_pid": os.getpid()}
            raise SystemExit(loop(control(), transcribe))
        ''')
        session = self.session_with(script)
        try:
            self.assertTrue(session.alive)
            self.assertEqual(session.worker_pid, session.pid)
            with open(self.audio, 'rb') as handle:
                first = session.transcribe(str(self.audio), pass_fds=(handle.fileno(),), language='de')
            with open(self.audio, 'rb') as handle:
                second = session.transcribe(str(self.audio), pass_fds=(handle.fileno(),), language='en')
            self.assertEqual(first['text'], 'fake audio bytes / de')
            self.assertEqual(second['text'], 'fake audio bytes / en')
            self.assertEqual(first['worker_pid'], second['worker_pid'])
            self.assertIs(first['model_unloaded'], False)
            self.assertIs(first['resident'], True)
            self.assertEqual(first['language'], 'de')
            self.assertTrue(session.alive)
            pid = session.pid
        finally:
            session.close()
            session.close()
        self.assertFalse(session.alive)
        self.assert_process_gone(pid)
        with self.assertRaises(backend.AppError):
            session.transcribe(str(self.audio))

    def test_worker_error_reply_keeps_the_session(self):
        script = self.fake_worker('''
            def transcribe(request, fds):
                return {"ok": False, "error": "Testfehler im Worker"}
            raise SystemExit(loop(control(), transcribe))
        ''')
        session = self.session_with(script)
        try:
            with self.assertRaisesRegex(backend.AppError, 'Testfehler im Worker'):
                session.transcribe(str(self.audio))
            self.assertTrue(session.alive)
        finally:
            session.close()

    def test_cancel_during_transcription_stops_the_worker(self):
        marker = self.root / 'busy.flag'
        script = self.fake_worker(f'''
            def transcribe(request, fds):
                open({str(marker)!r}, 'w').write('busy')
                time.sleep(30)
                return {{"ok": True, "text": "late", "worker_pid": os.getpid()}}
            raise SystemExit(loop(control(), transcribe))
        ''')
        session = self.session_with(script)
        pid = session.pid
        cancel = threading.Event()

        def cancel_when_busy():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            cancel.set()

        thread = threading.Thread(target=cancel_when_busy)
        thread.start()
        try:
            with self.assertRaises(backend.Cancelled):
                session.transcribe(str(self.audio), cancel)
        finally:
            thread.join(6)
            session.close()
        self.assertFalse(session.alive)
        self.assert_process_gone(pid)

    def test_slow_load_honours_cancel_and_timeout(self):
        marker = self.root / 'load.pid'
        script = self.fake_worker(f'''
            open({str(marker)!r}, 'w').write(str(os.getpid()))
            time.sleep(30)
        ''')
        cancel = threading.Event()

        def cancel_when_started():
            deadline = time.monotonic() + 5
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            cancel.set()

        thread = threading.Thread(target=cancel_when_started)
        thread.start()
        try:
            with self.assertRaises(backend.Cancelled):
                self.session_with(script, cancel=cancel)
        finally:
            thread.join(6)
        self.assert_process_gone(int(marker.read_text()))
        marker.unlink()
        with self.assertRaisesRegex(backend.AppError, 'time limit'):
            self.session_with(script, timeout=1)
        self.assert_process_gone(int(marker.read_text()))

    def test_worker_that_dies_before_loading_reports_its_last_line(self):
        script = self.fake_worker('''
            print("model files unusable", file=sys.stderr)
            raise SystemExit(3)
        ''')
        with self.assertRaisesRegex(backend.AppError, 'could not be loaded.*model files unusable'):
            self.session_with(script)

    def test_worker_refusing_to_load_reports_its_message(self):
        script = self.fake_worker('''
            control().send({"ok": False, "error": "No local model"})
            raise SystemExit(1)
        ''')
        with self.assertRaisesRegex(backend.AppError, 'No local model'):
            self.session_with(script)

    def test_already_cancelled_never_spawns(self):
        cancel = threading.Event()
        cancel.set()
        with mock.patch.object(backend.subprocess, 'Popen') as spawn, self.assertRaises(backend.Cancelled):
            backend.ModelSession('small', cancel=cancel)
        spawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
