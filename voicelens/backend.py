"""Private audio recording and one-shot offline transcription backend."""

from __future__ import annotations

import array
import json
import math
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave
import ctypes
from pathlib import Path
from typing import Any

from .i18n import current_language, t
from .settings import CACHE_ENV_KEYS, data_dir


class AppError(Exception):
    """An error that can be displayed to the user without a traceback."""


class Cancelled(AppError):
    """The user cancelled an active transcription."""


PACTL_PATH = "/usr/bin/pactl"
FFMPEG_PATH = "/usr/bin/ffmpeg"
SYSTEM_PYTHON = "/usr/bin/python3"
MAX_RECORD_SECONDS = 900.0
_PROJECT = Path(__file__).resolve().parent.parent


def _module_path(name: str) -> str:
    return str(Path(__file__).with_name(name))


def _create_memfd(name: str) -> int:
    """Use an anonymous Linux in-memory file, including Python builds without os.memfd_create."""
    native = getattr(os, "memfd_create", None)
    if native is not None:
        return native(name, flags=getattr(os, "MFD_CLOEXEC", 1))
    libc = ctypes.CDLL(None, use_errno=True)
    memfd_create = libc.memfd_create
    memfd_create.argtypes = (ctypes.c_char_p, ctypes.c_uint)
    memfd_create.restype = ctypes.c_int
    fd = memfd_create(name.encode("utf-8"), 1)  # MFD_CLOEXEC; pass_fds opens only intended children.
    if fd < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return fd


