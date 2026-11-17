#!/usr/bin/env python3
import sys
import webbrowser
import subprocess
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Any, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QTabWidget, QTextEdit, QDockWidget, QCheckBox,
    QListWidget, QLineEdit, QComboBox, QMessageBox, QFrame,
    QFileDialog, QRadioButton, QDialog, QDialogButtonBox, QInputDialog, QSpinBox,
    QSplitter, QStyleFactory, QScrollArea,
)
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtCore import Qt, QThreadPool

import yaml

# ---- import from existing modules ----
from torrent_automator.config import load_config_with_report, default_config
from torrent_automator.anilist import (
    fetch_anilist_progress, search_anilist, progress_bucket,
    BUCKET_BEHIND, BUCKET_FINISHED, BUCKET_CAUGHT_UP,
)
from torrent_automator.groups import POPULAR_GROUPS
from torrent_automator.plan import format_plan
from torrent_automator.ui import theme
from torrent_automator.ui.widgets import (
    AsyncWorker, GroupedCoverGrid, ThumbList, AniListBrowseDialog, ROLE_KEY,
)
from torrent_automator.ui.confirm_dialog import ConfirmDownloadDialog
from main import build_batch_plan, build_recent_plan, execute_plan_items

# ---------------------------------------------------------------------
# Helpers & persistent prefs
# ---------------------------------------------------------------------
PREFS_PATH = Path(__file__).parent / ".gui_prefs.yaml"
DEFAULT_GROUPS = ["ASW", "Judas"]
DEFAULT_QUALITIES = ["1080p", "720p"]
# blank option comes from UI as "(none)" and we simply don't save 'codec' when blank is chosen
DEFAULT_CODECS = ["HEVC", "x265", "x264"]
APP_VERSION = "0.2.0"
BATCH_NOTE = ("Batch automation only downloads shows that are on your AniList Watching list. "
              "Shows added from search are still useful for Recent Releases.")


def load_prefs() -> dict:
    if PREFS_PATH.exists():
        try:
            with open(PREFS_PATH, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}
    return {}


def save_prefs(prefs: dict):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(prefs, f, sort_keys=False, allow_unicode=True)
    except Exception:
        pass


def normalize_show_name(name: str) -> str:
    s = name or ""
    s = s.replace("×", "x").replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s-]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip().lower()


def pretty_title(name: str) -> str:
    return " ".join(w.capitalize() for w in normalize_show_name(name).split())


def _until(ts) -> str:
    """Short countdown like '2d 4h' / '5h' / '20m' to a unix timestamp."""
    try:
        secs = int(ts) - int(time.time())
    except Exception:
        return ""
    if secs <= 0:
        return "now"
    d, rem = divmod(secs, 86400)
    h, rem = divmod(rem, 3600)
    if d:
        return f"{d}d {h}h"
    return f"{h}h" if h else f"{max(1, rem // 60)}m"


def progress_label(info: dict, short: bool = False) -> str:
    """Card subtitle describing where you are in a show."""
    if not info:
        return ""
    prog = int(info.get("progress") or 0)
    eps = info.get("episodes")
    aired = info.get("aired")
    bucket = progress_bucket(info)
    base = f"Ep {prog} / {eps if eps else '?'}"
    if bucket == BUCKET_BEHIND and aired is not None:
        extra = f"{aired - prog} new"
    elif bucket == BUCKET_FINISHED:
        left = (eps - prog) if eps else None
        extra = f"{left} left · finished" if left else "finished"
    elif info.get("next_episode") and info.get("next_airing_at"):
        extra = f"ep {info['next_episode']} in {_until(info['next_airing_at'])}"
    else:
        extra = "up to date"
    return f"{base} · {extra}" if not short else (extra if extra != "up to date" else "Up to date")


