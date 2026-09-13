#!/usr/bin/python3
"""Install only user launchers for this local project; no packages or services."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil

from voicelens.diagnostics import format_report, inspect_setup
from voicelens.i18n import set_language, t
from voicelens.settings import load_settings, save_settings


def _quoted_exec(command: str) -> str:
    if any(char in command for char in ('\n', '\r', '\0')):
        raise ValueError('Unsupported control character in launcher path')
    quoted = '"' + ''.join('\\' + char if char in '\\"`$' else char for char in command) + '"'
    # Exec argument escaping, then desktop-entry string escaping; %% is literal.
    return quoted.replace('\\', '\\\\').replace('%', '%%')


def _desktop_exec_path(content: str) -> Path | None:
    for line in content.splitlines():
        if not line.startswith('Exec='):
            continue
        raw = line[5:].strip()
        decoded = []
        index = 0
        escapes = {'\\': '\\', 's': ' ', 'n': '\n', 'r': '\r', 't': '\t'}
        while index < len(raw):
            if raw[index] == '\\' and index + 1 < len(raw) and raw[index + 1] in escapes:
                decoded.append(escapes[raw[index + 1]])
                index += 2
            else:
                decoded.append(raw[index])
                index += 1
        raw = ''.join(decoded)
        if raw.startswith('"'):
            chars = []
            index = 1
            while index < len(raw):
                char = raw[index]
                if char == '\\' and index + 1 < len(raw):
                    chars.append(raw[index + 1])
                    index += 2
                    continue
                if char == '"':
                    break
                chars.append(char)
                index += 1
            command = ''.join(chars)
        else:
            command = raw.split(' ', 1)[0]
        return Path(command.replace('%%', '%')) if command else None
    return None


def _is_stale_launcher(destination: Path, content: str) -> bool:
    if not destination.exists():
        return False
    existing = destination.read_text()
    if existing == content:
        return False
    exec_path = _desktop_exec_path(existing)
    return exec_path is None or not exec_path.exists()


def _optional_command(command, warnings):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        if result.returncode:
            warnings.append(f'{command[0]}: {result.stderr.strip()}')
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as error:
        warnings.append(f'{command[0]}: {error}')
        return False


def _desktop_dir():
    try:
        value = subprocess.check_output(['xdg-user-dir', 'DESKTOP'], text=True, timeout=5).strip()
    except (OSError, subprocess.SubprocessError):
        return None
    path = Path(value)
    # XDG disables the desktop directory by pointing it at HOME.
    if not value or not path.is_absolute() or path == Path.home() or not path.is_dir():
        return None
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=t('install_description'))
    parser.add_argument('--check', action='store_true', help=t('cli_check'))
    parser.add_argument('--json', action='store_true', help='JSON output')
    parser.add_argument('--language', choices=('en', 'de'), default='en')
    args = parser.parse_args(argv)
    set_language(args.language)
    report = inspect_setup()
    if args.check:
        print(json.dumps(report, ensure_ascii=False) if args.json else format_report(report))
        return 0 if report['ready'] else 1

    project = Path(__file__).resolve().parent
    template = (project / 'assets/org.voicelens.VoiceLens.desktop.in').read_text()
    # Desktop-entry Exec follows its own quoting rules (not shell quoting).
    command = str(project / 'run.sh')
    quoted = _quoted_exec(command)
    content = template.replace('Exec=@PROJECT_DIR@/run.sh', 'Exec=' + quoted)
    content = content.replace('@PROJECT_DIR@', str(project))
    applications = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share')) / 'applications'
    desktop = _desktop_dir()
    destinations = [applications / 'org.voicelens.VoiceLens.desktop']
    if desktop is not None:
        destinations.append(desktop / 'VoiceLens.desktop')
    replaced_stale = []
    for destination in destinations:
        if destination.exists() and destination.read_text() != content:
            if not _is_stale_launcher(destination, content):
                raise SystemExit(t('launcher_conflict', path=destination))
            replaced_stale.append(str(destination))
    (project / 'run.sh').chmod(0o755)
    for destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content)
        destination.chmod(0o755 if destination.parent == desktop else 0o644)
    warnings = []
    for destination in destinations:
        if shutil.which('desktop-file-validate'):
            _optional_command(['desktop-file-validate', str(destination)], warnings)
    trusted = False
    if desktop is not None:
        trusted = _optional_command(['gio', 'set', str(destinations[1]), 'metadata::trusted', 'true'], warnings)
    if shutil.which('update-desktop-database'):
        _optional_command(['update-desktop-database', str(applications)], warnings)
    ptt_helper = {'installed': False, 'enabled': False}
    if 'gnome' in os.environ.get('XDG_CURRENT_DESKTOP', '').lower():
        from voicelens.shell_ext import ensure as ensure_ptt_extension
        try:
            ptt_helper = ensure_ptt_extension()
        except OSError as error:
            warnings.append(str(error))
    if any(model['id'] == report['selected_model'] and model['available'] for model in report['models']):
        save_settings(load_settings())
    result = {
        'launchers': [str(p) for p in destinations],
        'replaced_stale': replaced_stale,
        'desktop_trusted': trusted,
        'warnings': warnings,
        'push_to_talk_extension': ptt_helper,
        'setup': report,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(format_report(report))
        print(t('install_complete'))
        for destination in destinations:
            print(f'  {destination}')
        for warning in warnings:
            print(f'! {warning}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
