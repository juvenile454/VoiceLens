#!/usr/bin/env python3
"""One-shot, offline faster-whisper worker for VoiceLens."""

from __future__ import annotations

import json
import os
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
from voicelens.settings import resolve_model_path, normalize_language, normalize_model


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False), flush=True)


def _error(message: str) -> int:
    _emit({"ok": False, "error": message})
    return 1


def _parse(argv: list[str]) -> tuple[str | None, str, str]:
    model = os.environ.get("VOICELENS_MODEL", "small")
    language = os.environ.get("VOICELENS_LANGUAGE", "en")
    audio_path = None
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
        if token.startswith("-"):
            return None, model, language
        if audio_path is None:
            audio_path = token
        index += 1
    return audio_path, normalize_model(model), normalize_language(language)


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
    audio_path, model_id, language = _parse(args)
    set_language(language)
    if not audio_path:
        return _error(t("no_audio_path"))
    if not Path(audio_path).exists():
        return _error(t("audio_unreadable"))

    model_path = resolve_model_path(model_id)
    if model_path is None:
        return _error(t("model_missing"))
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(
            str(model_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            local_files_only=True,
        )
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
        _emit(
            {
                "ok": True,
                "text": " ".join(part for part in text_parts if part).strip(),
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
