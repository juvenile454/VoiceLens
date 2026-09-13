"""One bounded recording/STT operation; never call GTK from a worker thread."""
from __future__ import annotations

import queue
import threading
import time

from .i18n import t


class Controller:
    def __init__(self, backend, max_seconds: float = 900):
        self.backend = backend
        self.max_seconds = max_seconds
        self.events = queue.Queue()
        self.stop_requested = threading.Event()
        self.cancel_requested = threading.Event()
        self.thread = None
        self.model = "small"
        self.language = "en"

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self, source=None, model="small", language="en"):
        if self.busy:
            raise RuntimeError(t("already_recording"))
        self.model = model
        self.language = language
        self.stop_requested.clear()
        self.cancel_requested.clear()
        self.thread = threading.Thread(target=self._run, args=(source,), name="voicelens-operation")
        self.thread.start()

    def stop(self):
        self.stop_requested.set()

    def cancel(self):
        self.cancel_requested.set()

    def _run(self, source):
        recorder = None
        outcome = None
        try:
            if source is None:
                microphones = self.backend.list_microphones()
                if not microphones:
                    raise self.backend.AppError(t("no_microphone"))
                chosen = next((mic for mic in microphones if mic['default']), microphones[0])
                source = chosen['name']
            if self.cancel_requested.is_set():
                raise self.backend.Cancelled(t("cancelled"))
            recorder = self.backend.Recorder(source, max_seconds=self.max_seconds)
            # Keep this spawning thread alive until both children are reaped (PDEATHSIG).
            recorder.start()
            self.events.put(('recording', {'source': source}))
            next_update = 0.0
            peek_level = getattr(recorder, 'peek_level', None)
            while not self.stop_requested.is_set() and not recorder.finished:
                if self.cancel_requested.wait(0.03):
                    raise self.backend.Cancelled(t("cancelled"))
                if recorder.elapsed >= self.max_seconds:
                    break  # Wall-clock bound also covers a stalled/disconnected capture source.
                now = time.monotonic()
                if now >= next_update:
                    self.events.put(('elapsed', recorder.elapsed))
                    next_update = now + 0.25
                if peek_level is not None:
                    try:
                        self.events.put(('level', float(peek_level() or 0.0)))
                    except (TypeError, ValueError, OSError):
                        pass
            if self.cancel_requested.is_set():
                raise self.backend.Cancelled(t("cancelled"))
            automatic = recorder.elapsed >= self.max_seconds - 0.5
            audio_path = recorder.stop()
            self.events.put(('transcribing', {'automatic': automatic}))
            result = self.backend.transcribe_file(
                audio_path,
                self.cancel_requested,
                pass_fds=recorder.pass_fds,
                model=self.model,
                language=self.language,
            )
            if self.cancel_requested.is_set():
                raise self.backend.Cancelled(t("cancelled"))
            if result.get('model_unloaded') is not True:
                raise self.backend.AppError(t("model_not_released"))
            outcome = ('result', {'result': result, 'automatic': automatic})
        except self.backend.Cancelled:
            outcome = ('cancelled', None)
        except Exception as error:
            outcome = ('error', str(error))
        finally:
            if recorder is not None:
                try:
                    recorder.close()
                except Exception as error:
                    outcome = ('error', t("cleanup_failed", error=error))
            self.events.put(outcome or ('error', t("recording_ended_unexpectedly")))

    def drain(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return