def _pactl_environment() -> dict[str, str]:
    allowed = ('HOME', 'PATH', 'LANG', 'TZ', 'XDG_RUNTIME_DIR', 'PULSE_SERVER', 'PULSE_COOKIE')
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["LC_ALL"] = "C.UTF-8"
    env["VOICELENS_LANGUAGE"] = current_language()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_pactl(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [PACTL_PATH, *arguments],
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=10,
            env=_pactl_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AppError(t("mic_manager_unavailable")) from exc


def _source_is_monitor(source: dict[str, Any]) -> bool:
    properties = source.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    name = str(source.get("name") or "")
    monitor_source = source.get("monitor_source", properties.get("monitor_source", ""))
    device_class = source.get("device.class", properties.get("device.class", ""))
    monitor_of_sink = source.get("monitor_of_sink")
    return (name.endswith(".monitor") or bool(monitor_source) or device_class == "monitor"
            or monitor_of_sink not in (None, "", "n/a", 4294967295, "4294967295"))


def _source_is_unavailable(source: dict[str, Any]) -> bool:
    ports = source.get("ports")
    if isinstance(ports, list):
        active = next((p for p in ports if isinstance(p, dict) and p.get("name") == source.get("active_port")), {})
        return active.get("availability") in ("not available", "no")
    return False


def list_microphones() -> list[dict[str, Any]]:
    """Return selectable, non-monitor PulseAudio/PipeWire input sources."""
    result = _run_pactl(["--format=json", "list", "sources"])
    try:
        sources = json.loads(result.stdout)
        if not isinstance(sources, list):
            raise ValueError("source list is not a list")
    except (json.JSONDecodeError, ValueError) as exc:
        raise AppError(t("mic_list_unreadable")) from exc

    try:
        default_source = _run_pactl(["get-default-source"]).stdout.strip()
    except AppError:
        # Older servers may list sources without supporting get-default-source.
        default_source = ""
    microphones: list[dict[str, Any]] = []
    for source in sources:
        if not isinstance(source, dict) or _source_is_monitor(source) or _source_is_unavailable(source):
            continue
        name = str(source.get("name") or "")
        if not name:
            continue
        properties = source.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        description = str(source.get("description") or properties.get("device.description") or name)
        microphones.append(
            {
                "name": name,
                "description": description,
                "default": name == default_source,
                "muted": bool(source.get("mute", False)),
            }
        )
    return microphones


def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop only the process group started by this backend and reap it."""
    if process.poll() is None:
        _signal_process_group(process, signal.SIGINT)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _signal_process_group(process, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _signal_process_group(process, signal.SIGKILL)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired as error:
                    raise AppError(t("process_not_stopped")) from error
    try:
        process.wait(timeout=0)
    except subprocess.TimeoutExpired as error:
        raise AppError(t("process_still_running")) from error


def _sanitized_worker_environment(model: str = "small", language: str = "en") -> dict[str, str]:
    allowed = ("HOME", "PATH", "LANG", "LC_CTYPE", "TZ", "LD_LIBRARY_PATH", *CACHE_ENV_KEYS)
    env = {key: os.environ[key] for key in allowed if key in os.environ}
    env["LC_ALL"] = "C.UTF-8"
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    env["HF_DATASETS_OFFLINE"] = "1"
    env["HF_HUB_DISABLE_TELEMETRY"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["VOICELENS_MODEL"] = model
    env["VOICELENS_LANGUAGE"] = language
    model_path = os.environ.get("VOICELENS_MODEL_PATH")
    if model_path:
        env["VOICELENS_MODEL_PATH"] = model_path
    if os.environ.get("VOICELENS_MODEL_ID"):
        env["VOICELENS_MODEL_ID"] = os.environ["VOICELENS_MODEL_ID"]
    return env


def stt_python_candidates() -> list[str]:
    explicit = os.environ.get("VOICELENS_STT_PYTHON")
    if explicit:
        return [explicit]
    return [str(_PROJECT / ".venv/bin/python3"), str(data_dir() / "venv/bin/python3"),
            SYSTEM_PYTHON]


def _stt_python() -> str:
    for executable in stt_python_candidates():
        if os.path.isabs(executable) and os.path.isfile(executable) and os.access(executable, os.X_OK):
            return executable
    raise AppError(t("stt_not_installed"))


def check_runtime(*, timeout: float = 20, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Import-check STT in a guarded, reaped worker. No model or audio is loaded."""
    executable = _stt_python()
    if cancel is not None and cancel.is_set():
        raise Cancelled(t("cancelled"))
    try:
        process = subprocess.Popen(
            [SYSTEM_PYTHON, _module_path("guard.py"), "--parent-pid", str(os.getpid()),
             "--", executable, "-B", _module_path("worker.py"), "--check"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, env=_sanitized_worker_environment(language=current_language()),
        )
    except OSError as exc:
        raise AppError(t("stt_start_failed")) from exc
    try:
        deadline = time.monotonic() + timeout
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled(t("cancelled"))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise AppError(t("stt_not_installed"))
            try:
                stdout, _ = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        payload = json.loads(stdout)
        if process.returncode != 0 or not isinstance(payload, dict) or payload.get("ok") is not True:
            raise AppError(t("stt_not_installed"))
        return {"python": executable, "version": payload.get("version")}
    except (subprocess.TimeoutExpired, ValueError, UnicodeError) as exc:
        raise AppError(t("stt_not_installed")) from exc
    finally:
        _stop_process(process)
        process.communicate()


def check_capture_dependencies() -> None:
    for executable, package in ((FFMPEG_PATH, "ffmpeg"), (PACTL_PATH, "pulseaudio-utils")):
        if not os.path.isfile(executable) or not os.access(executable, os.X_OK):
            raise AppError(t("dependency_missing", package=package))


def _result_from_output(
    stdout: bytes,
    stderr: bytes,
    *,
    model: str = "small",
    language: str = "en",
) -> dict[str, Any]:
    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AppError(t("invalid_result")) from exc
    if not isinstance(payload, dict):
        raise AppError(t("invalid_result"))
    if not payload.get("ok"):
        detail = payload.get("error")
        if not isinstance(detail, str) or not detail.strip():
            detail = t("unknown_error")
        raise AppError(t("transcription_failed", detail=detail))
    text = payload.get("text")
    worker_pid = payload.get("worker_pid")
    if not isinstance(text, str) or not isinstance(worker_pid, int):
        raise AppError(t("invalid_result"))
    reported_language = payload.get("language")
    reported_model = payload.get("model")
    return {
        "text": text,
        "language": reported_language if reported_language in ("en", "de") else language,
        "model": reported_model if isinstance(reported_model, str) and reported_model else model,
        "model_unloaded": True,
        "worker_pid": worker_pid,
    }


def transcribe_file(
    path: str,
    cancel: threading.Event | None = None,
    *,
    pass_fds: tuple = (),
    timeout: float = 900,
    model: str = "small",
    language: str = "en",
) -> dict[str, Any]:
    """Run the offline worker and return only after it was reaped."""
    if timeout <= 0:
        raise AppError(t("timeout_positive"))
    if cancel is not None and cancel.is_set():
        raise Cancelled(t("transcription_cancelled"))

    worker_python = _stt_python()
    command = [
        SYSTEM_PYTHON,
        _module_path("guard.py"),
        "--parent-pid",
        str(os.getpid()),
        "--",
        worker_python,
        _module_path("worker.py"),
        "--model",
        model,
        "--language",
        language,
        path,
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=tuple(pass_fds),
            start_new_session=True,
            env=_sanitized_worker_environment(model=model, language=language),
        )
    except OSError as exc:
        raise AppError(t("stt_start_failed")) from exc

    deadline = time.monotonic() + timeout
    stdout = b""
    stderr = b""
    failure: AppError | None = None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                failure = Cancelled(t("transcription_cancelled"))
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                failure = AppError(t("transcription_timeout"))
                break
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if failure is not None:
            _stop_process(process)
            # communicate after wait drains pipes and makes the process definitively reaped.
            try:
                stdout, stderr = process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                _stop_process(process)
            raise failure

        if process.returncode != 0:
            # Worker errors are normally JSON, including a user-facing localized message.
            result = _result_from_output(stdout, stderr, model=model, language=language)
            # A malformed test/program must not turn a failing child into success.
            del result
            raise AppError(t("transcription_failed_generic"))
        return _result_from_output(stdout, stderr, model=model, language=language)
    finally:
        if process.poll() is None:
            _stop_process(process)
        try:
            process.communicate(timeout=1)
        except (subprocess.TimeoutExpired, ValueError):
            pass


_WAV_HEADER_SCAN = 1024
_LEVEL_WINDOW_BYTES = 1600  # 50 ms of 16 kHz mono s16le


def _wav_data_offset(header: bytes) -> int | None:
    """Return the PCM start offset of a RIFF WAVE buffer, or None if incomplete."""
    if len(header) < 12 or header[0:4] != b"RIFF" or header[8:12] != b"WAVE":
        return None
    pos = 12
    end = len(header)
    while pos + 8 <= end:
        chunk = header[pos:pos + 4]
        size = int.from_bytes(header[pos + 4:pos + 8], "little")
        pos += 8
        if chunk == b"data":
            return pos
        pos += size + (size % 2)
    return None


def _pcm16_level(pcm: bytes) -> float:
    """Map a little-endian s16le chunk to 0..1, with a small noise gate.

    Mixes RMS (speech body) with peak (consonants) so the overlay can punch
    on plosives instead of only following a slow loudness average.
    """
    count = len(pcm) // 2
    if count < 32:
        return 0.0
    samples = array.array("h")
    samples.frombytes(pcm[: count * 2])
    acc = 0
    peak = 0
    for sample in samples:
        acc += sample * sample
        mag = sample if sample >= 0 else -sample
        if mag > peak:
            peak = mag
    rms = math.sqrt(acc / count) / 32768.0
    peak_n = peak / 32768.0
    if rms < 0.01 and peak_n < 0.05:
        return 0.0
    body = (rms - 0.01) / 0.18
    if body <= 0:
        body = 0.0
    elif body >= 1:
        body = 1.0
    else:
        body = body ** 0.55
    punch = (peak_n - 0.04) / 0.50
    if punch <= 0:
        punch = 0.0
    elif punch >= 1:
        punch = 1.0
    else:
        punch = punch ** 0.70
    mixed = body * 0.78 + punch * 0.40
    if mixed <= 0:
        return 0.0
    if mixed >= 1:
        return 1.0
    return mixed


class Recorder:
    """A single private ffmpeg Pulse recording stored in a Linux memfd."""

    def __init__(self, source: str, max_seconds: float = MAX_RECORD_SECONDS) -> None:
        if not source:
            raise AppError(t("no_mic_source"))
        if max_seconds <= 0:
            raise AppError(t("max_duration_positive"))
        self.source = source
        self.max_seconds = min(float(max_seconds), MAX_RECORD_SECONDS)
        self._process: subprocess.Popen[bytes] | None = None
        self._audio_fd: int | None = None
        self._audio_file = None
        self._stderr_file = None
        self._started_at: float | None = None
        self._stopped_at: float | None = None
        self._stopped_path: str | None = None
        self._pcm_start: int | None = None

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return () if self._audio_fd is None else (self._audio_fd,)

    @property
    def pid(self) -> int | None:
        if self._process is None or self._process.poll() is not None:
            return None
        return self._process.pid

    @property
    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return max(0.0, (self._stopped_at or time.monotonic()) - self._started_at)

    @property
    def finished(self) -> bool:
        return self._process is not None and self._process.poll() is not None

    def peek_level(self) -> float:
        """Live 0..1 loudness from the newest PCM, without moving ffmpeg's write offset."""
        fd = self._audio_fd
        if fd is None:
            return 0.0
        try:
            size = os.fstat(fd).st_size
        except OSError:
            return 0.0
        start = self._pcm_start
        if start is None:
            if size < 44:
                return 0.0
            try:
                header = os.pread(fd, min(_WAV_HEADER_SCAN, size), 0)
            except OSError:
                return 0.0
            start = _wav_data_offset(header)
            if start is None:
                return 0.0
            self._pcm_start = start
        if size <= start + 64:
            return 0.0
        available = size - start
        window = min(_LEVEL_WINDOW_BYTES, available)
        window -= window % 2
        if window < 64:
            return 0.0
        offset = size - window
        if offset < start:
            offset = start
            window = (size - start) - ((size - start) % 2)
        try:
            pcm = os.pread(fd, window, offset)
        except OSError:
            return 0.0
        return _pcm16_level(pcm)

    def _check_source(self) -> None:
        try:
            microphones = list_microphones()
        except AppError:
            raise
        microphone = next((item for item in microphones if item["name"] == self.source), None)
        if microphone is None:
            raise AppError(t("mic_gone"))
        if microphone["muted"]:
            raise AppError(t("mic_muted_named", description=microphone.get("description") or self.source))

    def start(self) -> None:
        if self._process is not None:
            raise AppError(t("recording_already_active"))
        self._check_source()
        try:
            fd = _create_memfd("voicelens.wav")
            audio_file = os.fdopen(fd, "w+b", closefd=False)
            stderr_file = tempfile.TemporaryFile(mode="w+b")
            command = [
                FFMPEG_PATH,
                "-hide_banner",
                "-loglevel",
                "error",
                "-nostdin",
                "-y",
                "-f",
                "pulse",
                "-i",
                self.source,
                "-ar",
                "16000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                "-flush_packets",
                "1",
                "-t",
                str(self.max_seconds),
                "-f",
                "wav",
                f"/proc/self/fd/{fd}",
            ]
            guarded_command = [
                SYSTEM_PYTHON, _module_path('guard.py'), '--parent-pid', str(os.getpid()), '--', *command
            ]
            process = subprocess.Popen(
                guarded_command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=stderr_file,
                pass_fds=(fd,),
                start_new_session=True,
                env=_pactl_environment(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            try:
                audio_file.close()  # type: ignore[name-defined]
                os.close(fd)  # type: ignore[name-defined]
            except (OSError, UnboundLocalError):
                pass
            try:
                stderr_file.close()  # type: ignore[name-defined]
            except (OSError, UnboundLocalError):
                pass
            raise AppError(t("recording_start_failed")) from exc

        self._audio_fd = fd
        self._audio_file = audio_file
        self._stderr_file = stderr_file
        self._process = process
        self._started_at = time.monotonic()

    def _ffmpeg_detail(self) -> str:
        if self._stderr_file is None:
            return ""
        try:
            self._stderr_file.seek(0)
            detail = self._stderr_file.read(1200).decode("utf-8", "replace").strip()
            return detail.splitlines()[-1] if detail else ""
        except (OSError, UnicodeError):
            return ""

    def _validate_wav(self) -> None:
        if self._audio_fd is None:
            raise AppError(t("no_recording_present"))
        duplicate = os.dup(self._audio_fd)
        try:
            with os.fdopen(duplicate, "rb") as readable:
                readable.seek(0)
                with wave.open(readable, "rb") as wav:
                    duration = wav.getnframes() / float(wav.getframerate())
                    if duration <= 0.2:
                        raise AppError(t("recording_too_short"))
        except (OSError, EOFError, wave.Error, ZeroDivisionError) as exc:
            raise AppError(t("wav_failed")) from exc

    def stop(self) -> str:
        if self._stopped_path is not None:
            return self._stopped_path
        if self._process is None:
            raise AppError(t("no_recording_running"))
        _stop_process(self._process)
        self._stopped_at = time.monotonic()
        if self._process.returncode not in (0, 255, -signal.SIGINT):
            detail = self._ffmpeg_detail()
            suffix = f" ({detail})" if detail else ""
            raise AppError(t("recording_ended", suffix=suffix))
        self._validate_wav()
        assert self._audio_fd is not None
        self._stopped_path = f"/proc/self/fd/{self._audio_fd}"
        return self._stopped_path

    def close(self) -> None:
        """End/reap ffmpeg and release all anonymous descriptors; safe repeatedly."""
        if self._process is not None:
            _stop_process(self._process)
            self._process = None
        if self._audio_file is not None:
            self._audio_file.close()
            self._audio_file = None
        if self._audio_fd is not None:
            try:
                os.close(self._audio_fd)
            except OSError:
                pass
            self._audio_fd = None
        self._pcm_start = None
        if self._stderr_file is not None:
            self._stderr_file.close()
            self._stderr_file = None