def card(title: str = "") -> tuple[QFrame, QVBoxLayout]:
    """A rounded surface with an optional section title."""
    frame = QFrame()
    frame.setObjectName("Card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(10)
    if title:
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        lay.addWidget(t)
    return frame, lay


def hint(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("Hint")
    lbl.setWordWrap(True)
    return lbl


def transparent(widget: QWidget) -> QWidget:
    widget.setObjectName("Transparent")
    return widget


# ---------------------------------------------------------------------
# Group Reorder Dialog (drag & drop)
# ---------------------------------------------------------------------
class GroupReorderDialog(QDialog):
    def __init__(self, groups: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Set Group Priority Order")
        self.resize(340, 440)
        v = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.addItems(groups)
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        v.addWidget(QLabel("Drag to reorder (top = highest priority):"))
        v.addWidget(self.list)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

    def get_order(self) -> List[str]:
        return [self.list.item(i).text() for i in range(self.list.count())]


# ---------------------------------------------------------------------
# GUI MainWindow
# ---------------------------------------------------------------------
class TorrentAutomatorGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AniTorrent Sync")
        self.resize(1360, 820)

        self.thread_pool = QThreadPool()
        self.config_path = Path(__file__).parent / "config.yaml"
        self.config: Dict[str, Any] = {}
        self.prefs = load_prefs()
        self.prefs.setdefault("groups", DEFAULT_GROUPS[:])
        self.prefs.setdefault("group_mode", "priority")  # "priority" | "single"
        self.prefs.setdefault("preferred_group", "")
        self.prefs.setdefault("qualities", DEFAULT_QUALITIES[:])
        self.prefs.setdefault("codecs", DEFAULT_CODECS[:])
        self.prefs.setdefault("use_web_ui", False)
        self.prefs.setdefault("qbittorrent_path", "")
        self.prefs.setdefault("nyaa_groups", [])
        self.prefs.setdefault("theme", "dark")
        # show name (lowercase) -> {"cover", "color", "title"} so configured shows keep their covers
        self.prefs.setdefault("show_meta", {})
        if not self.prefs.get("nyaa_groups"):
            self.prefs["nyaa_groups"] = POPULAR_GROUPS[:]
        save_prefs(self.prefs)

        self.config_dirty = False
        self.anilist_titles: List[str] = []
        self.anilist_data: Dict[str, dict] = {}
        self.busy = False

        self._apply_theme(self.prefs.get("theme") != "light")

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        cv.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        self._init_library_tab()
        self._init_recent_tab()
        self._init_settings_tab()
        self._init_log_dock()
        self._init_menus()
        self.status_msg = QLabel("Ready")
        self.statusBar().addWidget(self.status_msg, 1)

        self._load_config()

    # -----------------------------------------------------------------
    # Chrome: header, menus, logs
    # -----------------------------------------------------------------
    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        h = QHBoxLayout(header)
        h.setContentsMargins(18, 10, 18, 10)
        h.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(0)
        title = QLabel("AniTorrent Sync")
        title.setObjectName("AppTitle")
        sub = QLabel("AniList  →  Nyaa  →  qBittorrent")
        sub.setObjectName("Muted")
        title_box.addWidget(title)
        title_box.addWidget(sub)
        h.addLayout(title_box)
        h.addStretch()

        h.addWidget(QLabel("AniList user"))
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("username")
        self.user_edit.setFixedWidth(180)
        self.user_edit.setToolTip("AniList username used to fetch your watching list.")
        self.user_edit.textChanged.connect(self._mark_dirty)
        self.user_edit.returnPressed.connect(self._fetch_anilist)
        h.addWidget(self.user_edit)

        self.save_btn = QPushButton("Save config")
        self.save_btn.setToolTip("Save config.yaml (Ctrl+S)")
        self.save_btn.clicked.connect(lambda: self._save_config())
        h.addWidget(self.save_btn)
        return header

    def _init_menus(self):
        file_menu = self.menuBar().addMenu("File")
        save_cfg = QAction("Save Config", self)
        save_cfg.setShortcut(QKeySequence.StandardKey.Save)
        save_cfg.triggered.connect(lambda: self._save_config())
        reload_cfg = QAction("Reload Config", self)
        reload_cfg.triggered.connect(self._load_config)
        file_menu.addAction(save_cfg)
        file_menu.addAction(reload_cfg)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.log_dock.toggleViewAction())

        about_menu = self.menuBar().addMenu("About")
        version_action = QAction(f"Version {APP_VERSION}", self)
        version_action.setEnabled(False)
        about_menu.addAction(version_action)
        how_to = QAction("How to use", self)
        how_to.triggered.connect(self._show_help_popup)
        about_menu.addAction(how_to)

    def _init_log_dock(self):
        self.log_dock = QDockWidget("Activity log", self)
        self.log_dock.setObjectName("LogDock")
        self.log_text = QTextEdit()
        self.log_text.setObjectName("Log")
        self.log_text.setReadOnly(True)
        self.log_dock.setWidget(self.log_text)
        self.log_dock.setMinimumWidth(300)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.resizeDocks([self.log_dock], [340], Qt.Orientation.Horizontal)

    def _apply_theme(self, dark: bool):
        app = QApplication.instance()
        app.setStyleSheet(theme.stylesheet(dark))
        self.prefs["theme"] = "dark" if dark else "light"
        save_prefs(self.prefs)
        for w in (getattr(self, "anilist_grid", None),):
            if w is not None:
                w.refresh()

    # -----------------------------------------------------------------
    # Library tab: AniList watching grid + configured shows
    # -----------------------------------------------------------------
    def _init_library_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # --- left: download basket (config "shows") ---
        left, ll = card()
        head = QHBoxLayout()
        self.my_shows_title = QLabel("Download basket")
        self.my_shows_title.setObjectName("SectionTitle")
        head.addWidget(self.my_shows_title)
        head.addStretch()
        ll.addLayout(head)
        ll.addWidget(hint("Click covers on the right to add or remove shows. "
                          "Only shows in the basket are downloaded."))
        self.shows_list = ThumbList()
        self.shows_list.setToolTip("Shows to download. Select and press Delete or 'Remove' to take them out.")
        ll.addWidget(self.shows_list, 1)
        self.basket_empty = hint("Your basket is empty.\nClick a cover to add it.")
        self.basket_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ll.addWidget(self.basket_empty, 1)  # takes the list's space while the basket is empty
        brow = QHBoxLayout()
        browse_btn = QPushButton("Add from AniList search…")
        ll.addWidget(browse_btn)
        browse_btn.setToolTip("Search AniList for a show that isn't on your Watching list.")
        browse_btn.clicked.connect(self._browse_for_config)
        rem_btn = QPushButton("Remove")
        rem_btn.setToolTip("Take the selected shows out of the basket.")
        rem_btn.clicked.connect(self._remove_selected_shows)
        clear_btn = QPushButton("Empty basket")
        clear_btn.setObjectName("Danger")
        clear_btn.setToolTip("Take every show out of the basket.")
        clear_btn.clicked.connect(self._clear_shows)
        brow.addWidget(rem_btn)
        brow.addStretch()
        brow.addWidget(clear_btn)
        ll.addLayout(brow)
        del_action = QAction(self.shows_list)
        del_action.setShortcut(QKeySequence.StandardKey.Delete)
        del_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        del_action.triggered.connect(self._remove_selected_shows)
        self.shows_list.addAction(del_action)
        left.setMinimumWidth(280)
        split.addWidget(left)

        # --- right: AniList watching grid ---
        right, rl = card()
        top = QHBoxLayout()
        t = QLabel("AniList · Watching")
        t.setObjectName("SectionTitle")
        top.addWidget(t)
        top.addStretch()
        self.fetch_btn = QPushButton("Fetch AniList")
        self.fetch_btn.setObjectName("Primary")
        self.fetch_btn.setToolTip("Fetch your AniList watching list.")
        self.fetch_btn.clicked.connect(self._fetch_anilist)
        top.addWidget(self.fetch_btn)
        rl.addLayout(top)

        tools = QHBoxLayout()
        self.anilist_filter = QLineEdit()
        self.anilist_filter.setPlaceholderText("Filter…")
        self.anilist_filter.setClearButtonEnabled(True)
        self.anilist_filter.setMaximumWidth(260)
        self.anilist_filter.textChanged.connect(lambda t: self.anilist_grid.filter(t))
        sel_all = QPushButton("Add all to basket")
        sel_all.setObjectName("Flat")
        sel_all.setToolTip("Add every show shown below to the basket.")
        sel_all.clicked.connect(lambda: self.anilist_grid.set_all_checked(True))
        sel_none = QPushButton("Remove all")
        sel_none.setObjectName("Flat")
        sel_none.setToolTip("Take every show shown below out of the basket.")
        sel_none.clicked.connect(lambda: self.anilist_grid.set_all_checked(False))
        tools.addWidget(self.anilist_filter)
        tools.addStretch()
        tools.addWidget(sel_all)
        tools.addWidget(sel_none)
        rl.addLayout(tools)

        self.anilist_grid = GroupedCoverGrid([
            (BUCKET_BEHIND, "Behind", "Aired episodes you haven't watched yet"),
            (BUCKET_FINISHED, "Finished airing", "The whole season is out, you haven't finished it"),
            (BUCKET_CAUGHT_UP, "Up to date", "You've watched everything that has aired"),
        ], card_width=138, select_all_text="Add all")
        self.anilist_grid.setToolTip("Click a cover to add it to (or remove it from) the download basket.")
        self.anilist_grid.checkedChanged.connect(self._sync_basket_from_grid)
        rl.addWidget(self.anilist_grid, 1)
        self.anilist_empty = hint("Enter your AniList username above and press “Fetch AniList” to load "
                                  "your Watching list with covers.")
        rl.addWidget(self.anilist_empty)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([320, 900])
        root.addWidget(split, 1)

        # --- action bar ---
        bar, bl = card()
        bl.setContentsMargins(14, 10, 14, 10)
        row = QHBoxLayout()
        col = QVBoxLayout()
        col.setSpacing(2)
        lab = QLabel("Download basket")
        lab.setStyleSheet("font-weight: 600;")
        self.batch_summary = QLabel("")
        self.batch_summary.setObjectName("Muted")
        col.addWidget(lab)
        col.addWidget(self.batch_summary)
        row.addLayout(col, 1)
        self.status_batch = QLabel("Idle")
        self.status_batch.setObjectName("Muted")
        row.addWidget(self.status_batch)
        self.run_btn = QPushButton("Download basket…")
        self.run_btn.setObjectName("Primary")
        self.run_btn.setToolTip("Find the new episodes for every show in the basket. "
                                "You'll review everything before it downloads.")
        self.run_btn.clicked.connect(self._run_automation)
        row.addWidget(self.run_btn)
        bl.addLayout(row)
        root.addWidget(bar)

        self.tabs.addTab(page, "Library")

    # -----------------------------------------------------------------
    # Recent Releases Tab
    # -----------------------------------------------------------------
    def _init_recent_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # --- shows ---
        shows_card, sl = card("Shows")
        sl.addWidget(hint("Tick the shows to fetch the latest releases for."))
        self.recent_show_list = ThumbList(checkable=True)
        self.recent_show_list.setToolTip("Select one or more shows for recent releases.")
        self.recent_show_list.itemChanged.connect(self._mark_dirty)
        sl.addWidget(self.recent_show_list, 1)

        src = QHBoxLayout()
        self.recent_use_config = QPushButton("From basket")
        self.recent_use_config.setToolTip("Populate the list with shows from your config.")
        self.recent_use_config.clicked.connect(lambda: self._set_recent_shows(self.config.get("shows", []), checked=True))
        self.recent_use_anilist = QPushButton("From AniList")
        self.recent_use_anilist.setToolTip("Populate the list with your fetched AniList Watching shows.")
        self.recent_use_anilist.clicked.connect(lambda: self._set_recent_shows(self.anilist_titles, checked=True))
        self.recent_browse = QPushButton("Browse AniList…")
        self.recent_browse.setToolTip("Search AniList for any show and add it here.")
        self.recent_browse.clicked.connect(self._browse_for_recent)
        self.recent_clear = QPushButton("Clear")
        self.recent_clear.setObjectName("Danger")
        self.recent_clear.setToolTip("Clear the recent show selection.")
        self.recent_clear.clicked.connect(self._clear_recent_shows)
        src.addWidget(self.recent_use_config)
        src.addWidget(self.recent_use_anilist)
        src.addWidget(self.recent_browse)
        src.addStretch()
        src.addWidget(self.recent_clear)
        sl.addLayout(src)

        add_row = QHBoxLayout()
        self.recent_add_edit = QLineEdit()
        self.recent_add_edit.setPlaceholderText("Or type a show name and press Enter")
        self.recent_add_edit.setToolTip("Add a show that isn't in your config or AniList.")
        self.recent_add_edit.returnPressed.connect(self._add_recent_show_from_input)
        self.recent_add_btn = QPushButton("Add")
        self.recent_add_btn.clicked.connect(self._add_recent_show_from_input)
        add_row.addWidget(self.recent_add_edit, 1)
        add_row.addWidget(self.recent_add_btn)
        sl.addLayout(add_row)
        split.addWidget(shows_card)

        # --- filters ---
        opts_card, ol = card("Filters")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)

        grp_row = QHBoxLayout()
        self.recent_group_combo = QComboBox()
        self.recent_group_combo.setEditable(True)
        self.recent_group_combo.setToolTip("Pick a specific release group or choose Any.")
        self.recent_group_combo.currentTextChanged.connect(self._mark_dirty)
        self.use_popular_groups_btn = QPushButton("Popular")
        self.use_popular_groups_btn.setToolTip("Load the built-in list of common release groups.")
        self.use_popular_groups_btn.clicked.connect(self._load_popular_groups)
        grp_row.addWidget(self.recent_group_combo, 1)
        grp_row.addWidget(self.use_popular_groups_btn)
        form.addRow("Group", transparent(self._wrap(grp_row)))

        self.recent_episode_edit = QLineEdit()
        self.recent_episode_edit.setPlaceholderText("any (e.g. 01)")
        self.recent_episode_edit.setToolTip("Optional: filter to a specific episode number.")
        self.recent_episode_edit.textChanged.connect(self._mark_dirty)
        form.addRow("Episode", self.recent_episode_edit)

        self.recent_count_spin = QSpinBox()
        self.recent_count_spin.setRange(1, 200)
        self.recent_count_spin.setValue(5)
        self.recent_count_spin.setToolTip("How many recent releases to fetch per show.")
        self.recent_count_spin.valueChanged.connect(self._mark_dirty)
        form.addRow("Per show", self.recent_count_spin)

        self.recent_quality_combo = QComboBox()
        self.recent_quality_combo.setEditable(True)
        self.recent_quality_combo.addItem("(use global)")
        self.recent_quality_combo.addItem("Any")
        self.recent_quality_combo.addItems(self.prefs["qualities"])
        self.recent_quality_combo.setToolTip("Override global quality for recent releases.")
        self.recent_quality_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Quality", self.recent_quality_combo)

        self.recent_codec_combo = QComboBox()
        self.recent_codec_combo.setEditable(True)
        self.recent_codec_combo.addItem("(use global)")
        self.recent_codec_combo.addItem("Any")
        self.recent_codec_combo.addItems(self.prefs["codecs"])
        self.recent_codec_combo.setToolTip("Override global codec for recent releases.")
        self.recent_codec_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Codec", self.recent_codec_combo)
        ol.addLayout(form)
        ol.addStretch()
        opts_card.setMinimumWidth(320)
        split.addWidget(opts_card)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)

        bar, bl = card()
        bl.setContentsMargins(14, 10, 14, 10)
        row = QHBoxLayout()
        self.recent_summary = QLabel("")
        self.recent_summary.setObjectName("Muted")
        row.addWidget(self.recent_summary, 1)
        self.status_recent = QLabel("Idle")
        self.status_recent.setObjectName("Muted")
        row.addWidget(self.status_recent)
        self.run_recent_btn = QPushButton("Find releases…")
        self.run_recent_btn.setObjectName("Primary")
        self.run_recent_btn.setToolTip("Fetch recent releases for the selected shows. You'll review them before downloading.")
        self.run_recent_btn.clicked.connect(self._run_recent)
        row.addWidget(self.run_recent_btn)
        bl.addLayout(row)
        root.addWidget(bar)
        self.recent_show_list.itemChanged.connect(lambda *_: self._update_recent_summary())
        self.tabs.addTab(page, "Recent Releases")

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    # -----------------------------------------------------------------
    # Settings Tab
    # -----------------------------------------------------------------
    def _init_settings_tab(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        v = QVBoxLayout(inner)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(12)
        scroll.setWidget(inner)
        outer.addWidget(scroll)

        # --- search preferences ---
        search_card, sl = card("Search preferences")
        sl.addWidget(hint("Used by batch automation and as defaults for Recent Releases."))
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.qual_combo = QComboBox()
        self.qual_combo.setEditable(True)
        self.qual_combo.addItem("Any")
        self.qual_combo.addItems(self.prefs["qualities"])
        self.qual_combo.setToolTip("Preferred video quality for searches.")
        self.qual_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Quality", self.qual_combo)

        self.codec_combo = QComboBox()
        self.codec_combo.setEditable(True)
        self.codec_combo.addItem("Any")
        for c in self.prefs["codecs"]:
            self.codec_combo.addItem(c)
        self.codec_combo.setToolTip("Preferred video codec for searches (optional).")
        self.codec_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Codec", self.codec_combo)
        sl.addLayout(form)
        v.addWidget(search_card)

        # --- release groups ---
        grp_card, gl = card("Release groups")
        modes = QHBoxLayout()
        self.grp_mode_single = QRadioButton("Single group only")
        self.grp_mode_single.setToolTip("Only download releases from the selected group.")
        self.grp_mode_prio = QRadioButton("Priority order")
        self.grp_mode_prio.setToolTip("Prefer releases by group priority order.")
        if self.prefs.get("group_mode") == "single":
            self.grp_mode_single.setChecked(True)
        else:
            self.grp_mode_prio.setChecked(True)
        self.grp_mode_single.toggled.connect(self._mark_dirty)
        self.grp_mode_prio.toggled.connect(self._mark_dirty)
        self.grp_mode_single.toggled.connect(lambda *_: self._update_group_summary())
        modes.addWidget(self.grp_mode_single)
        modes.addWidget(self.grp_mode_prio)
        modes.addStretch()
        gl.addLayout(modes)

        hl = QHBoxLayout()
        self.grp_combo = QComboBox()
        self.grp_combo.addItem("(none)")
        self.grp_combo.addItems(self.prefs["groups"])
        self.grp_combo.setToolTip("Select a preferred release group for single mode.")
        self.grp_combo.currentTextChanged.connect(self._mark_dirty)
        self.grp_combo.currentTextChanged.connect(lambda *_: self._update_group_summary())
        hl.addWidget(self.grp_combo, 1)
        self.grp_add = QPushButton("Add")
        self.grp_add.setToolTip("Add a new release group")
        self.grp_add.clicked.connect(self._add_group)
        self.grp_rem = QPushButton("Remove")
        self.grp_rem.setToolTip("Remove the currently selected group from known list")
        self.grp_rem.clicked.connect(self._remove_group)
        self.grp_reorder = QPushButton("Reorder…")
        self.grp_reorder.setToolTip("Drag & drop to set priority.")
        self.grp_reorder.clicked.connect(self._reorder_groups)
        hl.addWidget(self.grp_add)
        hl.addWidget(self.grp_rem)
        hl.addWidget(self.grp_reorder)
        gl.addLayout(hl)
        self.group_summary = hint("")
        gl.addWidget(self.group_summary)
        v.addWidget(grp_card)

        # --- qBittorrent ---
        qb_card, ql = card("qBittorrent")
        self.use_web = QCheckBox("Open the Web UI instead of the desktop app")
        self.use_web.setToolTip("Open qBittorrent in the browser instead of the desktop app.")
        self.use_web.setChecked(self.prefs.get("use_web_ui", False))
        self.use_web.stateChanged.connect(lambda s: self._set_pref("use_web_ui", bool(s)))
        ql.addWidget(self.use_web)
        prow = QHBoxLayout()
        self.qb_path = QLineEdit(self.prefs.get("qbittorrent_path", ""))
        self.qb_path.setPlaceholderText("Path to qbittorrent.exe (used when Web UI is disabled)")
        self.qb_path.setToolTip("Path to qbittorrent.exe when Web UI is disabled.")
        self.qb_path.textChanged.connect(lambda t: self._set_pref("qbittorrent_path", t.strip()))
        pick = QPushButton("Browse…")
        pick.setToolTip("Browse for qbittorrent.exe.")
        pick.clicked.connect(self._browse_qb)
        prow.addWidget(self.qb_path, 1)
        prow.addWidget(pick)
        ql.addLayout(prow)
        orow = QHBoxLayout()
        self.open_qb_btn = QPushButton("Open qBittorrent")
        self.open_qb_btn.setToolTip("Open qBittorrent (Web UI or app).")
        self.open_qb_btn.clicked.connect(self._open_qb)
        orow.addWidget(self.open_qb_btn)
        orow.addStretch()
        ql.addLayout(orow)
        v.addWidget(qb_card)

        # --- appearance ---
        app_card, al = card("Appearance")
        self.light_theme = QCheckBox("Light theme")
        self.light_theme.setToolTip("Toggle between light and dark themes.")
        self.light_theme.setChecked(self.prefs.get("theme") == "light")
        self.light_theme.toggled.connect(lambda on: self._apply_theme(not on))
        al.addWidget(self.light_theme)
        v.addWidget(app_card)

        v.addStretch()
        self.tabs.addTab(page, "Preferences")

    # -----------------------------------------------------------------
    # Config load/save
    # -----------------------------------------------------------------
    def _load_config(self):
        added: List[str] = []
        new_file = False
        try:
            self.config, added = load_config_with_report(str(self.config_path))
        except FileNotFoundError:
            # First run: start from the defaults so "Save config" writes a complete file.
            self.config = default_config()
            new_file = True
        except Exception as e:
            self._log(f"❌ Failed to load config: {e}")
            self.config = default_config()
            self._status("config.yaml could not be read; fix or delete it (see log)")
            QMessageBox.warning(self, "Config error",
                                f"config.yaml could not be read:\n{e}\n\n"
                                "Fix the file, or delete it and the app will start with defaults.")
            return

        self.user_edit.setText(self.config.get("anilist_username", ""))
        quality = (self.config.get("quality") or "").strip()
        self.qual_combo.setCurrentText(quality if quality else "Any")

        codec = (self.config.get("codec") or "").strip()
        self.codec_combo.setCurrentText(codec if codec else "Any")

        # refresh dropdown lists from prefs
        self.grp_combo.clear()
        self.grp_combo.addItem("(none)")
        self.grp_combo.addItems(self.prefs["groups"])

        # group mode
        if self.config.get("preferred_group"):
            self.prefs["group_mode"] = "single"
            self.grp_mode_single.setChecked(True)
            self.grp_combo.setCurrentText(self.config.get("preferred_group"))
        else:
            self.prefs["group_mode"] = "priority"
            self.grp_mode_prio.setChecked(True)

        self._refresh_shows_list()

        self.recent_count_spin.setValue(int(self.config.get("recent_count", 5) or 5))
        self._refresh_recent_groups()
        recent_group = self.config.get("recent_group") or self.config.get("preferred_group") or ""
        self.recent_group_combo.setCurrentText(recent_group if recent_group else "Any")

        recent_shows = self.config.get("recent_shows") or []
        if not recent_shows and self.config.get("recent_show"):
            recent_shows = [self.config.get("recent_show")]
        self._set_recent_shows(recent_shows, checked=True, append=False, mark_dirty=False)

        recent_quality = (self.config.get("recent_quality") or "").strip()
        if recent_quality == "__any__":
            self.recent_quality_combo.setCurrentText("Any")
        else:
            self.recent_quality_combo.setCurrentText(recent_quality if recent_quality else "(use global)")
        recent_codec = (self.config.get("recent_codec") or "").strip()
        if recent_codec == "__any__":
            self.recent_codec_combo.setCurrentText("Any")
        else:
            self.recent_codec_combo.setCurrentText(recent_codec if recent_codec else "(use global)")
        self.recent_episode_edit.setText((self.config.get("recent_episode") or "").strip())

        self.config_dirty = False
        self._update_group_summary()
        self._update_recent_summary()
        if new_file:
            self._status("No config.yaml yet: using defaults. Press Save config to create it.")
            self._log("ℹ️ No config.yaml found; started with defaults (Save config creates it)")
            self.config_dirty = True
        elif added:
            self._status("Config loaded; missing settings were filled with defaults (Save config to keep them)")
            self._log("⚠️ config.yaml was missing: " + ", ".join(added) + ". Using defaults; Save config to write them.")
            self.config_dirty = True
        else:
            self._status("Config loaded")
            self._log("✅ Config loaded")
        self._update_dirty_ui()

    def _save_config(self, save_to_disk: bool = True):
        self.config["anilist_username"] = self.user_edit.text().strip()
        q = self.qual_combo.currentText().strip()
        self.config["quality"] = "" if q == "Any" else q

        c = self.codec_combo.currentText().strip()
        self.config["codec"] = "" if c == "Any" else c
        if c and c != "Any" and c not in self.prefs["codecs"]:
            self.prefs["codecs"].append(c)

        # release groups per mode
        if self.grp_mode_single.isChecked():
            self.prefs["group_mode"] = "single"
            sel = self.grp_combo.currentText().strip()
            self.config["preferred_group"] = sel if sel != "(none)" else ""
            self.config["release_groups"] = []  # ignore priority list in single mode
            self.prefs["preferred_group"] = self.config["preferred_group"]
        else:
            self.prefs["group_mode"] = "priority"
            self.config["preferred_group"] = ""  # use priority list
            self.config["release_groups"] = list(self.prefs["groups"])

        recent_shows = self._get_recent_shows()
        self.config["recent_shows"] = recent_shows
        self.config["recent_show"] = recent_shows[0] if recent_shows else ""

        recent_group = self.recent_group_combo.currentText().strip()
        self.config["recent_group"] = "" if recent_group == "Any" else recent_group
        self.config["recent_count"] = int(self.recent_count_spin.value())

        recent_quality = self.recent_quality_combo.currentText().strip()
        if recent_quality == "Any":
            self.config["recent_quality"] = "__any__"
        elif recent_quality == "(use global)":
            self.config["recent_quality"] = ""
        else:
            self.config["recent_quality"] = recent_quality
        recent_codec = self.recent_codec_combo.currentText().strip()
        if recent_codec == "Any":
            self.config["recent_codec"] = "__any__"
        elif recent_codec == "(use global)":
            self.config["recent_codec"] = ""
        else:
            self.config["recent_codec"] = recent_codec
        self.config["recent_episode"] = self.recent_episode_edit.text().strip()

        save_prefs(self.prefs)

        if not save_to_disk:
            return

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, sort_keys=False, allow_unicode=True)
            self._log("💾 Config saved")
            self._status("Config saved")
            self.config_dirty = False
            self._update_dirty_ui()
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save config:\n{e}")
            self._log(f"❌ Save error: {e}")

    # -----------------------------------------------------------------
    # Show metadata (covers) helpers
    # -----------------------------------------------------------------
    def _remember_meta(self, key: str, info: dict):
        if not key or not info.get("cover"):
            return
        self.prefs["show_meta"][key.lower()] = {
            "cover": info.get("cover", ""),
            "color": info.get("color", "") or "",
            "title": info.get("title", "") or key,
        }

    def _meta_for(self, show: str) -> dict:
        meta = self.prefs.get("show_meta", {})
        k = (show or "").lower()
        if k in meta:
            return meta[k]
        norm = normalize_show_name(show)
        best, best_score = None, 0.0
        for mk, mv in meta.items():
            s = SequenceMatcher(None, norm, normalize_show_name(mk)).ratio()
            if s > best_score:
                best, best_score = mv, s
        return best if best and best_score > 0.85 else {}

    def _refresh_shows_list(self):
        self.shows_list.clear()
        shows = self.config.get("shows", []) or []
        watching = {pretty_title(k).lower() for k in self.anilist_data}
        for s in shows:
            m = self._meta_for(s)
            sub = ""
            if self.anilist_data and s.lower() not in watching:
                sub = "Not on Watching list"
            elif s.lower() in watching:
                sub = progress_label(self._anilist_info(s), short=True)
            self.shows_list.add_show(s, s, sub, m.get("cover", ""), m.get("color", ""))
        self.my_shows_title.setText(f"Download basket ({len(shows)})" if shows else "Download basket")
        self.basket_empty.setVisible(not shows)
        self.shows_list.setVisible(bool(shows))
        if not self.busy:
            self.run_btn.setEnabled(bool(shows))
        self.run_btn.setText(f"Download basket ({len(shows)})…" if shows else "Download basket…")
        self._update_batch_summary()
        self._refresh_badges()

    def _anilist_info(self, show: str) -> dict:
        for k, v in self.anilist_data.items():
            if pretty_title(k).lower() == (show or "").lower():
                return v
        return {}

    def _refresh_badges(self):
        if not hasattr(self, "anilist_grid"):
            return
        shows = {s.lower() for s in self.config.get("shows", []) or []}
        for it in self.anilist_grid.items():
            in_basket = (it.data(ROLE_KEY) or "").lower() in shows
            it.setCheckState(Qt.CheckState.Checked if in_basket else Qt.CheckState.Unchecked)
        self.anilist_grid.refresh()

    def _sync_basket_from_grid(self):
        """A cover was clicked (or Add all / Remove all): mirror the grid's ticks into the basket."""
        shows = list(self.config.get("shows", []) or [])
        lower = {s.lower() for s in shows}
        added, removed = [], []
        for it in self.anilist_grid.items():
            key = it.data(ROLE_KEY) or ""
            checked = it.checkState() == Qt.CheckState.Checked
            if checked and key.lower() not in lower:
                shows.append(key)
                lower.add(key.lower())
                added.append(key)
            elif not checked and key.lower() in lower:
                shows = [s for s in shows if s.lower() != key.lower()]
                lower.discard(key.lower())
                removed.append(key)
        if not added and not removed:
            return
        self.config["shows"] = sorted(shows, key=str.lower)
        self._refresh_shows_list()
        self._mark_dirty()
        if len(added) == 1 and not removed:
            self._status(f"Added {added[0]} to the basket")
        elif len(removed) == 1 and not added:
            self._status(f"Removed {removed[0]} from the basket")
        else:
            self._status(f"Basket: {len(self.config['shows'])} show(s)")

    # -----------------------------------------------------------------
    # AniList + shows
    # -----------------------------------------------------------------
    def _fetch_anilist(self):
        user = self.user_edit.text().strip()
        if not user:
            QMessageBox.warning(self, "AniList", "Set your AniList username first.")
            self.user_edit.setFocus()
            return
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText("Fetching…")
        worker = AsyncWorker(fetch_anilist_progress, user)
        worker.signals.result.connect(self._on_anilist)
        worker.signals.error.connect(lambda e: self._log(f"❌ AniList: {e}"))

        def done():
            self.fetch_btn.setEnabled(True)
            self.fetch_btn.setText("Fetch AniList")
        worker.signals.finished.connect(done)
        self.thread_pool.start(worker)
        self._log(f"🔗 Fetching AniList for {user}")
        self._status(f"Fetching AniList for {user}…")

    def _on_anilist(self, data: dict):
        data = data or {}
        self.anilist_data = data
        self.anilist_grid.clear()
        self.anilist_titles = []
        for k, v in sorted(data.items()):
            prog = v.get("progress", 0)
            eps = v.get("episodes")
            t = pretty_title(k)
            self.anilist_titles.append(t)
            self._remember_meta(t, v)
            total = eps or v.get("aired")
            frac = (prog / total) if total else None
            self.anilist_grid.add_card(t, v.get("title") or t, progress_label(v), v.get("cover", ""),
                                       v.get("color", ""), progress=frac, info=v, group=progress_bucket(v))
        save_prefs(self.prefs)
        self.anilist_filter.clear()
        self.anilist_empty.setVisible(not data)
        if not data:
            self.anilist_empty.setText("No shows found. Check the username, and that the list is public "
                                       "and has shows marked as Watching.")
        self._refresh_shows_list()
        self._status(f"Fetched {len(data)} titles from AniList")
        self._log(f"✅ Fetched {len(data)} AniList titles")

    def _add_shows(self, names: List[str]) -> int:
        shows = list(self.config.get("shows", []) or [])
        existing = {s.lower() for s in shows}
        added = 0
        for n in names:
            if n and n.lower() not in existing:
                shows.append(n)
                existing.add(n.lower())
                added += 1
        self.config["shows"] = sorted(shows, key=str.lower)
        self._refresh_shows_list()
        if added:
            self._mark_dirty()
        return added

    def _browse_dialog(self, title: str, note: str, existing: set) -> List[dict]:
        dlg = AniListBrowseDialog(self, search_fn=search_anilist, title=title, note=note,
                                  existing=existing, key_fn=pretty_title)
        if not dlg.exec():
            return []
        picked = dlg.selected()
        for info in picked:
            self._remember_meta(info["key"], info)
        save_prefs(self.prefs)
        return picked

    def _browse_for_config(self):
        picked = self._browse_dialog("Add shows to the download basket", BATCH_NOTE,
                                     set(self.config.get("shows", []) or []))
        if not picked:
            return
        added = self._add_shows([p["key"] for p in picked])
        self._log(f"➕ Added {added} show(s) from AniList search")
        if self.anilist_data:
            watching = {pretty_title(k).lower() for k in self.anilist_data}
            missing = [p["key"] for p in picked if p["key"].lower() not in watching]
            if missing:
                self._log("⚠️ Not on your Watching list (batch will skip them): " + ", ".join(missing))

    def _browse_for_recent(self):
        picked = self._browse_dialog("Add shows to Recent Releases", "",
                                     set(self.recent_show_list.keys()))
        for p in picked:
            self._add_recent_show_item(p["key"], checked=True)
        if picked:
            self._mark_dirty()
            self._update_recent_summary()

    def _remove_selected_shows(self):
        sel = [it.data(ROLE_KEY) for it in self.shows_list.selectedItems()]
        if not sel:
            self._status("Select shows in the basket to remove them")
            return
        self.config["shows"] = [s for s in self.config.get("shows", []) if s not in sel]
        self._refresh_shows_list()
        self._log(f"🗑️ Removed {len(sel)} show(s)")
        self._mark_dirty()

    def _clear_shows(self):
        if not self.config.get("shows"):
            return
        res = QMessageBox.question(self, "Empty basket",
                                   f"Take all {len(self.config['shows'])} shows out of the download basket?")
        if res != QMessageBox.StandardButton.Yes:
            return
        self.config["shows"] = []
        self._refresh_shows_list()
        self._log("🗑️ Cleared all shows")
        self._mark_dirty()

    # -----------------------------------------------------------------
    # Groups management
    # -----------------------------------------------------------------
    def _refresh_group_combo(self, keep: str | None = None):
        cur = keep if keep is not None else self.grp_combo.currentText()
        self.grp_combo.blockSignals(True)
        self.grp_combo.clear()
        self.grp_combo.addItem("(none)")
        self.grp_combo.addItems(self.prefs["groups"])
        if cur in ["(none)"] + self.prefs["groups"]:
            self.grp_combo.setCurrentText(cur)
        self.grp_combo.blockSignals(False)
        self._update_group_summary()

    def _add_group(self):
        text, ok = QInputDialog.getText(self, "Add Group", "Group name:")
        if not ok or not text.strip():
            return
        name = text.strip()
        if name not in self.prefs["groups"]:
            self.prefs["groups"].append(name)
            save_prefs(self.prefs)
            self._refresh_group_combo(keep=name)
            self._refresh_recent_groups()
            self._log(f"➕ Group added: {name}")
        self._mark_dirty()

    def _remove_group(self):
        g = self.grp_combo.currentText()
        if g and g != "(none)" and g in self.prefs["groups"]:
            self.prefs["groups"].remove(g)
            save_prefs(self.prefs)
            self._refresh_group_combo(keep="(none)")
            self._refresh_recent_groups()
            self._log(f"🗑️ Group removed: {g}")
            self._mark_dirty()

    def _reorder_groups(self):
        dlg = GroupReorderDialog(self.prefs["groups"], self)
        if dlg.exec():
            self.prefs["groups"] = dlg.get_order()
            save_prefs(self.prefs)
            self._refresh_group_combo()
            self._refresh_recent_groups()
            self._log("✅ Group priority updated")
            self._mark_dirty()

    def _update_group_summary(self):
        if not hasattr(self, "group_summary"):
            return
        if self.grp_mode_single.isChecked():
            g = self.grp_combo.currentText()
            txt = (f"Only releases from <b>{g}</b> will be selected." if g and g != "(none)"
                   else "No group selected: any group will be accepted.")
        else:
            groups = self.prefs.get("groups") or []
            txt = ("Priority: " + " &gt; ".join(f"<b>{g}</b>" for g in groups)) if groups \
                else "No groups configured: any group will be accepted."
        self.group_summary.setText(txt)
        self._update_batch_summary()

    def _update_batch_summary(self):
        if not hasattr(self, "batch_summary") or not hasattr(self, "grp_mode_single"):
            return
        n = len(self.config.get("shows", []) or [])
        if self.grp_mode_single.isChecked():
            g = self.grp_combo.currentText()
            grp = g if g and g != "(none)" else "any group"
        else:
            grp = " > ".join(self.prefs.get("groups") or []) or "any group"
        q = self.qual_combo.currentText() or "Any"
        c = self.codec_combo.currentText() or "Any"
        self.batch_summary.setText(f"{n} show(s) · {q} · {c} · {grp}")

    # -----------------------------------------------------------------
    # Recent releases helpers
    # -----------------------------------------------------------------
    def _add_recent_show_item(self, name: str, checked: bool = True):
        name = (name or "").strip()
        if not name:
            return
        existing = self.recent_show_list.find_key(name)
        if existing is not None:
            if checked:
                existing.setCheckState(Qt.CheckState.Checked)
            return
        m = self._meta_for(name)
        self.recent_show_list.add_show(name, name, "", m.get("cover", ""), m.get("color", ""), checked=checked)

    def _set_recent_shows(self, shows: List[str], checked: bool = True, append: bool = False, mark_dirty: bool = True):
        self.recent_show_list.blockSignals(True)
        if not append:
            self.recent_show_list.clear()
        for s in shows or []:
            self._add_recent_show_item(s, checked=checked)
        self.recent_show_list.blockSignals(False)
        self._update_recent_summary()
        if mark_dirty:
            self._mark_dirty()

    def _clear_recent_shows(self):
        self.recent_show_list.clear()
        self._update_recent_summary()
        self._mark_dirty()

    def _add_recent_show_from_input(self):
        name = self.recent_add_edit.text().strip()
        if not name:
            return
        self._add_recent_show_item(name, checked=True)
        self.recent_add_edit.clear()
        self._update_recent_summary()
        self._mark_dirty()

    def _get_recent_shows(self) -> List[str]:
        return self.recent_show_list.keys(checked_only=True)

    def _update_recent_summary(self):
        if hasattr(self, "recent_summary"):
            n = len(self._get_recent_shows())
            self.recent_summary.setText(f"{n} show(s) selected" if n else "No shows selected")

    def _refresh_recent_groups(self):
        current = self.recent_group_combo.currentText()
        items: List[str] = ["Any"]
        preferred = self.config.get("preferred_group") or self.prefs.get("preferred_group") or ""
        if preferred:
            items.append(preferred)
        items.extend(self.prefs.get("groups", []))
        items.extend(self.prefs.get("nyaa_groups", []))
        seen = set()
        unique = []
        for it in items:
            if it not in seen:
                seen.add(it)
                unique.append(it)
        self.recent_group_combo.clear()
        self.recent_group_combo.addItems(unique)
        self.recent_group_combo.setCurrentText(current if current else "Any")

    def _load_popular_groups(self):
        self.prefs["nyaa_groups"] = POPULAR_GROUPS[:]
        save_prefs(self.prefs)
        self._refresh_recent_groups()
        self._log(f"Loaded {len(self.prefs['nyaa_groups'])} popular groups.")

    # -----------------------------------------------------------------
    # Automation: plan -> confirm -> execute
    # -----------------------------------------------------------------
    def _set_busy(self, busy: bool, which: str = ""):
        self.busy = busy
        self.run_btn.setEnabled(not busy and bool(self.config.get("shows")))
        self.run_recent_btn.setEnabled(not busy)
        if busy:
            (self.status_batch if which == "batch" else self.status_recent).setText("Working…")

    def _status_label(self, kind: str) -> QLabel:
        return self.status_batch if kind == "batch" else self.status_recent

    def _run_recent(self):
        if self.busy:
            return
        self._save_config(save_to_disk=False)
        if not self.config.get("recent_shows"):
            QMessageBox.information(self, "Recent releases", "Tick at least one show first.")
            return
        if not self._has_qb_config():
            return
        self._log("🔎 Looking for recent releases…")
        self._start_plan("recent", build_recent_plan, dict(self.config))

    def _run_automation(self):
        if self.busy:
            return
        self._save_config(save_to_disk=False)
        if not self.config.get("shows"):
            QMessageBox.information(self, "Download basket",
                                    "Your basket is empty. Click covers to add the shows you want to download.")
            return
        if not (self.config.get("anilist_username") or "").strip():
            QMessageBox.information(self, "Batch automation",
                                    "Batch automation needs your AniList username to know which "
                                    "episodes you have watched.")
            return
        if not self._has_qb_config():
            return
        self._log("▶ Checking for new episodes…")
        self._start_plan("batch", build_batch_plan, dict(self.config))

    def _has_qb_config(self) -> bool:
        if not isinstance(self.config.get("qbittorrent"), dict):
            QMessageBox.warning(self, "qBittorrent", "config.yaml has no qbittorrent section. "
                                "Copy it from config.example.yaml.")
            return False
        return True

    def _start_plan(self, kind: str, fn, config: dict):
        self._set_busy(True, kind)
        self._status("Searching Nyaa… nothing will be downloaded until you confirm")
        worker = AsyncWorker(fn, config, pass_log=True)
        worker.signals.line.connect(self._log)
        worker.signals.result.connect(lambda plan, k=kind, cfg=config: self._on_plan(k, plan, cfg))
        worker.signals.error.connect(lambda e, k=kind: self._on_plan_error(k, e))
        self.thread_pool.start(worker)

    def _on_plan_error(self, kind: str, err: str):
        self._log(f"❌ Error: {err}")
        self._set_busy(False)
        self._status_label(kind).setText("Failed")

    def _on_plan(self, kind: str, plan, config: dict):
        self._set_busy(False)
        if plan is None or plan.error:
            self._status_label(kind).setText("Nothing to do")
            return
        # fill in covers we know about (recent releases do not query AniList)
        for sp in plan.shows:
            if not sp.cover:
                m = self._meta_for(sp.show)
                sp.cover, sp.color = m.get("cover", ""), m.get("color", "")
        for line in format_plan(plan):
            self._log(line)

        dlg = ConfirmDownloadDialog(plan, self)
        if not dlg.exec():
            self._log("⏭️ Cancelled, nothing was sent to qBittorrent.")
            self._status_label(kind).setText("Cancelled")
            self._status("Cancelled, nothing downloaded")
            return
        chosen = dlg.chosen()
        if not chosen:
            self._status_label(kind).setText("Nothing selected")
            return
        self._log(f"⬇ Sending {len(chosen)} torrent(s) to qBittorrent…")
        self._set_busy(True, kind)
        worker = AsyncWorker(execute_plan_items, chosen, config, pass_log=True)
        worker.signals.line.connect(self._log)

        def done(summary, k=kind):
            self._set_busy(False)
            summary = summary or {}
            msg = f"Sent {summary.get('sent', 0)}, failed {summary.get('failed', 0)}"
            self._status_label(k).setText(msg)
            self._status(msg)
        worker.signals.result.connect(done)
        worker.signals.error.connect(lambda e, k=kind: self._on_plan_error(k, e))
        self.thread_pool.start(worker)

    def _open_qb(self):
        if self.prefs.get("use_web_ui", False):
            qbc = self.config.get("qbittorrent") or {}
            scheme = "https" if qbc.get("https") else "http"
            url = f"{scheme}://{qbc.get('host') or 'localhost'}:{qbc.get('port') or 8080}"
            webbrowser.open(url)
            self._log(f"🌐 Opened qBittorrent Web UI ({url})")
        else:
            path = self.prefs.get("qbittorrent_path") or "qbittorrent"
            try:
                subprocess.Popen([path], shell=True)
                self._log(f"🖥️ Launched qBittorrent app: {path}")
            except Exception as e:
                self._log(f"⚠️ Failed to open app: {e}")

    # -----------------------------------------------------------------
    # Settings helpers
    # -----------------------------------------------------------------
    def _set_pref(self, key: str, value: Any):
        self.prefs[key] = value
        save_prefs(self.prefs)

    def _browse_qb(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select qBittorrent", str(Path.home()), "Executable (*.exe);;All files (*.*)")
        if path:
            self.qb_path.setText(path)
            self._set_pref("qbittorrent_path", path)

    # -----------------------------------------------------------------
    # Misc helpers
    # -----------------------------------------------------------------
    def _show_help_popup(self):
        QMessageBox.information(
            self, "How to use",
            f"AniTorrent Sync v{APP_VERSION}\n\n"
            "Library\n"
            "  • Enter your AniList username and Fetch AniList to see your Watching list.\n"
            "  • Shows are grouped into Behind, Finished airing and Up to date.\n"
            "  • Click a cover to put it in the download basket; click again to take it out.\n"
            "  • 'Download basket' finds the episodes after your AniList progress for every show in the basket.\n\n"
            "Recent Releases\n"
            "  • Grab the latest releases for any shows, optionally for one episode.\n\n"
            "Before anything is downloaded you'll see a review screen listing every release, "
            "the group it comes from and which other groups have it. Untick anything you don't want.\n\n"
            "Preferences holds quality, codec, release groups and qBittorrent options."
        )

    def _status(self, message: str):
        if hasattr(self, "status_msg"):
            self.status_msg.setText(message)

    def _log(self, message: str):
        self.log_text.append(message)

    def _mark_dirty(self, *args):
        self.config_dirty = True
        self._update_dirty_ui()
        self._update_batch_summary()

    def _update_dirty_ui(self):
        if hasattr(self, "save_btn"):
            self.save_btn.setText("Save config •" if self.config_dirty else "Save config")
            self.save_btn.setObjectName("Primary" if self.config_dirty else "")
            self.save_btn.style().unpolish(self.save_btn)
            self.save_btn.style().polish(self.save_btn)

    def closeEvent(self, event):
        if self.config_dirty:
            res = QMessageBox.question(
                self, "Unsaved changes",
                "You have unsaved changes. Save before exiting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if res == QMessageBox.StandardButton.Yes:
                self._save_config()
                if self.config_dirty:
                    event.ignore()
                    return
            elif res == QMessageBox.StandardButton.Cancel:
                event.ignore()
                return
        save_prefs(self.prefs)
        event.accept()


# ---------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    if "Fusion" in QStyleFactory.keys():
        app.setStyle("Fusion")
    window = TorrentAutomatorGUI()
    window.show()
    sys.exit(app.exec())
