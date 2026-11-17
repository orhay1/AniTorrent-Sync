"""
Offscreen GUI tests: the review dialog gates every download, and cover cards toggle once per click.
Skipped automatically if PyQt6 is not installed.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt, QEventLoop, QTimer, QPoint
    from PyQt6.QtTest import QTest
except ImportError:  # pragma: no cover
    QApplication = None

import main  # noqa: E402
from test_plan import ANILIST, FakeQB, base_config, fake_magnet, fake_rss  # noqa: E402


def spin_until(pred, timeout_ms=5000):
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: loop.quit() if pred() else None)
    timer.start(20)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    timer.stop()


@unittest.skipIf(QApplication is None, "PyQt6 not installed")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def setUp(self):
        import gui
        self.gui = gui
        patches = [
            mock.patch.object(gui, "load_prefs", return_value={}),
            mock.patch.object(gui, "save_prefs"),
            mock.patch.object(gui, "load_config_with_report", side_effect=lambda p: (base_config(recent_shows=["Frieren"]), [])),
            mock.patch.object(main, "fetch_nyaa_rss", fake_rss),
            mock.patch.object(main, "extract_magnet", fake_magnet),
            mock.patch.object(main, "fetch_anilist_progress", mock.AsyncMock(return_value=ANILIST)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.qb = FakeQB()
        p = mock.patch.object(main, "_make_qb", return_value=self.qb)
        p.start()
        self.addCleanup(p.stop)
        self.w = gui.TorrentAutomatorGUI()
        self.w.config_dirty = False

    def tearDown(self):
        self.w.config_dirty = False
        self.w.close()

    def _run(self, start, exec_result, untick_all_but=None):
        def fake_exec(dlg):
            if untick_all_but is not None:
                for ch in dlg._children():
                    it = ch.data(0, Qt.ItemDataRole.UserRole)
                    ch.setCheckState(0, Qt.CheckState.Checked if it.episode == untick_all_but
                                     else Qt.CheckState.Unchecked)
            self.dialog_seen = True
            return exec_result
        self.dialog_seen = False
        with mock.patch.object(self.gui.ConfirmDownloadDialog, "exec", fake_exec):
            start()
            spin_until(lambda: self.dialog_seen and not self.w.busy)
            spin_until(lambda: not self.w.busy)

    def test_batch_cancel_sends_nothing(self):
        self._run(self.w._run_automation, 0)
        self.assertTrue(self.dialog_seen)
        self.assertEqual(self.qb.added, [])
        self.assertFalse(self.qb.logged_in)

    def test_batch_accept_sends_only_ticked(self):
        self._run(self.w._run_automation, 1, untick_all_but="05")
        self.assertEqual(self.qb.added, ["magnet:?xt=L5asw"])

    def test_recent_cancel_and_accept(self):
        self._run(self.w._run_recent, 0)
        self.assertTrue(self.dialog_seen)
        self.assertEqual(self.qb.added, [])
        self._run(self.w._run_recent, 1)
        self.assertEqual(len(self.qb.added), 5)  # any group, recent_count defaults to 5

    def test_late_cover_does_not_mark_dirty(self):
        self.w._set_recent_shows(["Frieren"], mark_dirty=False)
        self.w.config_dirty = False
        self.w.recent_show_list.set_cover("Frieren", "http://img/x.jpg")
        self.w.recent_show_list._on_cover("http://img/x.jpg")
        self.assertFalse(self.w.config_dirty)

    def test_space_toggles_card(self):
        grid = self.w.anilist_grid.grids()[0]
        it = grid.add_card("A", "Show A")
        grid.setCurrentItem(it)
        QTest.keyClick(grid, Qt.Key.Key_Space)
        self.assertEqual(it.checkState(), Qt.CheckState.Checked)

    def test_card_click_toggles_once(self):
        grid = self.w.anilist_grid.grids()[0]
        grid.add_card("A", "Show A")
        grid.add_card("B", "Show B")
        self.w.resize(1300, 800)
        self.w.show()
        QTest.qWait(50)
        it = grid.item(0)
        rect = grid.visualItemRect(it)
        for pos in (rect.center(), QPoint(rect.left() + 10, rect.center().y()),
                    QPoint(rect.center().x(), rect.bottom() - 20)):
            before = it.checkState()
            QTest.mouseClick(grid.viewport(), Qt.MouseButton.LeftButton, pos=pos)
            self.assertNotEqual(it.checkState(), before, f"click at {pos} did not toggle exactly once")


    def test_library_grouped_by_progress(self):
        base = {"cover": "", "color": "", "format": "TV"}
        data = {
            "behind show": dict(base, title="Behind Show", progress=3, episodes=12, aired=6, status="RELEASING"),
            "done airing": dict(base, title="Done Airing", progress=0, episodes=10, aired=10, status="FINISHED"),
            "caught show": dict(base, title="Caught Show", progress=7, episodes=12, aired=7, status="RELEASING",
                                next_episode=8, next_airing_at=0),
        }
        self.w._on_anilist(data)
        secs = self.w.anilist_grid.sections
        titles = {k: [it.data(gui_role_title()) for it in v["grid"].items()] for k, v in secs.items()}
        self.assertEqual(titles, {"behind": ["Behind Show"], "finished": ["Done Airing"],
                                  "caught_up": ["Caught Show"]})
        self.assertEqual(self.w.anilist_grid.count(), 3)
        # select all + add goes across every section
        self.w.anilist_grid.set_all_checked(True)
        self.assertEqual(len(self.w.anilist_grid.checked_items()), 3)
        self.assertIn("3 new", self.gui.progress_label(data["behind show"]))
        self.assertIn("10 left", self.gui.progress_label(data["done airing"]))


    def test_click_cover_toggles_basket(self):
        base = {"cover": "", "color": "", "format": "TV", "status": "RELEASING"}
        data = {
            "frieren": dict(base, title="Frieren", progress=3, episodes=28, aired=6),
            "other show": dict(base, title="Other Show", progress=2, episodes=12, aired=5),
        }
        self.w.config["shows"] = []
        self.w._on_anilist(data)
        self.assertFalse(self.w.run_btn.isEnabled())          # empty basket: nothing to download
        self.assertTrue(self.w.basket_empty.isVisibleTo(self.w))
        grid = self.w.anilist_grid.sections["behind"]["grid"]
        frieren = next(it for it in grid.items() if it.data(gui_role_title()) == "Frieren")
        grid._toggle(frieren)                                  # click
        self.assertEqual(self.w.config["shows"], ["Frieren"])
        self.assertTrue(self.w.run_btn.isEnabled())
        self.assertIn("(1)", self.w.run_btn.text())
        grid._toggle(frieren)                                  # click again
        self.assertEqual(self.w.config["shows"], [])
        # removing from the basket list un-ticks the cover
        grid._toggle(frieren)
        self.w.shows_list.item(0).setSelected(True)
        self.w._remove_selected_shows()
        self.assertEqual(frieren.checkState(), Qt.CheckState.Unchecked)
        # Add all puts every visible show in the basket
        self.w.anilist_grid.set_all_checked(True)
        self.assertEqual(self.w.config["shows"], ["Frieren", "Other Show"])

    def test_basket_shows_marked_on_fetch(self):
        self.w.config["shows"] = ["Frieren"]
        base = {"cover": "", "color": "", "format": "TV", "status": "RELEASING"}
        self.w._on_anilist({"frieren": dict(base, title="Frieren", progress=3, episodes=28, aired=6),
                            "other": dict(base, title="Other", progress=1, episodes=12, aired=1)})
        checked = [it.data(gui_role_title()) for it in self.w.anilist_grid.checked_items()]
        self.assertEqual(checked, ["Frieren"])


def gui_role_title():
    from torrent_automator.ui.widgets import ROLE_TITLE
    return ROLE_TITLE


if __name__ == "__main__":
    unittest.main()
