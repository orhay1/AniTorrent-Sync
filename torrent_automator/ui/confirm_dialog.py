"""Confirmation step shown before anything is sent to qBittorrent."""
from __future__ import annotations

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon, QColor, QFont, QBrush
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QFrame, QHeaderView,
)

from torrent_automator.plan import (
    DownloadPlan, PlannedTorrent, STATUS_READY, STATUS_GROUPS_UNAVAILABLE,
)
from .covers import CoverLoader, cover_or_placeholder, rounded
from . import theme

ROLE_ITEM = Qt.ItemDataRole.UserRole
ROLE_COVER = Qt.ItemDataRole.UserRole + 1

STATUS_TEXT = {
    "ready": "Ready",
    "groups_unavailable": "Not from your groups",
    "no_new": "Up to date",
    "no_results": "Nothing found",
    "not_watching": "Not on Watching list",
    "error": "Search failed",
}


def _chip(text: str, accent: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("ChipAccent" if accent else "Chip")
    return lbl


class ConfirmDownloadDialog(QDialog):
    ICON = QSize(40, 56)

    def __init__(self, plan: DownloadPlan, parent=None):
        super().__init__(parent)
        self.plan = plan
        self.setWindowTitle("Confirm downloads")
        self.resize(1020, 640)
        c = theme.colors()

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(12)

        title = QLabel("Review before downloading")
        title.setObjectName("SectionTitle")
        v.addWidget(title)
        kind = "Download basket (new episodes after your AniList progress)" if plan.kind == "batch" \
            else "Recent releases"
        sub = QLabel(f"{kind}. Nothing has been sent to qBittorrent yet. Untick anything you don't want.")
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        v.addWidget(sub)

        # --- summary card: quality / codec / groups ---
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 12, 14, 12)
        cl.setSpacing(8)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        row1.addWidget(self._key("Quality"))
        row1.addWidget(_chip(plan.quality or "Any"))
        row1.addSpacing(14)
        row1.addWidget(self._key("Codec"))
        row1.addWidget(_chip(plan.codec or "Any"))
        if plan.kind == "recent":
            row1.addSpacing(14)
            row1.addWidget(self._key("Per show"))
            row1.addWidget(_chip(str(plan.count)))
            if plan.episode_filter:
                row1.addSpacing(14)
                row1.addWidget(self._key("Episode"))
                row1.addWidget(_chip(plan.episode_filter))
        row1.addStretch()
        cl.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(6)
        mode_txt = {"single": "Selected group (single)", "priority": "Selected groups (priority order)",
                    "any": "Selected groups"}[plan.group_mode if plan.groups else "any"]
        row2.addWidget(self._key(mode_txt))
        if plan.groups:
            for i, g in enumerate(plan.groups, start=1):
                row2.addWidget(_chip(f"{i}. {g}" if plan.group_mode == "priority" else g, accent=True))
        else:
            row2.addWidget(_chip("Any group"))
        row2.addStretch()
        cl.addLayout(row2)

        found = sorted({g for sp in plan.shows for g in sp.groups_found}, key=str.lower)
        if found:
            sel = {g.lower() for g in plan.groups}
            avail = QLabel("Groups available in search results: " + ", ".join(
                f"<b>{g}</b>" if g.lower() in sel else g for g in found))
            avail.setObjectName("Hint")
            avail.setWordWrap(True)
            avail.setTextFormat(Qt.TextFormat.RichText)
            cl.addWidget(avail)
        v.addWidget(card)

        # --- per-show tree ---
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Show / episode", "Group", "Release", "Also available from"])
        self.tree.setIconSize(self.ICON)
        self.tree.setUniformRowHeights(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setRootIsDecorated(True)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.tree.setColumnWidth(0, 290)
        self.tree.setColumnWidth(3, 170)
        v.addWidget(self.tree, 1)

        bold = QFont()
        bold.setBold(True)
        muted = QBrush(QColor(c["muted"]))
        warn = QBrush(QColor(c["warn"]))
        ok = QBrush(QColor(c["ok"]))
        self._show_items: list[QTreeWidgetItem] = []
        for sp in plan.shows:
            top = QTreeWidgetItem(self.tree)
            name = sp.matched_title or sp.show
            prog = ""
            if sp.progress is not None:
                prog = f"Watched {sp.progress}/{sp.total_episodes if sp.total_episodes is not None else '?'}"
            top.setText(0, f"{name}\n{prog}" if prog else name)
            top.setFont(0, bold)
            top.setToolTip(0, f"Config name: {sp.show}")
            status = STATUS_TEXT.get(sp.status, sp.status)
            top.setText(1, status)
            top.setForeground(1, ok if sp.status == STATUS_READY else
                              warn if sp.status == STATUS_GROUPS_UNAVAILABLE else muted)
            top.setText(2, sp.message or "")
            top.setToolTip(2, sp.message or "")
            top.setForeground(2, muted)
            if sp.groups_found and sp.status != STATUS_READY:
                top.setText(3, ", ".join(sp.groups_found))
                top.setToolTip(3, "Groups that have releases for this show: " + ", ".join(sp.groups_found))
            top.setData(0, ROLE_COVER, sp.cover)
            top.setSizeHint(0, QSize(0, self.ICON.height() + 8))
            self._apply_icon(top, sp.cover, name, sp.color)
            self._show_items.append(top)

            for it in sp.items:
                child = QTreeWidgetItem(top)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked if it.selected else Qt.CheckState.Unchecked)
                child.setText(0, f"Episode {it.episode}" if it.episode else "Episode ?")
                child.setText(1, it.group or "?")
                if not it.in_selected_groups:
                    child.setForeground(1, warn)
                    child.setToolTip(1, "This group is not in your selected group(s).")
                child.setText(2, it.title)
                child.setToolTip(2, it.title)
                others = [g for g in it.available_groups if g.lower() != (it.group or "").lower()]
                child.setText(3, ", ".join(others) if others else "—")
                child.setForeground(3, muted)
                child.setData(0, ROLE_ITEM, it)
            top.setExpanded(bool(sp.items))

        self.tree.itemChanged.connect(lambda *_: self._update_count())
        CoverLoader.instance().coverReady.connect(self._on_cover)

        # --- footer ---
        foot = QHBoxLayout()
        sel_all = QPushButton("Select all")
        sel_all.setObjectName("Flat")
        sel_all.clicked.connect(lambda: self._set_all(True))
        sel_none = QPushButton("Select none")
        sel_none.setObjectName("Flat")
        sel_none.clicked.connect(lambda: self._set_all(False))
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("Muted")
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.ok_btn = QPushButton("Download")
        self.ok_btn.setObjectName("Primary")
        self.ok_btn.clicked.connect(self.accept)
        foot.addWidget(sel_all)
        foot.addWidget(sel_none)
        foot.addSpacing(10)
        foot.addWidget(self.count_lbl)
        foot.addStretch()
        foot.addWidget(cancel)
        foot.addWidget(self.ok_btn)
        v.addLayout(foot)
        self._update_count()

    @staticmethod
    def _key(text: str) -> QLabel:
        lbl = QLabel(text + ":")
        lbl.setObjectName("Muted")
        return lbl

    def _apply_icon(self, item: QTreeWidgetItem, url: str, title: str, color: str):
        pm = cover_or_placeholder(url or "", title, color or "", self.ICON.width(), self.ICON.height())
        item.setIcon(0, QIcon(rounded(pm, 4)))

    def _on_cover(self, url: str):
        for top in self._show_items:
            if top.data(0, ROLE_COVER) == url:
                self._apply_icon(top, url, top.text(0), "")

    def _children(self):
        for top in self._show_items:
            for i in range(top.childCount()):
                yield top.child(i)

    def _set_all(self, on: bool):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        self.tree.blockSignals(True)
        for ch in self._children():
            ch.setCheckState(0, st)
        self.tree.blockSignals(False)
        self._update_count()

    def chosen(self) -> list[PlannedTorrent]:
        return [ch.data(0, ROLE_ITEM) for ch in self._children()
                if ch.checkState(0) == Qt.CheckState.Checked]

    def _update_count(self):
        total = sum(1 for _ in self._children())
        n = len(self.chosen())
        shows = len({it.show for it in self.chosen()})
        if total == 0:
            self.count_lbl.setText("Nothing available to download with the current settings.")
        else:
            self.count_lbl.setText(f"{n} of {total} release(s) selected across {shows} show(s)")
        self.ok_btn.setText(f"Download {n}" if n else "Download")
        self.ok_btn.setEnabled(n > 0)
