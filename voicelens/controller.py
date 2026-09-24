"""One bounded recording/STT operation; never call GTK from a worker thread.

The controller also owns the optional resident model worker: with the
``release`` policy every take spawns and reaps a one-shot worker (default);
``timed`` keeps the worker for a while after its last use; ``always`` keeps it
until the model changes, the policy changes or the window closes.
"""
from __future__ import annotations

import queue
import threading
import time

from .i18n import t

KEEP_RELEASE = "release"
KEEP_TIMED = "timed"
KEEP_ALWAYS = "always"


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
        self.keep_mode = KEEP_RELEASE
        self.keep_seconds = 0.0
        self._session = None
        self._session_lock = threading.RLock()
        self._idle_timer = None
        self.release_at = None

    @property
    def busy(self):
        return self.thread is not None and self.thread.is_alive()

    # ------------------------------------------------------------ resident model
    @property
    def resident_model(self):
        """The model id held by a live resident worker, or None."""
        with self._session_lock:
            session = self._session
            return session.model if session is not None and session.alive else None

    def set_keep_policy(self, mode, seconds=0.0):
        """Apply the user's policy; releasing takes effect immediately, timing is rescheduled."""
        mode = mode if mode in (KEEP_RELEASE, KEEP_TIMED, KEEP_ALWAYS) else KEEP_RELEASE
        self.keep_mode = mode
        self.keep_seconds = max(0.0, float(seconds or 0.0)) if mode == KEEP_TIMED else 0.0
        if mode == KEEP_RELEASE:
            self.release_model("policy")
        else:
            self._schedule_idle_release()

    def preload(self, model="small", language="en"):
        """Load the model ahead of the first take; only meaningful with a keep policy."""
        if self.busy:
            raise RuntimeError(t("already_recording"))
        if self.keep_mode == KEEP_RELEASE or self.resident_model == model:
            return False
        self.model = model
        self.language = language
        self.stop_requested.clear()
        self.cancel_requested.clear()
        self.thread = threading.Thread(target=self._run_preload, args=(model, language), name="voicelens-preload")
        self.thread.start()
        return True

    def release_model(self, reason="manual"):
        """End the resident worker now (also called on close). Returns True if one existed."""
        self._cancel_idle_timer()
        with self._session_lock:
            session, self._session = self._session, None
        if session is None:
            return False
        model = session.model
        was_alive = session.alive
        try:
            session.close()
        except Exception as error:
            self.events.put(('error', t("cleanup_failed", error=error)))
        if was_alive:
            self.events.put(('model_released', {'model': model, 'reason': reason}))
        return was_alive

    def _ensure_session(self, model, language):
        # Only the operation thread creates sessions; the lock guards the reference,
        # never the (slow) load itself, so the GTK thread can keep reading state.
        with self._session_lock:
            session = self._session
        if session is not None and session.alive and session.model == model:
            return session
        if session is not None:
            self.release_model("replaced" if session.alive else "stopped")
        self.events.put(('loading', {'model': model}))
        session = self.backend.ModelSession(model, language=language, cancel=self.cancel_requested)
        with self._session_lock:
            self._session = session
        self.events.put(('model_loaded', {'model': model}))
        return session

    def _reconcile_session(self):
        """Drop a worker that died or was killed by a cancel, so the UI stops showing it."""
        with self._session_lock:
            session = self._session
            if session is not None and not session.alive:
                self._session = None
                self.events.put(('model_released', {'model': session.model, 'reason': 'stopped'}))
                return
        # The policy may have been switched to "release" while a load was in flight.
        if session is not None and self.keep_mode == KEEP_RELEASE:
            self.release_model("policy")

    def _cancel_idle_timer(self):
        timer, self._idle_timer = self._idle_timer, None
        self.release_at = None
        if timer is not None:
            timer.cancel()

    def _schedule_idle_release(self):
        self._cancel_idle_timer()
        if self.keep_mode != KEEP_TIMED or self.resident_model is None:
            return
        timer = threading.Timer(self.keep_seconds, self._idle_release)
        timer.daemon = True
        self._idle_timer = timer
        self.release_at = time.monotonic() + self.keep_seconds
        timer.start()

    def _idle_release(self):
        if self.busy:
            return  # the running take reschedules when it finishes
        self._idle_timer = None
        self.release_at = None
        self.release_model("idle")

    def _run_preload(self, model, language):
        outcome = None
        try:
            self._ensure_session(model, language)
            outcome = ('preloaded', {'model': model})
        except self.backend.Cancelled:
            outcome = ('cancelled', None)
        except Exception as error:
            outcome = ('error', str(error))
        finally:
            self._reconcile_session()
            self._schedule_idle_release()
            self.events.put(outcome or ('error', t("recording_ended_unexpectedly")))

    # ---------------------------------------------------------------- operation
    def start(self, source=None, model="small", language="en"):
        if self.busy:
            raise RuntimeError(t("already_recording"))
        self.model = model
        self.language = language
        self.stop_requested.clear()
        self.cancel_requested.clear()
        self._cancel_idle_timer()
        self.thread = threading.Thread(target=self._run, args=(source,), name="voicelens-operation")
        self.thread.start()

    def stop(self):
        self.stop_requested.set()

    def cancel(self):
        self.cancel_requested.set()

    def _transcribe(self, audio_path, pass_fds):
        if self.keep_mode == KEEP_RELEASE:
            result = self.backend.transcribe_file(
                audio_path,
                self.cancel_requested,
                pass_fds=pass_fds,
                model=self.model,
                language=self.language,
            )
            if result.get('model_unloaded') is not True:
                raise self.backend.AppError(t("model_not_released"))
            return result
        session = self._ensure_session(self.model, self.language)
        result = session.transcribe(
            audio_path,
            self.cancel_requested,
            pass_fds=pass_fds,
            language=self.language,
        )
        if result.get('resident') is not True or not session.alive:
            raise self.backend.AppError(t("model_session_lost"))
        return result

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
            result = self._transcribe(audio_path, recorder.pass_fds)
            if self.cancel_requested.is_set():
                raise self.backend.Cancelled(t("cancelled"))
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
            self._reconcile_session()
            self._schedule_idle_release()
            self.events.put(outcome or ('error', t("recording_ended_unexpectedly")))

    def drain(self):
        while True:
            try:
                yield self.events.get_nowait()
            except queue.Empty:
                return
