#!/usr/bin/env python3
import sys
import asyncio
import webbrowser
import subprocess
import re
from pathlib import Path
from typing import Dict, Any, List

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QPushButton, QLabel, QTabWidget, QTextEdit, QDockWidget, QCheckBox,
    QListWidget, QListWidgetItem, QLineEdit, QComboBox, QGroupBox, QMessageBox,
    QFileDialog, QRadioButton, QDialog, QDialogButtonBox, QInputDialog, QSpinBox
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QRunnable, QThreadPool

import qdarkstyle
import yaml

# ---- import from existing modules ----
from torrent_automator.config import load_config
from torrent_automator.anilist import fetch_anilist_progress
from torrent_automator.groups import POPULAR_GROUPS
from main import run_automation, run_recent_fetch

# ---------------------------------------------------------------------
# Helpers & persistent prefs
# ---------------------------------------------------------------------
PREFS_PATH = Path(__file__).parent / ".gui_prefs.yaml"
DEFAULT_GROUPS = ["ASW", "Judas"]
DEFAULT_QUALITIES = ["1080p", "720p"]
# blank option comes from UI as "(none)" and we simply don't save 'codec' when blank is chosen
DEFAULT_CODECS = ["HEVC", "x265", "x264"]
APP_VERSION = "0.1.0"

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

# ---------------------------------------------------------------------
# Async workers
# ---------------------------------------------------------------------
class AniListWorker(QRunnable):
    class Signals(QObject):
        result = pyqtSignal(dict)
        error = pyqtSignal(str)
        finished = pyqtSignal()
    def __init__(self, username: str):
        super().__init__()
        self.username = username
        self.signals = self.Signals()
    def run(self):
        try:
            data = asyncio.run(fetch_anilist_progress(self.username))
            self.signals.result.emit(data)
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

class AutomationWorker(QRunnable):
    class Signals(QObject):
        line = pyqtSignal(str)
        done = pyqtSignal()
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.signals = self.Signals()
    def run(self):
        asyncio.run(self._run())
    async def _run(self):
        try:
            await run_automation(
                config=self.config,
                non_interactive=True,
                log_cb=self.signals.line.emit,
            )
        except Exception as e:
            self.signals.line.emit(f"❌ Error: {e}")
        finally:
            self.signals.done.emit()

class RecentWorker(QRunnable):
    class Signals(QObject):
        line = pyqtSignal(str)
        done = pyqtSignal()
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.signals = self.Signals()
    def run(self):
        asyncio.run(self._run())
    async def _run(self):
        try:
            await run_recent_fetch(
                config=self.config,
                non_interactive=True,
                log_cb=self.signals.line.emit,
            )
        except Exception as e:
            self.signals.line.emit(f"Error: {e}")
        finally:
            self.signals.done.emit()


