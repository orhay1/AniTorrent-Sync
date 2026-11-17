"""
Asynchronous AniList cover image loading with an in-memory and on-disk cache.

Widgets never hold on to callbacks: they listen to CoverLoader.coverReady(url)
and repaint/refresh whichever of their items use that URL. This avoids touching
list items that may already have been deleted when a download finishes.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, Qt, pyqtSignal, QRectF
from PyQt6.QtGui import QPixmap, QPainter, QColor, QFont, QPainterPath, QLinearGradient
from PyQt6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "covers"


class CoverLoader(QObject):
    coverReady = pyqtSignal(str)

    _instance: "CoverLoader | None" = None

    @classmethod
    def instance(cls) -> "CoverLoader":
        if cls._instance is None:
            cls._instance = CoverLoader()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._nam = QNetworkAccessManager(self)
        self._pixmaps: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    @staticmethod
    def _cache_path(url: str) -> Path:
        return CACHE_DIR / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".img")

    def pixmap(self, url: str) -> QPixmap | None:
        """Return the cover if available; otherwise start loading it and return None."""
        if not url:
            return None
        pm = self._pixmaps.get(url)
        if pm is not None:
            return pm
        if url in self._pending or url in self._failed:
            return None
        path = self._cache_path(url)
        if path.exists():
            pm = QPixmap()
            if pm.load(str(path)):
                self._pixmaps[url] = pm
                return pm
        self._request(url)
        return None

    def _request(self, url: str):
        self._pending.add(url)
        req = QNetworkRequest(QUrl(url))
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        reply = self._nam.get(req)
        reply.finished.connect(lambda r=reply, u=url: self._on_finished(r, u))

    def _on_finished(self, reply: QNetworkReply, url: str):
        self._pending.discard(url)
        try:
            if reply.error() != QNetworkReply.NetworkError.NoError:
                self._failed.add(url)
                return
            data = bytes(reply.readAll())
            pm = QPixmap()
            if not pm.loadFromData(data):
                self._failed.add(url)
                return
            self._pixmaps[url] = pm
            try:
                self._cache_path(url).write_bytes(data)
            except Exception:
                pass
            self.coverReady.emit(url)
        finally:
            reply.deleteLater()


def _initials(title: str) -> str:
    words = [w for w in (title or "").replace("-", " ").split() if w[:1].isalnum()]
    return "".join(w[0].upper() for w in words[:2]) or "?"


def placeholder(title: str, color: str, w: int, h: int) -> QPixmap:
    """A gradient tile with the show's initials, used until (or instead of) a cover."""
    pm = QPixmap(w, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    base = QColor(color) if color else QColor("#3a4256")
    grad = QLinearGradient(0, 0, w, h)
    grad.setColorAt(0, base.lighter(115))
    grad.setColorAt(1, base.darker(170))
    p.fillRect(0, 0, w, h, grad)
    p.setPen(QColor(255, 255, 255, 220))
    f = QFont()
    f.setBold(True)
    f.setPixelSize(max(10, int(min(w, h) * 0.32)))
    p.setFont(f)
    p.drawText(QRectF(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, _initials(title))
    p.end()
    return pm


def cover_or_placeholder(url: str, title: str, color: str, w: int, h: int) -> QPixmap:
    pm = CoverLoader.instance().pixmap(url) if url else None
    if pm is None or pm.isNull():
        return placeholder(title, color, w, h)
    return scaled_crop(pm, w, h)


def scaled_crop(pm: QPixmap, w: int, h: int) -> QPixmap:
    s = pm.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                  Qt.TransformationMode.SmoothTransformation)
    x = max(0, (s.width() - w) // 2)
    y = max(0, (s.height() - h) // 2)
    return s.copy(x, y, w, h)


def rounded(pm: QPixmap, radius: float) -> QPixmap:
    out = QPixmap(pm.size())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, pm.width(), pm.height()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out
