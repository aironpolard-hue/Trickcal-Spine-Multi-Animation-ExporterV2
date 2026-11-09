from __future__ import annotations

import re
from functools import lru_cache
from typing import Dict, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF)

_WHITE = QColor(255, 255, 255)


def _p(pts):
    return QPolygonF([QPointF(x, y) for x, y in pts])


@lru_cache(maxsize=512)
def icon_pixmap(name: str, size: int = 20, color: str = "#E9EDF7") -> QPixmap:
    scale = 4
    px = QPixmap(size * scale, size * scale)
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(size * scale / 24.0, size * scale / 24.0)
    col = QColor(color)
    pen = QPen(col, 1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    _draw(p, name, col)
    p.end()
    px.setDevicePixelRatio(scale)
    return px


def icon(name: str, size: int = 20, color: str = "#E9EDF7") -> QIcon:
    return QIcon(icon_pixmap(name, size, color))


def _draw(p: QPainter, name: str, col: QColor) -> None:
    if name == "play":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPolygon(_p([(8.2, 5.2), (19.2, 12), (8.2, 18.8)]))
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(7.2, 5, 3.4, 14), 1.5, 1.5)
        p.drawRoundedRect(QRectF(13.4, 5, 3.4, 14), 1.5, 1.5)
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(6.5, 6.5, 11, 11), 2.5, 2.5)
    elif name == "folder":
        path = QPainterPath()
        path.moveTo(3.6, 8.2)
        path.lineTo(3.6, 7)
        path.quadTo(3.6, 5.6, 5.6, 5)
        path.lineTo(9.3, 5)
        path.lineTo(11.4, 7.1)
        path.lineTo(18.4, 7.1)
        path.quadTo(20.4, 7.1, 20.4, 9.1)
        path.lineTo(20.4, 17)
        path.quadTo(20.4, 19, 18.4, 19)
        path.lineTo(5.6, 19)
        path.quadTo(3.6, 19, 3.6, 17)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "folder-open":
        path = QPainterPath()
        path.moveTo(3.6, 8.2)
        path.lineTo(3.6, 7)
        path.quadTo(3.6, 5.6, 5.6, 5)
        path.lineTo(9.3, 5)
        path.lineTo(11.4, 7.1)
        path.lineTo(18.4, 7.1)
        path.quadTo(20.4, 7.1, 20.4, 9.1)
        path.lineTo(20.4, 9.5)
        p.drawPath(path)
        p.drawPath(_path("M4.3 9.4 H21 L19 18 C18.8 18.9 18 19.5 17.1 19.5 H5.8 C4.7 19.5 3.8 18.6 3.8 17.5 Z"))
    elif name == "folder-plus":
        _draw(p, "folder", col)
        p.drawLine(QPointF(12, 10.4), QPointF(12, 16.4))
        p.drawLine(QPointF(9, 13.4), QPointF(15, 13.4))
    elif name == "plus":
        p.drawLine(QPointF(12, 5.2), QPointF(12, 18.8))
        p.drawLine(QPointF(5.2, 12), QPointF(18.8, 12))
    elif name == "minus":
        p.drawLine(QPointF(5.2, 12), QPointF(18.8, 12))
    elif name == "search":
        p.drawEllipse(QRectF(4.5, 4.5, 12.2, 12.2))
        p.drawLine(QPointF(15.1, 15.1), QPointF(20.2, 20.2))
    elif name == "trash":
        p.drawLine(QPointF(4.6, 7.1), QPointF(19.4, 7.1))
        p.drawLine(QPointF(9.2, 4.4), QPointF(14.8, 4.4))
        p.drawPath(_path("M6.6 7.1 L7.5 18.4 C7.6 19.3 8.3 20 9.2 20 H14.8 C15.7 20 16.4 19.3 16.5 18.4 L17.4 7.1"))
        p.drawLine(QPointF(10.2, 10.2), QPointF(10.2, 16.8))
        p.drawLine(QPointF(13.8, 10.2), QPointF(13.8, 16.8))
    elif name == "settings":
        p.save()
        for i in range(8):
            p.save()
            p.translate(12, 12)
            p.rotate(45 * i)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(10.7, -9.9, 2.6, 4.2), 1.2, 1.2)
            p.restore()
        p.restore()
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(5.6, 5.6, 12.8, 12.8))
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.drawEllipse(QRectF(9.4, 9.4, 5.2, 5.2))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
    elif name == "export":
        p.drawPath(_path("M4.6 14 V18.2 C4.6 19.2 5.4 20 6.4 20 H17.6 C18.6 20 19.4 19.2 19.4 18.2 V14"))
        p.drawPath(_path("M12 16 V4.6 M7.6 9 L12 4.6 L16.4 9"))
    elif name == "download":
        p.drawPath(_path("M4.6 14 V18.2 C4.6 19.2 5.4 20 6.4 20 H17.6 C18.6 20 19.4 19.2 19.4 18.2 V14"))
        p.drawPath(_path("M12 4.6 V16 M7.6 11.6 L12 16 L16.4 11.6"))
    elif name == "upload":
        p.drawPath(_path("M4.6 14 V18.2 C4.6 19.2 5.4 20 6.4 20 H17.6 C18.6 20 19.4 19.2 19.4 18.2 V14"))
        p.drawPath(_path("M12 16 V4.6 M7.6 9 L12 4.6 L16.4 9"))
    elif name == "queue":
        for i, y in enumerate((7, 12, 17)):
            p.setBrush(col)
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(5.1, y), 1.4, 1.4)
            p.setPen(QPen(col, 1.7))
            p.drawLine(QPointF(8.6, y), QPointF(20 - i, y))
    elif name == "undo":
        p.drawPath(_path("M9.2 6.2 L4.4 10.7 L9.4 15.2"))
        p.drawPath(_path("M4.6 10.7 C6.6 6.2 12 4.2 16.2 6.2 C20.2 8.1 21.2 13 19.2 16.4 C17.3 19.6 12.9 20.4 9.6 18.7"))
    elif name == "redo":
        p.drawPath(_path("M14.8 6.2 L19.6 10.7 L14.6 15.2"))
        p.drawPath(_path("M19.4 10.7 C17.4 6.2 12 4.2 7.8 6.2 C3.8 8.1 2.8 13 4.8 16.4 C6.7 19.6 11.1 20.4 14.4 18.7"))
    elif name == "eye":
        p.drawPath(_path("M2.3 12 C4.9 6.9 8.3 4.9 12 4.9 C15.7 4.9 19.1 6.9 21.7 12 C19.1 17.1 15.7 19.1 12 19.1 C8.3 19.1 4.9 17.1 2.3 12 Z"))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(12, 12), 2.9, 2.9)
    elif name == "eye-off":
        p.drawPath(_path("M2.3 12 C4.9 6.9 8.3 4.9 12 4.9 C15.7 4.9 19.1 6.9 21.7 12 C19.1 17.1 15.7 19.1 12 19.1 C8.3 19.1 4.9 17.1 2.3 12 Z"))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(12, 12), 2.9, 2.9)
        p.setPen(QPen(QColor(13, 18, 28), 3.4))
        p.drawLine(QPointF(4.1, 20.4), QPointF(19.9, 3.6))
        p.setPen(QPen(col, 1.7))
        p.drawLine(QPointF(4.1, 20.4), QPointF(19.9, 3.6))
    elif name == "chevron-down":
        p.drawPath(_path("M7 9.6 L12 14.6 L17 9.6"))
    elif name == "chevron-up":
        p.drawPath(_path("M7 14.4 L12 9.4 L17 14.4"))
    elif name == "chevron-left":
        p.drawPath(_path("M14.4 7 L9.4 12 L14.4 17"))
    elif name == "chevron-right":
        p.drawPath(_path("M9.6 7 L14.6 12 L9.6 17"))
    elif name == "close":
        p.drawLine(QPointF(6.2, 6.2), QPointF(17.8, 17.8))
        p.drawLine(QPointF(17.8, 6.2), QPointF(6.2, 17.8))
    elif name == "check":
        p.drawPath(_path("M5.2 12.4 L9.7 16.9 L18.8 7.1"))
    elif name == "film":
        p.drawRoundedRect(QRectF(3.4, 5.2, 17.2, 13.6), 2.2, 2.2)
        p.drawLine(QPointF(7.4, 5.6), QPointF(7.4, 18.4))
        p.drawLine(QPointF(16.6, 5.6), QPointF(16.6, 18.4))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for y in (7.2, 10.9, 14.6):
            p.drawRoundedRect(QRectF(4.6, y, 1.5, 1.5), .4, .4)
            p.drawRoundedRect(QRectF(17.9, y, 1.5, 1.5), .4, .4)
    elif name == "monitor":
        p.drawRoundedRect(QRectF(3, 4.6, 18, 12.4), 2, 2)
        p.drawLine(QPointF(12, 17), QPointF(12, 20.2))
        p.drawLine(QPointF(8, 20.6), QPointF(16, 20.6))
    elif name == "sliders":
        p.drawLine(QPointF(4, 7), QPointF(20, 7))
        p.drawLine(QPointF(4, 12), QPointF(20, 12))
        p.drawLine(QPointF(4, 17), QPointF(20, 17))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(8.4, 7), 2, 2)
        p.drawEllipse(QPointF(15.2, 12), 2, 2)
        p.drawEllipse(QPointF(10.4, 17), 2, 2)
    elif name == "keyboard":
        p.drawRoundedRect(QRectF(2.6, 6.4, 18.8, 11.2), 2, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for x in (5.2, 8.2, 11.2, 14.2, 17.2):
            for y in (9, 12.4):
                p.drawRoundedRect(QRectF(x, y, 1.4, 1.4), .4, .4)
        p.drawRoundedRect(QRectF(7.2, 15.4, 9.6, 1.4), .6, .6)
    elif name == "refresh":
        p.drawPath(_path("M19.6 12 C19.6 7.8 16.2 4.4 12 4.4 C8.8 4.4 6.1 6.3 4.8 9"))
        p.drawPath(_path("M4.6 4.8 V9.2 H9"))
        p.drawPath(_path("M4.4 12 C4.4 16.2 7.8 19.6 12 19.6 C15.2 19.6 17.9 17.7 19.2 15"))
        p.drawPath(_path("M19.4 19.2 V14.8 H15"))
    elif name in ("zoom-in", "zoom-out"):
        p.drawEllipse(QRectF(4.5, 4.5, 12.2, 12.2))
        p.drawLine(QPointF(15.1, 15.1), QPointF(20.2, 20.2))
        p.drawLine(QPointF(7.9, 10.6), QPointF(13.3, 10.6))
        if name == "zoom-in":
            p.drawLine(QPointF(10.6, 7.9), QPointF(10.6, 13.3))
    elif name == "fit":
        p.drawPath(_path("M4 8.2 V4 H8.2 M15.8 4 H20 V8.2 M20 15.8 V20 H15.8 M8.2 20 H4 V15.8"))
    elif name == "target":
        p.drawEllipse(QRectF(3.9, 3.9, 16.2, 16.2))
        p.drawEllipse(QRectF(9.4, 9.4, 5.2, 5.2))
        p.drawLine(QPointF(12, 2.6), QPointF(12, 5.8))
        p.drawLine(QPointF(12, 18.2), QPointF(12, 21.4))
        p.drawLine(QPointF(2.6, 12), QPointF(5.8, 12))
        p.drawLine(QPointF(18.2, 12), QPointF(21.4, 12))
    elif name == "sparkles":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawPolygon(_p([(10, 3.4), (12.1, 8.2), (16.9, 10.3), (12.1, 12.4), (10, 17.2), (7.9, 12.4), (3.1, 10.3), (7.9, 8.2)]))
        p.drawPolygon(_p([(18.2, 14.2), (19.2, 16.5), (21.5, 17.5), (19.2, 18.5), (18.2, 20.8), (17.2, 18.5), (14.9, 17.5), (17.2, 16.5)]))
    elif name == "save":
        p.drawPath(_path("M5 4.6 H15.4 L19 8.2 V19 C19 19.7 18.4 20.3 17.7 20.3 H6.3 C5.6 20.3 5 19.7 5 19 Z"))
        p.drawRoundedRect(QRectF(8.2, 13.2, 7.6, 7.1), 1, 1)
        p.drawPath(_path("M8.4 4.8 V9.2 H14.2 V4.8"))
    elif name == "copy":
        p.drawRoundedRect(QRectF(8.2, 8.2, 11.8, 11.8), 2, 2)
        p.drawRoundedRect(QRectF(4.4, 4.4, 11.8, 11.8), 2, 2)
    elif name == "paste":
        p.drawRoundedRect(QRectF(5.2, 4.6, 13.6, 16), 2, 2)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(9.2, 3.2, 5.6, 2.8), 1.2, 1.2)
        p.setPen(QPen(col, 1.7))
        p.drawLine(QPointF(8.6, 9.4), QPointF(15.4, 9.4))
        p.drawLine(QPointF(8.6, 12.8), QPointF(15.4, 12.8))
        p.drawLine(QPointF(8.6, 16.2), QPointF(13.2, 16.2))
    elif name == "scissors":
        p.drawEllipse(QRectF(4, 4.7, 4.4, 4.4))
        p.drawEllipse(QRectF(4, 14.9, 4.4, 4.4))
        p.drawLine(QPointF(8.1, 8.4), QPointF(20, 18))
        p.drawLine(QPointF(8.1, 15.6), QPointF(20, 6))
    elif name == "info":
        p.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(12, 7.9), 1.15, 1.15)
        p.setPen(QPen(col, 1.7))
        p.drawLine(QPointF(12, 11), QPointF(12, 16.6))
    elif name == "warning":
        p.drawPath(_path("M12 3.6 L21 19.4 H3 Z"))
        p.drawLine(QPointF(12, 9), QPointF(12, 14.2))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(12, 17.1), 1.05, 1.05)
    elif name in ("success", "error"):
        p.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
        if name == "success":
            p.drawPath(_path("M7.5 12.4 L10.7 15.6 L16.6 9"))
        else:
            p.drawLine(QPointF(8.6, 8.6), QPointF(15.4, 15.4))
            p.drawLine(QPointF(15.4, 8.6), QPointF(8.6, 15.4))
    elif name == "image":
        p.drawRoundedRect(QRectF(3.2, 4.8, 17.6, 14.4), 2.2, 2.2)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QPointF(8.1, 9.1), 1.6, 1.6)
        p.setPen(QPen(col, 1.7))
        p.drawPath(_path("M4.6 17 L10 11.4 L13.6 15 L16 12.4 L19.6 16.4"))
    elif name == "layers":
        p.drawPath(_path("M12 3.6 L20.6 8.2 L12 12.8 L3.4 8.2 Z"))
        p.drawPath(_path("M3.4 12.1 L12 16.7 L20.6 12.1"))
        p.drawPath(_path("M3.4 15.9 L12 20.5 L20.6 15.9"))
    elif name == "user":
        p.drawEllipse(QRectF(8.1, 4.1, 7.8, 7.8))
        p.drawPath(_path("M4.6 20 C4.6 15.9 7.9 13.6 12 13.6 C16.1 13.6 19.4 15.9 19.4 20"))
    elif name == "more":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for x in (5.6, 12, 18.4):
            p.drawEllipse(QPointF(x, 12), 1.5, 1.5)
    elif name == "wave":
        p.drawPath(_path("M2.4 12 C5.2 5.6 8.4 5.6 11.2 12 C14 18.4 17.2 18.4 20 12"))
    elif name == "clock":
        p.drawEllipse(QRectF(3.8, 3.8, 16.4, 16.4))
        p.drawPath(_path("M12 7.3 V12.4 L16.2 14.8"))
    elif name == "palette":
        p.drawPath(_path("M12 3.4 C6.6 3.4 2.8 7.2 2.8 12 C2.8 16.8 6.6 20.6 12 20.6 C13.6 20.6 14.3 19.6 14.3 18.6 C14.3 17.8 13.8 17.2 13.8 16.5 C13.8 15.7 14.4 15.1 15.3 15.1 H17.1 C19.2 15.1 21.2 13.6 21.2 11.1 C21.2 6.8 17.1 3.4 12 3.4 Z"))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for x, y in ((7.4, 9.2), (11, 6.8), (6.2, 14), (8.8, 17.4)):
            p.drawEllipse(QPointF(x, y), 1.15, 1.15)
    elif name == "grid":
        for x in (4.2, 13.4):
            for y in (4.2, 13.4):
                p.drawRoundedRect(QRectF(x, y, 6.4, 6.4), 1.4, 1.4)
    elif name == "list":
        p.drawLine(QPointF(8.4, 6.4), QPointF(20, 6.4))
        p.drawLine(QPointF(8.4, 12), QPointF(20, 12))
        p.drawLine(QPointF(8.4, 17.6), QPointF(20, 17.6))
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        for y in (6.4, 12, 17.6):
            p.drawEllipse(QPointF(4.4, y), 1.4, 1.4)
    elif name == "maximize":
        p.drawPath(_path("M4 8.2 V4 H8.2 M15.8 4 H20 V8.2 M20 15.8 V20 H15.8 M8.2 20 H4 V15.8"))


def _path(d: str) -> QPainterPath:
    """Minimal absolute SVG-ish path parser: M/L/H/V/C/Q/Z."""
    tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
    path = QPainterPath()
    i = 0
    cmd = ""
    x = y = 0.0

    def num():
        nonlocal i
        v = float(tokens[i])
        i += 1
        return v

    while i < len(tokens):
        t = tokens[i]
        if len(t) == 1 and t.isalpha():
            cmd = t
            i += 1
            if cmd == "Z":
                path.closeSubpath()
                continue
            continue
        if cmd == "M":
            x, y = num(), num()
            path.moveTo(x, y)
            cmd = "L"
        elif cmd == "L":
            x, y = num(), num()
            path.lineTo(x, y)
        elif cmd == "H":
            x = num()
            path.lineTo(x, y)
        elif cmd == "V":
            y = num()
            path.lineTo(x, y)
        elif cmd == "C":
            x1, y1, x2, y2, x, y = num(), num(), num(), num(), num(), num()
            path.cubicTo(x1, y1, x2, y2, x, y)
        elif cmd == "Q":
            x1, y1, x, y = num(), num(), num(), num()
            path.quadTo(x1, y1, x, y)
        else:
            i += 1
    return path