# ---------------------------------------------------------------------
# Group Reorder Dialog (drag & drop)
# ---------------------------------------------------------------------
class GroupReorderDialog(QDialog):
    def __init__(self, groups: List[str]):
        super().__init__()
        self.setWindowTitle("Set Group Priority Order")
        self.resize(320, 420)
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
        self.setWindowTitle("Torrent Automator GUI")
        self.resize(1200, 760)
        self.setStyleSheet(qdarkstyle.load_stylesheet_pyqt6())

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
        if not self.prefs.get("nyaa_groups"):
            self.prefs["nyaa_groups"] = POPULAR_GROUPS[:]
        save_prefs(self.prefs)

        self.config_dirty = False
        self.anilist_titles: List[str] = []

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._init_config_tab()
        self._init_recent_tab()
        self._init_settings_tab()
        self._init_log_dock()

        file_menu = self.menuBar().addMenu("File")
        save_cfg = QAction("Save Config", self)
        save_cfg.triggered.connect(self._save_config)
        reload_cfg = QAction("Reload Config", self)
        reload_cfg.triggered.connect(self._load_config)
        file_menu.addAction(save_cfg)
        file_menu.addAction(reload_cfg)

        view_menu = self.menuBar().addMenu("View")
        toggle_logs = QAction("Show/Hide Logs", self)
        toggle_logs.triggered.connect(lambda: self.log_dock.setVisible(not self.log_dock.isVisible()))
        view_menu.addAction(toggle_logs)

        about_menu = self.menuBar().addMenu("About")
        version_action = QAction(f"Version {APP_VERSION}", self)
        version_action.setEnabled(False)
        about_menu.addAction(version_action)
        how_to = QAction("How to use", self)
        how_to.triggered.connect(self._show_help_popup)
        about_menu.addAction(how_to)

        self._load_config()

    # -----------------------------------------------------------------
    # Config Tab
    # -----------------------------------------------------------------
    def _init_config_tab(self):
        self.cfg_tab = QWidget()
        layout = QVBoxLayout(self.cfg_tab)

        # --- editable config ---
        grp = QGroupBox("Config Parameters")
        form = QFormLayout(grp)

        self.user_edit = QLineEdit()
        self.user_edit.setToolTip("AniList username used to fetch your watching list.")
        self.user_edit.textChanged.connect(self._mark_dirty)
        form.addRow("AniList Username:", self.user_edit)

        self.qual_combo = QComboBox(); self.qual_combo.setEditable(True)
        self.qual_combo.addItem("Any")
        self.qual_combo.addItems(self.prefs["qualities"])
        self.qual_combo.setToolTip("Preferred video quality for searches.")
        self.qual_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Quality:", self.qual_combo)

        self.codec_combo = QComboBox(); self.codec_combo.setEditable(True)
        self.codec_combo.addItem("Any")
        for c in self.prefs["codecs"]:
            self.codec_combo.addItem(c)
        self.codec_combo.setToolTip("Preferred video codec for searches (optional).")
        self.codec_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Codec:", self.codec_combo)

        # --- release groups dual-mode ---
        groups_box = QWidget(); gl = QVBoxLayout(groups_box)
        modes = QHBoxLayout()
        self.grp_mode_single = QRadioButton("Use Single Group Only")
        self.grp_mode_single.setToolTip("Always use the single selected group.")
        self.grp_mode_prio = QRadioButton("Use Priority Order")
        self.grp_mode_prio.setToolTip("Prefer releases by group priority order.")
        if self.prefs.get("group_mode") == "single":
            self.grp_mode_single.setChecked(True)
        else:
            self.grp_mode_prio.setChecked(True)
        self.grp_mode_single.toggled.connect(self._mark_dirty)
        self.grp_mode_prio.toggled.connect(self._mark_dirty)
        modes.addWidget(self.grp_mode_single); modes.addWidget(self.grp_mode_prio)
        gl.addLayout(modes)

        hl = QHBoxLayout()
        self.grp_combo = QComboBox()
        self.grp_combo.addItem("(none)")
        self.grp_combo.addItems(self.prefs["groups"])
        self.grp_combo.setToolTip("Select a preferred release group for single mode.")
        self.grp_combo.currentTextChanged.connect(self._mark_dirty)
        hl.addWidget(self.grp_combo)

        self.grp_add = QPushButton("Add")
        self.grp_add.setToolTip("Add a new release group")
        self.grp_add.clicked.connect(self._add_group)

        self.grp_rem = QPushButton("Remove")
        self.grp_rem.setToolTip("Remove the currently selected group from known list")
        self.grp_rem.clicked.connect(self._remove_group)

        self.grp_reorder = QPushButton("Reorder...")
        self.grp_reorder.setToolTip("Drag & drop to set priority.")
        self.grp_reorder.clicked.connect(self._reorder_groups)

        hl.addWidget(self.grp_add); hl.addWidget(self.grp_rem); hl.addWidget(self.grp_reorder)
        gl.addLayout(hl)
        form.addRow("Release Groups:", groups_box)

        layout.addWidget(grp)

        # Shows field + controls
        self.shows_box = QTextEdit(); self.shows_box.setReadOnly(True); self.shows_box.setMinimumHeight(110)
        layout.addWidget(QLabel("Configured Shows:"))
        layout.addWidget(self.shows_box)
        clear_btn = QPushButton("Clear All Shows from Config")
        clear_btn.setToolTip("Remove every show from the config (no confirmation).")
        clear_btn.clicked.connect(self._clear_shows)
        layout.addWidget(clear_btn)

        # AniList section
        row = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch AniList")
        self.fetch_btn.setToolTip("Fetch your AniList watching list.")
        self.fetch_btn.clicked.connect(self._fetch_anilist)
        self.select_all = QPushButton("Select All")
        self.select_all.setToolTip("Select all fetched AniList shows.")
        self.select_all.clicked.connect(lambda: self._set_all_checks(True))
        self.deselect_all = QPushButton("Deselect All")
        self.deselect_all.setToolTip("Deselect all fetched AniList shows.")
        self.deselect_all.clicked.connect(lambda: self._set_all_checks(False))
        self.add_selected = QPushButton("Add Selected to Config")
        self.add_selected.setToolTip("Add the selected AniList shows to the config.")
        self.add_selected.clicked.connect(self._add_selected)

        row.addWidget(self.fetch_btn); row.addWidget(self.select_all)
        row.addWidget(self.deselect_all); row.addWidget(self.add_selected)
        row.addStretch()
        layout.addLayout(row)

        self.anilist_list = QListWidget()
        self.anilist_list.setToolTip("AniList shows you can add to your config.")
        layout.addWidget(self.anilist_list)
        self.status_lbl = QLabel("Ready")
        layout.addWidget(self.status_lbl)

        self.run_btn = QPushButton("Run Batch Automation")
        self.run_btn.setToolTip("Run batch automation for configured shows.")
        self.run_btn.clicked.connect(self._run_automation)
        layout.addWidget(self.run_btn)

        self.status_batch = QLabel("Batch Status: Idle")
        layout.addWidget(self.status_batch)
        self.tabs.addTab(self.cfg_tab, "Config Manager")

    # -----------------------------------------------------------------
    # Recent Releases Tab
    # -----------------------------------------------------------------
    def _init_recent_tab(self):
        w = QWidget(); v = QVBoxLayout(w)

        recent_grp = QGroupBox("Recent Releases")
        recent_form = QFormLayout(recent_grp)

        self.recent_show_list = QListWidget()
        self.recent_show_list.setMinimumHeight(140)
        self.recent_show_list.setToolTip("Select one or more shows for recent releases.")

        show_controls = QHBoxLayout()
        self.recent_use_config = QPushButton("Use Config Shows")
        self.recent_use_config.setToolTip("Populate the list with shows from your config.")
        self.recent_use_config.clicked.connect(lambda: self._set_recent_shows(self.config.get("shows", []), checked=True))
        self.recent_use_anilist = QPushButton("Use AniList Shows")
        self.recent_use_anilist.setToolTip("Populate the list with shows from AniList.")
        self.recent_use_anilist.clicked.connect(lambda: self._set_recent_shows(self.anilist_titles, checked=True))
        self.recent_clear = QPushButton("Clear")
        self.recent_clear.setToolTip("Clear the recent show selection.")
        self.recent_clear.clicked.connect(self._clear_recent_shows)
        show_controls.addWidget(self.recent_use_config)
        show_controls.addWidget(self.recent_use_anilist)
        show_controls.addWidget(self.recent_clear)
        recent_form.addRow(show_controls)
        recent_form.addRow("Shows:", self.recent_show_list)

        self.recent_add_edit = QLineEdit()
        self.recent_add_edit.setPlaceholderText("Show name")
        self.recent_add_edit.setToolTip("Add a show that isn't in your config or AniList.")
        self.recent_add_btn = QPushButton("Add Show")
        self.recent_add_btn.setToolTip("Add the manual show name to the list.")
        self.recent_add_btn.clicked.connect(self._add_recent_show_from_input)
        add_row = QHBoxLayout()
        add_row.addWidget(self.recent_add_edit)
        add_row.addWidget(self.recent_add_btn)
        recent_form.addRow("Manual show:", add_row)

        self.recent_group_combo = QComboBox(); self.recent_group_combo.setEditable(True)
        self.recent_group_combo.setToolTip("Pick a specific release group or choose (any).")
        self.recent_group_combo.currentTextChanged.connect(self._mark_dirty)
        recent_form.addRow("Group:", self.recent_group_combo)

        self.recent_episode_edit = QLineEdit()
        self.recent_episode_edit.setPlaceholderText("e.g. 01")
        self.recent_episode_edit.setToolTip("Optional: filter to a specific episode number.")
        self.recent_episode_edit.textChanged.connect(self._mark_dirty)
        recent_form.addRow("Episode:", self.recent_episode_edit)

        self.recent_count_spin = QSpinBox()
        self.recent_count_spin.setRange(1, 200)
        self.recent_count_spin.setValue(5)
        self.recent_count_spin.setToolTip("How many recent releases to fetch per show.")
        self.recent_count_spin.valueChanged.connect(self._mark_dirty)
        recent_form.addRow("Count:", self.recent_count_spin)

        self.recent_quality_combo = QComboBox(); self.recent_quality_combo.setEditable(True)
        self.recent_quality_combo.addItem("(use global)")
        self.recent_quality_combo.addItem("Any")
        self.recent_quality_combo.addItems(self.prefs["qualities"])
        self.recent_quality_combo.setToolTip("Override global quality for recent releases.")
        self.recent_quality_combo.currentTextChanged.connect(self._mark_dirty)
        recent_form.addRow("Quality override:", self.recent_quality_combo)

        self.recent_codec_combo = QComboBox(); self.recent_codec_combo.setEditable(True)
        self.recent_codec_combo.addItem("(use global)")
        self.recent_codec_combo.addItem("Any")
        self.recent_codec_combo.addItems(self.prefs["codecs"])
        self.recent_codec_combo.setToolTip("Override global codec for recent releases.")
        self.recent_codec_combo.currentTextChanged.connect(self._mark_dirty)
        recent_form.addRow("Codec override:", self.recent_codec_combo)

        self.use_popular_groups_btn = QPushButton("Load Popular Groups")
        self.use_popular_groups_btn.setToolTip("Load the built-in list of common release groups.")
        self.use_popular_groups_btn.clicked.connect(self._load_popular_groups)
        recent_form.addRow(self.use_popular_groups_btn)

        v.addWidget(recent_grp)

        run_row = QHBoxLayout()
        self.run_recent_btn = QPushButton("Fetch Recent Releases")
        self.run_recent_btn.setToolTip("Fetch recent releases for the selected shows.")
        self.run_recent_btn.clicked.connect(self._run_recent)
        run_row.addWidget(self.run_recent_btn)
        v.addLayout(run_row)

        self.status_recent = QLabel("Recent Status: Idle")
        v.addWidget(self.status_recent)
        v.addStretch()
        self.tabs.addTab(w, "Recent Releases")

    # -----------------------------------------------------------------
    # Settings Tab
    # -----------------------------------------------------------------
    def _init_settings_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        theme = QCheckBox("Light Theme")
        theme.setToolTip("Toggle between light and dark themes.")
        theme.stateChanged.connect(lambda s: self.setStyleSheet("" if s else qdarkstyle.load_stylesheet_pyqt6()))
        v.addWidget(theme)

        self.use_web = QCheckBox("Use Web UI instead of App")
        self.use_web.setToolTip("Open qBittorrent in the browser instead of the desktop app.")
        self.use_web.setChecked(self.prefs.get("use_web_ui", False))
        self.use_web.stateChanged.connect(lambda s: self._set_pref("use_web_ui", bool(s)))
        v.addWidget(self.use_web)

        self.qb_path = QLineEdit(self.prefs.get("qbittorrent_path", ""))
        self.qb_path.setPlaceholderText("Path to qbittorrent.exe (used when Web UI is disabled)")
        self.qb_path.setToolTip("Path to qbittorrent.exe when Web UI is disabled.")
        self.qb_path.textChanged.connect(lambda t: self._set_pref("qbittorrent_path", t.strip()))
        v.addWidget(self.qb_path)

        pick = QPushButton("Browse qBittorrent…")
        pick.setToolTip("Browse for qbittorrent.exe.")
        pick.clicked.connect(self._browse_qb)
        v.addWidget(pick)

        self.open_qb_btn = QPushButton("Open qBittorrent")
        self.open_qb_btn.setToolTip("Open qBittorrent (Web UI or app).")
        self.open_qb_btn.clicked.connect(self._open_qb)
        v.addWidget(self.open_qb_btn)

        v.addStretch()
        self.tabs.addTab(w, "Settings")

    # -----------------------------------------------------------------
    def _init_log_dock(self):
        self.log_dock = QDockWidget("Logs", self)
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True)
        self.log_dock.setWidget(self.log_text)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.log_dock.show()

    # -----------------------------------------------------------------
    # Config load/save
    # -----------------------------------------------------------------
    def _load_config(self):
        try:
            self.config = load_config(str(self.config_path))
        except Exception as e:
            self._log(f"❌ Failed to load config: {e}")
            self.config = {}
            return

        self.user_edit.setText(self.config.get("anilist_username", ""))
        quality = (self.config.get("quality") or "").strip()
        self.qual_combo.setCurrentText(quality if quality else "Any")

        codec = (self.config.get("codec") or "").strip()
        self.codec_combo.setCurrentText(codec if codec else "Any")

        # group mode
        if self.config.get("preferred_group"):
            self.prefs["group_mode"] = "single"
            self.grp_mode_single.setChecked(True)
            self.grp_combo.setCurrentText(self.config.get("preferred_group"))
        else:
            self.prefs["group_mode"] = "priority"
            self.grp_mode_prio.setChecked(True)

        # refresh dropdown lists from prefs
        self.grp_combo.clear()
        self.grp_combo.addItem("(none)")
        self.grp_combo.addItems(self.prefs["groups"])

        shows = self.config.get("shows", [])
        self.shows_box.setText("\n".join(shows))

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

        self.status_lbl.setText("Config loaded ✅")
        self._log("✅ Config loaded")

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
            self.status_lbl.setText("Saved ✅")
            self.config_dirty = False
        except Exception as e:
            QMessageBox.critical(self, "Save Error", f"Failed to save config:\n{e}")
            self._log(f"❌ Save error: {e}")

    # -----------------------------------------------------------------
    # AniList + shows
    # -----------------------------------------------------------------
    def _fetch_anilist(self):
        user = self.user_edit.text().strip()
        if not user:
            QMessageBox.warning(self, "AniList", "Set AniList username first")
            return
        self.fetch_btn.setEnabled(False)
        worker = AniListWorker(user)
        worker.signals.result.connect(self._on_anilist)
        worker.signals.error.connect(lambda e: self._log(f"❌ AniList: {e}"))
        worker.signals.finished.connect(lambda: self.fetch_btn.setEnabled(True))
        self.thread_pool.start(worker)
        self._log(f"🔗 Fetching AniList for {user}")

    def _on_anilist(self, data: dict):
        self.anilist_list.clear()
        self.anilist_titles = []
        for k, v in sorted(data.items()):
            prog = v.get("progress", 0); eps = v.get("episodes") or "?"
            t = pretty_title(k)
            self.anilist_titles.append(t)
            it = QListWidgetItem(f"{t} — Ep {prog}/{eps}")
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Unchecked)
            it.setData(Qt.ItemDataRole.UserRole, t)
            self.anilist_list.addItem(it)
        self.status_lbl.setText(f"Fetched {len(data)} titles ✅")

    def _set_all_checks(self, on: bool):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for i in range(self.anilist_list.count()):
            self.anilist_list.item(i).setCheckState(st)

    def _add_selected(self):
        shows = set(self.config.get("shows", []))
        for i in range(self.anilist_list.count()):
            it = self.anilist_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                shows.add(it.data(Qt.ItemDataRole.UserRole))
        self.config["shows"] = sorted(shows)
        self.shows_box.setText("\n".join(self.config["shows"]))
        self._log(f"➕ Added shows ({len(self.config['shows'])})")
        self._mark_dirty()

    def _clear_shows(self):
        self.config["shows"] = []
        self.shows_box.clear()
        self._log("🗑️ Cleared all shows")
        self._mark_dirty()

    # -----------------------------------------------------------------
    # Groups management
    # -----------------------------------------------------------------
    def _add_group(self):
        text, ok = QInputDialog.getText(self, "Add Group", "Group name:")
        if not ok or not text.strip():
            return
        name = text.strip()
        if name not in self.prefs["groups"]:
            self.prefs["groups"].append(name)
            save_prefs(self.prefs)
            self.grp_combo.addItem(name)
            self._refresh_recent_groups()
            self._log(f"➕ Group added: {name}")
        self._mark_dirty()

    def _remove_group(self):
        g = self.grp_combo.currentText()
        if g and g != "(none)" and g in self.prefs["groups"]:
            self.prefs["groups"].remove(g)
            save_prefs(self.prefs)
            self.grp_combo.clear()
            self.grp_combo.addItem("(none)")
            self.grp_combo.addItems(self.prefs["groups"])
            self._refresh_recent_groups()
            self._log(f"🗑️ Group removed: {g}")
            self._mark_dirty()

    def _reorder_groups(self):
        dlg = GroupReorderDialog(self.prefs["groups"])
        if dlg.exec():
            self.prefs["groups"] = dlg.get_order()
            save_prefs(self.prefs)
            # refresh dropdown
            cur = self.grp_combo.currentText()
            self.grp_combo.clear(); self.grp_combo.addItem("(none)")
            self.grp_combo.addItems(self.prefs["groups"])
            if cur in ["(none)"] + self.prefs["groups"]:
                self.grp_combo.setCurrentText(cur)
            self._refresh_recent_groups()
            self._log("✅ Group priority updated")
            self._mark_dirty()

    # -----------------------------------------------------------------
    # Recent releases helpers
    # -----------------------------------------------------------------
    def _add_recent_show_item(self, name: str, checked: bool = True):
        name = (name or "").strip()
        if not name:
            return
        for i in range(self.recent_show_list.count()):
            if self.recent_show_list.item(i).text() == name:
                if checked:
                    self.recent_show_list.item(i).setCheckState(Qt.CheckState.Checked)
                return
        it = QListWidgetItem(name)
        it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.recent_show_list.addItem(it)

    def _set_recent_shows(self, shows: List[str], checked: bool = True, append: bool = False, mark_dirty: bool = True):
        if not append:
            self.recent_show_list.clear()
        for s in shows or []:
            self._add_recent_show_item(s, checked=checked)
        if mark_dirty:
            self._mark_dirty()

    def _clear_recent_shows(self):
        self.recent_show_list.clear()
        self._mark_dirty()

    def _add_recent_show_from_input(self):
        name = self.recent_add_edit.text().strip()
        if not name:
            return
        self._add_recent_show_item(name, checked=True)
        self.recent_add_edit.clear()
        self._mark_dirty()

    def _get_recent_shows(self) -> List[str]:
        shows: List[str] = []
        for i in range(self.recent_show_list.count()):
            it = self.recent_show_list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                shows.append(it.text())
        return shows

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
    # Automation
    # -----------------------------------------------------------------
    def _run_recent(self):
        self._log("Starting recent releases fetch...")
        self.status_recent.setText("Running (recent)")
        self._save_config(save_to_disk=False)
        worker = RecentWorker(self.config)
        worker.signals.line.connect(self._log)
        worker.signals.done.connect(lambda: self.status_recent.setText("Done"))
        self.thread_pool.start(worker)

    def _run_automation(self):
        self._log("▶ Starting automation...")
        self.status_batch.setText("Running...")
        self._save_config(save_to_disk=False)
        worker = AutomationWorker(self.config)
        worker.signals.line.connect(self._log)
        worker.signals.done.connect(lambda: self.status_batch.setText("Done ✅"))
        self.thread_pool.start(worker)

    def _open_qb(self):
        if self.prefs.get("use_web_ui", False):
            webbrowser.open("http://localhost:8080")
            self._log("🌐 Opened qBittorrent Web UI")
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
        dlg = QDialog(self, flags=Qt.WindowType.Popup)
        dlg.setWindowTitle("How to use")
        layout = QVBoxLayout(dlg)
        title = QLabel(f"Torrent Automator GUI v{APP_VERSION}")
        body = QLabel(
            "Capabilities:\n"
            "- Fetch AniList shows and add them to your config\n"
            "- Run batch automation for configured shows\n"
            "- Fetch recent releases for selected shows\n\n"
            "Tips:\n"
            "- Use the Config tab to manage shows and groups\n"
            "- Use Recent Releases for quick backfill or single-episode grabs\n"
            "- Check Logs for real-time output"
        )
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)
        dlg.setLayout(layout)
        dlg.adjustSize()
        dlg.show()

    def _log(self, message: str):
        self.log_text.append(message)

    def _mark_dirty(self, *args):
        self.config_dirty = True

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
                    event.ignore(); return
            elif res == QMessageBox.StandardButton.Cancel:
                event.ignore(); return
        save_prefs(self.prefs)
        event.accept()

# ---------------------------------------------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TorrentAutomatorGUI()
    window.show()
    sys.exit(app.exec())
