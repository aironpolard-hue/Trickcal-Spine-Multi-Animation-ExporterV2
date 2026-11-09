from __future__ import annotations

import ctypes
import math
import time
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
from PIL import Image
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QPainter, QPainterPath,
                           QPen, QPixmap, QRegion)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QStackedLayout, QVBoxLayout, QWidget)

from . import theme
from .atlas_utils import atlas_is_premultiplied, prepare_atlas_page
from .icons import icon, icon_pixmap
from .model import LoadedRole, clamp
from .state import EditorState

VERT = '''
#version 330 core
layout(location=0) in vec2 a_pos;
layout(location=1) in vec2 a_uv;
layout(location=2) in vec4 a_color;
uniform vec2 u_viewport;
uniform vec2 u_offset;
uniform vec2 u_scale;
out vec2 v_uv;
out vec4 v_color;
void main() {
    vec2 p = u_offset + a_pos * u_scale;
    vec2 ndc = vec2(p.x / u_viewport.x * 2.0 - 1.0, 1.0 - p.y / u_viewport.y * 2.0);
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = a_uv;
    v_color = a_color;
}
'''

FRAG = '''
#version 330 core
uniform sampler2D u_tex;
in vec2 v_uv;
in vec4 v_color;
out vec4 out_color;
void main() {
    vec4 t = texture(u_tex, v_uv);
    out_color = vec4(t.rgb * v_color.rgb * v_color.a, t.a * v_color.a);
}
'''


def _hex_color(value: str, alpha: int = 255) -> QColor:
    c = QColor(value)
    c.setAlpha(alpha)
    return c


