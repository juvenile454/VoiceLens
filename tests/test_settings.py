"""Settings and model discovery with temporary file doubles; no models or downloads."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from voicelens.i18n import DEFAULT_LANGUAGE, STRINGS, set_language, t
from voicelens.settings import (
    DEFAULT_MODEL,
    WHISPER_MODELS,
    Settings,
    get_model_spec,
    is_model_available,
    load_settings,
    normalize_model,
    resolve_model_path,
    save_settings,
    CACHE_ENV_KEYS,
    cache_dir,
    discover_models,
)


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self._old_xdg = os.environ.get("XDG_CONFIG_HOME")
        os.environ["XDG_CONFIG_HOME"] = self.tempdir.name
        self.environment = mock.patch.dict(os.environ, {key: "" for key in (
            *CACHE_ENV_KEYS, "VOICELENS_MODEL_PATH", "VOICELENS_MODEL_ID")})
        self.environment.start()
        self.home = mock.patch('pathlib.Path.home', return_value=Path(self.tempdir.name))
        self.home.start()
        set_language("en")

    def tearDown(self) -> None:
        set_language("en")
        if self._old_xdg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = self._old_xdg
        self.tempdir.cleanup()
        self.home.stop()
        self.environment.stop()

    def model_folder(self, model='small', *, complete=True):
        path = cache_dir() / f'models--Systran--faster-whisper-{model}/snapshots/abcdef'
        path.mkdir(parents=True)
        for name in (('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt') if complete else ('model.bin',)):
            (path / name).write_text('test double')
        return path

    def test_english_and_german_keys_match(self) -> None:
        self.assertEqual(set(STRINGS["en"]), set(STRINGS["de"]))

    def test_defaults_are_english_and_small(self) -> None:
        prefs = load_settings()
        self.assertEqual(prefs.language, DEFAULT_LANGUAGE)
        self.assertEqual(prefs.language, "en")
        self.assertEqual(prefs.model, DEFAULT_MODEL)
        self.assertEqual(prefs.model, "small")
        self.assertTrue(prefs.push_to_talk)
        self.assertFalse(prefs.append_transcript)
        self.assertFalse(prefs.auto_copy)

    def test_invalid_values_fall_back(self) -> None:
        self.assertEqual(normalize_model("nope"), "small")
        self.assertEqual(get_model_spec("medium").id, "medium")

    def test_roundtrip_persistence(self) -> None:
        save_settings(Settings(language="de", model="base", push_to_talk=False))
        loaded = load_settings()
        self.assertEqual(loaded.language, "de")
        self.assertEqual(loaded.model, "base")
        self.assertFalse(loaded.push_to_talk)
        self.assertFalse(loaded.append_transcript)
        self.assertFalse(loaded.auto_copy)
        save_settings(Settings(append_transcript=True, auto_copy=True))
        loaded = load_settings()
        self.assertTrue(loaded.append_transcript)
        self.assertTrue(loaded.auto_copy)

    def test_legacy_payload_without_behaviour_flags_uses_defaults(self) -> None:
        from voicelens.settings import settings_path
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"language": "de", "model": "small", "push_to_talk": true, "append_transcript": "yes"}')
        loaded = load_settings()
        self.assertEqual(loaded.language, "de")
        self.assertFalse(loaded.append_transcript)
        self.assertFalse(loaded.auto_copy)

    def test_keep_model_policy_roundtrip_and_normalization(self) -> None:
        from voicelens.settings import keep_policy, normalize_keep_minutes, normalize_keep_mode, settings_path
        prefs = load_settings()
        self.assertEqual(prefs.keep_model, "release")
        self.assertEqual(prefs.keep_minutes, 10)
        self.assertEqual(keep_policy(prefs), ("release", 0.0))
        save_settings(Settings(keep_model="timed", keep_minutes=25))
        loaded = load_settings()
        self.assertEqual((loaded.keep_model, loaded.keep_minutes), ("timed", 25))
        self.assertEqual(keep_policy(loaded), ("timed", 1500.0))
        save_settings(Settings(keep_model="always", keep_minutes=99999))
        loaded = load_settings()
        self.assertEqual((loaded.keep_model, loaded.keep_minutes), ("always", 720))
        self.assertEqual(keep_policy(loaded), ("always", 0.0))
        path = settings_path()
        path.write_text('{"model": "small", "keep_model": "forever", "keep_minutes": "5"}')
        loaded = load_settings()
        self.assertEqual((loaded.keep_model, loaded.keep_minutes), ("release", 10))
        self.assertEqual(normalize_keep_mode(None), "release")
        self.assertEqual(normalize_keep_minutes(0), 1)
        self.assertEqual(normalize_keep_minutes(True), 10)
        self.assertEqual(normalize_keep_minutes(2.9), 2)

    def test_catalog_includes_classic_sizes_and_ram(self) -> None:
        ids = [spec.id for spec in WHISPER_MODELS]
        self.assertEqual(ids, ["tiny", "base", "small", "medium", "large-v2", "large-v3"])
        ram = {spec.id: spec.ram for spec in WHISPER_MODELS}
        self.assertEqual(ram["tiny"], "1 GB")
        self.assertEqual(ram["base"], "1 GB")
        self.assertEqual(ram["small"], "2 GB")
        self.assertEqual(ram["medium"], "5 GB")
        self.assertEqual(ram["large-v2"], "10 GB")
        self.assertEqual(ram["large-v3"], "10 GB")

    def test_english_ram_caption(self) -> None:
        set_language("en")
        self.assertEqual(t("ram_caption", ram="2 GB"), "Est. RAM ~2 GB")
        set_language("de")
        self.assertEqual(t("ram_caption", ram="2 GB"), "ca. 2 GB RAM")

    def test_small_model_detected_when_cache_present(self) -> None:
        expected = self.model_folder()
        path = resolve_model_path("small")
        self.assertEqual(path, expected)
        self.assertTrue((Path(path) / "model.bin").is_file())
        self.assertTrue(is_model_available("small"))

    def test_missing_model_is_not_invented(self) -> None:
        self.assertIsNone(resolve_model_path("tiny"))
        self.assertFalse(is_model_available("tiny"))

    def test_first_run_selects_available_model_but_preserves_saved_choice(self):
        self.model_folder('tiny')
        self.assertEqual(load_settings().model, 'tiny')
        save_settings(Settings(model='medium'))
        self.assertEqual(load_settings().model, 'medium')

    def test_small_preferred_and_corrupt_settings_recover(self):
        self.model_folder('base')
        self.model_folder('small')
        self.assertEqual(load_settings().model, 'small')
        from voicelens.settings import settings_path
        settings_path().parent.mkdir(parents=True, exist_ok=True)
        settings_path().write_text('{')
        self.assertEqual(load_settings().model, 'small')

    def test_custom_cache_and_snapshot_without_main_ref(self):
        for key, suffix in (('HF_HUB_CACHE', ''), ('HUGGINGFACE_HUB_CACHE', ''),
                            ('HF_HOME', 'hub'), ('XDG_CACHE_HOME', 'huggingface/hub')):
            with self.subTest(key=key), mock.patch.dict(os.environ, {key: self.tempdir.name + '/' + key}):
                self.assertEqual(cache_dir(), Path(self.tempdir.name) / key / suffix)
                path = self.model_folder('base')
                self.assertEqual(resolve_model_path('base'), path)

    def test_incomplete_snapshot_does_not_hide_complete_one(self):
        incomplete = self.model_folder(complete=False)
        complete = incomplete.parent / '123456'
        complete.mkdir()
        for name in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.json'):
            (complete / name).write_text('test double')
        ref = incomplete.parent.parent / 'refs/main'
        ref.parent.mkdir()
        ref.write_text(incomplete.name)
        self.assertEqual(resolve_model_path('small'), complete)
        record = next(m for m in discover_models() if m['id'] == 'small')
        self.assertEqual(record['incomplete'][0]['path'], str(incomplete))
        self.assertIn('tokenizer.json', record['incomplete'][0]['missing'])

    def test_missing_tokenizer_and_broken_symlink_are_unavailable(self):
        path = self.model_folder()
        (path / 'tokenizer.json').unlink()
        (path / 'tokenizer.json').symlink_to(path / 'missing-blob')
        self.assertFalse(is_model_available('small'))

    def test_explicit_model_is_not_mislabeled_as_small(self):
        path = self.model_folder('tiny')
        with mock.patch.dict(os.environ, {'VOICELENS_MODEL_PATH': str(path)}):
            self.assertEqual(resolve_model_path('tiny'), path)
            self.assertIsNone(resolve_model_path('small'))
        renamed = Path(self.tempdir.name) / 'my-model'
        path.rename(renamed)
        with mock.patch.dict(os.environ, {'VOICELENS_MODEL_PATH': str(renamed), 'VOICELENS_MODEL_ID': 'tiny'}):
            self.assertEqual(resolve_model_path('tiny'), renamed)
            self.assertIsNone(resolve_model_path('small'))

    def test_managed_directory_overrides_cached_model(self):
        cached = self.model_folder('small')
        managed = Path(self.tempdir.name) / '.local/share/voicelens/models/small'
        managed.parent.mkdir(parents=True)
        managed.symlink_to(cached, target_is_directory=True)
        self.assertEqual(resolve_model_path('small'), managed)


if __name__ == "__main__":
    unittest.main()
