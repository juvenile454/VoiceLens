"""Read-only installation checks. No recording, model loading or downloads."""
from __future__ import annotations

from pathlib import Path

from . import backend
from .i18n import t
from .settings import cache_dir, data_dir, discover_models, load_settings

ROOT = Path(__file__).resolve().parent.parent


def check_desktop() -> str:
    """Check GTK and bundled assets without opening a display or microphone."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib, Gtk
        import cairo  # noqa: F401
    except (ImportError, ValueError):
        raise backend.AppError(t("dependency_missing", package="python3-gi, python3-cairo, gir1.2-gtk-3.0"))

    if not any(fmt.get_name() == "svg" and not fmt.is_disabled() for fmt in GdkPixbuf.Pixbuf.get_formats()):
        raise backend.AppError(t("dependency_missing", package="librsvg2-common (SVG)"))
    icon = ROOT / "assets/voicelens.svg"
    stylesheet = ROOT / "assets/ui.css"
    for path, load in (
        (icon, lambda: GdkPixbuf.Pixbuf.new_from_file_at_size(str(icon), 64, 64)),
        (stylesheet, lambda: Gtk.CssProvider().load_from_path(str(stylesheet))),
    ):
        try:
            load()
        except GLib.Error as error:
            raise backend.AppError(t("asset_unreadable", path=path, detail=error.message)) from error
    return "GTK 3 / Cairo / SVG / CSS"


def inspect_setup() -> dict:
    checks = []

    def check(name, action):
        try:
            detail = action()
            checks.append({"id": name, "ok": True, "detail": detail})
        except Exception as error:
            checks.append({"id": name, "ok": False, "detail": str(error)})

    check("gtk", check_desktop)
    check("capture", backend.check_capture_dependencies)
    check("runtime", backend.check_runtime)
    microphones = []

    def inputs():
        microphones.extend(backend.list_microphones())
        if not microphones:
            raise backend.AppError(t("status_no_mic"))
        if all(mic["muted"] for mic in microphones):
            raise backend.AppError(t("mic_muted"))
        return len(microphones)

    check("microphones", inputs)
    models = discover_models()
    prefs = load_settings()
    selected = next(model for model in models if model["id"] == prefs.model)
    checks.append({"id": "model", "ok": selected["available"],
                   "detail": prefs.model if selected["available"] else t("model_not_local")})
    return {"ready": all(item["ok"] for item in checks), "checks": checks,
            "microphones": microphones, "models": models, "selected_model": prefs.model,
            "model_directory": str(data_dir() / "models"), "cache_directory": str(cache_dir())}


def format_report(report: dict) -> str:
    lines = [t("setup_title")]
    for item in report["checks"]:
        detail = item["detail"]
        if isinstance(detail, dict):
            detail = " · ".join(str(value) for value in detail.values() if value)
        lines.append(f"{'OK' if item['ok'] else '!'}  {t('check_' + item['id'])}: {detail or 'OK'}")
    for mic in report["microphones"]:
        suffix = t("muted_suffix") if mic["muted"] else ""
        lines.append(f"   {'*' if mic['default'] else '-'} {mic['description']}{suffix}")
    for model in report["models"]:
        lines.append(f"   {model['id']}: {t('installed') if model['available'] else t('not_installed')}")
        if model["path"]:
            lines.append(f"      {model['path']}")
        for incomplete in model["incomplete"]:
            lines.append(f"      {incomplete['path']}: {t('missing_files')} {', '.join(incomplete['missing'])}")
        if not model["available"]:
            lines.append(f"      {model['source']}")
    lines.append(t("setup_ready") if report["ready"] else t("setup_help"))
    return "\n".join(lines)
