#!/usr/bin/env python3
"""Offline faster-whisper worker for VoiceLens: one-shot, or resident with --serve."""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

# These must be in the environment before importing faster_whisper/huggingface.
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"

# Script invocation puts this file's directory on sys.path[0]; add the project root.
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from voicelens.i18n import set_language, t
from voicelens.ipc import Channel, ChannelClosed
from voicelens.settings import resolve_model_path, normalize_language, normalize_model


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def _error(message: str) -> int:
    _emit({"ok": False, "error": message})
    return 1


def _parse(argv: list[str]) -> tuple[str | None, str, str, int | None, bool]:
    model = os.environ.get("VOICELENS_MODEL", "small")
    language = os.environ.get("VOICELENS_LANGUAGE", "en")
    audio_path = None
    control_fd = None
    serve = False
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--model" and index + 1 < len(argv):
            model = argv[index + 1]
            index += 2
            continue
        if token == "--language" and index + 1 < len(argv):
            language = argv[index + 1]
            index += 2
            continue
        if token == "--control-fd" and index + 1 < len(argv):
            try:
                control_fd = int(argv[index + 1])
            except ValueError:
                return None, model, language, None, serve
            index += 2
            continue
        if token == "--serve":
            serve = True
            index += 1
            continue
        if token.startswith("-"):
            return None, model, language, control_fd, serve
        if audio_path is None:
            audio_path = token
        index += 1
    return audio_path, normalize_model(model), normalize_language(language), control_fd, serve


def _load_model(model_id: str):
    model_path = resolve_model_path(model_id)
    if model_path is None:
        raise FileNotFoundError(model_id)
    from faster_whisper import WhisperModel

    return WhisperModel(
        str(model_path),
        device="cpu",
        compute_type="int8",
        cpu_threads=4,
        local_files_only=True,
    )


def _transcribe(model, audio_path: str, language: str) -> str:
    segments, _info = model.transcribe(
        audio_path,
        language=language,
        task="transcribe",
        beam_size=5,
        condition_on_previous_text=False,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
    )
    text_parts: list[str] = []
    for segment in segments:
        if segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0:
            continue
        text_parts.append(segment.text.strip())
    return " ".join(part for part in text_parts if part).strip()


def serve(channel: Channel, model_id: str, transcribe) -> int:
    """Answer transcription requests until the peer says quit or goes away.

    ``transcribe(audio_path, language) -> str`` is the loaded model; requests carry
    the audio as a passed descriptor (preferred) or a path. Every received
    descriptor is closed here, whatever the outcome.
    """
    channel.send({"ok": True, "event": "loaded", "model": model_id, "worker_pid": os.getpid()})
    while True:
        try:
            request, fds = channel.receive()
        except ChannelClosed:
            return 0
        try:
            operation = request.get("op")
            if operation == "quit":
                channel.send({"ok": True, "event": "bye", "worker_pid": os.getpid()})
                return 0
            if operation != "transcribe":
                channel.send({"ok": False, "error": t("unknown_error")})
                continue
            language = normalize_language(request.get("language"))
            set_language(language)
            audio_path = f"/proc/self/fd/{fds[0]}" if fds else request.get("path")
            if not isinstance(audio_path, str) or not audio_path:
                channel.send({"ok": False, "error": t("no_audio_path")})
                continue
            if not Path(audio_path).exists():
                channel.send({"ok": False, "error": t("audio_unreadable")})
                continue
            try:
                text = transcribe(audio_path, language)
            except Exception as exc:
                # Keep the protocol machine-readable and do not emit a traceback with paths.
                channel.send({"ok": False, "error": t("transcription_exception", type=type(exc).__name__)})
                continue
            channel.send({
                "ok": True,
                "text": text,
                "language": language,
                "model": model_id,
                "worker_pid": os.getpid(),
            })
        finally:
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass


def _serve_main(model_id: str, language: str, control_fd: int | None) -> int:
    set_language(language)
    if control_fd is None:
        return _error(t("guard_invalid_call"))
    try:
        channel = Channel(socket.socket(fileno=control_fd))
    except OSError:
        return _error(t("guard_invalid_call"))
    try:
        model = _load_model(model_id)
    except FileNotFoundError:
        channel.send({"ok": False, "error": t("model_missing")})
        return 1
    except Exception as exc:
        channel.send({"ok": False, "error": t("transcription_exception", type=type(exc).__name__)})
        return 1
    try:
        return serve(channel, model_id, lambda path, lang: _transcribe(model, path, lang))
    except (ChannelClosed, OSError):
        return 0
    finally:
        channel.close()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--check"]:
        try:
            import faster_whisper
            import ctranslate2
            if "int8" not in ctranslate2.get_supported_compute_types("cpu"):
                return _error(t("stt_not_installed"))
            _emit({"ok": True, "version": faster_whisper.__version__})
            return 0
        except Exception:
            return _error(t("stt_not_installed"))
    audio_path, model_id, language, control_fd, resident = _parse(args)
    if resident:
        return _serve_main(model_id, language, control_fd)
    set_language(language)
    if not audio_path:
        return _error(t("no_audio_path"))
    if not Path(audio_path).exists():
        return _error(t("audio_unreadable"))

    try:
        model = _load_model(model_id)
    except FileNotFoundError:
        return _error(t("model_missing"))
    except Exception as exc:
        return _error(t("transcription_exception", type=type(exc).__name__))
    try:
        _emit(
            {
                "ok": True,
                "text": _transcribe(model, audio_path, language),
                "language": language,
                "model": model_id,
                "worker_pid": os.getpid(),
            }
        )
        return 0
    except Exception as exc:
        # Keep the protocol machine-readable and do not emit a traceback with paths.
        return _error(t("transcription_exception", type=type(exc).__name__))


if __name__ == "__main__":
    raise SystemExit(main())
