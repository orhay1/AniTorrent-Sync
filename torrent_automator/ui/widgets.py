"""Reusable widgets: cover-card grid, thumbnail list, async worker and AniList browser."""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from PyQt6.QtCore import (
    Qt, QSize, QRect, QRectF, QPointF, QObject, QRunnable, QThreadPool, pyqtSignal, QTimer,
)
from PyQt6.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QIcon, QPainterPath
from PyQt6.QtWidgets import (
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyle, QDialog, QVBoxLayout,
    QHBoxLayout, QLineEdit, QPushButton, QLabel, QListView, QAbstractItemView,
)

from .covers import CoverLoader, cover_or_placeholder, rounded
from . import theme

# Item data roles
ROLE_KEY = Qt.ItemDataRole.UserRole           # value stored in config (show name)
ROLE_TITLE = Qt.ItemDataRole.UserRole + 1     # display title
ROLE_SUB = Qt.ItemDataRole.UserRole + 2       # subtitle line
ROLE_COVER = Qt.ItemDataRole.UserRole + 3     # cover URL
ROLE_COLOR = Qt.ItemDataRole.UserRole + 4     # AniList cover color
ROLE_BADGE = Qt.ItemDataRole.UserRole + 5     # small badge text (e.g. "In config")
ROLE_PROGRESS = Qt.ItemDataRole.UserRole + 6  # 0..1 or None
ROLE_INFO = Qt.ItemDataRole.UserRole + 7      # full info dict


# ---------------------------------------------------------------------
# Async worker
# ---------------------------------------------------------------------
class AsyncWorker(QRunnable):
    """Run an async function in the thread pool and report back via signals."""

    class Signals(QObject):
        result = pyqtSignal(object)
        error = pyqtSignal(str)
        line = pyqtSignal(str)
        finished = pyqtSignal()

    def __init__(self, fn: Callable[..., Any], *args, pass_log: bool = False, **kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = self.Signals()
        if pass_log:
            self.kwargs["log_cb"] = self.signals.line.emit

    def run(self):
        try:
            self.signals.result.emit(asyncio.run(self.fn(*self.args, **self.kwargs)))
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()


# ---------------------------------------------------------------------
# Cover card grid
# ---------------------------------------------------------------------
class CardDelegate(QStyledItemDelegate):
    def __init__(self, card_width: int = 150, parent=None):
        super().__init__(parent)
        self.cw = card_width
        self.ch = int(card_width * 1.42)
        self.text_h = 54
        self.pad = 7

    def sizeHint(self, option, index):
        return QSize(self.cw + 2 * self.pad, self.ch + self.text_h + 2 * self.pad)

    def paint(self, p: QPainter, option, index):
        c = theme.colors()
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = option.rect.adjusted(self.pad, self.pad, -self.pad, -self.pad)
        cover_rect = QRect(r.x(), r.y(), self.cw, self.ch)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        checkable = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        state = index.data(Qt.ItemDataRole.CheckStateRole)  # PyQt6 may hand back a plain int
        checked = state in (Qt.CheckState.Checked, Qt.CheckState.Checked.value)

        title = index.data(ROLE_TITLE) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        pm = cover_or_placeholder(index.data(ROLE_COVER) or "", title,
                                  index.data(ROLE_COLOR) or "", self.cw, self.ch)
        p.drawPixmap(cover_rect.topLeft(), rounded(pm, 8))

        if hover and not checked:
            p.fillRect(cover_rect, QColor(255, 255, 255, 18))

        # progress bar along the bottom of the cover
        prog = index.data(ROLE_PROGRESS)
        if prog is not None:
            bar = QRectF(cover_rect.x() + 6, cover_rect.bottom() - 9, self.cw - 12, 4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(bar, 2, 2)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), bar.width() * max(0.0, min(1.0, prog)), 4), 2, 2)

        # badge (top-left)
        badge = index.data(ROLE_BADGE)
        if badge:
            f = QFont(option.font)
            f.setPointSizeF(7.5)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetrics(f)
            bw = fm.horizontalAdvance(badge) + 12
            br = QRectF(cover_rect.x() + 6, cover_rect.y() + 6, bw, 18)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 175))
            p.drawRoundedRect(br, 9, 9)
            p.setPen(QColor("#ffffff"))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)

        # selection ring + check mark (top-right)
        if checkable:
            if checked:
                p.setPen(QPen(QColor(c["accent"]), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(cover_rect).adjusted(1.5, 1.5, -1.5, -1.5), 8, 8)
            if checked or hover:
                center = QPointF(cover_rect.right() - 15, cover_rect.y() + 15)
                p.setPen(QPen(QColor("#ffffff"), 2))
                p.setBrush(QColor(c["accent"]) if checked else QColor(0, 0, 0, 120))
                p.drawEllipse(center, 10, 10)
                if checked:
                    path = QPainterPath()
                    path.moveTo(center.x() - 4.5, center.y())
                    path.lineTo(center.x() - 1, center.y() + 3.5)
                    path.lineTo(center.x() + 5, center.y() - 3.5)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(path)

        # title + subtitle
        tf = QFont(option.font)
        tf.setBold(True)
        p.setFont(tf)
        p.setPen(QColor(c["text"]))
        text_rect = QRect(r.x(), cover_rect.bottom() + 6, self.cw, 34)
        fm = QFontMetrics(tf)
        lines = _wrap_two_lines(title, fm, self.cw)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, "\n".join(lines))
        sub = index.data(ROLE_SUB) or ""
        if sub:
            sf = QFont(option.font)
            sf.setPointSizeF(max(7.0, option.font.pointSizeF() - 1))
            p.setFont(sf)
            p.setPen(QColor(c["muted"]))
            sub = QFontMetrics(sf).elidedText(sub, Qt.TextElideMode.ElideRight, self.cw)
            y = text_rect.y() + fm.height() * len(lines) + 2
            p.drawText(QRect(r.x(), y, self.cw, 18), Qt.AlignmentFlag.AlignLeft, sub)
        p.restore()


