from __future__ import annotations

import time
from typing import Optional

from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_SCISSOR_TEST, glClear, glClearColor, glDisable, glViewport
from PySide6.QtCore import QPoint, QTimer, Qt
from PySide6.QtGui import QColor
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy,
                               QStackedLayout, QVBoxLayout, QWidget)

from . import services, theme
from .gl_renderer import GLSpineRenderer
from .icons import icon_pixmap
from .model import LoadedRole
from .state import EditorState, Task
from .widgets import ElidedLabel


class _PreviewCanvas(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.loaded: Optional[LoadedRole] = None
        self.model = None
        self.renderer: Optional[GLSpineRenderer] = None
        self.status = ""
        self.action = ""
        self.hidden: set[str] = set()
        self.skin = ""
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)

    def initializeGL(self) -> None:
        try:
            self.renderer = GLSpineRenderer()
            self.renderer.initialize()
            if self.loaded is not None:
                self.renderer.load_atlas(self.loaded)
        except Exception as exc:
            self.status = f"预览初始化失败：{exc}"
            self.renderer = None

    def set_role(self, loaded: Optional[LoadedRole]) -> None:
        if self.loaded is loaded:
            return
        self.loaded = loaded
        self.model = loaded.model if loaded else None
        self.action = ""
        self.status = ""
        if self.renderer is not None and loaded is not None:
            try:
                self.makeCurrent()
                self.renderer.load_atlas(loaded)
            except Exception as exc:
                self.status = f"预览贴图失败：{exc}"
            finally:
                self.doneCurrent()
        self.update()

    def set_skin(self, skin: str) -> None:
        if not self.model or not skin or skin == self.skin:
            return
        self.skin = skin
        try:
            self.model.set_skin(skin)
        except Exception:
            pass
        self.action = ""
        self.update()

    def set_action(self, action: str) -> None:
        if action == self.action:
            return
        self.action = action
        self.status = ""
        if self.model and action:
            self.model.clear_tracks()
            if not self.model.set_animation(action, True):
                self.status = "找不到这个动作"
            else:
                self.model.set_to_setup_pose()
                self.model.update(0.0)
        self.update()

    def set_hidden(self, names: set[str]) -> None:
        self.hidden = set(names)

    def advance(self, dt: float) -> None:
        if self.model is not None and self.action:
            self.model.set_to_setup_pose()
            self.model.update(max(0.0, dt))
        self.update()

    def paintGL(self) -> None:
        dpr = self.devicePixelRatioF()
        width = max(1, int(self.width() * dpr))
        height = max(1, int(self.height() * dpr))
        glViewport(0, 0, width, height)
        glDisable(GL_SCISSOR_TEST)
        bg = QColor(theme.SURFACE)
        glClearColor(bg.redF(), bg.greenF(), bg.blueF(), 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        if self.loaded is None or self.model is None or self.renderer is None:
            return
        if not self.action:
            return
        for index, name in enumerate(self.loaded.slots):
            if name in self.hidden:
                self.model.set_slot_alpha_by_index(index, 0.0)
        bounds = self.loaded.reference_bounds
        if not bounds:
            bounds = self.model.collect_bounds()
        if not bounds:
            return
        min_x, min_y, max_x, max_y = bounds
        span_x = max(1.0, max_x - min_x)
        span_y = max(1.0, max_y - min_y)
        scale = min(width * 0.78 / span_x, height * 0.88 / span_y)
        offset_x = width * 0.5 - (min_x + max_x) * 0.5 * scale
        offset_y = height * 0.54 - (min_y + max_y) * 0.5 * scale
        try:
            self.renderer.draw(self.model, width, height, offset_x, offset_y, scale)
        except Exception as exc:
            self.status = f"预览绘制失败：{exc}"

    def cleanup(self) -> None:
        try:
            if self.renderer is not None and self.context() is not None:
                self.makeCurrent()
                self.renderer.dispose()
                self.doneCurrent()
        except Exception:
            pass
        self.renderer = None


class ActionPreview(QWidget):
    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setVisible(False)
        self._hover_action = ""
        self._anchor = QPoint()
        self._preview_role: Optional[LoadedRole] = None
        self._preview_key = None
        self._task: Optional[Task] = None
        self._task_token = 0
        self._last_tick = time.perf_counter()
        self._build()
        self._anim = QTimer(self)
        self._anim.setInterval(33)
        self._anim.timeout.connect(self._tick)
        self._delay = QTimer(self)
        self._delay.setSingleShot(True)
        self._delay.setInterval(150)
        self._delay.timeout.connect(self._reveal)
        state.role_loading.connect(self._on_role_loading)
        state.skin_changed.connect(self._on_skin_changed)
        state.parts_changed.connect(self.hide_preview)
        state.settings_changed.connect(self._on_settings_changed)

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.card = QFrame()
        self.card.setObjectName("Card")
        outer.addWidget(self.card)
        card = QVBoxLayout(self.card)
        card.setContentsMargins(10, 9, 10, 10)
        card.setSpacing(7)

        head = QHBoxLayout()
        head.setSpacing(7)
        mark = QLabel()
        mark.setPixmap(icon_pixmap("play", 13, theme.ACCENT_TEXT))
        head.addWidget(mark)
        self.title = ElidedLabel("", self, theme.TEXT, 13)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        head.addWidget(self.title, 1)
        self.time_label = QLabel("")
        self.time_label.setProperty("kind", "faint")
        head.addWidget(self.time_label)
        hint = QLabel("双击添加")
        hint.setProperty("kind", "faint")
        head.addWidget(hint)
        card.addLayout(head)
        self.card.setToolTip("双击动作添加到播放头")

        self.stack = QStackedLayout()
        self.loading = QLabel("正在准备动作预览…")
        self.loading.setAlignment(Qt.AlignCenter)
        self.loading.setProperty("kind", "faint")
        loading_page = QWidget()
        lp = QVBoxLayout(loading_page)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.addWidget(self.loading)
        self.canvas = _PreviewCanvas()
        self.stack.addWidget(loading_page)
        self.stack.addWidget(self.canvas)
        self.stack.setCurrentIndex(0)
        holder = QWidget()
        holder.setLayout(self.stack)
        self.stack.setContentsMargins(0, 0, 0, 0)
        card.addWidget(holder, 1)
        self._resize_card()

    def _card_width(self) -> int:
        return max(240, min(380, int(self.state.settings.preview_width)))

    def _resize_card(self) -> None:
        width = self._card_width()
        height = int(width * 0.64) + 58
        self.setFixedSize(width, height)
        self.canvas.setMinimumSize(100, 80)

    # ------------------------------------------------------------------
    # hover lifecycle
    # ------------------------------------------------------------------

    def hover(self, action: str, anchor: QPoint) -> None:
        if not action:
            self.hide_preview()
            return
        self._anchor = anchor
        if self.isVisible():
            self._delay.stop()
            if action != self._hover_action:
                self._hover_action = action
                self._apply_action()
            self._place()
            self.raise_()
            return
        self._hover_action = action
        self._delay.start()

    def hide_preview(self) -> None:
        self._delay.stop()
        self._anim.stop()
        self._hover_action = ""
        self.setVisible(False)

    def _reveal(self) -> None:
        if not self._hover_action:
            return
        if self.state.loaded is None or self.state.selected_role_entry is None:
            return
        self._resize_card()
        self.title.setText(self._hover_action)
        duration = self.state.loaded.durations.get(self._hover_action)
        self.time_label.setText(f"{duration:.2f}s" if duration else "")
        self._place()
        self.setVisible(True)
        self.raise_()
        self._ensure_role()
        self._apply_action()

    def _place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 12
        x = self._anchor.x()
        y = self._anchor.y() - self.height() // 3
        max_x = parent.width() - self.width() - margin
        max_y = parent.height() - self.height() - 38
        self.move(max(margin, min(x, max_x)), max(70, min(y, max_y)))

    def _apply_action(self) -> None:
        if not self._hover_action:
            return
        self.title.setText(self._hover_action)
        duration = self.state.loaded.durations.get(self._hover_action) if self.state.loaded else None
        self.time_label.setText(f"{duration:.2f}s" if duration else "")
        if self._preview_role is None:
            return
        self.canvas.set_skin(self.state.current_skin)
        self.canvas.set_hidden(set(self.state.hidden_slots))
        self.canvas.set_action(self._hover_action)
        self.stack.setCurrentIndex(1)
        if self.isVisible():
            self._last_tick = time.perf_counter()
            self._anim.start()

    def _tick(self) -> None:
        now = time.perf_counter()
        dt = min(0.08, now - self._last_tick)
        self._last_tick = now
        if self._preview_role is None:
            return
        self.canvas.advance(dt)

    # ------------------------------------------------------------------
    # preview role cache
    # ------------------------------------------------------------------

    def _ensure_role(self) -> None:
        entry = self.state.selected_role_entry
        if entry is None:
            return
        key = entry.unique_key
        if self._preview_role is not None and self._preview_key == key:
            self.canvas.set_role(self._preview_role)
            self.canvas.set_skin(self.state.current_skin)
            self.canvas.set_hidden(set(self.state.hidden_slots))
            self.canvas.set_action(self._hover_action)
            self.stack.setCurrentIndex(1 if not self.canvas.status else 0)
            if self.canvas.status:
                self.loading.setText(self.canvas.status)
            self._anim.start()
            return
        if self._task is not None and self._preview_key == key:
            return
        self._preview_key = key
        self._task_token += 1
        token = self._task_token
        skin = self.state.current_skin
        self.loading.setText("正在准备动作预览…")
        self.stack.setCurrentIndex(0)
        task = Task(token, lambda: services.load_role(entry, skin))
        task.signals.done.connect(self._on_loaded)
        self._task = task
        from PySide6.QtCore import QThreadPool
        QThreadPool.globalInstance().start(task)

    def _on_loaded(self, token: int, result, error) -> None:
        if token != self._task_token:
            if result is not None:
                services.dispose_role(result)
            return
        self._task = None
        if error is not None or result is None:
            self.loading.setText(f"预览载入失败：{error or '未知错误'}")
            self.stack.setCurrentIndex(0)
            return
        entry = self.state.selected_role_entry
        if entry is None or entry.unique_key != self._preview_key:
            services.dispose_role(result)
            return
        if self._preview_role is not None:
            services.dispose_role(self._preview_role)
        self._preview_role = result
        if self.state.current_skin:
            try:
                result.model.set_skin(self.state.current_skin)
            except Exception:
                pass
        self.canvas.set_role(result)
        self.canvas.set_hidden(set(self.state.hidden_slots))
        if self._hover_action:
            self.canvas.set_action(self._hover_action)
            self.stack.setCurrentIndex(1)
            self._last_tick = time.perf_counter()
            self._anim.start()
        else:
            self.stack.setCurrentIndex(0)

    def _on_role_loading(self, _name: str) -> None:
        self.hide_preview()
        self._invalidate_role()

    def _invalidate_role(self) -> None:
        self._task_token += 1
        self._task = None
        self._preview_key = None
        self.canvas.set_role(None)
        if self._preview_role is not None:
            services.dispose_role(self._preview_role)
            self._preview_role = None
        self.stack.setCurrentIndex(0)

    def _on_skin_changed(self) -> None:
        if self._preview_role is None:
            return
        self.canvas.set_skin(self.state.current_skin)
        if self.isVisible() and self._hover_action:
            self.canvas.set_action(self._hover_action)
            self.stack.setCurrentIndex(1)
            self._anim.start()

    def _on_settings_changed(self) -> None:
        self._resize_card()
        if self.isVisible():
            self._place()

    def shutdown(self) -> None:
        self._delay.stop()
        self._anim.stop()
        self.canvas.cleanup()
        self._task_token += 1
        self._task = None
        self.canvas.set_role(None)
        if self._preview_role is not None:
            services.dispose_role(self._preview_role)
            self._preview_role = None
