from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set

import numpy as np
from PIL import Image
from OpenGL.GL import *
from PySide6.QtCore import QObject, QThread, Signal, Qt
from PySide6.QtGui import QOffscreenSurface, QOpenGLContext, QSurfaceFormat

from . import services
from .gl_renderer import GLSpineRenderer
from .model import (APP_DIR_NAME, Clip, ExportSettings, LoadedRole,
                    RoleEntry, app_data_dir, app_home_dir, clamp,
                    clip_index_at, clip_start, now_millis, total_duration)

ROOT = services.PROJECT_ROOT
ASSETS = ROOT / "assets"
FFMPEG = ASSETS / "ffmpeg.exe"
GIFSICLE = ASSETS / "gifsicle.exe"


def quality_crf(quality: int) -> str:
    return {0: "32", 1: "28", 2: "23", 3: "18", 4: "14"}.get(quality, "23")


def quality_vp9_crf(quality: int) -> str:
    return {0: "42", 1: "36", 2: "30", 3: "24", 4: "18"}.get(quality, "30")


def quality_webp(quality: int) -> str:
    return {0: "60", 1: "72", 2: "82", 3: "90", 4: "95"}.get(quality, "82")


def quality_gifsicle(quality: int) -> int:
    return {0: 200, 1: 160, 2: 120, 3: 80, 4: 40}.get(quality, 120)


@dataclass
class ExportSnapshot:
    id: str = ""
    name: str = ""
    created: int = 0
    role_name: str = ""
    role_folder: str = ""
    atlas: str = ""
    skeleton: str = ""
    unityfs: bool = False
    skin: str = ""
    clips: List[Clip] = field(default_factory=list)
    hidden: List[str] = field(default_factory=list)
    export: ExportSettings = field(default_factory=ExportSettings)

    def total_duration(self) -> float:
        return total_duration(self.clips)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "created": self.created,
            "roleName": self.role_name, "roleFolder": self.role_folder,
            "atlas": self.atlas, "skeleton": self.skeleton, "unityfs": self.unityfs,
            "skin": self.skin, "clips": [c.to_dict() for c in self.clips],
            "hidden": self.hidden, "export": self.export.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict) -> "ExportSnapshot":
        s = ExportSnapshot()
        if not isinstance(data, dict):
            return s
        s.id = str(data.get("id") or "")
        s.name = str(data.get("name") or "")
        s.created = int(data.get("created") or 0)
        s.role_name = str(data.get("roleName") or "")
        s.role_folder = str(data.get("roleFolder") or "")
        s.atlas = str(data.get("atlas") or "")
        s.skeleton = str(data.get("skeleton") or "")
        s.unityfs = bool(data.get("unityfs", False))
        s.skin = str(data.get("skin") or "")
        s.clips = [Clip.from_dict(c) for c in (data.get("clips") or [])
                   if isinstance(c, dict) and c.get("action")]
        s.hidden = [str(v) for v in (data.get("hidden") or [])]
        s.export = ExportSettings.from_dict(data.get("export") or {})
        return s


class ExportSignals(QObject):
    progress = Signal(int, int, str)
    finished = Signal(bool, str, str)
    log = Signal(str)