def _wrap_two_lines(text: str, fm: QFontMetrics, width: int) -> list[str]:
    words = text.split()
    line1 = ""
    i = 0
    while i < len(words):
        trial = (line1 + " " + words[i]).strip()
        if fm.horizontalAdvance(trial) > width and line1:
            break
        line1 = trial
        i += 1
    if fm.horizontalAdvance(line1) > width:
        return [fm.elidedText(line1, Qt.TextElideMode.ElideRight, width)]
    rest = " ".join(words[i:])
    if not rest:
        return [line1]
    return [line1, fm.elidedText(rest, Qt.TextElideMode.ElideRight, width)]


class CoverGrid(QListWidget):
    """Grid of cover cards. Click a card to toggle its selection."""
    checkedChanged = pyqtSignal()

    def __init__(self, card_width: int = 150, checkable: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("CoverGrid")
        self.checkable = checkable
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setMouseTracking(True)
        self.setSpacing(2)
        self._delegate = CardDelegate(card_width, self)
        self.setItemDelegate(self._delegate)
        self.itemClicked.connect(self._toggle)
        CoverLoader.instance().coverReady.connect(self._on_cover)

    def add_card(self, key: str, title: str, subtitle: str = "", cover: str = "", color: str = "",
                 badge: str = "", progress: float | None = None, checked: bool = False,
                 info: dict | None = None) -> QListWidgetItem:
        it = QListWidgetItem(title)
        it.setData(ROLE_KEY, key)
        it.setData(ROLE_TITLE, title)
        it.setData(ROLE_SUB, subtitle)
        it.setData(ROLE_COVER, cover)
        it.setData(ROLE_COLOR, color)
        it.setData(ROLE_BADGE, badge)
        it.setData(ROLE_PROGRESS, progress)
        it.setData(ROLE_INFO, info or {})
        it.setToolTip(title if not subtitle else f"{title}\n{subtitle}")
        if self.checkable:
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.addItem(it)
        return it

    def _toggle(self, it: QListWidgetItem):
        if not self.checkable:
            return
        it.setCheckState(Qt.CheckState.Unchecked if it.checkState() == Qt.CheckState.Checked
                         else Qt.CheckState.Checked)
        self.checkedChanged.emit()

    def items(self) -> list[QListWidgetItem]:
        return [self.item(i) for i in range(self.count())]

    def checked_items(self) -> list[QListWidgetItem]:
        return [it for it in self.items() if it.checkState() == Qt.CheckState.Checked]

    def set_all_checked(self, on: bool, visible_only: bool = True):
        st = Qt.CheckState.Checked if on else Qt.CheckState.Unchecked
        for it in self.items():
            if visible_only and it.isHidden():
                continue
            it.setCheckState(st)
        self.checkedChanged.emit()

    def filter(self, text: str):
        t = (text or "").strip().lower()
        for it in self.items():
            hay = f"{it.data(ROLE_TITLE)} {(it.data(ROLE_INFO) or {}).get('title_english', '')}".lower()
            it.setHidden(bool(t) and t not in hay)

    def _on_cover(self, url: str):
        if any(it.data(ROLE_COVER) == url for it in self.items()):
            self.viewport().update()


class ThumbList(QListWidget):
    """Compact list with small cover thumbnails (used for show lists)."""
    THUMB = QSize(34, 48)

    def __init__(self, checkable: bool = False, parent=None):
        super().__init__(parent)
        self.checkable = checkable
        self.setIconSize(self.THUMB)
        self.setSpacing(1)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        CoverLoader.instance().coverReady.connect(self._on_cover)

    def add_show(self, key: str, title: str | None = None, subtitle: str = "", cover: str = "",
                 color: str = "", checked: bool = True) -> QListWidgetItem:
        title = title or key
        it = QListWidgetItem(title if not subtitle else f"{title}\n{subtitle}")
        it.setData(ROLE_KEY, key)
        it.setData(ROLE_TITLE, title)
        it.setData(ROLE_COVER, cover)
        it.setData(ROLE_COLOR, color)
        it.setSizeHint(QSize(0, self.THUMB.height() + 8))
        if self.checkable:
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._apply_icon(it)
        self.addItem(it)
        return it

    def _apply_icon(self, it: QListWidgetItem):
        pm = cover_or_placeholder(it.data(ROLE_COVER) or "", it.data(ROLE_TITLE) or "",
                                  it.data(ROLE_COLOR) or "", self.THUMB.width(), self.THUMB.height())
        it.setIcon(QIcon(rounded(pm, 4)))

    def items(self) -> list[QListWidgetItem]:
        return [self.item(i) for i in range(self.count())]

    def keys(self, checked_only: bool = False) -> list[str]:
        return [it.data(ROLE_KEY) for it in self.items()
                if not checked_only or not self.checkable or it.checkState() == Qt.CheckState.Checked]

    def find_key(self, key: str) -> QListWidgetItem | None:
        k = (key or "").strip().lower()
        for it in self.items():
            if (it.data(ROLE_KEY) or "").strip().lower() == k:
                return it
        return None

    def set_cover(self, key: str, cover: str, color: str = ""):
        it = self.find_key(key)
        if it is not None and cover:
            it.setData(ROLE_COVER, cover)
            it.setData(ROLE_COLOR, color)
            self._apply_icon(it)

    def _on_cover(self, url: str):
        for it in self.items():
            if it.data(ROLE_COVER) == url:
                self._apply_icon(it)


# ---------------------------------------------------------------------
# AniList browse / search dialog
# ---------------------------------------------------------------------
def media_subtitle(info: dict) -> str:
    parts = []
    if info.get("format"):
        parts.append(info["format"].replace("_", " ").title() if info["format"] not in ("TV", "OVA", "ONA") else info["format"])
    if info.get("season_year"):
        parts.append(str(info["season_year"]))
    if info.get("episodes"):
        parts.append(f"{info['episodes']} eps")
    if info.get("score"):
        parts.append(f"★ {info['score']}%")
    return " · ".join(parts)


class AniListBrowseDialog(QDialog):
    """Browse airing anime or search AniList, pick shows with their covers."""

    def __init__(self, parent=None, search_fn=None, title: str = "Browse AniList", note: str = "",
                 existing: set[str] | None = None, key_fn: Callable[[str], str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(940, 680)
        self.search_fn = search_fn
        self.key_fn = key_fn or (lambda s: s)
        self.existing = {e.lower() for e in (existing or set())}
        self.pool = QThreadPool.globalInstance()
        self._busy = False

        v = QVBoxLayout(self)
        v.setContentsMargins(16, 16, 16, 16)
        v.setSpacing(10)
        head = QLabel("Browse AniList")
        head.setObjectName("SectionTitle")
        v.addWidget(head)
        if note:
            n = QLabel(note)
            n.setObjectName("Hint")
            n.setWordWrap(True)
            v.addWidget(n)

        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search anime by title… (leave empty for trending airing shows)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self._run_search)
        go = QPushButton("Search")
        go.setObjectName("Primary")
        go.clicked.connect(self._run_search)
        row.addWidget(self.search, 1)
        row.addWidget(go)
        v.addLayout(row)

        self.status = QLabel("")
        self.status.setObjectName("Muted")
        v.addWidget(self.status)

        self.grid = CoverGrid(card_width=140)
        self.grid.checkedChanged.connect(self._update_count)
        v.addWidget(self.grid, 1)

        foot = QHBoxLayout()
        self.count_lbl = QLabel("No shows selected")
        self.count_lbl.setObjectName("Muted")
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.add_btn = QPushButton("Add selected")
        self.add_btn.setObjectName("Primary")
        self.add_btn.setEnabled(False)
        self.add_btn.clicked.connect(self.accept)
        foot.addWidget(self.count_lbl)
        foot.addStretch()
        foot.addWidget(cancel)
        foot.addWidget(self.add_btn)
        v.addLayout(foot)

        QTimer.singleShot(0, self._run_search)

    def _run_search(self):
        if self._busy or self.search_fn is None:
            return
        self._busy = True
        q = self.search.text().strip()
        self.status.setText(f"Searching AniList for “{q}”…" if q else "Loading trending airing anime…")
        w = AsyncWorker(self.search_fn, q)
        w.signals.result.connect(lambda res, q=q: self._on_results(res, q))
        w.signals.error.connect(lambda e: self.status.setText(f"AniList error: {e}"))
        w.signals.finished.connect(self._done)
        self.pool.start(w)

    def _done(self):
        self._busy = False

    def _on_results(self, results: list, query: str):
        # keep current selections across searches
        keep = {it.data(ROLE_KEY): it.data(ROLE_INFO) for it in self.grid.checked_items()}
        self.grid.clear()
        shown = set()
        for key, info in keep.items():
            self._add(info, checked=True)
            shown.add(key)
        for info in results or []:
            if self.key_fn(info.get("title", "")) in shown:
                continue
            self._add(info, checked=False)
        label = f"results for “{query}”" if query else "trending airing shows"
        self.status.setText(f"{len(results or [])} {label}. Click covers to select.")
        self._update_count()

    def _add(self, info: dict, checked: bool):
        key = self.key_fn(info.get("title", ""))
        badge = "Added" if key.lower() in self.existing else ""
        title = info.get("title", "")
        self.grid.add_card(key, title, media_subtitle(info), info.get("cover", ""), info.get("color", ""),
                           badge=badge, checked=checked, info=info)

    def _update_count(self):
        n = len(self.grid.checked_items())
        self.count_lbl.setText(f"{n} show(s) selected" if n else "No shows selected")
        self.add_btn.setText(f"Add {n} selected" if n else "Add selected")
        self.add_btn.setEnabled(n > 0)

    def selected(self) -> list[dict]:
        return [dict(it.data(ROLE_INFO) or {}, key=it.data(ROLE_KEY)) for it in self.grid.checked_items()]
