"""Controller contract tests. Backend below is an explicit test double, not STT."""
import threading
import time
import unittest

from voicelens.controller import Controller


class FakeBackend:
    class AppError(Exception):
        pass

    class Cancelled(AppError):
        pass

    def __init__(self):
        self.created = []
        self.calls = 0
        self.result_text = 'Testdouble: Beispieltext.'
        self.fail = False
        self.allow_result = threading.Event()
        self.allow_result.set()
        self.stt_started = threading.Event()
        self.last_model = 'small'
        self.last_language = 'en'

    def list_microphones(self):
        return [dict(name='test-source', description='Testmikrofon', default=True, muted=False)]

    def check_capture_dependencies(self):
        pass

    def check_runtime(self, *, cancel=None):
        return {'python': '/test/python3', 'version': 'double'}

    def Recorder(self, source, max_seconds=900):
        recorder = FakeRecorder(source, max_seconds)
        self.created.append(recorder)
        return recorder

    def transcribe_file(self, path, cancel, *, pass_fds, model='small', language='en'):
        self.calls += 1
        self.last_model = model
        self.last_language = language
        self.stt_started.set()
        while not self.allow_result.wait(0.01):
            if cancel.is_set():
                raise self.Cancelled()
        if self.fail:
            raise self.AppError('Expliziter Testfehler')
        return dict(text=self.result_text, model_unloaded=True, worker_pid=0, language=language, model=model)


class FakeRecorder:
    def __init__(self, source, maximum):
        self.source = source
        self.maximum = maximum
        self.closed = False
        self.start_time = None
        self.pass_fds = ()
        self.pid = None

    def start(self):
        self.start_time = time.monotonic()

    @property
    def elapsed(self):
        assert self.start_time is not None
        return time.monotonic() - self.start_time

    @property
    def finished(self):
        return self.elapsed >= self.maximum

    def stop(self):
        return 'explicit-test-double.wav'

    def close(self):
        self.closed = True


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError('Condition did not become true before timeout')


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.api = FakeBackend()
        self.controller = Controller(self.api)

    def tearDown(self):
        self.controller.cancel()
        if self.controller.thread:
            self.controller.thread.join(4)
        self.assertFalse(self.controller.busy)

    def test_start_stop_returns_result_after_cleanup(self):
        self.controller.start()
        wait_for(lambda: bool(self.api.created))
        self.controller.stop()
        wait_for(lambda: not self.controller.busy)
        events = list(self.controller.drain())
        self.assertEqual(events[-1][0], 'result')
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(self.api.created[0].source, 'test-source')
        self.assertEqual(self.api.calls, 1)
        self.assertEqual(self.api.last_model, 'small')
        self.assertEqual(self.api.last_language, 'en')

    def test_start_forwards_model_and_language(self):
        self.controller.start(model='base', language='de')
        wait_for(lambda: bool(self.api.created))
        self.controller.stop()
        wait_for(lambda: not self.controller.busy)
        self.assertEqual(self.api.last_model, 'base')
        self.assertEqual(self.api.last_language, 'de')

    def test_double_start_rejected(self):
        self.controller.start()
        with self.assertRaises(RuntimeError):
            self.controller.start()

    def test_cancel_recording_never_transcribes(self):
        self.controller.start()
        wait_for(lambda: bool(self.api.created))
        self.controller.cancel()
        wait_for(lambda: not self.controller.busy)
        self.assertEqual(self.api.calls, 0)
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(list(self.controller.drain())[-1][0], 'cancelled')

    def test_cancel_stt_cleans_recording(self):
        self.api.allow_result.clear()
        self.controller.start()
        self.controller.stop()
        self.assertTrue(self.api.stt_started.wait(4))
        self.controller.cancel()
        wait_for(lambda: not self.controller.busy)
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(list(self.controller.drain())[-1][0], 'cancelled')

    def test_stt_error_still_cleans_recording(self):
        self.api.fail = True
        self.controller.start()
        self.controller.stop()
        wait_for(lambda: not self.controller.busy)
        self.assertTrue(self.api.created[0].closed)
        self.assertEqual(list(self.controller.drain())[-1][0], 'error')

    def test_automatic_limit_and_second_recording(self):
        self.controller.max_seconds = 0.2
        for _ in range(2):
            self.controller.start()
            wait_for(lambda: not self.controller.busy)
            event = list(self.controller.drain())[-1]
            self.assertEqual(event[0], 'result')
            self.assertTrue(event[1]['automatic'])
        self.assertEqual(self.api.calls, 2)
        self.assertTrue(all(rec.closed for rec in self.api.created))

    def test_wall_limit_also_stops_stalled_recorder(self):
        from unittest import mock
        self.controller.max_seconds = 0.2
        with mock.patch.object(FakeRecorder, 'finished', new_callable=mock.PropertyMock, return_value=False):
            self.controller.start()
            wait_for(lambda: not self.controller.busy)
        outcome = list(self.controller.drain())[-1]
        self.assertEqual(outcome[0], 'result')
        self.assertTrue(outcome[1]['automatic'])
        self.assertTrue(self.api.created[0].closed)

    def test_recording_emits_microphone_level(self):
        def make(source, max_seconds=900):
            rec = FakeRecorder(source, max_seconds)
            rec.peek_level = lambda: 0.33
            self.api.created.append(rec)
            return rec

        self.api.Recorder = make
        found = []

        def has_level():
            found.extend(self.controller.drain())
            return any(kind == 'level' for kind, _ in found)

        self.controller.start()
        wait_for(lambda: bool(self.api.created))
        wait_for(has_level)
        self.controller.stop()
        wait_for(lambda: not self.controller.busy)
        found.extend(self.controller.drain())
        levels = [data for kind, data in found if kind == 'level']
        self.assertTrue(levels)
        self.assertTrue(all(value == 0.33 for value in levels))
        self.assertEqual(found[-1][0], 'result')

    def test_no_microphone_fails_without_recording(self):
        self.api.list_microphones = lambda: []
        self.controller.start()
        wait_for(lambda: not self.controller.busy)
        self.assertEqual(self.api.created, [])
        self.assertEqual(list(self.controller.drain())[-1][0], 'error')