class ExportWorker(QThread):
    def __init__(self, snapshot: ExportSnapshot, parent=None):
        super().__init__(parent)
        self.snapshot = snapshot
        self.signals = ExportSignals()
        self._cancel = False
        self._process: Optional[subprocess.Popen] = None
        self.output_dir: Optional[Path] = None

    def cancel(self) -> None:
        self._cancel = True
        proc = self._process
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass

    def run(self) -> None:
        loaded: Optional[LoadedRole] = None
        surface = None
        ctx = None
        renderer = None
        fbo = 0
        tex = 0
        try:
            exp = self.snapshot.export
            exp.keep_inside()
            total = self.snapshot.total_duration()
            fps = max(1, exp.fps)
            frames = max(1, int(np.ceil(total * fps)))
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            base = Path(exp.output_dir)
            if not base.is_absolute():
                base = app_home_dir() / base
            out = base / f"导出-{timestamp}"
            frames_dir = out / "图片"
            video_dir = out / "视频"
            log_dir = out / "日志"
            info_dir = out / "信息"
            for d in (frames_dir, video_dir, log_dir, info_dir):
                d.mkdir(parents=True, exist_ok=True)
            self.output_dir = out
            self.signals.progress.emit(0, frames, "正在准备资源…")

            entry = RoleEntry(self.snapshot.role_name, self.snapshot.role_folder,
                              self.snapshot.atlas, self.snapshot.skeleton,
                              self.snapshot.unityfs)
            loaded = services.load_role(entry, self.snapshot.skin)
            model = loaded.model
            if self.snapshot.skin:
                try:
                    model.set_skin(self.snapshot.skin)
                except Exception:
                    pass
            hidden = set(self.snapshot.hidden) & set(loaded.slots)

            fmt = QSurfaceFormat()
            fmt.setVersion(3, 3)
            fmt.setProfile(QSurfaceFormat.CoreProfile)
            fmt.setDepthBufferSize(24)
            surface = QOffscreenSurface()
            surface.setFormat(fmt)
            surface.create()
            ctx = QOpenGLContext()
            ctx.setFormat(fmt)
            if not ctx.create() or not ctx.makeCurrent(surface):
                raise RuntimeError("无法创建离屏 OpenGL 上下文")
            renderer = GLSpineRenderer()
            renderer.initialize()
            renderer.load_atlas(loaded)

            width = exp.width()
            height = exp.height()
            tex = int(glGenTextures(1))
            glBindTexture(GL_TEXTURE_2D, tex)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            fbo = int(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, fbo)
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, tex, 0)
            if glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError("离屏帧缓冲创建失败")
            glViewport(0, 0, width, height)

            qscale = exp.quality_scale()
            region = exp.region
            offset_x = (exp.role_x - region[0]) * qscale
            offset_y = (exp.role_y - region[1]) * qscale
            role_scale = exp.role_scale * qscale
            transparent = exp.transparent_enabled()
            bg = exp.bg
            current_action = ""
            current_index = -1
            active_mix = 0.0
            mix_speed = 1.0
            for frame in range(frames):
                if self._cancel:
                    raise InterruptedError("导出已取消")
                t = min(frame / fps, max(0.0, total - 1e-4))
                index = clip_index_at(self.snapshot.clips, t)
                action = self.snapshot.clips[index].action if index >= 0 else ""
                clip = self.snapshot.clips[index] if index >= 0 else None
                local = max(0.0, t - clip_start(self.snapshot.clips, index)) if clip else 0.0
                action_time = (clip.start_offset + local * clip.speed) if clip else 0.0
                clip_changed = index != current_index
                if clip_changed or action != current_action:
                    mix = 0.0
                    speed = 1.0
                    if (clip is not None and index > 0 and current_action
                            and action != current_action and clip.transition_enabled
                            and clip.transition_duration > 0 and clip.transition_speed > 0):
                        mix = max(0.0, min(clip.transition_duration, clip.duration))
                        speed = clip.transition_speed
                    if mix > 0:
                        model.set_mix(current_action, action, mix)
                        if not model.set_animation(action, True):
                            model.clear_tracks()
                            model.set_animation(loaded.actions[0] if loaded.actions else "", True)
                            mix = 0.0
                    else:
                        model.clear_tracks()
                        if not model.set_animation(action, True):
                            model.set_animation(loaded.actions[0] if loaded.actions else "", True)
                    current_action = action
                    current_index = index
                    active_mix = mix
                    mix_speed = max(0.0, speed)
                if active_mix > 0:
                    progress = min(1.0, local * mix_speed / active_mix)
                    mix_time = progress * progress * (3.0 - 2.0 * progress) * active_mix
                else:
                    mix_time = 0.0
                model.set_to_setup_pose()
                model.set_track_time(0, action_time, mix_time)
                model.update(0.0)
                renderer.apply_hidden(model, hidden)
                if transparent:
                    glClearColor(0, 0, 0, 0)
                else:
                    glClearColor(bg[0] / 255, bg[1] / 255, bg[2] / 255, 1.0)
                glClear(GL_COLOR_BUFFER_BIT)
                renderer.draw(model, width, height, offset_x, offset_y, role_scale)
                glFinish()
                data = glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE)
                arr = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)[::-1]
                if transparent:
                    alpha = arr[..., 3:4].astype(np.float32) / 255.0
                    rgb = arr[..., :3].astype(np.float32)
                    safe = np.where(alpha > 0.002, alpha, 1.0)
                    rgb = np.clip(rgb / safe, 0, 255)
                    arr = np.concatenate([rgb.astype(np.uint8), arr[..., 3:4]], axis=2)
                Image.fromarray(arr, "RGBA").save(frames_dir / f"frame_{frame + 1:05d}.png")
                if frame % 2 == 0 or frame + 1 == frames:
                    self.signals.progress.emit(frame + 1, frames,
                                               f"正在渲染 {frame + 1}/{frames} 帧")
            if exp.format != "PNG":
                self.signals.progress.emit(frames, frames, "正在合成视频…")
                success = self._encode(frames_dir, video_dir, log_dir, frames, fps, exp)
                if self._cancel:
                    raise InterruptedError("导出已取消")
                if not success:
                    raise RuntimeError("视频合成失败，详见日志")
            self._write_info(out / "信息", total, frames, width, height, fps, exp)
            self.signals.progress.emit(frames, frames, "导出完成")
            self.signals.finished.emit(True, "导出完成", str(out))
        except InterruptedError:
            self.signals.finished.emit(False, "导出已停止", str(self.output_dir or ""))
        except Exception as exc:
            self.signals.finished.emit(False, f"导出失败：{exc}", str(self.output_dir or ""))
        finally:
            try:
                if loaded:
                    services.dispose_role(loaded)
            except Exception:
                pass
            try:
                if ctx and renderer:
                    ctx.makeCurrent(surface)
                    renderer.dispose()
                    if fbo:
                        glDeleteFramebuffers(1, [fbo])
                    if tex:
                        glDeleteTextures([tex])
                    ctx.doneCurrent()
            except Exception:
                pass

    def _write_info(self, info_dir: Path, total: float, frames: int,
                    width: int, height: int, fps: int, exp: ExportSettings) -> None:
        try:
            data = {
                "role": self.snapshot.role_name,
                "skin": self.snapshot.skin,
                "width": width,
                "height": height,
                "fps": fps,
                "frames": frames,
                "durationSeconds": round(total, 4),
                "format": exp.format,
                "quality": exp.quality,
                "transparent": exp.transparent_enabled(),
                "createdAt": now_millis(),
            }
            (info_dir / "export-info.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _run_process(self, command: List[str], cwd: Path, log_path: Path) -> bool:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with log_path.open("a", encoding="utf-8", errors="replace") as log:
                log.write("Command: " + " ".join(command) + "\n\n")
                log.flush()
                self._process = subprocess.Popen(
                    command, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                code = self._process.wait(timeout=60 * 60)
                log.write(f"\nExitCode: {code}\n")
                return code == 0
        except Exception as exc:
            try:
                log_path.write_text(f"执行失败：{exc}\n", encoding="utf-8")
            except Exception:
                pass
            return False
        finally:
            self._process = None

    def _encode(self, frames_dir: Path, video_dir: Path, log_dir: Path,
                frames: int, fps: int, exp: ExportSettings) -> bool:
        if not FFMPEG.is_file():
            raise RuntimeError("找不到内置 FFmpeg")
        pattern = str(frames_dir / "frame_%05d.png")
        ext = {"MP4": "mp4", "MKV": "mkv", "WebM": "webm", "MOV": "mov",
               "GIF": "gif", "APNG": "apng", "WebP": "webp"}.get(exp.format, "mp4")
        name = {"MP4": "timeline.mp4", "MKV": "timeline.mkv",
                "WebM": "timeline-alpha.webm", "MOV": "timeline-alpha.mov",
                "GIF": "timeline.gif", "APNG": "timeline.apng",
                "WebP": "timeline.webp"}.get(exp.format, "timeline.mp4")
        out = video_dir / name
        common = [str(FFMPEG), "-y", "-framerate", str(fps),
                  "-start_number", "1", "-i", pattern]
        if exp.format == "MP4":
            cmd = common + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                            "-c:v", "libx264", "-preset", "medium",
                            "-crf", quality_crf(exp.quality), "-pix_fmt", "yuv420p",
                            "-movflags", "+faststart", str(out)]
        elif exp.format == "MKV":
            cmd = common + ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
                            "-c:v", "libx264", "-preset", "medium",
                            "-crf", quality_crf(exp.quality), "-pix_fmt", "yuv420p", str(out)]
        elif exp.format == "WebM":
            cmd = common + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                            "-auto-alt-ref", "0", "-crf", quality_vp9_crf(exp.quality),
                            "-b:v", "0", str(out)]
        elif exp.format == "MOV":
            cmd = common + ["-c:v", "qtrle", "-pix_fmt", "argb", str(out)]
        elif exp.format == "APNG":
            cmd = common + ["-plays", "0", "-f", "apng", str(out)]
        elif exp.format == "WebP":
            if exp.lossy:
                cmd = common + ["-loop", "0", "-c:v", "libwebp_anim",
                                "-lossless", "0", "-q:v", quality_webp(exp.quality),
                                "-compression_level", "6", str(out)]
            else:
                cmd = common + ["-loop", "0", "-c:v", "libwebp_anim",
                                "-lossless", "1", "-compression_level", "6", str(out)]
        else:  # GIF
            if exp.transparent:
                vf = ("[0:v]split[s0][s1];[s0]palettegen=reserve_transparent=on:"
                      "transparency_color=00FF00[p];[s1][p]paletteuse=alpha_threshold=128")
            else:
                vf = "[0:v]split[s0][s1];[s0]palettegen=stats_mode=diff[p];[s1][p]paletteuse=dither=bayer"
            cmd = common + ["-filter_complex", vf, str(out)]
        ok = self._run_process(cmd, video_dir, log_dir / "ffmpeg-log.txt")
        if not ok or not out.is_file() or out.stat().st_size == 0:
            return False
        if exp.format == "GIF" and exp.lossy and GIFSICLE.is_file():
            optimized = video_dir / "timeline-lossy.gif"
            gif_cmd = [str(GIFSICLE), "-O3", f"--lossy={quality_gifsicle(exp.quality)}",
                       name, "-o", optimized.name]
            if self._run_process(gif_cmd, video_dir, log_dir / "gifsicle-log.txt"):
                if optimized.is_file() and optimized.stat().st_size > 0:
                    out.unlink(missing_ok=True)
                    optimized.replace(out)
            optimized.unlink(missing_ok=True)
        return True


class ExportManager(QObject):
    started = Signal(object)
    finished = Signal(bool, str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[ExportWorker] = None
        self._running = False
        self._live: Set[ExportWorker] = set()

    def is_exporting(self) -> bool:
        return self._running and self.worker is not None

    def start(self, snapshot: ExportSnapshot) -> ExportWorker:
        if self.is_exporting():
            raise RuntimeError("已有导出任务正在进行")
        worker = ExportWorker(snapshot)
        self.worker = worker
        self._running = True
        self._live.add(worker)
        worker.signals.finished.connect(self._on_finished)
        worker.finished.connect(lambda w=worker: self._on_thread_done(w))
        self.started.emit(snapshot)
        worker.start()
        return worker

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()

    def _on_finished(self, ok: bool, message: str, path: str) -> None:
        self._running = False
        self.finished.emit(ok, message, path)

    def _on_thread_done(self, worker: ExportWorker) -> None:
        self._live.discard(worker)
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()
