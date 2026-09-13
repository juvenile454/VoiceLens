"""Offline setup/installer tests with temporary files and subprocess/API doubles."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import install
from voicelens import backend, diagnostics
from voicelens.i18n import set_language
from voicelens.settings import Settings


class SetupTests(unittest.TestCase):
    def setUp(self):
        set_language('en')
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.environment = mock.patch.dict(os.environ, {
            'XDG_DATA_HOME': str(self.root / 'data'), 'XDG_CONFIG_HOME': str(self.root / 'config'),
            'XDG_CURRENT_DESKTOP': '',
        })
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def test_report_collects_all_failures_without_recording(self):
        models = [dict(id='small', available=False, path=None, incomplete=[], source='https://example.invalid')]
        with mock.patch.object(backend, 'check_capture_dependencies'), mock.patch.object(
            backend, 'check_runtime', side_effect=backend.AppError('Runtime missing')
        ), mock.patch.object(backend, 'list_microphones', return_value=[]), mock.patch.object(
            diagnostics, 'discover_models', return_value=models
        ), mock.patch.object(
            diagnostics, 'load_settings', return_value=Settings()
        ), mock.patch.object(backend, 'Recorder') as recorder:
            report = diagnostics.inspect_setup()
        self.assertFalse(report['ready'])
        failures = {c['id'] for c in report['checks'] if not c['ok']}
        self.assertTrue({'runtime', 'microphones', 'model'} <= failures)
        self.assertIn('README.md', diagnostics.format_report(report))
        recorder.assert_not_called()

    def test_desktop_check_reports_missing_or_invalid_assets(self):
        try:
            import gi
            gi.require_version('Gtk', '3.0')
        except (ImportError, ValueError):
            self.skipTest('GTK is not installed')
        assets = self.root / 'assets'
        assets.mkdir()
        original = diagnostics.ROOT / 'assets'
        for name in ('voicelens.svg', 'ui.css'):
            for content in (None, 'invalid asset contents'):
                with self.subTest(name=name, content=content):
                    for source in ('voicelens.svg', 'ui.css'):
                        shutil.copyfile(original / source, assets / source)
                    target = assets / name
                    if content is None:
                        target.unlink()
                    else:
                        target.write_text(content)
                    with mock.patch.object(diagnostics, 'ROOT', self.root):
                        with self.assertRaises(backend.AppError) as error:
                            diagnostics.check_desktop()
                    self.assertIn(str(target), str(error.exception))

    def test_desktop_check_detects_missing_svg_loader_without_a_display(self):
        try:
            import gi
            gi.require_version('Gtk', '3.0')
        except (ImportError, ValueError):
            self.skipTest('GTK is not installed')
        # A fresh process is necessary: GdkPixbuf caches the loader inventory.
        loaders = self.root / 'empty-loaders.cache'
        loaders.write_text('')
        env = dict(os.environ, GDK_PIXBUF_MODULE_FILE=str(loaders), DISPLAY='', WAYLAND_DISPLAY='')
        result = subprocess.run(
            [sys.executable, '-c', 'from voicelens.diagnostics import check_desktop; check_desktop()'],
            cwd=diagnostics.ROOT, env=env, capture_output=True, text=True, timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('librsvg2-common', result.stderr)

    def test_report_fails_if_desktop_assets_cannot_load(self):
        models = [dict(id='small', available=True, path='/test/model', incomplete=[], source='')]
        with mock.patch.object(diagnostics, 'check_desktop', side_effect=backend.AppError('Broken icon')), mock.patch.object(
            backend, 'check_capture_dependencies'
        ), mock.patch.object(backend, 'check_runtime'), mock.patch.object(
            backend, 'list_microphones', return_value=[dict(name='test', muted=False)]
        ), mock.patch.object(diagnostics, 'discover_models', return_value=models), mock.patch.object(
            diagnostics, 'load_settings', return_value=Settings()
        ):
            report = diagnostics.inspect_setup()
        self.assertFalse(report['ready'])
        self.assertEqual([c['id'] for c in report['checks'] if not c['ok']], ['gtk'])

    def test_check_only_writes_nothing_even_when_setup_incomplete(self):
        report = {'ready': False, 'microphones': [], 'models': [], 'checks': []}
        with mock.patch.object(install, 'inspect_setup', return_value=report), mock.patch.object(
            install, '_desktop_dir'
        ) as desktop, contextlib.redirect_stdout(io.StringIO()) as output:
            code = install.main(['--check', '--json'])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(output.getvalue())['ready'])
        self.assertEqual(list(self.root.iterdir()), [])
        desktop.assert_not_called()

    def test_launcher_install_without_desktop_or_optional_utilities(self):
        report = {'ready': False, 'selected_model': 'small', 'models': [], 'checks': []}
        with mock.patch.object(install, 'inspect_setup', return_value=report), mock.patch.object(
            install, '_desktop_dir', return_value=None
        ), mock.patch.object(install.shutil, 'which', return_value=None), mock.patch.object(
            install, '_optional_command'
        ) as optional, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(install.main(['--json']), 0)
            self.assertEqual(install.main(['--json']), 0)  # idempotent
        launcher = self.root / 'data/applications/org.voicelens.VoiceLens.desktop'
        self.assertTrue(launcher.is_file())
        self.assertEqual(len(json.loads(output.getvalue().splitlines()[0])['launchers']), 1)
        self.assertFalse((self.root / 'config').exists())
        optional.assert_not_called()

    def test_desktop_disabled_missing_or_unconfigured(self):
        with mock.patch.object(install.subprocess, 'check_output', return_value=str(Path.home())):
            self.assertIsNone(install._desktop_dir())
        with mock.patch.object(install.subprocess, 'check_output', return_value=''):
            self.assertIsNone(install._desktop_dir())
        with mock.patch.object(install.subprocess, 'check_output', side_effect=FileNotFoundError):
            self.assertIsNone(install._desktop_dir())

    def test_existing_live_launcher_is_preserved(self):
        report = {'ready': False, 'selected_model': 'small', 'models': [], 'checks': []}
        launcher = self.root / 'data/applications/org.voicelens.VoiceLens.desktop'
        launcher.parent.mkdir(parents=True)
        original = 'Exec=/usr/bin/python3\n'
        launcher.write_text(original)
        for language, expected in (('en', 'will not be overwritten'), ('de', 'wird nicht überschrieben')):
            with self.subTest(language=language), mock.patch.object(install, 'inspect_setup', return_value=report), mock.patch.object(
                install, '_desktop_dir', return_value=None
            ), self.assertRaises(SystemExit) as error:
                install.main(['--json', '--language', language])
            self.assertIn(expected, str(error.exception))
            self.assertIn(str(launcher), str(error.exception))
            self.assertEqual(launcher.read_text(), original)
        set_language('en')

    def test_launcher_quoting_roundtrips_spaces_and_reserved_characters(self):
        program = self.root / 'Voice Lens $test `literal` 100% "quote" back\\slash'
        program.write_text('test double')
        content = 'Exec=' + install._quoted_exec(str(program)) + '\n'
        self.assertEqual(install._desktop_exec_path(content), program)
        launcher = self.root / 'test.desktop'
        launcher.write_text(content)
        self.assertFalse(install._is_stale_launcher(launcher, 'changed'))

    def test_optional_command_timeout_is_a_warning(self):
        warnings = []
        with mock.patch.object(install.subprocess, 'run', side_effect=subprocess.TimeoutExpired('gio', 10)):
            self.assertFalse(install._optional_command(['gio'], warnings))
        self.assertTrue(warnings)

    def test_runtime_selection_uses_portable_paths_and_explicit_override(self):
        with mock.patch.dict(os.environ, {'VOICELENS_STT_PYTHON': ''}), mock.patch.object(
            backend, '_PROJECT', self.root
        ):
            runtime = self.root / '.venv/bin/python3'
            runtime.parent.mkdir(parents=True)
            runtime.write_text('double')
            runtime.chmod(0o755)
            self.assertEqual(backend._stt_python(), str(runtime))
            self.assertEqual(backend.stt_python_candidates(), [
                str(runtime), str(backend.data_dir() / 'venv/bin/python3'), backend.SYSTEM_PYTHON,
            ])
        with mock.patch.dict(os.environ, {'VOICELENS_STT_PYTHON': 'relative/python'}):
            with self.assertRaises(backend.AppError):
                backend._stt_python()

    def test_worker_environment_keeps_cache_locations_but_drops_secrets(self):
        with mock.patch.dict(os.environ, {'HF_HUB_CACHE': '/test/cache', 'XDG_DATA_HOME': '/test/data',
                                         'VOICELENS_MODEL_PATH': '/test/model', 'VOICELENS_MODEL_ID': 'tiny',
                                         'HF_TOKEN': 'test-double-secret', 'PYTHONPATH': '/test/injected'}):
            env = backend._sanitized_worker_environment()
        self.assertEqual(env['HF_HUB_CACHE'], '/test/cache')
        self.assertEqual(env['XDG_DATA_HOME'], '/test/data')
        self.assertEqual(env['VOICELENS_MODEL_ID'], 'tiny')
        self.assertEqual(env['HF_HUB_OFFLINE'], '1')
        self.assertNotIn('HF_TOKEN', env)
        self.assertNotIn('PYTHONPATH', env)