class StageCanvas(QOpenGLWidget):
    edited = Signal()
    inspector_stage = Signal(bool)
    message = Signal(str)
    pick_mode_changed = Signal(bool)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.loaded: Optional[LoadedRole] = None
        self.model = None
        self.model_key = ""
        self.texture = 0
        self.page_offsets = []
        self.page_sizes = []
        self.atlas_size = (1, 1)
        self.quad = 0
        self.vao = self.vbo_pos = self.vbo_uv = self.vbo_col = self.ebo = 0
        self.program = 0
        self.mesh_cap = 0
        self.current_action = ""
        self.current_clip_index = -1
        self.active_mix = 0.0
        self.mix_speed = 1.0
        self.frame_clock = time.perf_counter()
        self.preview_clock = 0.0
        self._drag = ""
        self._drag_start = QPointF()
        self._drag_role_start = (0.0, 0.0)
        self._drag_region_start = (0.0, 0.0, 0.0, 0.0)
        self._drag_offset = (0.0, 0.0)
        self._stage_rect = QRectF()
        self._stage_scale = 1.0
        self._hover_part = ""
        self.pick_mode = False
        self._status = ""
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # resources / model
    # ------------------------------------------------------------------

    def set_loaded(self, loaded: Optional[LoadedRole]) -> None:
        if loaded is self.loaded:
            return
        self.loaded = loaded
        self.model = loaded.model if loaded else None
        self.model_key = loaded.entry.unique_key[0] if loaded else ""
        self.current_action = ""
        self.current_clip_index = -1
        self.active_mix = 0.0
        self.mix_speed = 1.0
        self.preview_clock = 0.0
        if loaded:
            self.slot_index = {name: i for i, name in enumerate(loaded.slots)}
            self.makeCurrent()
            self._load_atlas()
            self.doneCurrent()
        self.update()

    def _tick(self) -> None:
        if self.model is not None:
            self.update()

    def initializeGL(self) -> None:
        self.program = compileProgram(
            compileShader(VERT, GL_VERTEX_SHADER),
            compileShader(FRAG, GL_FRAGMENT_SHADER),
        )
        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        self.vbo_pos = glGenBuffers(1)
        self.vbo_uv = glGenBuffers(1)
        self.vbo_col = glGenBuffers(1)
        self.ebo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_pos)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_uv)
        glEnableVertexAttribArray(1)
        glVertexAttribPointer(1, 2, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_col)
        glEnableVertexAttribArray(2)
        glVertexAttribPointer(2, 4, GL_FLOAT, GL_FALSE, 0, ctypes.c_void_p(0))
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBindVertexArray(0)
        if self.loaded:
            self._load_atlas()

    def _premultiplied(self) -> bool:
        atlas = Path(self.loaded.entry.atlas)
        # UnityFS 角色的原始 atlas 可能在缓存目录，缓存后的 atlas 同一份
        if self.loaded:
            candidates = [self.loaded.atlas_dir / "manifest.json", atlas]
        else:
            candidates = []
        try:
            text = (self.loaded.atlas_dir / Path(self.loaded.entry.atlas).name).read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        return atlas_is_premultiplied(text)

    def _load_atlas(self) -> None:
        if not self.loaded:
            return
        pages = []
        offsets = []
        sizes = []
        pma = self._premultiplied()
        for name in self.loaded.pages:
            path = self.loaded.atlas_dir / name
            try:
                img = Image.open(path).convert("RGBA")
            except Exception as exc:
                self._status = f"贴图加载失败：{name}"
                return
            pages.append(prepare_atlas_page(img, pma))
        if not pages:
            return
        width = sum(p.width for p in pages)
        height = max(p.height for p in pages)
        atlas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        x = 0
        for img in pages:
            offsets.append(float(x))
            sizes.append((img.width, img.height))
            atlas.alpha_composite(img, (x, 0))
            x += img.width
        data = np.array(atlas, dtype=np.uint8)
        if self.texture:
            glDeleteTextures([int(self.texture)])
        self.texture = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.page_offsets = offsets
        self.page_sizes = sizes
        self.atlas_size = (width, height)
        self._status = ""

    def _clip_mix(self, index: int) -> tuple[float, float]:
        clips = self.state.timeline
        if index <= 0 or index >= len(clips):
            return 0.0, 1.0
        clip = clips[index]
        if not clip.transition_enabled or clip.transition_duration <= 0:
            return 0.0, 1.0
        speed = max(0.0, clip.transition_speed)
        if speed <= 0:
            return 0.0, 1.0
        return max(0.0, min(clip.transition_duration, clip.duration)), speed

    def _update_pose(self, dt: float) -> None:
        model = self.model
        if model is None:
            return
        if self.state.timeline:
            index = self.state.clip_at()
            if 0 <= index < len(self.state.timeline):
                clip = self.state.timeline[index]
                action = clip.action
                start = sum(c.duration for c in self.state.timeline[:index])
                local = max(0.0, self.state.playhead - start)
                action_time = clip.start_offset + local * max(0.0, clip.speed)
                mix, mix_speed = self._clip_mix(index)
                clip_changed = index != self.current_clip_index
                if clip_changed or action != self.current_action:
                    if clip_changed and action == self.current_action:
                        model.clear_tracks()
                        model.set_animation(action, True)
                        self.active_mix = 0.0
                    elif self.current_action and mix > 0:
                        model.set_mix(self.current_action, action, mix)
                        model.set_animation(action, True)
                        self.active_mix = mix
                        self.mix_speed = mix_speed
                    else:
                        model.clear_tracks()
                        model.set_animation(action, True)
                        self.active_mix = 0.0
                    self.current_action = action
                    self.current_clip_index = index
                if self.active_mix > 0:
                    progress = min(1.0, local * self.mix_speed / self.active_mix)
                    mix_time = progress * progress * (3.0 - 2.0 * progress) * self.active_mix
                else:
                    mix_time = 0.0
                model.set_to_setup_pose()
                model.set_track_time(0, action_time, mix_time)
                model.update(0.0)
        else:
            action = self.state.preview_action or self.state.selected_action
            if action:
                if action != self.current_action or self.current_clip_index != -1:
                    model.clear_tracks()
                    model.set_to_setup_pose()
                    model.set_animation(action, True)
                    self.current_action = action
                    self.current_clip_index = -1
                    self.active_mix = 0.0
                model.set_to_setup_pose()
                model.update(max(0.0, dt))
        for name in self.state.hidden_slots:
            idx = self.slot_index.get(name)
            if idx is not None:
                model.set_slot_alpha_by_index(idx, 0.0)

    def _update_layout(self) -> None:
        stage_w = max(1.0, self.state.export.stage_w)
        stage_h = max(1.0, self.state.export.stage_h)
        pad_x, pad_y = 28.0, 26.0
        avail_w = max(80.0, self.width() - pad_x * 2)
        avail_h = max(80.0, self.height() - pad_y * 2)
        scale = min(avail_w / stage_w, avail_h / stage_h)
        scale = max(0.02, scale)
        w = stage_w * scale
        h = stage_h * scale
        x = (self.width() - w) * 0.5
        y = (self.height() - h) * 0.5 + 2
        self._stage_rect = QRectF(x, y, w, h)
        self._stage_scale = scale

    def _stage_to_widget(self, x: float, y: float) -> QPointF:
        return QPointF(self._stage_rect.left() + x * self._stage_scale,
                       self._stage_rect.top() + y * self._stage_scale)

    def _widget_to_stage(self, p: QPointF) -> QPointF:
        s = max(0.0001, self._stage_scale)
        return QPointF((p.x() - self._stage_rect.left()) / s,
                       (p.y() - self._stage_rect.top()) / s)

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, int(w * self.devicePixelRatioF()), int(h * self.devicePixelRatioF()))

    def paintGL(self) -> None:
        self._update_layout()
        state = self.state
        state.export.keep_inside()
        dpr = self.devicePixelRatioF()
        vw = max(1, int(self.width() * dpr))
        vh = max(1, int(self.height() * dpr))
        glViewport(0, 0, vw, vh)
        glDisable(GL_SCISSOR_TEST)
        glClearColor(0.031, 0.039, 0.055, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        painter = None
        if self.model is not None and self.texture:
            now = time.perf_counter()
            dt = min(0.05, now - self.frame_clock)
            self.frame_clock = now
            self._update_pose(dt)
            self._draw_spine(dpr, vw, vh)
        glDisable(GL_SCISSOR_TEST)
        glUseProgram(0)
        glBindVertexArray(0)
        glDisable(GL_BLEND)
        self._draw_overlay()

    def _draw_spine(self, dpr: float, vw: int, vh: int) -> None:
        rect = self._stage_rect
        sx = int(rect.left() * dpr)
        sy = int((self.height() - rect.bottom()) * dpr)
        sw = max(1, int(rect.width() * dpr))
        sh = max(1, int(rect.height() * dpr))
        glEnable(GL_SCISSOR_TEST)
        glScissor(sx, sy, sw, sh)
        bg = self.state.export.bg
        glClearColor(bg[0] / 255.0, bg[1] / 255.0, bg[2] / 255.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        model = self.model
        n_pages = len(self.page_offsets)
        offs = (ctypes.c_float * n_pages)(*self.page_offsets)
        pw = (ctypes.c_float * n_pages)(*[s[0] for s in self.page_sizes])
        ph = (ctypes.c_float * n_pages)(*[s[1] for s in self.page_sizes])
        try:
            nv, nt, cap, blends, segs = model.build_mesh(
                0.0, 0.0, 1.0, offs, pw, ph,
                self.atlas_size[0], self.atlas_size[1])
        except Exception as exc:
            self._status = f"网格构建失败：{exc}"
            glDisable(GL_SCISSOR_TEST)
            return
        if nv <= 0:
            glDisable(GL_SCISSOR_TEST)
            return
        geo, attrs, tris = model.mesh_data(nv, nt)
        pos = np.asarray(geo, dtype=np.float32).reshape(-1, 2)
        attr = np.asarray(attrs, dtype=np.float32).reshape(-1, 6)
        idx = np.asarray(tris, dtype=np.uint16)
        role_screen_x = (rect.left() + self.state.export.role_x * self._stage_scale) * dpr
        role_screen_y = (rect.top() + self.state.export.role_y * self._stage_scale) * dpr
        scale_px = self.state.export.role_scale * self._stage_scale * dpr
        glUseProgram(self.program)
        glUniform2f(glGetUniformLocation(self.program, "u_viewport"), float(vw), float(vh))
        glUniform2f(glGetUniformLocation(self.program, "u_offset"),
                    float(role_screen_x), float(role_screen_y))
        glUniform2f(glGetUniformLocation(self.program, "u_scale"), float(scale_px), float(scale_px))
        glUniform1i(glGetUniformLocation(self.program, "u_tex"), 0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glBindVertexArray(self.vao)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_pos)
        glBufferData(GL_ARRAY_BUFFER, pos.nbytes, pos.tobytes(), GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_uv)
        glBufferData(GL_ARRAY_BUFFER, attr[:, 0:2].nbytes, attr[:, 0:2].copy().tobytes(), GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ARRAY_BUFFER, self.vbo_col)
        glBufferData(GL_ARRAY_BUFFER, attr[:, 2:6].nbytes, attr[:, 2:6].copy().tobytes(), GL_DYNAMIC_DRAW)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, self.ebo)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx.tobytes(), GL_DYNAMIC_DRAW)
        glEnable(GL_BLEND)
        if blends:
            for i, blend in enumerate(blends):
                if blend == 0:
                    glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
                elif blend == 1:
                    glBlendFunc(GL_ONE, GL_ONE)
                elif blend == 2:
                    glBlendFuncSeparate(GL_DST_COLOR, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE)
                else:
                    glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_COLOR, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
                count = (segs[i + 1] - segs[i]) * 3
                glDrawElements(GL_TRIANGLES, count, GL_UNSIGNED_SHORT,
                               ctypes.c_void_p(segs[i] * 3 * 2))
        else:
            glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            glDrawElements(GL_TRIANGLES, nt * 3, GL_UNSIGNED_SHORT, ctypes.c_void_p(0))
        glBindVertexArray(0)
        glDisable(GL_BLEND)
        glDisable(GL_SCISSOR_TEST)

    # ------------------------------------------------------------------
    # overlay
    # ------------------------------------------------------------------

    def _draw_overlay(self) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        rect = self._stage_rect
        # dotted background outside stage
        p.save()
        outside = QRegion(self.rect()).subtracted(QRegion(rect.toRect()))
        p.setClipRegion(outside)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 10))
        for y in range(0, self.height(), 28):
            for x in range(0, self.width(), 28):
                p.drawEllipse(QPointF(x, y), 1.0, 1.0)
        p.restore()
        # stage border
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        # region
        exp = self.state.export
        rx, ry, rw, rh = exp.region
        region = QRectF(rect.left() + rx * self._stage_scale,
                        rect.top() + ry * self._stage_scale,
                        rw * self._stage_scale, rh * self._stage_scale)
        p.save()
        p.setClipRect(rect)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 100))
        if region.top() > rect.top():
            p.drawRect(QRectF(rect.left(), rect.top(), rect.width(), region.top() - rect.top()))
        if region.bottom() < rect.bottom():
            p.drawRect(QRectF(rect.left(), region.bottom(), rect.width(), rect.bottom() - region.bottom()))
        if region.left() > rect.left():
            p.drawRect(QRectF(rect.left(), region.top(), region.left() - rect.left(), region.height()))
        if region.right() < rect.right():
            p.drawRect(QRectF(region.right(), region.top(), rect.right() - region.right(), region.height()))
        p.setPen(QPen(QColor(theme.AMBER), 1.4))
        p.setBrush(Qt.NoBrush)
        p.drawRect(region)
        # handles
        p.setPen(QPen(QColor(theme.AMBER), 1.3))
        p.setBrush(QColor(theme.SURFACE))
        for point in (region.topLeft(), region.topRight(), region.bottomLeft(), region.bottomRight()):
            p.drawRoundedRect(QRectF(point.x() - 4.5, point.y() - 4.5, 9, 9), 2, 2)
        p.restore()
        # labels
        font = QFont(self.font())
        font.setPixelSize(11)
        p.setFont(font)
        label = f"{round(rw)} × {round(rh)}"
        metrics = p.fontMetrics()
        lw = metrics.horizontalAdvance(label) + 16
        lx = clamp(region.left(), rect.left() + 4, rect.right() - lw - 4)
        ly = region.top() - 25
        if ly < rect.top() + 4:
            ly = region.top() + 4
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE))
        p.drawRoundedRect(QRectF(lx, ly, lw, 20), 5, 5)
        p.setPen(QPen(QColor(theme.AMBER), 1.0))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(lx, ly, lw, 20), 5, 5)
        p.setPen(QColor(theme.AMBER))
        p.drawText(QRectF(lx, ly, lw, 20), Qt.AlignCenter, label)
        # stage size pill
        label = f"{round(exp.stage_w)} × {round(exp.stage_h)}"
        lw = metrics.horizontalAdvance(label) + 36
        lx = rect.left() + 8
        ly = rect.bottom() - 29
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 130))
        p.drawRoundedRect(QRectF(lx, ly, lw, 21), 5, 5)
        p.drawPixmap(QPointF(lx + 7, ly + 4), icon_pixmap("monitor", 12, theme.TEXT2))
        p.setPen(QColor(theme.TEXT2))
        p.drawText(QRectF(lx + 24, ly, lw - 28, 21), Qt.AlignVCenter | Qt.AlignLeft, label)
        # part pick banner
        if self.pick_mode:
            text = "点选模式 · 点击部件隐藏 / 显示"
            lw = metrics.horizontalAdvance(text) + 40
            lx = rect.center().x() - lw * 0.5
            ly = rect.top() + 10
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.SURFACE))
            p.drawRoundedRect(QRectF(lx, ly, lw, 24), 7, 7)
            p.setPen(QPen(QColor(theme.ACCENT), 1.0))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(lx, ly, lw, 24), 7, 7)
            p.drawPixmap(QPointF(lx + 10, ly + 5), icon_pixmap("target", 14, theme.ACCENT_TEXT))
            p.setPen(QColor(theme.ACCENT_TEXT))
            p.drawText(QRectF(lx + 31, ly, lw - 34, 24), Qt.AlignVCenter | Qt.AlignLeft, text)
        if self._status:
            p.setPen(QColor(theme.RED))
            p.drawText(self.rect().adjusted(16, 16, -16, -16), Qt.AlignTop | Qt.AlignLeft, self._status)
        p.end()

    # ------------------------------------------------------------------
    # interaction
    # ------------------------------------------------------------------

    def _region_hit(self, pos: QPointF) -> str:
        exp = self.state.export
        r = self._stage_rect
        x0 = r.left() + exp.region[0] * self._stage_scale
        y0 = r.top() + exp.region[1] * self._stage_scale
        w = exp.region[2] * self._stage_scale
        h = exp.region[3] * self._stage_scale
        x, y = pos.x(), pos.y()
        near = 10
        if abs(x - x0) <= near and abs(y - y0) <= near:
            return "tl"
        if abs(x - (x0 + w)) <= near and abs(y - y0) <= near:
            return "tr"
        if abs(x - x0) <= near and abs(y - (y0 + h)) <= near:
            return "bl"
        if abs(x - (x0 + w)) <= near and abs(y - (y0 + h)) <= near:
            return "br"
        if y0 <= y <= y0 + h and abs(x - x0) <= near:
            return "left"
        if y0 <= y <= y0 + h and abs(x - (x0 + w)) <= near:
            return "right"
        if x0 <= x <= x0 + w and abs(y - y0) <= near:
            return "top"
        if x0 <= x <= x0 + w and abs(y - (y0 + h)) <= near:
            return "bottom"
        if x0 <= x <= x0 + w and y0 <= y <= y0 + h:
            return "content"
        return ""

    def _model_hit(self, pos: QPointF) -> Optional[dict]:
        if not self.model:
            return None
        stage_pt = self._widget_to_stage(pos)
        exp = self.state.export
        scale = max(0.001, exp.role_scale)
        wx = (stage_pt.x() - exp.role_x) / scale
        wy = (stage_pt.y() - exp.role_y) / scale
        try:
            return self.model.hit_test(wx, wy)
        except Exception:
            return None

    def mousePressEvent(self, event) -> None:
        if self.model is None:
            return
        pos = QPointF(event.position())
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            return
        if event.button() != Qt.LeftButton:
            return
        if self.pick_mode:
            hit = self._model_hit(pos)
            if hit and hit.get("slot_name"):
                self.state.toggle_slot(hit["slot_name"])
            else:
                self.state.message.emit("没有点中可选择部件")
            return
        hit = self._region_hit(pos)
        if hit in ("tl", "tr", "bl", "br", "left", "right", "top", "bottom"):
            self._drag = "region:move" if hit in ("left", "right", "top", "bottom") else "region:" + hit
            self._drag_start = pos
            self._drag_region_start = tuple(self.state.export.region)
            stage_pt = self._widget_to_stage(pos)
            self._drag_offset = (stage_pt.x() - self.state.export.region[0],
                                 stage_pt.y() - self.state.export.region[1])
            self.setCursor(Qt.ClosedHandCursor)
            return
        role_hit = self._model_hit(pos)
        stage_pt = self._widget_to_stage(pos)
        center_dist = math.hypot(stage_pt.x() - self.state.export.role_x,
                                 stage_pt.y() - self.state.export.role_y)
        if hit == "content" or role_hit or center_dist <= 110 * self.state.export.role_scale:
            self._drag = "role"
            self._drag_start = pos
            self._drag_role_start = (self.state.export.role_x, self.state.export.role_y)
            self._drag_offset = (stage_pt.x() - self.state.export.role_x,
                                 stage_pt.y() - self.state.export.role_y)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:
        pos = QPointF(event.position())
        if self._drag:
            stage_pt = self._widget_to_stage(pos)
            exp = self.state.export
            if self._drag == "role":
                exp.role_x = clamp(stage_pt.x() - self._drag_offset[0], 0, exp.stage_w)
                exp.role_y = clamp(stage_pt.y() - self._drag_offset[1], 0, exp.stage_h)
            else:
                self._update_region_drag(stage_pt)
            self.state.export.keep_inside()
            self.edited.emit()
            self.update()
            return
        if self.model is None:
            return
        if self.pick_mode:
            self.setCursor(Qt.CrossCursor)
            return
        hit = self._region_hit(pos)
        if hit in ("tl", "br"):
            self.setCursor(Qt.SizeFDiagCursor)
        elif hit in ("tr", "bl"):
            self.setCursor(Qt.SizeBDiagCursor)
        elif hit in ("left", "right", "top", "bottom"):
            self.setCursor(Qt.SizeAllCursor)
        elif hit == "content":
            self.setCursor(Qt.OpenHandCursor)
        elif self._model_hit(pos):
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def _update_region_drag(self, stage_pt: QPointF) -> None:
        x, y, w, h = self._drag_region_start
        left, top, right, bottom = x, y, x + w, y + h
        min_size = 40.0
        kind = self._drag.split(":", 1)[1]
        if kind in ("tl", "bl", "left"):
            left = clamp(stage_pt.x(), 0, right - min_size)
        if kind in ("tr", "br", "right"):
            right = clamp(stage_pt.x(), left + min_size, self.state.export.stage_w)
        if kind in ("tl", "tr", "top"):
            top = clamp(stage_pt.y(), 0, bottom - min_size)
        if kind in ("bl", "br", "bottom"):
            bottom = clamp(stage_pt.y(), top + min_size, self.state.export.stage_h)
        if kind == "move":
            nx = clamp(stage_pt.x() - self._drag_offset[0], 0, self.state.export.stage_w - w)
            ny = clamp(stage_pt.y() - self._drag_offset[1], 0, self.state.export.stage_h - h)
            left, top, right, bottom = nx, ny, nx + w, ny + h
        self.state.export.region = (left, top, right - left, bottom - top)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag:
            was_region = self._drag.startswith("region:")
            self._drag = ""
            self.setCursor(Qt.ArrowCursor)
            if was_region and self.state.export.region:
                self.state.message.emit(
                    f"导出区域：{round(self.state.export.region[2])} × {round(self.state.export.region[3])}")
            self.edited.emit()

    def wheelEvent(self, event) -> None:
        event.ignore()

    def _show_context_menu(self, global_pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.addAction(icon("user"), "角色设置…", lambda: self.inspector_stage.emit(True))
        menu.addAction(icon("monitor"), "舞台设置…", lambda: self.inspector_stage.emit(False))
        menu.addSeparator()
        menu.addAction(icon("target"), "把角色移到导出区域中心", self._center_role)
        pick = menu.addAction(icon("eye"), "点选部件")
        pick.setCheckable(True)
        pick.setChecked(self.pick_mode)
        pick.triggered.connect(self.set_pick_mode)
        menu.addSeparator()
        menu.addAction(icon("refresh"), "恢复默认角色位置", self._reset_role)
        menu.exec(global_pos)

    def _center_role(self) -> None:
        exp = self.state.export
        exp.role_x = exp.region[0] + exp.region[2] * 0.5
        exp.role_y = exp.region[1] + exp.region[3] * 0.55
        exp.keep_inside()
        self.edited.emit()
        self.state.message.emit("已将角色移到导出区域中心")

    def _reset_role(self) -> None:
        exp = self.state.export
        exp.role_x = exp.stage_w * 0.5
        exp.role_y = exp.stage_h * 0.60
        exp.role_scale = 0.8
        exp.keep_inside()
        self.edited.emit()
        self.state.message.emit("已恢复默认角色位置")

    def set_pick_mode(self, enabled: bool) -> None:
        self.pick_mode = enabled
        self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)
        self.pick_mode_changed.emit(enabled)
        self.state.message.emit("点击预览中的模型部件即可隐藏/显示" if enabled else "已退出部件点击选择")
        self.update()


