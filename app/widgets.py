from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .icons import icon_pixmap


class ElidedLabel(QWidget):
    def __init__(self, text: str = "", parent=None, color: str = theme.TEXT2, size: int = 11):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self._font = QFont(theme.FONT_FAMILY)
        self._font.setPixelSize(size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(20)
        self.setFixedHeight(size + 8)

    def setText(self, text: str) -> None:
        if text == self._text:
            return
        self._text = text or ""
        self.update()

    def text(self) -> str:
        return self._text

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setFont(self._font)
        p.setPen(self._color)
        metrics = QFontMetrics(self._font)
        text = metrics.elidedText(self._text, Qt.ElideRight, max(0, self.width() - 2))
        p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()


class Toast(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            f"QFrame#Card {{ background: {theme.SURFACE3}; border: 1px solid {theme.LINE3}; border-radius: 10px; }}"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 14, 10)
        layout.setSpacing(9)
        self.icon = QLabel()
        layout.addWidget(self.icon)
        self.label = QLabel("")
        self.label.setStyleSheet(f"color: {theme.TEXT}; font-size: 12px;")
        self.label.setWordWrap(True)
        self.label.setMaximumWidth(320)
        layout.addWidget(self.label)
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self._kind = "info"

    def show_message(self, text: str, kind: str = "info") -> None:
        names = {"info": "info", "success": "success", "warning": "warning", "error": "error"}
        colors = {"info": theme.ACCENT_TEXT, "success": theme.GREEN,
                  "warning": theme.AMBER, "error": theme.RED}
        name = names.get(kind, "info")
        self.icon.setPixmap(icon_pixmap(name, 16, colors.get(kind, theme.ACCENT_TEXT)))
        self.label.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            self.move(parent.width() - self.width() - 22,
                      parent.height() - self.height() - 44)
        self.show()
        self.raise_()
        self._timer.start(3400)


from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Signal


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._pos = 1.0 if checked else 0.0
        self.setFixedSize(40, 22)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"posValue", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if value == self._checked:
            return
        self._checked = value
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if value else 0.0)
        self._anim.start()
        self.toggled.emit(value)

    def setCheckedSilently(self, value: bool) -> None:
        self._checked = value
        self._pos = 1.0 if value else 0.0
        self.update()

    def getPosValue(self) -> float:
        return self._pos

    def setPosValue(self, value: float) -> None:
        self._pos = value
        self.update()

    posValue = Property(float, getPosValue, setPosValue)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.isEnabled():
            self.setChecked(not self._checked)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        h = self.height()
        w = self.width()
        if not self.isEnabled():
            track = QColor(theme.SURFACE3)
            border = QColor(theme.LINE2)
            knob_color = QColor("#59637A")
        else:
            track = QColor(theme.ACCENT if self._checked else theme.SURFACE4)
            border = QColor(theme.ACCENT_HOVER if self._checked else theme.LINE3)
            knob_color = QColor("#FFFFFF")
        p.setPen(QPen(border, 1))
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), (h - 1) / 2, (h - 1) / 2)
        knob = h - 6
        x = 3 + (w - knob - 6) * max(0.0, min(1.0, self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(knob_color)
        p.drawEllipse(QRectF(x, 3, knob, knob))
        p.end()
