from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QByteArray, QMimeData, QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QDrag, QFont, QFontMetrics, QPainter, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractItemView, QListWidget,
                               QListWidgetItem, QStyledItemDelegate, QStyle,
                               QStyleOptionViewItem)

from . import theme
from .icons import icon_pixmap

TITLE_ROLE = Qt.UserRole + 1
SUB_ROLE = Qt.UserRole + 2
DOT_ROLE = Qt.UserRole + 3
TAG_ROLE = Qt.UserRole + 4
KIND_ROLE = Qt.UserRole + 5
TRAILING_ROLE = Qt.UserRole + 6
DATA_ROLE = Qt.UserRole + 7
MUTED_ROLE = Qt.UserRole + 8
INSET_ROLE = Qt.UserRole + 9

DOT_COLORS = ["#6B7CFF", "#8B5CF6", "#22C3D6", "#10B981", "#F5B94D", "#F25C77"]
ACTION_MIME = "application/x-spine-action"


def color_for(text: str) -> QColor:
    h = 0
    for ch in text:
        h = (h * 31 + ord(ch)) & 0x7FFFFFFF
    return QColor(DOT_COLORS[h % len(DOT_COLORS)])


def make_item(title: str, *, subtitle: str = "", dot: Optional[QColor] = None,
              tag: str = "", kind: str = "plain", trailing: str = "",
              data=None, muted: bool = False, inset: int = 0,
              height: int = 0, tooltip: str = "") -> QListWidgetItem:
    item = QListWidgetItem(title)
    item.setData(TITLE_ROLE, title)
    item.setData(SUB_ROLE, subtitle)
    item.setData(DOT_ROLE, dot)
    item.setData(TAG_ROLE, tag)
    item.setData(KIND_ROLE, kind)
    item.setData(TRAILING_ROLE, trailing)
    item.setData(DATA_ROLE, data)
    item.setData(MUTED_ROLE, muted)
    item.setData(INSET_ROLE, inset)
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    if tooltip:
        item.setToolTip(tooltip)
    if height:
        item.setSizeHint(QSize(0, height))
    return item


class AssetDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.font = QFont(parent.font() if parent else QFont())
        self.font.setPixelSize(13)
        self.small = QFont(self.font)
        self.small.setPixelSize(11)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        kind = index.data(KIND_ROLE)
        h = 28 if kind in ("group", "part") else 33
        return QSize(option.rect.width(), h)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect.adjusted(2, 1, -6, -1)
        kind = index.data(KIND_ROLE) or "plain"
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        muted = bool(index.data(MUTED_ROLE))
        inset = int(index.data(INSET_ROLE) or 0)
        if selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.accent_qcolor(42))
            painter.drawRoundedRect(rect, 7, 7)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(QRectF(rect.left(), rect.center().y() - 8, 3, 16), 1.5, 1.5)
        elif hover:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 10))
            painter.drawRoundedRect(rect, 7, 7)
        x = rect.left() + 11 + inset
        cy = rect.center().y()
        title = str(index.data(TITLE_ROLE) or "")
        tag = str(index.data(TAG_ROLE) or "")
        trailing = str(index.data(TRAILING_ROLE) or "")
        dot = index.data(DOT_ROLE)
        if kind == "group":
            icon_name = "chevron-down" if index.data(DATA_ROLE) else "chevron-right"
            painter.drawPixmap(QPoint(x, int(cy - 7)), icon_pixmap(icon_name, 14, theme.TEXT3))
            x += 21
            f = QFont(self.font)
            f.setPixelSize(12)
            painter.setFont(f)
            title_color = QColor(theme.TEXT2)
        else:
            if dot:
                painter.setPen(Qt.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(QRectF(x + 1, cy - 3, 6, 6))
                x += 15
            painter.setFont(self.font)
            title_color = QColor(theme.TEXT if selected or hover else theme.TEXT2)
            if muted:
                title_color = QColor(theme.TEXT4)
        right = rect.right() - 8
        if trailing:
            tint = theme.RED if trailing == "eye-off" else (theme.ACCENT if selected else theme.TEXT3)
            painter.drawPixmap(QPoint(right - 16, int(cy - 8)),
                               icon_pixmap("eye-off" if trailing == "eye-off" else trailing, 15, tint))
            right -= 24
        if tag:
            f = QFont(self.small)
            painter.setFont(f)
            metrics = QFontMetrics(f)
            tw = min(metrics.horizontalAdvance(tag) + 12, 80)
            tag_rect = QRectF(right - tw, cy - 9, tw, 18)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.SURFACE3))
            painter.drawRoundedRect(tag_rect, 9, 9)
            painter.setPen(QColor(theme.ACCENT_TEXT if selected else theme.TEXT3))
            painter.drawText(tag_rect, Qt.AlignCenter, metrics.elidedText(tag, Qt.ElideRight, int(tw - 8)))
            right -= tw + 7
        painter.setFont(self.font)
        metrics = QFontMetrics(self.font)
        max_w = max(10, right - x)
        text = metrics.elidedText(title, Qt.ElideRight, max_w)
        painter.setPen(title_color)
        painter.drawText(QRectF(x, rect.top(), max_w, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        painter.restore()


class AssetList(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setItemDelegate(AssetDelegate(self))
        self.setFrameShape(QListWidget.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setSpacing(0)
        self.setUniformItemSizes(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("QListWidget { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        self._drag_start: Optional[QPoint] = None
        self._drag_item: Optional[QListWidgetItem] = None

    def mousePressEvent(self, event) -> None:
        self._drag_start = event.position().toPoint()
        self._drag_item = self.itemAt(self._drag_start)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.LeftButton and self._drag_item is not None and self._drag_start is not None:
            if (event.position().toPoint() - self._drag_start).manhattanLength() > 8:
                self.start_action_drag(self._drag_item)
                self._drag_item = None
                self._drag_start = None
                return
        super().mouseMoveEvent(event)

    def start_action_drag(self, item: QListWidgetItem) -> None:
        if item.data(KIND_ROLE) != "action":
            return
        action = str(item.data(TITLE_ROLE) or "")
        if not action:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(ACTION_MIME, QByteArray(action.encode("utf-8")))
        mime.setText(action)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap(action))
        drag.setHotSpot(QPoint(18, 16))
        drag.exec(Qt.CopyAction)

    def _drag_pixmap(self, action: str) -> QPixmap:
        font = QFont(self.font())
        font.setPixelSize(12)
        metrics = QFontMetrics(font)
        width = min(260, metrics.horizontalAdvance(action) + 46)
        pix = QPixmap(width, 34)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(QColor(theme.ACCENT), 1.2))
        p.setBrush(QColor(theme.SURFACE3))
        p.drawRoundedRect(QRectF(0.5, 0.5, width - 1, 33), 8, 8)
        p.drawPixmap(QPoint(10, 9), icon_pixmap("play", 15, theme.ACCENT_TEXT))
        p.setFont(font)
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(32, 0, width - 40, 34), Qt.AlignVCenter | Qt.AlignLeft,
                   metrics.elidedText(action, Qt.ElideRight, width - 44))
        p.end()
        return pix