class StagePanel(QFrame):
    choose_folder_requested = Signal()
    rescan_requested = Signal()
    inspector_stage_requested = Signal(bool)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Panel")
        self.canvas = StageCanvas(state)
        self.pick_button = QPushButton("点选")
        self.pick_button.setProperty("kind", "chip")
        self.pick_button.setCheckable(True)
        self.pick_button.setIcon(icon("target", 14, theme.TEXT2))
        self.pick_button.setToolTip("点选舞台上的部件来隐藏或显示")
        self.pick_button.clicked.connect(self.canvas.set_pick_mode)
        self.canvas.pick_mode_changed.connect(self.pick_button.setChecked)
        self.canvas.inspector_stage.connect(self.inspector_stage_requested)
        self._build_header()
        self._build_body()
        self.state.roles_changed.connect(self._refresh_empty)
        self.state.role_loading.connect(self._on_loading)
        self.state.role_ready.connect(self._on_ready)
        self.state.role_failed.connect(self._on_failed)
        self.state.skin_changed.connect(self._refresh_role_label)
        self._refresh_empty()

    def _build_header(self) -> None:
        header = QWidget()
        lay = QHBoxLayout(header)
        lay.setContentsMargins(14, 8, 10, 6)
        lay.setSpacing(8)
        title_icon = QLabel()
        title_icon.setPixmap(icon_pixmap("monitor", 17, theme.TEXT3))
        lay.addWidget(title_icon)
        title = QLabel("预览")
        title.setProperty("kind", "medium")
        lay.addWidget(title)
        self.role_label = QLabel("未选择角色")
        self.role_label.setProperty("kind", "muted")
        lay.addWidget(self.role_label)
        lay.addStretch(1)
        lay.addWidget(self.pick_button)
        self.role_settings = QPushButton()
        self.role_settings.setProperty("kind", "tool")
        self.role_settings.setIcon(icon("user", 18, theme.TEXT2))
        self.role_settings.setFixedSize(30, 30)
        self.role_settings.setToolTip("角色位置与缩放")
        self.role_settings.clicked.connect(lambda: self.inspector_stage_requested.emit(True))
        self.stage_settings = QPushButton()
        self.stage_settings.setProperty("kind", "tool")
        self.stage_settings.setIcon(icon("sliders", 18, theme.TEXT2))
        self.stage_settings.setFixedSize(30, 30)
        self.stage_settings.setToolTip("舞台与导出区域设置")
        self.stage_settings.clicked.connect(lambda: self.inspector_stage_requested.emit(False))
        lay.addWidget(self.role_settings)
        lay.addWidget(self.stage_settings)
        self.header = header

    def _build_body(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.header)
        self.stack = QStackedLayout()
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.canvas)
        self.empty = QWidget()
        empty_lay = QVBoxLayout(self.empty)
        empty_lay.setContentsMargins(24, 24, 24, 24)
        empty_lay.addStretch(1)
        self.empty_icon = QLabel()
        self.empty_icon.setAlignment(Qt.AlignCenter)
        self.empty_icon.setPixmap(icon_pixmap("sparkles", 34, theme.TEXT4))
        empty_lay.addWidget(self.empty_icon)
        self.empty_title = QLabel("选择一个角色")
        self.empty_title.setProperty("kind", "title")
        self.empty_title.setAlignment(Qt.AlignCenter)
        empty_lay.addWidget(self.empty_title)
        self.empty_sub = QLabel("在左侧资源库中选择角色，这里会显示实时预览。")
        self.empty_sub.setProperty("kind", "muted")
        self.empty_sub.setAlignment(Qt.AlignCenter)
        self.empty_sub.setWordWrap(True)
        empty_lay.addWidget(self.empty_sub)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.empty_primary = QPushButton("选择文件夹")
        self.empty_primary.setProperty("kind", "primary")
        self.empty_primary.setIcon(icon("folder-open", 15, "#FFFFFF"))
        self.empty_primary.clicked.connect(self.choose_folder_requested)
        self.empty_secondary = QPushButton("重新扫描")
        self.empty_secondary.setProperty("kind", "ghost")
        self.empty_secondary.setIcon(icon("refresh", 15, theme.TEXT2))
        self.empty_secondary.clicked.connect(self.rescan_requested)
        btn_row.addWidget(self.empty_primary)
        btn_row.addSpacing(8)
        btn_row.addWidget(self.empty_secondary)
        btn_row.addStretch(1)
        empty_lay.addLayout(btn_row)
        empty_lay.addStretch(1)
        self.stack.addWidget(self.empty)
        root.addLayout(self.stack, 1)
        self.stack.setCurrentWidget(self.canvas)

    def _refresh_empty(self) -> None:
        if self.state.loaded is not None:
            self.stack.setCurrentWidget(self.canvas)
            self.role_label.setText(self.state.loaded.entry.name)
            self.pick_button.setEnabled(True)
            return
        self.role_label.setText(self.state.selected_role_entry.name if self.state.selected_role_entry else "未选择角色")
        self.pick_button.setEnabled(False)
        self.stack.setCurrentWidget(self.empty)
        if not self.state.roles:
            self.empty_title.setText("还没有角色")
            self.empty_sub.setText("选择一个包含 Spine 资源的文件夹，开始编排动作。")
            self.empty_primary.show()
            self.empty_secondary.show()
        elif self.state.selected_role_entry is None:
            self.empty_title.setText("选择一个角色开始")
            self.empty_sub.setText("在左侧资源库中选择角色，这里会显示实时预览。")
            self.empty_primary.hide()
            self.empty_secondary.hide()
        else:
            self.empty_title.setText("正在准备资源…")
            self.empty_sub.setText(self.state.selected_role_entry.name)
            self.empty_primary.hide()
            self.empty_secondary.hide()

    def _on_loading(self, name: str) -> None:
        self.stack.setCurrentWidget(self.empty)
        self.empty_icon.setPixmap(icon_pixmap("sparkles", 34, theme.ACCENT_TEXT))
        self.empty_title.setText("正在加载角色…")
        self.empty_sub.setText(name)
        self.empty_primary.hide()
        self.empty_secondary.hide()
        self.role_label.setText(name)
        self.pick_button.setEnabled(False)

    def _on_ready(self) -> None:
        self.canvas.set_loaded(self.state.loaded)
        self.stack.setCurrentWidget(self.canvas)
        self.pick_button.setEnabled(True)
        self._refresh_role_label()

    def _on_failed(self, error: str) -> None:
        self.stack.setCurrentWidget(self.empty)
        self.empty_icon.setPixmap(icon_pixmap("warning", 34, theme.AMBER))
        self.empty_title.setText("角色读取失败")
        self.empty_sub.setText(error or "请检查资源文件是否完整。")
        self.empty_primary.setText("重试")
        self.empty_primary.show()
        self.empty_secondary.setText("重新扫描")
        self.empty_secondary.show()
        try:
            self.empty_primary.clicked.disconnect()
        except Exception:
            pass
        self.empty_primary.clicked.connect(self._retry)
        self.pick_button.setEnabled(False)

    def _retry(self) -> None:
        if self.state.selected_role_entry:
            self.state.select_role(self.state.selected_role_entry)
        else:
            self.state.reload_current_role()

    def _refresh_role_label(self) -> None:
        if self.state.loaded:
            self.role_label.setText(self.state.loaded.entry.name)

    def refresh_model(self) -> None:
        self.canvas.set_loaded(self.state.loaded)
        self._refresh_role_label()
        self._refresh_empty()
