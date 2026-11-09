from __future__ import annotations

import math
from typing import Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPolygonF)
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import theme
from .icons import icon, icon_pixmap
from .lists import ACTION_MIME, DOT_COLORS
from .model import Clip, clamp, clip_index_at, clip_start, insertion_index_at, total_duration
from .state import EditorState


class TimelineWidget(QWidget):
    step_settings_requested = Signal()
    message = Signal(str)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setMinimumHeight(130)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAcceptDrops(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.pps = 90.0
        self.scroll = 0.0
        self.hover_index = -1
        self.hover_edge = ""
        self._drag = ""
        self._press = QPointF()
        self._start_x = 0.0
        self._start_duration = 0.0
        self._start_index = -1
        self._start_selection: set[int] = set()
        self._box_current = QPointF()
        self._box_active = False
        self._box_additive = False
        self._move_target = -1
        self._scroll_drag = False
        self._scroll_offset = 0.0
        self._click_candidate = False
        self._drop_index = -1
        self._mouse = QPointF(-100, -100)
        self._content = QRectF()
        self._ruler = QRectF()
        self._track = QRectF()
        self._scrollbar = QRectF()

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------

    def _update_geometry(self) -> None:
        margin = 14.0
        self._content = QRectF(margin, 4, max(20, self.width() - margin * 2), max(20, self.height() - 8))
        self._ruler = QRectF(self._content.left(), self._content.top(), self._content.width(), 22)
        self._scrollbar = QRectF(self._content.left(), self._content.bottom() - 8, self._content.width(), 6)
        self._track = QRectF(self._content.left(), self._ruler.bottom() + 2, self._content.width(),
                             max(40, self._content.height() - 22 - 16))

    def _time_to_x(self, time: float) -> float:
        return self._content.left() + (time - self.scroll) * self.pps

    def _x_to_time(self, x: float) -> float:
        return self.scroll + (x - self._content.left()) / max(1.0, self.pps)

    def _visible(self) -> float:
        return max(0.1, self._content.width() / max(1.0, self.pps))

    def _max_scroll(self) -> float:
        total = self.state.total_duration()
        return max(0.0, max(total, self._visible()) - self._visible())

    def _clamp_scroll(self) -> None:
        self.scroll = clamp(self.scroll, 0.0, self._max_scroll())

    def _clip_rect(self, index: int) -> QRectF:
        clips = self.state.timeline
        start = clip_start(clips, index)
        w = max(7.0, clips[index].duration * self.pps)
        x = self._time_to_x(start)
        return QRectF(x, self._track.top() + 7, w, max(24, self._track.height() - 14))

    def _clip_at(self, pos: QPointF) -> Tuple[int, str]:
        y = pos.y()
        if not (self._track.top() - 2 <= y <= self._track.bottom() + 2):
            return -1, ""
        for i in range(len(self.state.timeline)):
            rect = self._clip_rect(i)
            if rect.left() - 1 <= pos.x() <= rect.right() + 1:
                edge = 7.0
                if pos.x() <= rect.left() + edge:
                    return i, "left"
                if pos.x() >= rect.right() - edge:
                    return i, "right"
                clip = self.state.timeline[i]
                if i > 0 and clip.transition_enabled and clip.transition_duration > 0:
                    mix_x = rect.left() + min(rect.width(), clip.transition_duration * self.pps)
                    if (rect.left() + edge + 3 < mix_x < rect.right() - edge - 3
                            and abs(pos.x() - mix_x) <= 6):
                        return i, "mix"
                return i, "body"
        return -1, ""

    def _scrollbar_thumb(self) -> QRectF:
        total = max(self.state.total_duration(), self._visible())
        thumb_w = max(36.0, self._scrollbar.width() * self._visible() / max(0.001, total))
        max_scroll = self._max_scroll()
        ratio = 0.0 if max_scroll <= 0 else self.scroll / max_scroll
        x = self._scrollbar.left() + (self._scrollbar.width() - thumb_w) * ratio
        return QRectF(x, self._scrollbar.top(), thumb_w, self._scrollbar.height())

    def ensure_playhead(self) -> None:
        visible = self._visible()
        t = self.state.playhead
        if t < self.scroll + visible * 0.05:
            self.scroll = max(0.0, t - visible * 0.10)
        elif t > self.scroll + visible * 0.90:
            self.scroll = t - visible * 0.82
        self._clamp_scroll()

    def fit(self) -> None:
        total = max(0.5, self.state.total_duration())
        self.pps = clamp((self._content.width() - 30) / total, 15, 400)
        self.scroll = 0
        self.update()

    def zoom(self, factor: float, anchor: Optional[float] = None) -> None:
        ax = anchor if anchor is not None else self._content.center().x()
        anchor_time = self._x_to_time(ax)
        self.pps = clamp(self.pps * factor, 15, 400)
        self.scroll = anchor_time - (ax - self._content.left()) / self.pps
        self._clamp_scroll()
        self.update()

    # ------------------------------------------------------------------
    # painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        self._update_geometry()
        if self.state.playing and self.state.settings.follow_playhead:
            self.ensure_playhead()
        self._clamp_scroll()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        self._draw_track(p)
        self._draw_ruler(p)
        self._draw_clips(p)
        self._draw_playhead(p)
        if self._drop_index >= 0:
            self._draw_drop(p)
        if self._box_active:
            self._draw_box(p)
        if not self.state.timeline:
            self._draw_empty(p)
        self._draw_scrollbar(p)
        self._draw_hover(p)
        p.end()

    def _draw_track(self, p: QPainter) -> None:
        path = QPainterPath()
        path.addRoundedRect(self._track, 9, 9)
        p.setPen(QPen(QColor(theme.LINE2), 1))
        p.setBrush(QColor(theme.CANVAS))
        p.drawPath(path)
        # grid
        step = self._tick_step()
        t = math.floor(self.scroll / step) * step
        p.setPen(QPen(QColor(255, 255, 255, 9), 1))
        while t <= self.scroll + self._visible() + step:
            x = self._time_to_x(t)
            if self._track.left() < x < self._track.right():
                p.drawLine(QPointF(x, self._track.top() + 1), QPointF(x, self._track.bottom() - 1))
            t += step

    def _draw_ruler(self, p: QPainter) -> None:
        step = self._tick_step()
        t = math.floor(self.scroll / step) * step
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(10)
        p.setFont(font)
        metrics = QFontMetrics(font)
        while t <= self.scroll + self._visible() + step:
            x = self._time_to_x(t)
            if self._ruler.left() <= x <= self._ruler.right():
                major = abs(round(t / step) % 2) == 0
                p.setPen(QPen(QColor(255, 255, 255, 48 if major else 22), 1))
                p.drawLine(QPointF(x, self._ruler.bottom() - (8 if major else 4)),
                           QPointF(x, self._ruler.bottom()))
                if major or step * self.pps > 90:
                    text = f"{t:.0f}s" if step >= 1 else f"{t:.2f}s"
                    p.setPen(QColor(theme.TEXT3))
                    p.drawText(QPointF(x + 4, self._ruler.top() + 10), text)
            t += step
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        p.drawLine(QPointF(self._content.left(), self._ruler.bottom()),
                   QPointF(self._content.right(), self._ruler.bottom()))

    def _tick_step(self) -> float:
        raw = 70.0 / max(1.0, self.pps)
        for step in (0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300):
            if step >= raw:
                return step
        return 600

    def _draw_clips(self, p: QPainter) -> None:
        clips = self.state.timeline
        p.save()
        p.setClipRect(self._track.adjusted(1, 0, -1, 0))
        for i, clip in enumerate(clips):
            rect = self._clip_rect(i)
            if rect.right() < self._track.left() - 4 or rect.left() > self._track.right() + 4:
                continue
            selected = i in self.state.selected_indices
            hover = i == self.hover_index
            base = QColor(DOT_COLORS[abs(hash(clip.action)) % len(DOT_COLORS)])
            if selected:
                fill_top = QColor(theme.ACCENT)
                fill_top.setAlpha(62)
                fill_bottom = QColor(theme.ACCENT)
                fill_bottom.setAlpha(28)
                border = QColor(theme.ACCENT_HOVER)
                border.setAlpha(235)
                text_color = QColor(theme.TEXT)
            elif hover:
                fill_top = QColor(base)
                fill_top.setAlpha(50)
                fill_bottom = QColor(base)
                fill_bottom.setAlpha(24)
                border = QColor(base)
                border.setAlpha(180)
                text_color = QColor(theme.TEXT)
            else:
                fill_top = QColor(base)
                fill_top.setAlpha(34)
                fill_bottom = QColor(base)
                fill_bottom.setAlpha(16)
                border = QColor(base)
                border.setAlpha(110)
                text_color = QColor(theme.TEXT2)
            grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            grad.setColorAt(0, fill_top)
            grad.setColorAt(1, fill_bottom)
            path = QPainterPath()
            path.addRoundedRect(rect, 7, 7)
            p.setPen(QPen(border, 1.1))
            p.setBrush(grad)
            p.drawPath(path)
            # top accent line
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(base if not selected else theme.ACCENT_HOVER))
            p.drawRoundedRect(QRectF(rect.left() + 3, rect.top() + 1.5, max(0, rect.width() - 6), 2), 1, 1)
            if rect.width() > 18 and (hover or selected):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(255, 255, 255, 115))
                p.drawRoundedRect(QRectF(rect.left() + 3, rect.top() + 8, 2.5, max(4, rect.height() - 16)), 1.2, 1.2)
                p.drawRoundedRect(QRectF(rect.right() - 5.5, rect.top() + 8, 2.5, max(4, rect.height() - 16)), 1.2, 1.2)
            # transition band
            if i > 0 and clip.transition_enabled and clip.transition_duration > 0:
                band_w = min(rect.width(), clip.transition_duration * self.pps)
                if band_w > 2:
                    p.setBrush(QColor(theme.CYAN))
                    p.setPen(Qt.NoPen)
                    band = QPainterPath()
                    band.addRoundedRect(QRectF(rect.left(), rect.top(), band_w, rect.height()), 6, 6)
                    c = QColor(theme.CYAN)
                    c.setAlpha(22)
                    p.setBrush(c)
                    p.drawPath(band)
                    if band_w > 6:
                        mx = rect.left() + band_w
                        p.setPen(QPen(QColor(214, 248, 255, 210), 1.15))
                        p.drawLine(QPointF(mx, rect.top() + 4), QPointF(mx, rect.bottom() - 4))
                        p.setPen(Qt.NoPen)
                        p.setBrush(QColor(214, 248, 255, 230))
                        p.drawEllipse(QPointF(mx, rect.center().y()), 2.2, 2.2)
            if rect.width() > 28:
                font = QFont(theme.FONT_FAMILY)
                font.setPixelSize(11)
                p.setFont(font)
                metrics = QFontMetrics(font)
                p.setPen(text_color)
                text = metrics.elidedText(clip.action, Qt.ElideRight, int(rect.width() - 16))
                p.drawText(QRectF(rect.left() + 8, rect.top() + 6, rect.width() - 16, 18),
                           Qt.AlignVCenter | Qt.AlignLeft, text)
                if rect.height() > 45 and rect.width() > 64:
                    p.setPen(QColor(theme.TEXT3 if not selected else theme.ACCENT_TEXT))
                    p.drawText(QRectF(rect.left() + 8, rect.bottom() - 19, rect.width() - 16, 15),
                               Qt.AlignVCenter | Qt.AlignLeft, f"{clip.duration:.2f}s")
        p.restore()

    def _draw_playhead(self, p: QPainter) -> None:
        x = self._time_to_x(self.state.playhead)
        if x < self._content.left() or x > self._content.right():
            return
        p.setPen(QPen(QColor(theme.ACCENT_HOVER), 1.4))
        p.drawLine(QPointF(x, self._ruler.top()), QPointF(x, self._track.bottom() + 1))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawRoundedRect(QRectF(x - 6, self._ruler.top() + 1, 12, 7), 3.5, 3.5)
        p.drawEllipse(QPointF(x, self._ruler.top() + 4), 2.5, 2.5)

    def _draw_drop(self, p: QPainter) -> None:
        clips = self.state.timeline
        if self._drop_index < 0:
            return
        if self._drop_index >= len(clips):
            t = total_duration(clips)
        else:
            t = clip_start(clips, self._drop_index)
        x = clamp(self._time_to_x(t), self._track.left(), self._track.right())
        p.setPen(QPen(QColor(theme.GREEN), 1.6))
        p.drawLine(QPointF(x, self._track.top() - 2), QPointF(x, self._track.bottom() + 2))
        p.setBrush(QColor(theme.GREEN))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(x, self._track.top() - 2), 4, 4)

    def _draw_box(self, p: QPainter) -> None:
        rect = QRectF(self._press, self._box_current).normalized()
        if rect.width() < 2 or rect.height() < 2:
            return
        fill = QColor(theme.ACCENT)
        fill.setAlpha(28)
        p.setPen(QPen(QColor(theme.ACCENT_HOVER), 1, Qt.DashLine))
        p.setBrush(fill)
        p.drawRect(rect)

    def _draw_empty(self, p: QPainter) -> None:
        rect = self._track.adjusted(14, 14, -14, -14)
        pen = QPen(QColor(255, 255, 255, 28), 1, Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rect, 8, 8)
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(12)
        p.setFont(font)
        p.setPen(QColor(theme.TEXT3))
        p.drawText(rect.adjusted(0, 0, 0, 10), Qt.AlignCenter, "把左侧动作拖进时间轴")
        small = QFont(font)
        small.setPixelSize(10)
        p.setFont(small)
        p.setPen(QColor(theme.TEXT4))
        p.drawText(rect.adjusted(0, 26, 0, 0), Qt.AlignCenter, "双击动作也可以添加到播放头位置")

    def _draw_scrollbar(self, p: QPainter) -> None:
        if self._max_scroll() <= 0.001:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(self._scrollbar, 3, 3)
        thumb = self._scrollbar_thumb()
        p.setBrush(QColor(255, 255, 255, 70))
        p.drawRoundedRect(thumb, 3, 3)

    def _draw_hover(self, p: QPainter) -> None:
        if self.hover_index < 0 or self._drag or self._box_active:
            return
        if not (0 <= self.hover_index < len(self.state.timeline)):
            return
        clip = self.state.timeline[self.hover_index]
        rect = self._clip_rect(self.hover_index)
        text = f"{clip.action}   {clip.duration:.2f}s"
        font = QFont(theme.FONT_FAMILY)
        font.setPixelSize(10)
        p.setFont(font)
        metrics = QFontMetrics(font)
        w = metrics.horizontalAdvance(text) + 18
        x = min(max(8, self._mouse.x() + 12), self.width() - w - 8)
        y = min(max(8, self._mouse.y() - 28), self.height() - 28)
        path = QPainterPath()
        path.addRoundedRect(QRectF(x, y, w, 22), 6, 6)
        p.setPen(QPen(QColor(theme.LINE3), 1))
        p.setBrush(QColor(theme.SURFACE3))
        p.drawPath(path)
        p.setPen(QColor(theme.TEXT2))
        p.drawText(QRectF(x, y, w, 22), Qt.AlignCenter, text)

    # ------------------------------------------------------------------
    # mouse
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        self._update_geometry()
        pos = QPointF(event.position())
        self._mouse = pos
        if event.button() == Qt.RightButton:
            index, _ = self._clip_at(pos)
            if index >= 0:
                if index not in self.state.selected_indices:
                    self.state.select_only(index)
                self._clip_menu(index, event.globalPosition().toPoint())
            else:
                self._empty_menu(pos, event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        self._press = pos
        self._click_candidate = False
        if self._max_scroll() > 0 and self._scrollbar.adjusted(-4, -6, 4, 6).contains(pos):
            thumb = self._scrollbar_thumb()
            if thumb.contains(pos):
                self._scroll_offset = pos.x() - thumb.left()
            else:
                self._scroll_offset = thumb.width() / 2
                self._scroll_to(pos.x(), thumb.width())
            self._drag = "scrollbar"
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self._ruler.contains(pos):
            self._drag = "playhead"
            self.state.seek(self._x_to_time(pos.x()))
            self.state.selection_changed.emit()
            self.update()
            return
        index, edge = self._clip_at(pos)
        if index >= 0:
            if event.modifiers() & Qt.ControlModifier:
                self.state.toggle_selection(index)
            elif index not in self.state.selected_indices:
                self.state.select_only(index)
            self._start_index = index
            self._start_duration = self.state.timeline[index].duration
            self._start_x = pos.x()
            self._start_selection = set(self.state.selected_indices)
            if edge in ("left", "right"):
                self._drag = "trim-" + edge
                self.state.checkpoint("trim")
                self.setCursor(Qt.SizeHorCursor)
            elif edge == "mix":
                self._drag = "mix"
                self._start_duration = self.state.timeline[index].transition_duration
                self.state.checkpoint("transition")
                self.setCursor(Qt.SizeHorCursor)
            else:
                self._drag = "move"
                self._move_target = insertion_index_at(self.state.timeline, self._x_to_time(pos.x()))
                self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return
        if self._track.contains(pos):
            self._drag = "box"
            self._box_active = True
            self._box_current = pos
            self._box_additive = bool(event.modifiers() & Qt.ControlModifier)
            if not self._box_additive:
                self.state.set_selection([])
            self._click_candidate = True
            self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        self._mouse = pos
        if self._drag:
            if self._drag == "scrollbar":
                self._scroll_to(pos.x(), self._scrollbar_thumb().width())
            elif self._drag == "playhead":
                self.state.seek(self._x_to_time(pos.x()))
                self.state.selection_changed.emit()
            elif self._drag.startswith("trim-"):
                delta = (pos.x() - self._start_x) / max(1.0, self.pps)
                if self._drag == "trim-left":
                    duration = self._start_duration - delta
                else:
                    duration = self._start_duration + delta
                self.state.update_clip_duration_live(self._start_index, duration)
            elif self._drag == "mix":
                delta = (pos.x() - self._start_x) / max(1.0, self.pps)
                self.state.update_transition_duration_live(self._start_index,
                                                           self._start_duration + delta)
            elif self._drag == "move":
                self._move_target = insertion_index_at(self.state.timeline, self._x_to_time(pos.x()))
            elif self._drag == "box":
                self._box_current = pos
                if abs(pos.x() - self._press.x()) > 4 or abs(pos.y() - self._press.y()) > 4:
                    self._click_candidate = False
            self.update()
            return
        index, edge = self._clip_at(pos)
        self.hover_index = index
        self.hover_edge = edge
        if edge in ("left", "right", "mix"):
            self.setCursor(Qt.SizeHorCursor)
        elif index >= 0:
            self.setCursor(Qt.OpenHandCursor)
        elif self._track.contains(pos):
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        pos = QPointF(event.position())
        self._mouse = pos
        mode = self._drag
        self._drag = ""
        self.setCursor(Qt.ArrowCursor)
        if mode == "scrollbar":
            return
        if mode == "playhead":
            return
        if mode == "mix":
            self.state.finish_live_edit("过渡时长已修改")
            self.update()
            return
        if mode.startswith("trim-"):
            self.state.finish_live_edit("片段时长已修改")
            self.update()
            return
        if mode == "move":
            self._drop_index = -1
            if self._move_target >= 0:
                self.state.move_selected(self._move_target)
            self.update()
            return
        if mode == "box":
            self._box_active = False
            rect = QRectF(self._press, self._box_current).normalized()
            if rect.width() >= 4 and rect.height() >= 4:
                hits = []
                for i in range(len(self.state.timeline)):
                    if self._clip_rect(i).intersects(rect):
                        hits.append(i)
                if self._box_additive:
                    selection = set(self.state.selected_indices)
                    for i in hits:
                        if i in selection:
                            selection.remove(i)
                        else:
                            selection.add(i)
                    self.state.set_selection(selection)
                else:
                    self.state.set_selection(hits)
                self.state.message.emit(f"已选择 {len(self.state.selected_indices)} 个片段" if self.state.selected_indices else "没有框选到片段")
                self.update()
                return
            self._click_candidate = True
        if self._click_candidate:
            self.state.seek(self._x_to_time(pos.x()))
            index = self.state.clip_at()
            if index >= 0:
                self.state.select_only(index)
            self.state.selection_changed.emit()
            self.update()

    def mouseDoubleClickEvent(self, event) -> None:
        index, _ = self._clip_at(QPointF(event.position()))
        if index >= 0:
            self.state.select_only(index)
            self.step_settings_requested.emit()

    def wheelEvent(self, event) -> None:
        self._update_geometry()
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            self.zoom(1.18 if delta > 0 else 0.85, event.position().x())
        else:
            visible = self._visible()
            self.scroll -= math.copysign(visible * 0.10, delta) if delta else 0
            self._clamp_scroll()
            self.update()
        event.accept()

    def _scroll_to(self, x: float, thumb_w: float) -> None:
        track = max(1.0, self._scrollbar.width() - thumb_w)
        ratio = clamp((x - self._scrollbar.left() - self._scroll_offset) / track, 0, 1)
        self.scroll = ratio * self._max_scroll()
        self.update()

    def _clip_menu(self, index: int, global_pos) -> None:
        menu = QMenu(self)
        menu.addAction(icon("sliders"), "片段设置…", lambda: self.step_settings_requested.emit())
        menu.addAction(icon("copy"), "复制", self.state.copy_selected)
        menu.addAction(icon("scissors"), "剪切", self.state.cut_selected)
        menu.addSeparator()
        menu.addAction(icon("trash"), "删除片段", self.state.remove_selected)
        menu.exec(global_pos)

    def _empty_menu(self, pos: QPointF, global_pos) -> None:
        menu = QMenu(self)
        menu.addAction(icon("paste"), "在此粘贴", self._paste_here)
        menu.addSeparator()
        menu.addAction(icon("fit"), "适配所有片段", self.fit)
        menu.exec(global_pos)

    def _paste_here(self) -> None:
        self.state.paste()

    # ------------------------------------------------------------------
    # drag&drop from action list
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(ACTION_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(ACTION_MIME):
            return
        self._update_geometry()
        pos = event.position()
        t = self._x_to_time(clamp(pos.x(), self._track.left(), self._track.right()))
        self._drop_index = insertion_index_at(self.state.timeline, t)
        self.update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_index = -1
        self.update()

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(ACTION_MIME):
            return
        data = bytes(event.mimeData().data(ACTION_MIME)).decode("utf-8", "replace")
        self._update_geometry()
        pos = event.position()
        t = self._x_to_time(clamp(pos.x(), self._track.left(), self._track.right()))
        index = insertion_index_at(self.state.timeline, t)
        self._drop_index = -1
        if data:
            self.state.add_action(data, index)
        event.acceptProposedAction()


class TimelinePanel(QFrame):
    step_settings_requested = Signal()

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Panel")
        self._last_time_text = ""
        self._last_icon = ""
        self._syncing_transition = False
        self._build()
        self._connect()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QHBoxLayout()
        header.setContentsMargins(14, 6, 10, 4)
        header.setSpacing(6)
        film = QLabel()
        film.setPixmap(icon("film", 16, theme.TEXT3).pixmap(16, 16))
        header.addWidget(film)
        title = QLabel("时间轴")
        title.setProperty("kind", "medium")
        header.addWidget(title)
        self.clip_count = QLabel("0 片段")
        self.clip_count.setProperty("kind", "faint")
        header.addWidget(self.clip_count)
        self.selected_count = QLabel("")
        self.selected_count.setProperty("kind", "accent")
        header.addWidget(self.selected_count)
        header.addStretch(1)
        self.undo_button = self._tool("undo", "撤销 (Ctrl+Z)", self.state.undo)
        self.redo_button = self._tool("redo", "重做 (Ctrl+Y)", self.state.redo)
        self.copy_button = self._tool("copy", "复制 (Ctrl+C)", self.state.copy_selected)
        self.cut_button = self._tool("scissors", "剪切 (Ctrl+X)", self.state.cut_selected)
        self.paste_button = self._tool("paste", "粘贴 (Ctrl+V)", self.state.paste)
        self.step_button = QPushButton("片段")
        self.step_button.setProperty("kind", "ghost")
        self.step_button.setIcon(icon("sliders", 15, theme.TEXT2))
        self.step_button.setFixedHeight(28)
        self.step_button.clicked.connect(lambda: self.step_settings_requested.emit())
        self.delete_button = self._tool("trash", "删除 (Delete)", self.state.remove_selected)
        for b in (self.undo_button, self.redo_button, self.copy_button, self.cut_button,
                  self.paste_button, self.step_button, self.delete_button):
            header.addWidget(b)
        root.addLayout(header)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(12, 2, 12, 4)
        toolbar.setSpacing(8)
        self.play_button = QPushButton()
        self.play_button.setProperty("kind", "primary")
        self.play_button.setFixedSize(36, 36)
        self.play_button.setIcon(icon("play", 18, "#FFFFFF"))
        self.play_button.clicked.connect(self.state.toggle_play)
        toolbar.addWidget(self.play_button)
        self.time_edit = QLineEdit("0.000")
        self.time_edit.setFixedWidth(92)
        self.time_edit.setAlignment(Qt.AlignRight)
        self.time_edit.returnPressed.connect(self._commit_time)
        toolbar.addWidget(self.time_edit)
        total_label = QLabel("s")
        total_label.setProperty("kind", "faint")
        toolbar.addWidget(total_label)
        self.total_label = QLabel("总 0.000s")
        self.total_label.setProperty("kind", "faint")
        toolbar.addWidget(self.total_label)
        self.step_label = QLabel("空时间轴")
        self.step_label.setProperty("kind", "small")
        self.step_label.setMinimumWidth(80)
        toolbar.addWidget(self.step_label, 1)
        self.transition_label = QLabel("过渡")
        self.transition_label.setProperty("kind", "faint")
        toolbar.addWidget(self.transition_label)
        self.transition_spin = QDoubleSpinBox()
        self.transition_spin.setRange(0.0, 20.0)
        self.transition_spin.setDecimals(2)
        self.transition_spin.setSingleStep(0.05)
        self.transition_spin.setSuffix("s")
        self.transition_spin.setFixedWidth(82)
        self.transition_spin.setToolTip("选中片段的过渡时长；也可直接拖动时间轴上的青色过渡线")
        self.transition_spin.valueChanged.connect(self._apply_transition)
        toolbar.addWidget(self.transition_spin)
        self.follow_button = QPushButton("跟随")
        self.follow_button.setProperty("kind", "chip")
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(self.state.settings.follow_playhead)
        self.follow_button.setIcon(icon("target", 13, theme.TEXT2))
        self.follow_button.setFixedHeight(25)
        self.follow_button.toggled.connect(self._set_follow)
        toolbar.addWidget(self.follow_button)
        zoom_out = self._tool("zoom-out", "缩小时间轴", lambda: self.timeline.zoom(0.8))
        zoom_in = self._tool("zoom-in", "放大时间轴", lambda: self.timeline.zoom(1.25))
        fit = self._tool("fit", "适配所有片段", lambda: self.timeline.fit())
        self.zoom_label = QLabel("90 px/s")
        self.zoom_label.setProperty("kind", "faint")
        toolbar.addWidget(zoom_out)
        toolbar.addWidget(self.zoom_label)
        toolbar.addWidget(zoom_in)
        toolbar.addWidget(fit)
        root.addLayout(toolbar)

        self.timeline = TimelineWidget(self.state)
        root.addWidget(self.timeline, 1)
        self.timeline.step_settings_requested.connect(self.step_settings_requested.emit)

    def _tool(self, name: str, tooltip: str, slot) -> QPushButton:
        b = QPushButton()
        b.setProperty("kind", "tool")
        b.setIcon(icon(name, 17, theme.TEXT2))
        b.setFixedSize(28, 28)
        b.setToolTip(tooltip)
        b.clicked.connect(slot)
        return b

    def _connect(self) -> None:
        s = self.state
        s.timeline_changed.connect(self.refresh)
        s.selection_changed.connect(self.refresh)
        s.playing_changed.connect(self.refresh)
        s.role_ready.connect(self._on_role_ready)
        s.settings_changed.connect(self.refresh)

    def _on_role_ready(self) -> None:
        self.timeline.scroll = 0
        self.timeline.pps = 90
        self.refresh()

    def refresh(self) -> None:
        s = self.state
        self.clip_count.setText(f"{len(s.timeline)} 片段")
        selected = len(s.selected_indices)
        self.selected_count.setText(f"已选 {selected}" if selected else "")
        self.undo_button.setEnabled(bool(s.undo_stack))
        self.redo_button.setEnabled(bool(s.redo_stack))
        for b in (self.copy_button, self.cut_button, self.delete_button, self.step_button):
            b.setEnabled(bool(s.selected_indices))
        self.paste_button.setEnabled(bool(s.clipboard))
        playing = s.playing
        icon_name = "pause" if playing else "play"
        if icon_name != self._last_icon:
            self._last_icon = icon_name
            self.play_button.setIcon(icon(icon_name, 18, "#FFFFFF"))
        if not self.time_edit.hasFocus():
            text = f"{s.playhead:.3f}"
            if text != self._last_time_text:
                self._last_time_text = text
                self.time_edit.setText(text)
        self.total_label.setText(f"总 {s.total_duration():.3f}s")
        index = s.clip_at()
        if 0 <= index < len(s.timeline):
            clip = s.timeline[index]
            self.step_label.setText(f"片段 {index + 1}/{len(s.timeline)} · {clip.action}")
        else:
            self.step_label.setText("空时间轴")
        self.follow_button.setChecked(s.settings.follow_playhead)
        selected = s.selected_clips()
        self.transition_label.setEnabled(bool(selected))
        self.transition_spin.setEnabled(bool(selected))
        self._syncing_transition = True
        if selected:
            self.transition_spin.setValue(clamp(s.timeline[selected[0]].transition_duration, 0.0, 20.0))
        self._syncing_transition = False
        self.zoom_label.setText(f"{round(self.timeline.pps)} px/s")
        self.timeline.update()

    def _commit_time(self) -> None:
        try:
            value = float(self.time_edit.text().strip())
        except ValueError:
            value = self.state.playhead
        self.state.seek(value)
        self.state.selection_changed.emit()
        self.refresh()

    def _apply_transition(self, value: float) -> None:
        if self._syncing_transition:
            return
        indices = self.state.selected_clips()
        if not indices:
            return
        self.state.checkpoint("transition")
        for index in indices:
            clip = self.state.timeline[index]
            clip.transition_enabled = True
            clip.transition_duration = clamp(value, 0.0, max(0.0, clip.duration))
        self.state.finish_live_edit("过渡时长已调整")

    def _set_follow(self, value: bool) -> None:
        self.state.settings.follow_playhead = value
        self.state.settings_changed.emit()
