"""
Offline tests for the plan -> confirm -> execute flow.
Run with:  python -m unittest discover -s tests
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from torrent_automator.plan import (  # noqa: E402
    STATUS_GROUPS_UNAVAILABLE, STATUS_NOT_WATCHING, STATUS_READY,
)

RSS = [
    {"title": "[SubsPlease] Frieren - 05 (1080p) [AAAA].mkv", "link": "L5sp", "group": "SubsPlease"},
    {"title": "[ASW] Frieren - 05 [1080p HEVC][BBBB].mkv", "link": "L5asw", "group": "ASW"},
    {"title": "[Judas] Frieren - 04 [1080p][HEVC x265 10bit]", "link": "L4judas", "group": "Judas"},
    {"title": "[SubsPlease] Frieren - 04 (1080p) [CCCC].mkv", "link": "L4sp", "group": "SubsPlease"},
    {"title": "[SubsPlease] Frieren - 06 (1080p) [DDDD].mkv", "link": "L6sp", "group": "SubsPlease"},
    {"title": "[ASW] Frieren - 03 [1080p HEVC][EEEE].mkv", "link": "L3asw", "group": "ASW"},
]

ANILIST = {
    "frieren": {"progress": 3, "episodes": 28, "title": "Frieren", "cover": "http://img/frieren.jpg"},
}


def base_config(**kw):
    cfg = {
        "anilist_username": "someone",
        "shows": ["Frieren", "Unknown Show"],
        "quality": "1080p",
        "codec": "",
        "qbittorrent": {"host": "localhost", "port": 8080, "username": "", "password": ""},
        "preferred_group": "",
        "release_groups": ["ASW", "Judas"],
    }
    cfg.update(kw)
    return cfg


class FakeQB:
    def __init__(self):
        self.added = []
        self.logged_in = False

    def login(self):
        self.logged_in = True

    def add_magnet(self, magnet):
        self.added.append(magnet)


async def fake_rss(query):
    return list(RSS)


async def fake_magnet(link):
    return f"magnet:?xt={link}"


def run(coro):
    return asyncio.run(coro)


class ParsingTests(unittest.TestCase):
    """Real release titles seen on Nyaa while testing."""

    def test_episode_numbers(self):
        cases = {
            "[Erai-raws] Ao no Hako Season 2 - 04 [1080p NF WEBRip HEVC EAC3][MultiSub][BFC35CE3]": "04",
            "[SubsPlease] Hotaru no Yomeiri - 05 (1080p) [7825FCC8].mkv": "05",
            "Firefly Wedding S01E02 Tennyo Island 1080p CR WEB-DL MULTi AAC2.0 H.264-VARYG": "02",
            "[Judas] Frieren - 04 [1080p][HEVC x265 10bit]": "04",
            "[ASW] Frieren - 05v2 [1080p HEVC][BBBB].mkv": "05v2",
            # bit depth used to be read as the episode (8 / 10)
            "【TSDM字幕组】[学生会也有洞！][02][MP4][WEB-DL][AVC 8bit 1080p AAC][简日双语内嵌]": "02",
            "【TSDM字幕组】[学生会也有洞！][02][MP4][WEB-DL][HEVC 10bit 1080p AAC][简日双语内嵌]": "02",
            "[SubsPlease] Kaiju No. 8 - 07 (1080p) [ABCD1234].mkv": "07",
            # the "2" in the show name used to win over the bracketed episode
            "[绿茶字幕组] 赛博朋克：边缘行者 2 / Cyberpunk - Edgerunners 2 [03][WebRip][1080p][简繁日内封]": "03",
            "[喵萌奶茶屋&LoliHouse] Cyberpunk Edgerunners 2 - 04 [WebRip 1080p HEVC-10bit AAC]": "04",
        }
        for title, ep in cases.items():
            self.assertEqual(main.extract_episode_number(title), ep, title)
        self.assertIsNone(main.extract_episode_number(
            "[Raze-Salieri] Cyberpunk - Edgerunners S1 (Dual-Audio) x265 HDR 10bit 1080p 119.88fps"))

    def test_batch_detection(self):
        self.assertTrue(main.is_batch_release(
            "[Erai-raws] Cyberpunk: Edgerunners 2 - 01 ~ 10 [1080p NF WEB-DL HEVC EAC3][MultiSub] [BATCH]"))
        self.assertTrue(main.is_batch_release("[Anime Time] Cyberpunk Edgerunners (Season 1) [BD] [Batch]"))
        self.assertTrue(main.is_batch_release("[Group] Show (01-12) [1080p]"))
        self.assertFalse(main.is_batch_release("[SubsPlease] Ao no Hako Season 2 - 04 (1080p) [AAAA].mkv"))
        self.assertFalse(main.is_batch_release("[SubsPlease] Spy x Family S2 - 05 (1080p)"))

    def test_anilist_season(self):
        self.assertEqual(main.anilist_season_number("Cyberpunk: Edgerunners 2"), 2)
        self.assertEqual(main.anilist_season_number("Aoashi 2nd Season"), 2)
        self.assertEqual(main.anilist_season_number("Ranma 1/2 (2024) 3rd Season"), 3)
        self.assertEqual(main.anilist_season_number("Ao no Hako Season 2"), 2)
        self.assertIsNone(main.anilist_season_number("Kaiju No. 8"))
        self.assertIsNone(main.anilist_season_number("Chitose-kun wa Ramune Bin no Naka Part 2"))
        self.assertIsNone(main.anilist_season_number("Hotaru no Yomeiri"))

    def test_release_season(self):
        self.assertEqual(main.extract_season_number("Cyberpunk - Edgerunners S1 (Dual-Audio)"), 1)
        self.assertEqual(main.extract_season_number("Firefly Wedding S01E02 Tennyo"), 1)
        self.assertEqual(main.extract_season_number("Cyberpunk Edgerunners (Season 1) [BD]"), 1)
        self.assertIsNone(main.extract_season_number("[Erai-raws] Cyberpunk: Edgerunners 2 - 05 [1080p]"))
        self.assertIsNone(main.extract_season_number("[ASW] Show - 05 [1080p HEVC x265][MultiSubs]"))


class ProgressBucketTests(unittest.TestCase):
    def test_buckets(self):
        from torrent_automator.anilist import progress_bucket, _media_info
        airing = _media_info({"title": {"romaji": "X"}, "episodes": 12, "status": "RELEASING",
                              "nextAiringEpisode": {"episode": 7, "airingAt": 0}})
        self.assertEqual(airing["aired"], 6)
        self.assertEqual(progress_bucket(dict(airing, progress=3)), "behind")
        self.assertEqual(progress_bucket(dict(airing, progress=6)), "caught_up")
        done = _media_info({"title": {"romaji": "Y"}, "episodes": 10, "status": "FINISHED"})
        self.assertEqual(progress_bucket(dict(done, progress=0)), "finished")
        self.assertEqual(progress_bucket(dict(done, progress=10)), "caught_up")
        # airing with no schedule known: can't tell, treat as up to date
        hiatus = _media_info({"title": {"romaji": "Z"}, "episodes": None, "status": "RELEASING"})
        self.assertEqual(progress_bucket(dict(hiatus, progress=4)), "caught_up")
        upcoming = _media_info({"title": {"romaji": "W"}, "status": "NOT_YET_RELEASED"})
        self.assertEqual(progress_bucket(dict(upcoming, progress=0)), "caught_up")


class QueryTokenTests(unittest.TestCase):
    def test_title_ending_with_season(self):
        # used to raise "not enough values to unpack" and abort the batch run
        self.assertEqual(main._safe_query_tokens("Aoashi 2nd Season", "1080p", ""),
                         ["aoashi 2nd season 1080p", "aoashi 2nd s 1080p"])

    def test_numbered_season(self):
        self.assertEqual(main._safe_query_tokens("Spy x Family Season 2", "1080p", "HEVC"), [
            "spy x family season 2 1080p HEVC",
            "spy x family s 2 1080p HEVC",
            "spy x family 2 1080p HEVC",
        ])


@mock.patch.object(main, "fetch_nyaa_rss", fake_rss)
@mock.patch.object(main, "extract_magnet", fake_magnet)
class PlanTests(unittest.TestCase):
    def test_batch_plan_priority_groups(self):
        plan = run(main.build_batch_plan(base_config(), log_cb=lambda m: None, anilist=ANILIST))
        self.assertEqual(plan.group_mode, "priority")
        self.assertEqual(plan.groups, ["ASW", "Judas"])
        frieren, unknown = plan.shows
        self.assertEqual(unknown.status, STATUS_NOT_WATCHING)
        self.assertEqual(frieren.status, STATUS_READY)
        self.assertEqual(frieren.cover, "http://img/frieren.jpg")
        by_ep = {it.episode: it for it in frieren.items}
        # Ep 03 is already watched
        self.assertEqual(sorted(by_ep), ["04", "05", "06"])
        self.assertEqual(by_ep["05"].group, "ASW")      # ASW beats SubsPlease and is top priority
        self.assertEqual(by_ep["04"].group, "Judas")    # only allowed group for ep 4
        self.assertEqual(set(by_ep["05"].available_groups), {"ASW", "SubsPlease"})
        # Ep 06 only exists from a non-selected group -> listed, but not pre-selected
        self.assertFalse(by_ep["06"].in_selected_groups)
        self.assertFalse(by_ep["06"].selected)
        self.assertEqual(set(frieren.groups_found), {"SubsPlease", "ASW", "Judas"})

    def test_single_group_mode_is_enforced(self):
        cfg = base_config(preferred_group="SubsPlease", release_groups=[])
        plan = run(main.build_batch_plan(cfg, log_cb=lambda m: None, anilist=ANILIST))
        self.assertEqual(plan.group_mode, "single")
        items = plan.shows[0].items
        self.assertTrue(all(it.group == "SubsPlease" for it in items if it.selected))
        self.assertEqual(len(plan.selected_items()), 3)

    def test_groups_unavailable_status(self):
        cfg = base_config(preferred_group="NoSuchGroup")
        plan = run(main.build_batch_plan(cfg, log_cb=lambda m: None, anilist=ANILIST))
        self.assertEqual(plan.shows[0].status, STATUS_GROUPS_UNAVAILABLE)
        self.assertEqual(plan.selected_items(), [])

    def test_recent_plan(self):
        cfg = base_config(recent_shows=["Frieren"], recent_group="ASW", recent_count=5)
        plan = run(main.build_recent_plan(cfg, log_cb=lambda m: None))
        self.assertEqual(plan.groups, ["ASW"])
        self.assertEqual([it.link for it in plan.items], ["L5asw", "L3asw"])

    def test_execute_only_sends_given_items(self):
        plan = run(main.build_batch_plan(base_config(), log_cb=lambda m: None, anilist=ANILIST))
        qb = FakeQB()
        chosen = [it for it in plan.items if it.episode == "05"]
        summary = run(main.execute_plan_items(chosen, base_config(), log_cb=lambda m: None, qb_client=qb))
        self.assertEqual(summary, {"sent": 1, "failed": 0})
        self.assertEqual(qb.added, ["magnet:?xt=L5asw"])


@mock.patch.object(main, "fetch_nyaa_rss", fake_rss)
@mock.patch.object(main, "extract_magnet", fake_magnet)
@mock.patch.object(main, "fetch_anilist_progress", mock.AsyncMock(return_value=ANILIST))
class CliConfirmationTests(unittest.TestCase):
    def _run_with_answer(self, answers, non_interactive=False):
        qb = FakeQB()
        it = iter(answers)
        with mock.patch.object(main, "_make_qb", return_value=qb), \
                mock.patch("builtins.input", lambda prompt="": next(it)):
            run(main.run_automation(base_config(), non_interactive=non_interactive, log_cb=lambda m: None))
        return qb

    def test_decline_sends_nothing(self):
        qb = self._run_with_answer(["n"])
        self.assertEqual(qb.added, [])
        self.assertFalse(qb.logged_in)

    def test_accept_sends_preselected(self):
        qb = self._run_with_answer(["y"])
        self.assertEqual(sorted(qb.added), ["magnet:?xt=L4judas", "magnet:?xt=L5asw"])

    def test_select_individually(self):
        # items: ep04 (Y), ep05 (Y), ep06 (N, other group) -> answer n, y, y
        qb = self._run_with_answer(["s", "n", "", "y"])
        self.assertEqual(qb.added, ["magnet:?xt=L5asw", "magnet:?xt=L6sp"])

    def test_non_interactive_keeps_auto_send(self):
        qb = self._run_with_answer([], non_interactive=True)
        self.assertEqual(len(qb.added), 2)


if __name__ == "__main__":
    unittest.main()
