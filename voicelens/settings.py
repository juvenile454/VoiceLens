"""Persisted language/model choice and local Whisper catalog (offline only)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .i18n import DEFAULT_LANGUAGE, normalize_language

DEFAULT_MODEL = "small"
KEEP_MODES = ("release", "timed", "always")
DEFAULT_KEEP_MODE = "release"
DEFAULT_KEEP_MINUTES = 10
MIN_KEEP_MINUTES = 1
MAX_KEEP_MINUTES = 720
REQUIRED_MODEL_FILES = ("model.bin", "config.json", "tokenizer.json")
CACHE_ENV_KEYS = ("HF_HUB_CACHE", "HUGGINGFACE_HUB_CACHE", "HF_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    ram: str
    name_key: str
    hint_key: str


# RAM figures match the usual Whisper CPU/INT8 estimates (Tiny/Base ~1 GB, Large ~10 GB).
WHISPER_MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("tiny", "1 GB", "model_tiny", "model_tiny_hint"),
    ModelSpec("base", "1 GB", "model_base", "model_base_hint"),
    ModelSpec("small", "2 GB", "model_small", "model_small_hint"),
    ModelSpec("medium", "5 GB", "model_medium", "model_medium_hint"),
    ModelSpec("large-v2", "10 GB", "model_large_v2", "model_large_v2_hint"),
    ModelSpec("large-v3", "10 GB", "model_large_v3", "model_large_v3_hint"),
)
KNOWN_MODELS = {spec.id: spec for spec in WHISPER_MODELS}


@dataclass
class Settings:
    language: str = DEFAULT_LANGUAGE
    model: str = DEFAULT_MODEL
    push_to_talk: bool = True
    append_transcript: bool = False
    auto_copy: bool = False
    keep_model: str = DEFAULT_KEEP_MODE
    keep_minutes: int = DEFAULT_KEEP_MINUTES


def normalize_keep_mode(value: object) -> str:
    return value if value in KEEP_MODES else DEFAULT_KEEP_MODE


def normalize_keep_minutes(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_KEEP_MINUTES
    return max(MIN_KEEP_MINUTES, min(MAX_KEEP_MINUTES, int(value)))


def keep_policy(prefs: Settings) -> tuple[str, float]:
    """(mode, idle seconds) for the controller; seconds only matter for the timed mode."""
    mode = normalize_keep_mode(prefs.keep_model)
    return mode, float(normalize_keep_minutes(prefs.keep_minutes) * 60) if mode == "timed" else 0.0


def normalize_model(value: str | None) -> str:
    if value in KNOWN_MODELS:
        return value
    return DEFAULT_MODEL


def get_model_spec(model_id: str | None) -> ModelSpec:
    return KNOWN_MODELS[normalize_model(model_id)]


def data_dir() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share").expanduser() / "voicelens"


def missing_model_files(path: Path) -> list[str]:
    """Check local files, including broken cache symlinks; never load weights."""
    def present(name):
        try:
            file = path / name
            return file.is_file() and file.stat().st_size > 0 and os.access(file, os.R_OK)
        except OSError:
            return False
    missing = [name for name in REQUIRED_MODEL_FILES if not present(name)]
    if not any(present(name) for name in ("vocabulary.json", "vocabulary.txt")):
        missing.append("vocabulary.json / vocabulary.txt")
    return missing


def cache_dir() -> Path:
    explicit = os.environ.get("HF_HUB_CACHE") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home).expanduser() / "hub"
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache").expanduser()
    return base / "huggingface/hub"


def _cached_candidates(model_id: str) -> list[Path]:
    hub = cache_dir() / f"models--Systran--faster-whisper-{model_id}"
    snapshots = hub / "snapshots"
    candidates: list[Path] = []
    try:
        digest = (hub / "refs/main").read_text(encoding="utf-8").strip()
        # A cache ref is a snapshot name, never an arbitrary path.
        if digest and all(c in "0123456789abcdefABCDEF" for c in digest):
            candidates.append(snapshots / digest)
    except (OSError, UnicodeError):
        pass
    try:
        candidates.extend(sorted(path for path in snapshots.iterdir() if path.is_dir()))
    except OSError:
        pass
    return list(dict.fromkeys(candidates))


def find_cached_model(model_id: str) -> Path | None:
    """Return a local Hugging Face snapshot for Systran/faster-whisper-<id>, if present."""
    if model_id not in KNOWN_MODELS:
        return None
    return next((p for p in _cached_candidates(model_id) if not missing_model_files(p)), None)


def model_candidates(model_id: str) -> list[Path]:
    """An explicit folder belongs to the named size (or Small for legacy configs)."""
    candidates = []
    env = os.environ.get("VOICELENS_MODEL_PATH")
    if env:
        path = Path(env).expanduser()
        inferred = next((spec.id for spec in WHISPER_MODELS
                         if path.name in (spec.id, f"faster-whisper-{spec.id}")
                         or f"models--Systran--faster-whisper-{spec.id}" in path.parts), DEFAULT_MODEL)
        assigned = os.environ.get("VOICELENS_MODEL_ID") or inferred
        if model_id == assigned:
            candidates.append(path)
    candidates.append(data_dir() / "models" / model_id)
    candidates.extend(_cached_candidates(model_id))
    return list(dict.fromkeys(candidates))


def resolve_model_path(model_id: str | None) -> Path | None:
    """Locate an already-installed model directory. Never downloads."""
    requested = normalize_model(model_id)
    return next((p for p in model_candidates(requested) if not missing_model_files(p)), None)


def discover_models() -> list[dict]:
    catalog = []
    for spec in WHISPER_MODELS:
        path = resolve_model_path(spec.id)
        incomplete = []
        for candidate in model_candidates(spec.id):
            if candidate.is_dir() and (missing := missing_model_files(candidate)):
                incomplete.append({"path": str(candidate), "missing": missing})
        catalog.append({"id": spec.id, "available": path is not None,
                        "path": str(path) if path is not None else None,
                        "incomplete": incomplete,
                        "source": f"https://huggingface.co/Systran/faster-whisper-{spec.id}"})
    return catalog


def initial_model() -> str:
    for model_id in (DEFAULT_MODEL, "base", "tiny", "medium", "large-v2", "large-v3"):
        if is_model_available(model_id):
            return model_id
    return DEFAULT_MODEL


def is_model_available(model_id: str | None) -> bool:
    return resolve_model_path(model_id) is not None


def config_dir() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "voicelens"


def settings_path() -> Path:
    return config_dir() / "settings.json"


def load_settings() -> Settings:
    path = settings_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return Settings(model=initial_model())
    if not isinstance(payload, dict):
        return Settings(model=initial_model())

    def flag(key: str, default: bool) -> bool:
        value = payload.get(key)
        return value if isinstance(value, bool) else default

    return Settings(
        language=normalize_language(payload.get("language") if isinstance(payload.get("language"), str) else None),
        model=payload["model"] if isinstance(payload.get("model"), str) and payload["model"] in KNOWN_MODELS else initial_model(),
        push_to_talk=flag("push_to_talk", True),
        append_transcript=flag("append_transcript", False),
        auto_copy=flag("auto_copy", False),
        keep_model=normalize_keep_mode(payload.get("keep_model")),
        keep_minutes=normalize_keep_minutes(payload.get("keep_minutes")),
    )


def save_settings(prefs: Settings) -> None:
    directory = config_dir()
    path = settings_path()
    payload = json.dumps(
        {
            "language": prefs.language,
            "model": prefs.model,
            "push_to_talk": bool(prefs.push_to_talk),
            "append_transcript": bool(prefs.append_transcript),
            "auto_copy": bool(prefs.auto_copy),
            "keep_model": normalize_keep_mode(prefs.keep_model),
            "keep_minutes": normalize_keep_minutes(prefs.keep_minutes),
        },
        indent=2,
    ) + "\n"
    tmp = path.with_suffix(".json.tmp")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
