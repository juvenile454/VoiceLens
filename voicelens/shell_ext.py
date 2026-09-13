"""Install the user GNOME Shell helper for Control hold-to-talk (no system service)."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

UUID = "voicelens-ptt@org.voicelens.VoiceLens"
FILES = ("metadata.json", "extension.js", "lens.js", "stylesheet.css")


def source_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "gnome-shell-extension"


def dest_dir() -> Path:
    data = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
    return data / "gnome-shell" / "extensions" / UUID


def install_files() -> bool:
    src = source_dir()
    dest = dest_dir()
    if not all((src / name).is_file() for name in FILES):
        return False
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        dest.joinpath(name).write_text(src.joinpath(name).read_text(encoding="utf-8"), encoding="utf-8")
    return True


def _files_match_source() -> bool:
    src = source_dir()
    dest = dest_dir()
    try:
        return all(
            src.joinpath(name).read_text(encoding="utf-8") == dest.joinpath(name).read_text(encoding="utf-8")
            for name in FILES
        )
    except OSError:
        return False


def reload() -> bool:
    """Load copied helper code into the running GNOME session."""
    try:
        subprocess.run(
            ["gnome-extensions", "disable", UUID],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
        result = subprocess.run(
            ["gnome-extensions", "enable", UUID],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return is_enabled()
    return bool(result.returncode == 0) or is_enabled()


def is_enabled() -> bool:
    try:
        result = subprocess.run(
            ["gnome-extensions", "list", "--enabled"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return UUID in (result.stdout or "")


def _persist_enabled() -> bool:
    """Remember the helper for the next GNOME session (user settings only)."""
    try:
        from gi.repository import Gio

        settings = Gio.Settings.new("org.gnome.shell")
        current = list(settings.get_strv("enabled-extensions"))
        if UUID not in current:
            settings.set_strv("enabled-extensions", current + [UUID])
        return UUID in settings.get_strv("enabled-extensions")
    except Exception:
        return False


def enable() -> bool:
    if is_enabled():
        return True
    persisted = _persist_enabled()
    try:
        result = subprocess.run(
            ["gnome-extensions", "enable", UUID],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        result = None
    live = bool(result and result.returncode == 0) or is_enabled()
    return live or persisted


def ensure() -> dict[str, object]:
    unchanged = _files_match_source()
    was_enabled = is_enabled()
    installed = install_files()
    enabled = enable() if installed else False
    reloaded = False
    if installed and was_enabled and not unchanged:
        reloaded = reload()
        enabled = is_enabled() or enabled
    return {"uuid": UUID, "installed": installed, "enabled": enabled, "reloaded": reloaded}
