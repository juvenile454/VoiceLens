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
        self.sessions = []
        self.load_started = threading.Event()
        self.allow_load = threading.Event()
        self.allow_load.set()
        self.load_fail = False

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

    def ModelSession(self, model='small', *, language='en', cancel=None, timeout=300):
        session = FakeModelSession(self, model, cancel)
        self.sessions.append(session)
        return session


class FakeModelSession:
    """Explicit double for backend.ModelSession: no process, no model."""

    def __init__(self, api, model, cancel):
        self.api = api
        self.model = model
        self.alive = False
        self.closed = False
        self.calls = 0
        api.load_started.set()
        while not api.allow_load.wait(0.01):
            if cancel is not None and cancel.is_set():
                raise api.Cancelled()
        if api.load_fail:
            raise api.AppError('Testdouble: Modell nicht ladbar')
        self.alive = True

    def transcribe(self, path, cancel, *, pass_fds=(), language='en', timeout=900):
        self.calls += 1
        self.api.calls += 1
        self.api.last_model = self.model
        self.api.last_language = language
        self.api.stt_started.set()
        while not self.api.allow_result.wait(0.01):
            if cancel.is_set():
                self.close()
                raise self.api.Cancelled()
        if self.api.fail:
            raise self.api.AppError('Expliziter Testfehler')
        return dict(text=self.api.result_text, model_unloaded=False, resident=True, worker_pid=4242,
                    language=language, model=self.model)

    def close(self):
        self.alive = False
        self.closed = True


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


class ResidentModelTests(unittest.TestCase):
    """Keep-model policies with the explicit FakeModelSession double."""

    def setUp(self):
        self.api = FakeBackend()
        self.controller = Controller(self.api)

    def tearDown(self):
        self.controller.cancel()
        if self.controller.thread:
            self.controller.thread.join(4)
        self.controller.release_model('test')
        self.assertFalse(self.controller.busy)

    def take(self):
        self.controller.start(model=self.controller.model, language='en')
        wait_for(lambda: bool(self.api.created) and self.api.created[-1].start_time is not None)
        self.controller.stop()
        wait_for(lambda: not self.controller.busy)
        return list(self.controller.drain())

    def kinds(self, events):
        return [kind for kind, _ in events]

    def test_default_policy_uses_one_shot_worker(self):
        events = self.take()
        self.assertEqual(events[-1][0], 'result')
        self.assertTrue(events[-1][1]['result']['model_unloaded'])
        self.assertEqual(self.api.sessions, [])
        self.assertIsNone(self.controller.resident_model)

    def test_always_policy_loads_once_and_reuses_the_worker(self):
        self.controller.set_keep_policy('always')
        first = self.take()
        self.assertIn('loading', self.kinds(first))
        self.assertIn('model_loaded', self.kinds(first))
        self.assertEqual(first[-1][0], 'result')
        self.assertIs(first[-1][1]['result']['model_unloaded'], False)
        second = self.take()
        self.assertNotIn('loading', self.kinds(second))
        self.assertEqual(second[-1][0], 'result')
        self.assertEqual(len(self.api.sessions), 1)
        self.assertEqual(self.api.sessions[0].calls, 2)
        self.assertEqual(self.controller.resident_model, 'small')
        self.assertTrue(self.controller.release_model())
        self.assertTrue(self.api.sessions[0].closed)
        self.assertIsNone(self.controller.resident_model)
        self.assertEqual(list(self.controller.drain())[-1], ('model_released', {'model': 'small', 'reason': 'manual'}))
        self.assertFalse(self.controller.release_model())

    def test_timed_policy_releases_after_idle(self):
        self.controller.set_keep_policy('timed', 0.3)
        self.take()
        self.assertEqual(self.controller.resident_model, 'small')
        self.assertIsNotNone(self.controller.release_at)
        wait_for(lambda: self.controller.resident_model is None, timeout=3)
        self.assertTrue(self.api.sessions[0].closed)
        self.assertEqual(list(self.controller.drain())[-1], ('model_released', {'model': 'small', 'reason': 'idle'}))
        self.assertIsNone(self.controller.release_at)

    def test_switching_to_release_policy_unloads_immediately(self):
        self.controller.set_keep_policy('always')
        self.take()
        self.controller.set_keep_policy('release')
        self.assertTrue(self.api.sessions[0].closed)
        self.assertEqual(list(self.controller.drain())[-1][1]['reason'], 'policy')
        self.take()
        self.assertEqual(len(self.api.sessions), 1)

    def test_model_change_replaces_the_resident_worker(self):
        self.controller.set_keep_policy('always')
        self.controller.model = 'small'
        self.take()
        self.controller.model = 'base'
        events = self.take()
        self.assertEqual(self.kinds(events)[:3], ['recording', 'elapsed', 'transcribing'][:3])
        self.assertIn(('model_released', {'model': 'small', 'reason': 'replaced'}), events)
        self.assertEqual([s.model for s in self.api.sessions], ['small', 'base'])
        self.assertTrue(self.api.sessions[0].closed)
        self.assertEqual(self.controller.resident_model, 'base')

    def test_cancel_during_resident_transcription_stops_the_worker(self):
        self.controller.set_keep_policy('always')
        self.api.allow_result.clear()
        self.controller.start()
        self.controller.stop()
        self.assertTrue(self.api.stt_started.wait(4))
        self.controller.cancel()
        wait_for(lambda: not self.controller.busy)
        events = list(self.controller.drain())
        self.assertEqual(events[-1][0], 'cancelled')
        self.assertIn(('model_released', {'model': 'small', 'reason': 'stopped'}), events)
        self.assertTrue(self.api.sessions[0].closed)
        self.assertIsNone(self.controller.resident_model)
        self.assertTrue(self.api.created[0].closed)

    def test_preload_and_its_cancellation(self):
        self.assertFalse(self.controller.preload('small'))
        self.controller.set_keep_policy('always')
        self.assertTrue(self.controller.preload('small'))
        wait_for(lambda: not self.controller.busy)
        events = list(self.controller.drain())
        self.assertEqual(self.kinds(events), ['loading', 'model_loaded', 'preloaded'])
        self.assertEqual(self.controller.resident_model, 'small')
        self.assertFalse(self.controller.preload('small'))
        self.assertEqual(self.api.calls, 0)
        self.controller.release_model()
        self.api.allow_load.clear()
        self.api.load_started.clear()
        self.assertTrue(self.controller.preload('small'))
        self.assertTrue(self.api.load_started.wait(4))
        self.controller.cancel()
        wait_for(lambda: not self.controller.busy)
        self.assertEqual(list(self.controller.drain())[-1][0], 'cancelled')
        self.assertIsNone(self.controller.resident_model)

    def test_load_failure_is_an_error_outcome_and_next_take_retries(self):
        self.controller.set_keep_policy('always')
        self.api.load_fail = True
        events = self.take()
        self.assertEqual(events[-1][0], 'error')
        self.assertIn('nicht ladbar', events[-1][1])
        self.assertTrue(self.api.created[0].closed)
        self.assertIsNone(self.controller.resident_model)
        self.api.load_fail = False
        self.assertEqual(self.take()[-1][0], 'result')
