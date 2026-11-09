from __future__ import annotations

import ctypes
from pathlib import Path
from typing import List, Optional, Set

import numpy as np
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
from PIL import Image

from .atlas_utils import atlas_is_premultiplied, prepare_atlas_page
from .model import LoadedRole

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


class GLSpineRenderer:
    """负责在“当前 OpenGL 上下文”里绘制 Spine 模型。"""

    def __init__(self):
        self.program = 0
        self.vao = 0
        self.vbo_pos = 0
        self.vbo_uv = 0
        self.vbo_col = 0
        self.ebo = 0
        self.texture = 0
        self.page_offsets: List[float] = []
        self.page_sizes: List[tuple] = []
        self.atlas_size = (1, 1)
        self.loaded: Optional[LoadedRole] = None
        self.slot_index = {}

    def initialize(self) -> None:
        self.program = compileProgram(
            compileShader(VERT, GL_VERTEX_SHADER),
            compileShader(FRAG, GL_FRAGMENT_SHADER),
        )
        self.vao = int(glGenVertexArrays(1))
        glBindVertexArray(self.vao)
        self.vbo_pos = int(glGenBuffers(1))
        self.vbo_uv = int(glGenBuffers(1))
        self.vbo_col = int(glGenBuffers(1))
        self.ebo = int(glGenBuffers(1))
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

    def load_atlas(self, loaded: LoadedRole) -> None:
        self.loaded = loaded
        self.slot_index = {name: i for i, name in enumerate(loaded.slots)}
        try:
            text = (loaded.atlas_dir / Path(loaded.entry.atlas).name).read_text(
                encoding="utf-8", errors="replace")
        except Exception:
            text = ""
        pma = atlas_is_premultiplied(text)
        pages = []
        offsets = []
        sizes = []
        for name in loaded.pages:
            img = Image.open(loaded.atlas_dir / name).convert("RGBA")
            pages.append(prepare_atlas_page(img, pma))
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
            glDeleteTextures([self.texture])
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

    def apply_hidden(self, model, hidden: Set[str]) -> None:
        for name in hidden:
            idx = self.slot_index.get(name)
            if idx is not None:
                model.set_slot_alpha_by_index(idx, 0.0)

    def draw(self, model, viewport_w: int, viewport_h: int,
             offset_x: float, offset_y: float, scale: float) -> None:
        n_pages = len(self.page_offsets)
        offs = (ctypes.c_float * n_pages)(*self.page_offsets)
        pw = (ctypes.c_float * n_pages)(*[s[0] for s in self.page_sizes])
        ph = (ctypes.c_float * n_pages)(*[s[1] for s in self.page_sizes])
        nv, nt, cap, blends, segs = model.build_mesh(
            0.0, 0.0, 1.0, offs, pw, ph, self.atlas_size[0], self.atlas_size[1])
        if nv <= 0:
            return
        geo, attrs, tris = model.mesh_data(nv, nt)
        pos = np.asarray(geo, dtype=np.float32).reshape(-1, 2)
        attr = np.asarray(attrs, dtype=np.float32).reshape(-1, 6)
        idx = np.asarray(tris, dtype=np.uint16)
        glUseProgram(self.program)
        glUniform2f(glGetUniformLocation(self.program, "u_viewport"), float(viewport_w), float(viewport_h))
        glUniform2f(glGetUniformLocation(self.program, "u_offset"), float(offset_x), float(offset_y))
        glUniform2f(glGetUniformLocation(self.program, "u_scale"), float(scale), float(scale))
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
                glDrawElements(GL_TRIANGLES, (segs[i + 1] - segs[i]) * 3, GL_UNSIGNED_SHORT,
                               ctypes.c_void_p(segs[i] * 3 * 2))
        else:
            glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
            glDrawElements(GL_TRIANGLES, nt * 3, GL_UNSIGNED_SHORT, ctypes.c_void_p(0))
        glBindVertexArray(0)
        glDisable(GL_BLEND)

    def dispose(self) -> None:
        if self.texture:
            glDeleteTextures([self.texture])
            self.texture = 0
        if self.program:
            glDeleteProgram(self.program)
            self.program = 0
        if self.vao:
            glDeleteVertexArrays(1, [self.vao])
            self.vao = 0
