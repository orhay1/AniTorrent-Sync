"""Config loading: incomplete files get defaults instead of failing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from torrent_automator.config import load_config, load_config_with_report  # noqa: E402

# What an older GUI wrote when it started without a config.yaml
BROKEN = """anilist_username: someone
quality: ''
codec: ''
preferred_group: ''
release_groups:
- ASW
- Judas
recent_shows: []
recent_count: 5
"""


class ConfigTests(unittest.TestCase):
    def _write(self, text: str) -> str:
        fd, path = tempfile.mkstemp(suffix=".yaml")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_missing_keys_filled_and_existing_kept(self):
        cfg, added = load_config_with_report(self._write(BROKEN))
        self.assertIn("shows", added)
        self.assertIn("qbittorrent", added)
        self.assertEqual(cfg["shows"], [])
        self.assertEqual(cfg["qbittorrent"]["port"], 8080)
        # values the user had are untouched (empty quality stays "Any", not 1080p)
        self.assertEqual(cfg["quality"], "")
        self.assertEqual(cfg["anilist_username"], "someone")
        self.assertEqual(cfg["release_groups"], ["ASW", "Judas"])

    def test_partial_qbittorrent_section(self):
        cfg, added = load_config_with_report(self._write(
            "shows: []\nquality: 1080p\ncodec: ''\nqbittorrent:\n  host: nas\n  port: 9090\n"))
        self.assertEqual(cfg["qbittorrent"]["host"], "nas")
        self.assertEqual(cfg["qbittorrent"]["username"], "")
        self.assertIn("qbittorrent.username", added)

    def test_unicode_titles(self):
        cfg = load_config(self._write("shows:\n- Keroro Gunsou☆\nquality: 1080p\ncodec: ''\nqbittorrent: {}\n"))
        self.assertEqual(cfg["shows"], ["Keroro Gunsou☆"])

    def test_empty_file(self):
        cfg, added = load_config_with_report(self._write(""))
        self.assertEqual(cfg["shows"], [])
        self.assertIn("qbittorrent", added)

    def test_missing_file_still_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_config("definitely-not-here.yaml")


try:
    from PyQt6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class GuiFirstRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def _gui(self, load_side_effect):
        import gui
        gui.TorrentAutomatorGUI.AUTO_FETCH = False
        for p in (mock.patch.object(gui, "load_prefs", return_value={}),
                  mock.patch.object(gui, "save_prefs"),
                  mock.patch.object(gui, "load_config_with_report", side_effect=load_side_effect)):
            p.start()
            self.addCleanup(p.stop)
        w = gui.TorrentAutomatorGUI()
        self.addCleanup(lambda: (setattr(w, "config_dirty", False), w.close()))
        return w

    def test_first_run_saves_a_complete_config(self):
        w = self._gui(FileNotFoundError("nope"))
        self.assertTrue(w.config_dirty)                     # prompts to save
        with tempfile.TemporaryDirectory() as d:
            w.config_path = Path(d) / "config.yaml"
            w.user_edit.setText("someone")
            w._save_config()
            cfg, added = load_config_with_report(str(w.config_path))
        self.assertEqual(added, [])                         # nothing missing any more
        self.assertEqual(cfg["anilist_username"], "someone")

    def test_broken_config_is_repaired_on_save(self):
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        self.addCleanup(os.remove, path)
        Path(path).write_text(BROKEN, encoding="utf-8")
        w = self._gui(lambda p: load_config_with_report(path))
        self.assertEqual(w.user_edit.text(), "someone")
        w.config_path = Path(path)
        w._save_config()
        _, added = load_config_with_report(path)
        self.assertEqual(added, [])


if __name__ == "__main__":
    unittest.main()
