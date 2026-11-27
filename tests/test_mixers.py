"""Testes unitários para o backend de áudio e perfis do Mixers."""

from pathlib import Path
import tempfile
import unittest

from mixers.audio_backend import DemoAudioBackend, clamp_volume, format_app_name
from mixers.profiles import ProfileManager


class TestAudioHelpers(unittest.TestCase):
    def test_clamp_volume(self) -> None:
        self.assertEqual(clamp_volume(-0.5), 0.0)
        self.assertEqual(clamp_volume(0.42), 0.42)
        self.assertEqual(clamp_volume(1.8), 1.0)

    def test_format_app_name(self) -> None:
        self.assertEqual(format_app_name("chrome.exe"), "Chrome")
        self.assertEqual(format_app_name("Spotify.EXE"), "Spotify")
        self.assertEqual(format_app_name("discord"), "Discord")


class TestDemoBackendAndProfiles(unittest.TestCase):
    def test_master_and_app_controls(self) -> None:
        backend = DemoAudioBackend()
        backend.set_master_volume(0.5)
        backend.set_master_mute(True)
        self.assertAlmostEqual(backend.get_master_volume(), 0.5)
        self.assertTrue(backend.get_master_mute())

        backend.set_app_volume("chrome.exe", 0.25)
        backend.set_app_mute("chrome.exe", True)
        sessions = {s.app_id: s for s in backend.list_app_sessions()}
        self.assertAlmostEqual(sessions["chrome.exe"].volume, 0.25)
        self.assertTrue(sessions["chrome.exe"].muted)

    def test_profile_save_apply_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profiles_file = Path(tmp) / "profiles.json"
            manager = ProfileManager(path=profiles_file)
            backend = DemoAudioBackend()

            backend.set_master_volume(0.6)
            backend.set_app_volume("spotify.exe", 0.2)
            backend.set_app_mute("discord.exe", True)
            manager.save_from_backend("Foco", backend)

            self.assertIn("Foco", manager.list_names())

            # Altera estado e reaplica perfil
            backend.set_master_volume(1.0)
            backend.set_app_volume("spotify.exe", 0.9)
            backend.set_app_mute("discord.exe", False)

            applied = manager.apply_to_backend("Foco", backend)
            self.assertTrue(applied)
            self.assertAlmostEqual(backend.get_master_volume(), 0.6)
            sessions = {s.app_id: s for s in backend.list_app_sessions()}
            self.assertAlmostEqual(sessions["spotify.exe"].volume, 0.2)
            self.assertTrue(sessions["discord.exe"].muted)

            self.assertTrue(manager.delete("Foco"))
            self.assertNotIn("Foco", manager.list_names())


if __name__ == "__main__":
    unittest.main()
