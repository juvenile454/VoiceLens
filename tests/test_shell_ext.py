"""User-level GNOME helper files; does not enable the session extension."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from voicelens.shell_ext import FILES, UUID, dest_dir, ensure, install_files, source_dir


class ShellExtTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self._old = os.environ.get("XDG_DATA_HOME")
        os.environ["XDG_DATA_HOME"] = self.tempdir.name

    def tearDown(self):
        if self._old is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = self._old
        self.tempdir.cleanup()

    def test_source_files_exist_and_metadata_targets_gnome_46(self):
        src = source_dir()
        for name in FILES:
            self.assertTrue((src / name).is_file(), name)
        meta = json.loads((src / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["uuid"], UUID)
        self.assertIn("46", meta["shell-version"])
        script = (src / "extension.js").read_text(encoding="utf-8")
        self.assertIn("ptt-down", script)
        self.assertIn("Control_L", script)
        self.assertIn("EVENT_PROPAGATE", script)
        self.assertIn("get_pointer", script)
        self.assertIn("CONTROL_MASK", script)
        self.assertIn("HideStatus", script)
        self.assertIn("SetLevel", script)
        self.assertIn("_hudPersist", script)
        self.assertIn("_enterTranscribing", script)
        self.assertIn("transcribing", script)
        self.assertIn("_tickOrb", script)
        self.assertIn("_paintOrb", script)
        self.assertIn("St.DrawingArea", script)
        self.assertIn("queue_repaint", script)
        self.assertIn("FRAME_MS", script)
        self.assertIn("FinishSessionAsync", script)
        self.assertIn("cursor-location-changed", script)
        self.assertIn("voicelens-orb-core", script)
        self.assertIn("style_class", script)
        self.assertNotIn("new Clutter.Canvas", script)
        self.assertNotIn("osd-window", script)
        self.assertNotIn("osdWindowManager", script)
        css = (src / "stylesheet.css").read_text(encoding="utf-8")
        self.assertIn("voicelens-orb-core", css)
        self.assertIn("228px", css)

    def test_install_files_copies_into_xdg_data_home(self):
        self.assertTrue(install_files())
        dest = dest_dir()
        self.assertEqual(dest, Path(self.tempdir.name) / "gnome-shell" / "extensions" / UUID)
        self.assertTrue((dest / "extension.js").is_file())
        copied = json.loads((dest / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(copied["uuid"], UUID)

    def test_desktop_and_helper_share_the_application_identity(self):
        from gi.repository import Gio
        from voicelens.inject import HELPER_IFACE, HELPER_NAME, HELPER_PATH, OWN_APP_NAMES
        from voicelens.ui import APP_ID

        source = source_dir()
        script = (source / "extension.js").read_text(encoding="utf-8")
        constants = dict(re.findall(r"const (APP_NAME|APP_PATH|HELPER_NAME|HELPER_PATH) = '([^']+)';", script))
        self.assertEqual(constants["APP_NAME"], APP_ID)
        self.assertEqual(constants["APP_PATH"], '/' + APP_ID.replace('.', '/'))
        self.assertEqual(constants["HELPER_NAME"], HELPER_NAME)
        self.assertEqual(constants["HELPER_PATH"], HELPER_PATH)
        self.assertIn(APP_ID, OWN_APP_NAMES)
        xml = re.search(r'const IFACE = `([^`]+)`;', script).group(1)
        interface = Gio.DBusNodeInfo.new_for_xml(xml).interfaces[0]
        self.assertEqual(interface.name, HELPER_IFACE)
        self.assertIn('PasteWithOptions', [method.name for method in interface.methods])
        template = source.parent / 'assets' / (APP_ID + '.desktop.in')
        self.assertIn('StartupWMClass=' + APP_ID, template.read_text())

    def test_install_files_false_when_source_missing(self):
        with mock.patch("voicelens.shell_ext.source_dir", return_value=Path(self.tempdir.name) / "missing"):
            self.assertFalse(install_files())

    def test_ensure_reloads_when_installed_files_change(self):
        dest = dest_dir()
        dest.mkdir(parents=True)
        (dest / "extension.js").write_text("old-helper", encoding="utf-8")
        (dest / "metadata.json").write_text("{}", encoding="utf-8")
        with mock.patch("voicelens.shell_ext.is_enabled", return_value=True), mock.patch(
            "voicelens.shell_ext.enable", return_value=True
        ), mock.patch("voicelens.shell_ext.reload", return_value=True) as reload_helper:
            result = ensure()
        self.assertTrue(result["installed"])
        self.assertTrue(result["reloaded"])
        reload_helper.assert_called_once()
        self.assertIn("_hudPersist", (dest / "extension.js").read_text(encoding="utf-8"))

    def test_ensure_skips_reload_when_files_already_current(self):
        self.assertTrue(install_files())
        with mock.patch("voicelens.shell_ext.is_enabled", return_value=True), mock.patch(
            "voicelens.shell_ext.enable", return_value=True
        ), mock.patch("voicelens.shell_ext.reload") as reload_helper:
            result = ensure()
        self.assertTrue(result["installed"])
        self.assertFalse(result["reloaded"])
        reload_helper.assert_not_called()


if __name__ == "__main__":
    unittest.main()
