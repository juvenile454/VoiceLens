"""Real GJS/Cairo with explicit Shell, clock and D-Bus doubles; no desktop I/O."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import re


class OverlayTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('gjs'), 'GJS is not installed')
    def test_shell_lifecycle_geometry_and_native_cairo(self):
        root = Path(__file__).resolve().parent.parent
        source = (root / 'gnome-shell-extension/extension.js').read_text()
        source = re.sub(r'^import .*;\n', '', source, flags=re.MULTILINE)
        source = source.replace('export default class', 'class')
        harness = (root / 'tests/overlay_harness.js').read_text()
        lens = (root / 'gnome-shell-extension/lens.js').as_uri()
        harness = harness.replace('// LENS_IMPORT',
            f"import {{VIEW, ENTER_MS, RETURN_MS, FRAME_MS, placement, drawLens, labelOpacity}} from '{lens}';")
        harness = harness.replace('// INSERT_EXTENSION', source)
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'overlay-test.js'
            script.write_text(harness)
            result = subprocess.run(['gjs', '-m', str(script)], capture_output=True,
                                    text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('CRITICAL', result.stderr)
        self.assertIn('overlay checks passed', result.stdout)
