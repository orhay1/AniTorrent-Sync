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
    QFileDialog, QRadioButton, QDialog, QDialogButtonBox, QInputDialog
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QObject, pyqtSignal, QRunnable, QThreadPool

import qdarkstyle
import yaml

# ---- import from existing modules ----
from torrent_automator.config import load_config
from torrent_automator.anilist import fetch_anilist_progress
from torrent_automator.qbittorrent import QBitClient
from torrent_automator.nyaa import search_nyaa, extract_magnet

# ---------------------------------------------------------------------
# Helpers & persistent prefs
# ---------------------------------------------------------------------
PREFS_PATH = Path(__file__).parent / ".gui_prefs.yaml"
DEFAULT_GROUPS = ["ASW", "Judas"]
DEFAULT_QUALITIES = ["1080p", "720p"]
# blank option comes from UI as "(none)" and we simply don't save 'codec' when blank is chosen
DEFAULT_CODECS = ["HEVC", "x265", "x264"]

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
            qb_cfg = self.config.get("qbittorrent", {})
            qb = QBitClient(
                host=qb_cfg.get("host"),
                port=qb_cfg.get("port"),
                username=qb_cfg.get("username"),
                password=qb_cfg.get("password"),
                use_https=qb_cfg.get("https", False),
            )
            qb.login()
            shows = self.config.get("shows", [])
            groups = self.config.get("release_groups") or []
            preferred = self.config.get("preferred_group") or ""
            # If single-group mode was chosen, narrow to that one group only
            allowed_groups = [preferred] if preferred else (groups or None)

            for show in shows:
                self.signals.line.emit(f"🔎 Searching for {show} ...")
                results = await search_nyaa(show, allowed_groups)
                if not results:
                    self.signals.line.emit(f"⚠️ No results for {show}")
                    continue
                first = results[0]
                magnet = await extract_magnet(first["link"])
                if magnet:
                    qb.add_magnet(magnet)
                    self.signals.line.emit(f"✅ Added {first['title']}")
                await asyncio.sleep(0.2)
        except Exception as e:
            self.signals.line.emit(f"❌ Error: {e}")
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
        save_prefs(self.prefs)

        self.config_dirty = False

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self._init_config_tab()
        self._init_automation_tab()
        self._init_settings_tab()
        self._init_log_dock()

        view_menu = self.menuBar().addMenu("View")
        toggle_logs = QAction("Show/Hide Logs", self)
        toggle_logs.triggered.connect(lambda: self.log_dock.setVisible(not self.log_dock.isVisible()))
        view_menu.addAction(toggle_logs)

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
        self.user_edit.textChanged.connect(self._mark_dirty)
        form.addRow("AniList Username:", self.user_edit)

        self.qual_combo = QComboBox(); self.qual_combo.setEditable(True)
        self.qual_combo.addItems(self.prefs["qualities"])
        self.qual_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Quality:", self.qual_combo)

        self.codec_combo = QComboBox(); self.codec_combo.setEditable(True)
        self.codec_combo.addItem("(none)")  # choosing this means: don't save 'codec'
        for c in self.prefs["codecs"]:
            self.codec_combo.addItem(c)
        self.codec_combo.currentTextChanged.connect(self._mark_dirty)
        form.addRow("Codec:", self.codec_combo)

        # --- release groups dual-mode ---
        groups_box = QWidget(); gl = QVBoxLayout(groups_box)
        modes = QHBoxLayout()
        self.grp_mode_single = QRadioButton("Use Single Group Only")
        self.grp_mode_prio = QRadioButton("Use Priority Order")
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
        self.grp_combo.currentTextChanged.connect(self._mark_dirty)
        hl.addWidget(self.grp_combo)

        self.grp_add = QPushButton("Add")
        self.grp_add.setToolTip("Add a new release group")
        self.grp_add.clicked.connect(self._add_group)

        self.grp_rem = QPushButton("Remove")
        self.grp_rem.setToolTip("Remove the currently selected group from known list")
        self.grp_rem.clicked.connect(self._remove_group)

        self.grp_reorder = QPushButton("Reorder…")
        self.grp_reorder.setToolTip("Drag & drop to set priority")
        self.grp_reorder.clicked.connect(self._reorder_groups)

        hl.addWidget(self.grp_add); hl.addWidget(self.grp_rem); hl.addWidget(self.grp_reorder)
        gl.addLayout(hl)
        form.addRow("Release Groups:", groups_box)

        layout.addWidget(grp)

        # Shows field + controls
        self.shows_box = QTextEdit(); self.shows_box.setReadOnly(True); self.shows_box.setMinimumHeight(110)
        layout.addWidget(QLabel("Configured Shows:"))
        layout.addWidget(self.shows_box)
        clear_btn = QPushButton("🗑️ Clear All Shows from Config")
        clear_btn.setToolTip("Remove every show from the config (no confirmation)")
        clear_btn.clicked.connect(self._clear_shows)
        layout.addWidget(clear_btn)

        # AniList section
        row = QHBoxLayout()
        self.fetch_btn = QPushButton("Fetch AniList")
        self.fetch_btn.clicked.connect(self._fetch_anilist)
        self.select_all = QPushButton("Select All")
        self.select_all.clicked.connect(lambda: self._set_all_checks(True))
        self.deselect_all = QPushButton("Deselect All")
        self.deselect_all.clicked.connect(lambda: self._set_all_checks(False))
        self.add_selected = QPushButton("Add Selected to Config")
        self.add_selected.clicked.connect(self._add_selected)
        self.save_btn = QPushButton("Save Config")
        self.save_btn.clicked.connect(self._save_config)
        self.reload_btn = QPushButton("Reload Config")
        self.reload_btn.clicked.connect(self._load_config)

        row.addWidget(self.fetch_btn); row.addWidget(self.select_all)
        row.addWidget(self.deselect_all); row.addWidget(self.add_selected)
        row.addStretch(); row.addWidget(self.reload_btn); row.addWidget(self.save_btn)
        layout.addLayout(row)

        self.anilist_list = QListWidget()
        layout.addWidget(self.anilist_list)
        self.status_lbl = QLabel("Ready")
        layout.addWidget(self.status_lbl)
        self.tabs.addTab(self.cfg_tab, "Config Manager")

    # -----------------------------------------------------------------
    # Automation Tab
    # -----------------------------------------------------------------
    def _init_automation_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        self.run_btn = QPushButton("▶ Run Automation")
        self.run_btn.clicked.connect(self._run_automation)
        self.open_qb_btn = QPushButton("Open qBittorrent")
        self.open_qb_btn.clicked.connect(self._open_qb)
        self.status_run = QLabel("Status: Idle")
        v.addWidget(self.run_btn); v.addWidget(self.open_qb_btn); v.addWidget(self.status_run)
        v.addStretch()
        self.tabs.addTab(w, "Automation")

    # -----------------------------------------------------------------
    # Settings Tab
    # -----------------------------------------------------------------
    def _init_settings_tab(self):
        w = QWidget(); v = QVBoxLayout(w)
        theme = QCheckBox("Light Theme")
        theme.stateChanged.connect(lambda s: self.setStyleSheet("" if s else qdarkstyle.load_stylesheet_pyqt6()))
        v.addWidget(theme)

        self.use_web = QCheckBox("Use Web UI instead of App")
        self.use_web.setChecked(self.prefs.get("use_web_ui", False))
        self.use_web.stateChanged.connect(lambda s: self._set_pref("use_web_ui", bool(s)))
        v.addWidget(self.use_web)

        self.qb_path = QLineEdit(self.prefs.get("qbittorrent_path", ""))
        self.qb_path.setPlaceholderText("Path to qbittorrent.exe (used when Web UI is disabled)")
        self.qb_path.textChanged.connect(lambda t: self._set_pref("qbittorrent_path", t.strip()))
        v.addWidget(self.qb_path)

        pick = QPushButton("Browse qBittorrent…")
        pick.clicked.connect(self._browse_qb)
        v.addWidget(pick)

        v.addStretch()
        self.tabs.addTab(w, "Settings")

    # -----------------------------------------------------------------
    def _init_log_dock(self):
        self.log_dock = QDockWidget("Logs", self)
        self.log_text = QTextEdit(); self.log_text.setReadOnly(True)
        self.log_dock.setWidget(self.log_text)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.log_dock)
        self.log_dock.hide()

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
        self.qual_combo.setCurrentText(self.config.get("quality", "1080p"))

        codec = self.config.get("codec", "")
        self.codec_combo.setCurrentText(codec if codec else "(none)")

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
        self.status_lbl.setText("Config loaded ✅")
        self._log("✅ Config loaded")

    def _save_config(self):
        self.config["anilist_username"] = self.user_edit.text().strip()
        q = self.qual_combo.currentText().strip()
        if q:
            self.config["quality"] = q

        c = self.codec_combo.currentText().strip()
        if c and c != "(none)":
            self.config["codec"] = c
            if c not in self.prefs["codecs"]:
                self.prefs["codecs"].append(c)
        else:
            self.config.pop("codec", None)  # blank means don't filter/save

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

        save_prefs(self.prefs)

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
        for k, v in sorted(data.items()):
            prog = v.get("progress", 0); eps = v.get("episodes") or "?"
            t = pretty_title(k)
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
            self._log("✅ Group priority updated")
            self._mark_dirty()

    # -----------------------------------------------------------------
    # Automation
    # -----------------------------------------------------------------
    def _run_automation(self):
        self._log("▶ Starting automation...")
        self.status_run.setText("Running…")
        worker = AutomationWorker(self.config)
        worker.signals.line.connect(self._log)
        worker.signals.done.connect(lambda: self.status_run.setText("Done ✅"))
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
