from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import spine_core

APP_NAME = "Spine Studio"
APP_VERSION = "2.0.0"
APP_DIR_NAME = "SpineStudioV2"

QUALITY_NAMES = ["低", "中", "高", "超高", "极佳"]
QUALITY_SCALES = [0.5, 0.75, 1.0, 1.5, 2.0]
FPS_CHOICES = [12, 15, 24, 30, 60]
FORMATS = [
    ("PNG", "PNG 帧图片", "PNG SEQUENCE", "image"),
    ("MP4", "MP4 视频", "MP4", "film"),
    ("MKV", "MKV 视频", "MKV", "film"),
    ("WebM", "WebM 透明视频", "WEBM ALPHA", "film"),
    ("MOV", "MOV 透明视频", "MOV ALPHA", "film"),
    ("GIF", "GIF 动图", "GIF", "image"),
    ("APNG", "APNG 动图", "APNG", "image"),
    ("WebP", "WebP 动图", "WEBP", "image"),
]
FORMAT_NAMES = {f[0]: f[1] for f in FORMATS}
TRANSPARENT_FORMATS = {"PNG", "WebM", "MOV", "GIF", "APNG"}
LOSSY_FORMATS = {"GIF", "WebP"}


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def app_home_dir() -> Path:
    """可写的应用目录：单文件打包时使用 exe 所在目录，避免写进临时解包目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def project_dir() -> Path:
    path = app_data_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def autosave_file() -> Path:
    path = app_data_dir() / "autosave.json"
    return path


def settings_file() -> Path:
    return app_data_dir() / "settings.json"


def queue_file() -> Path:
    return app_data_dir() / "queue.json"


def unityfs_cache_dir() -> Path:
    path = app_data_dir() / "unityfs-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_millis() -> int:
    return int(time.time() * 1000)


def clamp(value: float, low: float, high: float) -> float:
    if not math.isfinite(value):
        return low
    return max(low, min(high, value))


def safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else fallback
    except (TypeError, ValueError):
        return fallback


@dataclass
class Clip:
    action: str
    duration: float = 1.5
    start_offset: float = 0.0
    speed: float = 1.0
    transition_enabled: bool = True
    transition_duration: float = 0.2
    transition_speed: float = 1.0

    def copy(self) -> "Clip":
        return Clip(self.action, self.duration, self.start_offset, self.speed,
                    self.transition_enabled, self.transition_duration, self.transition_speed)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "duration": self.duration,
            "startOffset": self.start_offset,
            "speed": self.speed,
            "transitionEnabled": self.transition_enabled,
            "transitionDuration": self.transition_duration,
            "transitionSpeed": self.transition_speed,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Clip":
        return Clip(
            str(data.get("action") or ""),
            clamp(safe_float(data.get("duration"), 1.5), 0.05, 3600.0),
            clamp(safe_float(data.get("startOffset"), 0.0), 0.0, 3600.0),
            clamp(safe_float(data.get("speed"), 1.0), 0.0, 8.0),
            bool(data.get("transitionEnabled", True)),
            clamp(safe_float(data.get("transitionDuration"), 0.2), 0.0, 3600.0),
            clamp(safe_float(data.get("transitionSpeed"), 1.0), 0.0, 8.0),
        )


@dataclass
class RoleEntry:
    name: str
    folder: str
    atlas: str
    skeleton: str
    unityfs: bool
    parent: str = ""

    @property
    def unique_key(self) -> Tuple[str, str]:
        return self.atlas.lower(), self.skeleton.lower()


@dataclass
class ExportSettings:
    format: str = "PNG"
    quality: int = 2
    fps: int = 30
    custom_fps: int = 30
    transparent: bool = False
    lossy: bool = False
    output_dir: str = "export-output"
    bg: Tuple[float, float, float] = (31.0, 33.0, 46.0)
    role_x: float = 720.0
    role_y: float = 633.0
    role_scale: float = 0.8
    region: Tuple[float, float, float, float] = (390.0, 180.0, 660.0, 540.0)
    stage_w: float = 1440.0
    stage_h: float = 900.0
    workers: int = 4

    def quality_scale(self) -> float:
        return QUALITY_SCALES[max(0, min(len(QUALITY_SCALES) - 1, self.quality))]

    def width(self) -> int:
        return max(1, round(self.region[2] * self.quality_scale()))

    def height(self) -> int:
        return max(1, round(self.region[3] * self.quality_scale()))

    def supports_transparent(self) -> bool:
        return self.format in TRANSPARENT_FORMATS

    def supports_lossy(self) -> bool:
        return self.format in LOSSY_FORMATS

    def transparent_enabled(self) -> bool:
        return self.transparent and self.supports_transparent()

    def keep_inside(self) -> None:
        self.stage_w = clamp(self.stage_w, 320, 3840)
        self.stage_h = clamp(self.stage_h, 200, 2160)
        x, y, w, h = self.region
        w = clamp(w, 40, self.stage_w)
        h = clamp(h, 40, self.stage_h)
        x = clamp(x, 0, self.stage_w - w)
        y = clamp(y, 0, self.stage_h - h)
        self.region = (x, y, w, h)
        self.role_x = clamp(self.role_x, 0, self.stage_w)
        self.role_y = clamp(self.role_y, 0, self.stage_h)
        self.role_scale = clamp(self.role_scale, 0.01, 25.0)

    def copy(self) -> "ExportSettings":
        return ExportSettings(
            self.format, self.quality, self.fps, self.custom_fps, self.transparent,
            self.lossy, self.output_dir, self.bg, self.role_x, self.role_y,
            self.role_scale, self.region, self.stage_w, self.stage_h, self.workers,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "format": self.format,
            "quality": self.quality,
            "fps": self.fps,
            "customFps": self.custom_fps,
            "transparent": self.transparent,
            "lossy": self.lossy,
            "outputDir": self.output_dir,
            "background": list(self.bg),
            "roleX": self.role_x,
            "roleY": self.role_y,
            "roleScale": self.role_scale,
            "region": list(self.region),
            "stageWidth": self.stage_w,
            "stageHeight": self.stage_h,
            "workers": self.workers,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ExportSettings":
        s = ExportSettings()
        if not isinstance(data, dict):
            return s
        if data.get("format") in FORMAT_NAMES:
            s.format = data["format"]
        s.quality = max(0, min(4, int(safe_float(data.get("quality"), 2))))
        s.fps = max(1, min(240, int(safe_float(data.get("fps"), 30))))
        s.custom_fps = max(1, min(240, int(safe_float(data.get("customFps"), 30))))
        s.transparent = bool(data.get("transparent", False))
        s.lossy = bool(data.get("lossy", False))
        s.output_dir = str(data.get("outputDir") or "export-output")
        bg = data.get("background") or [31, 33, 46]
        if isinstance(bg, (list, tuple)) and len(bg) >= 3:
            s.bg = (safe_float(bg[0], 31), safe_float(bg[1], 33), safe_float(bg[2], 46))
        s.role_x = safe_float(data.get("roleX"), 720)
        s.role_y = safe_float(data.get("roleY"), 633)
        s.role_scale = safe_float(data.get("roleScale"), 0.8)
        region = data.get("region") or [390, 180, 660, 540]
        if isinstance(region, (list, tuple)) and len(region) >= 4:
            s.region = tuple(safe_float(v, 0) for v in region[:4])  # type: ignore
        s.stage_w = safe_float(data.get("stageWidth"), 1440)
        s.stage_h = safe_float(data.get("stageHeight"), 900)
        s.workers = max(1, min(100, int(safe_float(data.get("workers"), 4))))
        s.keep_inside()
        return s


@dataclass
class LoadedRole:
    entry: RoleEntry
    model: spine_core.SpineModel
    atlas_dir: Path
    pages: List[str]
    actions: List[str]
    durations: Dict[str, float]
    skins: List[str]
    slots: List[str]
    groups: List[Tuple[str, List[str]]]
    reference_bounds: Optional[Tuple[float, float, float, float]]


@dataclass
class ProjectState:
    project_id: str = ""
    name: str = ""
    scan_roots: List[str] = field(default_factory=list)
    active_root: str = ""
    role_name: str = ""
    skin: str = ""
    timeline: List[Clip] = field(default_factory=list)
    hidden_slots: List[str] = field(default_factory=list)
    export: ExportSettings = field(default_factory=ExportSettings)
    saved_at: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": 2,
            "savedAt": self.saved_at,
            "projectId": self.project_id,
            "name": self.name,
            "scanRoots": self.scan_roots,
            "activeRoot": self.active_root,
            "roleName": self.role_name,
            "skin": self.skin,
            "timeline": [c.to_dict() for c in self.timeline],
            "hiddenSlots": self.hidden_slots,
            "export": self.export.to_dict(),
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ProjectState":
        s = ProjectState()
        if not isinstance(data, dict):
            return s
        s.saved_at = int(safe_float(data.get("savedAt"), 0))
        s.project_id = str(data.get("projectId") or "")
        s.name = str(data.get("name") or "")
        s.scan_roots = [str(v) for v in (data.get("scanRoots") or []) if str(v).strip()]
        s.active_root = str(data.get("activeRoot") or "")
        s.role_name = str(data.get("roleName") or "")
        s.skin = str(data.get("skin") or "")
        s.timeline = [Clip.from_dict(c) for c in (data.get("timeline") or [])
                      if isinstance(c, dict) and c.get("action")]
        s.hidden_slots = [str(v) for v in (data.get("hiddenSlots") or [])]
        s.export = ExportSettings.from_dict(data.get("export") or {})
        return s


@dataclass
class Settings:
    accent: str = "#6B7CFF"
    font_size: int = 13
    preview_width: int = 260
    preview_scale: float = 0.6
    preview_offset_x: float = 0
    preview_offset_y: float = -22
    follow_playhead: bool = True
    shortcuts: Dict[str, str] = field(default_factory=lambda: {
        "trim_right": "W", "split_right": "S", "trim_left": "Q",
        "split_left": "A", "trim_timeline_left": "E", "trim_timeline_right": "R",
    })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accent": self.accent, "fontSize": self.font_size,
            "previewWidth": self.preview_width, "previewScale": self.preview_scale,
            "previewOffsetX": self.preview_offset_x, "previewOffsetY": self.preview_offset_y,
            "followPlayhead": self.follow_playhead, "shortcuts": self.shortcuts,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "Settings":
        s = Settings()
        if not isinstance(data, dict):
            return s
        accent = str(data.get("accent") or "#6B7CFF")
        if re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
            s.accent = accent
        s.font_size = max(11, min(16, int(safe_float(data.get("fontSize"), 13))))
        s.preview_width = max(160, min(420, int(safe_float(data.get("previewWidth"), 260))))
        s.preview_scale = clamp(safe_float(data.get("previewScale"), 0.6), 0.2, 2.0)
        s.preview_offset_x = clamp(safe_float(data.get("previewOffsetX"), 0), -200, 200)
        s.preview_offset_y = clamp(safe_float(data.get("previewOffsetY"), -22), -200, 200)
        s.follow_playhead = bool(data.get("followPlayhead", True))
        shortcuts = data.get("shortcuts")
        if isinstance(shortcuts, dict):
            for key, value in shortcuts.items():
                if key in s.shortcuts and isinstance(value, str) and value:
                    s.shortcuts[key] = value[:1].upper()
        return s


def total_duration(clips: List[Clip]) -> float:
    return sum(max(0.0, c.duration) for c in clips)


def clip_start(clips: List[Clip], index: int) -> float:
    return sum(max(0.0, c.duration) for c in clips[:max(0, index)])


def clip_index_at(clips: List[Clip], time_seconds: float) -> int:
    cursor = 0.0
    for i, clip in enumerate(clips):
        if time_seconds < cursor + max(0.0, clip.duration):
            return i
        cursor += max(0.0, clip.duration)
    return len(clips) - 1 if clips else -1


def insertion_index_at(clips: List[Clip], time_seconds: float) -> int:
    cursor = 0.0
    for i, clip in enumerate(clips):
        mid = cursor + max(0.0, clip.duration) * 0.5
        if time_seconds < mid:
            return i
        cursor += max(0.0, clip.duration)
    return len(clips)


def local_time_in_clip(clips: List[Clip], time_seconds: float) -> float:
    index = clip_index_at(clips, time_seconds)
    if index < 0:
        return 0.0
    return max(0.0, time_seconds - clip_start(clips, index))


def group_slots(slots: List[str]) -> List[Tuple[str, List[str]]]:
    groups: Dict[str, List[str]] = {}
    for slot in slots:
        cut = -1
        for ch in ("_", "/", "-"):
            pos = slot.find(ch)
            if pos > 0 and (cut < 0 or pos < cut):
                cut = pos
        group = slot[:cut] if cut > 0 else "通用"
        groups.setdefault(group, []).append(slot)
    return list(groups.items())


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json_atomic(path: Path, data: Dict[str, Any]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        return False
