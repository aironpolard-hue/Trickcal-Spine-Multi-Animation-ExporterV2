from __future__ import annotations

import copy
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from . import services
from .model import (
    Clip, ExportSettings, LoadedRole, ProjectState, RoleEntry, Settings,
    autosave_file, clamp, clip_index_at, clip_start,
    insertion_index_at, local_time_in_clip, now_millis, total_duration,
)


class TaskSignals(QObject):
    done = Signal(int, object, object)


class Task(QRunnable):
    def __init__(self, token: int, fn):
        super().__init__()
        self.token = token
        self.fn = fn
        self.signals = TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
            self.signals.done.emit(self.token, result, None)
        except Exception as exc:  # noqa: BLE001
            self.signals.done.emit(self.token, None, exc)


class EditorState(QObject):
    message = Signal(str)
    roles_changed = Signal()
    role_loading = Signal(str)
    role_ready = Signal()
    role_failed = Signal(str)
    timeline_changed = Signal()
    selection_changed = Signal()
    settings_changed = Signal()
    playing_changed = Signal()
    skin_changed = Signal()
    parts_changed = Signal()
    project_changed = Signal()
    scan_changed = Signal()
    queue_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = services.load_settings()
        self.roles: List[RoleEntry] = []
        self.scan_roots: List[str] = []
        self.active_root = ""
        self.selected_role_entry: Optional[RoleEntry] = None
        self.loaded: Optional[LoadedRole] = None
        self.selected_action = ""
        self.preview_action = ""
        self.current_skin = ""
        self.hidden_slots: set[str] = set()
        self.timeline: List[Clip] = []
        self.selected_indices: set[int] = set()
        self.playhead = 0.0
        self.playing = False
        self.export = ExportSettings()
        self.project_id = ""
        self.project_name = ""
        self.undo_stack: List[Tuple[List[Clip], set, float]] = []
        self.clipboard: List[Clip] = []
        self.redo_stack: List[Tuple[List[Clip], set, float]] = []
        self._history_key = ""
        self._history_time = 0.0
        self._task_token = 0
        self._load_token = 0
        self._scan_token = 0
        self._pool = QThreadPool.globalInstance()
        self._tasks: List[Task] = []
        self._role_defaults_applied = False
        self._pending_restore: Optional[ProjectState] = None
        self._autosave_timer = None
        self._last_autosave = 0
        self._loading = False
        self._bootstrap()

    # ------------------------------------------------------------------
    # bootstrap
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        state: Optional[ProjectState] = None
        if autosave_file().is_file():
            state = services.load_autosave()
        else:
            state = self._migrate_old_autosave()
        if state:
            self.scan_roots = [p for p in state.scan_roots if p.strip()]
            self.active_root = state.active_root or (self.scan_roots[0] if self.scan_roots else "")
            self.export = state.export
            self.project_id = state.project_id
            self.project_name = state.name
            self._pending_restore = state
        elif not self.scan_roots:
            legacy_root = Path("C:/project/com.epidgames.trickcalrevive/files/Packages/spine")
            if legacy_root.is_dir():
                self.scan_roots = [str(legacy_root)]
                self.active_root = str(legacy_root)
        if not self.scan_roots:
            self.scan_roots = [str(services.PROJECT_ROOT / "assets")]
            self.active_root = self.scan_roots[0]
        self._refresh_roles(initial=True)

    def _migrate_old_autosave(self) -> Optional[ProjectState]:
        old = Path.home() / "AppData/Local/AAspineTool/autosave/project-autosave.json"
        if not old.is_file():
            return None
        import json
        try:
            data = json.loads(old.read_text(encoding="utf-8"))
        except Exception:
            return None
        state = ProjectState()
        state.scan_roots = [str(v) for v in (data.get("scanRoots") or []) if str(v).strip()]
        state.active_root = str(data.get("activeScanRoot") or "")
        state.role_name = str(data.get("roleName") or "")
        state.skin = str(data.get("skinName") or "")
        export = data.get("export") or {}
        state.export = ExportSettings.from_dict({
            "format": "PNG",
            "quality": export.get("qualityIndex", 2),
            "fps": 30,
            "customFps": 30,
            "transparent": True,
            "outputDir": "export-output",
            "background": [export.get("bgR", 31), export.get("bgG", 33), export.get("bgB", 46)],
            "roleX": export.get("roleX", 720),
            "roleY": export.get("roleY", 633),
            "roleScale": export.get("roleScale", 0.8),
            "region": [
                export.get("regionX", 390), export.get("regionY", 180),
                export.get("regionWidth", 660), export.get("regionHeight", 540),
            ],
            "stageWidth": 1440, "stageHeight": 900, "workers": 4,
        })
        timeline = data.get("timeline")
        if isinstance(timeline, list):
            for item in timeline:
                if isinstance(item, dict) and item.get("action"):
                    state.timeline.append(Clip.from_dict(item))
        state.hidden_slots = [str(v) for v in (data.get("hiddenParts") or [])]
        return state

    # ------------------------------------------------------------------
    # scanning
    # ------------------------------------------------------------------

    def add_scan_root(self, path: str) -> bool:
        value = (path or "").strip()
        if not value:
            self.message.emit("请输入文件夹路径")
            return False
        root = Path(value)
        if not root.is_dir():
            self.message.emit("路径不是有效文件夹")
            return False
        normalized = str(root.resolve())
        for existing in self.scan_roots:
            try:
                if Path(existing).resolve() == root.resolve():
                    self.active_root = existing
                    self.message.emit("文件夹已在列表中")
                    self._refresh_roles()
                    return True
            except OSError:
                pass
        self.scan_roots.append(normalized)
        self.active_root = normalized
        self.message.emit("已添加扫描文件夹")
        self._refresh_roles()
        return True

    def remove_scan_root(self, path: str) -> None:
        if len(self.scan_roots) <= 1:
            self.message.emit("至少保留一个扫描路径")
            return
        try:
            self.scan_roots.remove(path)
        except ValueError:
            return
        if self.active_root == path:
            self.active_root = self.scan_roots[0]
        self._refresh_roles()
        self.message.emit("已删除扫描路径")

    def select_scan_root(self, path: str) -> None:
        if path in self.scan_roots:
            self.active_root = path
            self.message.emit("已切换扫描文件夹")
            self._refresh_roles()

    def rescan(self) -> None:
        self._refresh_roles()

    def _refresh_roles(self, initial: bool = False) -> None:
        self._scan_token += 1
        token = self._scan_token
        roots = list(self.scan_roots)
        task = Task(token, lambda: services.scan_roles(roots))
        task.signals.done.connect(self._on_scan_done)
        self._tasks.append(task)
        self._pool.start(task)
        if not initial:
            self.scan_changed.emit()

    def _on_scan_done(self, token: int, result, error) -> None:
        self._tasks = [t for t in self._tasks if t.token != token]
        if token != self._scan_token:
            return
        if error:
            self.message.emit(f"扫描失败：{error}")
            return
        self.roles = result or []
        self.roles_changed.emit()
        if self.roles:
            self.message.emit(f"已扫描 {len(self.roles)} 个角色")
        else:
            self.message.emit("当前文件夹没有找到 Spine 角色")
        target = None
        if self._pending_restore and self._pending_restore.role_name:
            wanted = self._pending_restore.role_name
            for entry in self.roles:
                if entry.name.lower() == wanted.lower():
                    target = entry
                    break
        if target is None and self.roles and self.selected_role_entry is None:
            target = self.roles[0]
        if target is not None and (self.selected_role_entry is None or
                                   self.selected_role_entry.unique_key != target.unique_key):
            self.select_role(target)
        elif not self.roles:
            self.selected_role_entry = None
            self.loaded = None
            self.timeline = []
            self.selected_indices.clear()
            self.timeline_changed.emit()
            self.role_failed.emit("没有可用角色")

    # ------------------------------------------------------------------
    # role loading
    # ------------------------------------------------------------------

    def select_role(self, entry: RoleEntry) -> None:
        self.selected_role_entry = entry
        self._loading = True
        self._load_token += 1
        token = self._load_token
        preferred = self.current_skin
        self.role_loading.emit(entry.name)
        task = Task(token, lambda: services.load_role(entry, preferred))
        task.signals.done.connect(self._on_role_loaded)
        self._tasks.append(task)
        self._pool.start(task)

    def _on_role_loaded(self, token: int, result, error) -> None:
        self._tasks = [t for t in self._tasks if t.token != token]
        if token != self._load_token:
            if result is not None:
                services.dispose_role(result)
            return
        self._loading = False
        if error or result is None:
            self.message.emit(f"角色读取失败：{error}")
            self.role_failed.emit(str(error))
            return
        old = self.loaded
        self.loaded = result
        if old is not None:
            services.dispose_role(old)
        self.current_skin = ""
        skins = result.skins
        if skins:
            preferred = ""
            if self._pending_restore and self._pending_restore.skin in skins:
                preferred = self._pending_restore.skin
            self.current_skin = preferred or result.model.default_skin_name or skins[0]
            try:
                result.model.set_skin(self.current_skin)
            except Exception:
                pass
        idle = next((a for a in result.actions if a.strip().lower() in ("idle", "stand", "wait", "default")),
                    None)
        self.selected_action = idle or (result.actions[0] if result.actions else "")
        self.preview_action = self.selected_action
        self.hidden_slots.clear()
        self.timeline = []
        self.selected_indices.clear()
        self.playhead = 0.0
        self.undo_stack.clear()
        self.redo_stack.clear()
        self._history_key = ""
        if self._pending_restore is not None:
            state = self._pending_restore
            self._pending_restore = None
            if state.role_name.lower() == result.entry.name.lower():
                self.timeline = [c.copy() for c in state.timeline if c.action in set(result.actions)]
                self.hidden_slots = set(s for s in state.hidden_slots if s in set(result.slots))
                if state.skin in skins:
                    self.current_skin = state.skin
                    try:
                        result.model.set_skin(self.current_skin)
                    except Exception:
                        pass
                self.playhead = 0.0
                if self.timeline:
                    self.selected_indices = {0}
                    self.preview_action = self.timeline[0].action
                self.message.emit(f"已恢复上次自动保存：{result.entry.name}，时间轴 {len(self.timeline)} 个片段")
        if not self._role_defaults_applied:
            self._role_defaults_applied = True
            self._fit_role_defaults(result)
        if not self.timeline:
            self.message.emit(f"已读取角色：{result.entry.name}，动作 {len(result.actions)} 个，皮肤 {len(result.skins)} 个")
        self.role_ready.emit()
        self.skin_changed.emit()
        self.parts_changed.emit()
        self.timeline_changed.emit()
        self.selection_changed.emit()
        self._schedule_autosave()

    def _fit_role_defaults(self, loaded: LoadedRole) -> None:
        bounds = loaded.reference_bounds
        if not bounds:
            return
        minx, miny, maxx, maxy = bounds
        width = max(1.0, maxx - minx)
        height = max(1.0, maxy - miny)
        stage = self.export.stage_w, self.export.stage_h
        scale = min(stage[0] * 0.55 / width, stage[1] * 0.70 / height)
        scale = clamp(scale, 0.05, 5.0)
        self.export.role_scale = scale
        self.export.role_x = stage[0] * 0.5 - (minx + maxx) * 0.5 * scale
        self.export.role_y = stage[1] * 0.55 - (miny + maxy) * 0.5 * scale
        self.export.keep_inside()
        self.export.region = (
            clamp(stage[0] * 0.18, 0, stage[0]),
            clamp(stage[1] * 0.10, 0, stage[1]),
            clamp(stage[0] * 0.64, 40, stage[0]),
            clamp(stage[1] * 0.80, 40, stage[1]),
        )
        self.export.keep_inside()

    def reload_current_role(self) -> None:
        if self.selected_role_entry is not None:
            self.select_role(self.selected_role_entry)

    # ------------------------------------------------------------------
    # skin / action / parts
    # ------------------------------------------------------------------

    def set_skin(self, name: str) -> None:
        if not self.loaded or name not in self.loaded.skins:
            return
        try:
            self.loaded.model.set_skin(name)
        except Exception as exc:
            self.message.emit(f"切换皮肤失败：{exc}")
            return
        self.current_skin = name
        self.hidden_slots.clear()
        self.skin_changed.emit()
        self.parts_changed.emit()
        self.message.emit(f"已选择皮肤：{name}")
        self._schedule_autosave()

    def set_action(self, name: str) -> None:
        if not self.loaded or name not in self.loaded.actions:
            return
        self.selected_action = name
        if not self.timeline:
            self.preview_action = name
        self.message.emit(f"已选择动作：{name}")
        self._schedule_autosave()

    def preview_only(self, name: str) -> None:
        if name in self.loaded.actions if self.loaded else False:
            self.selected_action = name
            if not self.timeline:
                self.preview_action = name

    def toggle_slot(self, name: str) -> None:
        if name in self.hidden_slots:
            self.hidden_slots.remove(name)
            self.message.emit(f"已显示部件：{name}")
        else:
            self.hidden_slots.add(name)
            self.message.emit(f"已隐藏部件：{name}")
        self.parts_changed.emit()
        self._schedule_autosave()

    def reset_hidden_slots(self) -> None:
        self.hidden_slots.clear()
        self.parts_changed.emit()
        self.message.emit("已重置模型部件显示")

    # ------------------------------------------------------------------
    # timeline
    # ------------------------------------------------------------------

    def total_duration(self) -> float:
        return total_duration(self.timeline)

    def clip_at(self, time_seconds: Optional[float] = None) -> int:
        t = self.playhead if time_seconds is None else time_seconds
        return clip_index_at(self.timeline, t)

    def selected_clips(self) -> List[int]:
        return sorted(i for i in self.selected_indices if 0 <= i < len(self.timeline))

    def checkpoint(self, merge_key: str = "") -> None:
        key = merge_key or ""
        if key and key == self._history_key and now_millis() - self._history_time < 700:
            self._history_time = now_millis()
            return
        self.undo_stack.append(([c.copy() for c in self.timeline], set(self.selected_indices), self.playhead))
        if len(self.undo_stack) > 100:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self._history_key = key
        self._history_time = now_millis()

    def undo(self) -> None:
        if not self.undo_stack:
            self.message.emit("没有可撤销的时间轴修改")
            return
        self.redo_stack.append(([c.copy() for c in self.timeline], set(self.selected_indices), self.playhead))
        clips, selection, playhead = self.undo_stack.pop()
        self.timeline = [c.copy() for c in clips]
        self.selected_indices = set(i for i in selection if 0 <= i < len(self.timeline))
        self.playhead = clamp(playhead, 0, max(0, self.total_duration() - 0.001))
        self._after_timeline_change()
        self.message.emit("已撤销时间轴修改")

    def redo(self) -> None:
        if not self.redo_stack:
            self.message.emit("没有可重做的时间轴修改")
            return
        self.undo_stack.append(([c.copy() for c in self.timeline], set(self.selected_indices), self.playhead))
        clips, selection, playhead = self.redo_stack.pop()
        self.timeline = [c.copy() for c in clips]
        self.selected_indices = set(i for i in selection if 0 <= i < len(self.timeline))
        self.playhead = clamp(playhead, 0, max(0, self.total_duration() - 0.001))
        self._after_timeline_change()
        self.message.emit("已重做时间轴修改")

    def add_action(self, action: str, index: Optional[int] = None) -> None:
        if not self.loaded or action not in self.loaded.actions:
            return
        self.checkpoint()
        if index is None:
            index = insertion_index_at(self.timeline, self.playhead)
            if not self.timeline:
                index = 0
        index = max(0, min(index, len(self.timeline)))
        duration = self.loaded.durations.get(action, 1.5)
        self.timeline.insert(index, Clip(action, duration))
        self.selected_indices = {index}
        self.playhead = clip_start(self.timeline, index)
        self.selected_action = action
        self.preview_action = action
        self._after_timeline_change()
        self.message.emit(f"已添加动作：{action}")

    def add_clip(self, clip: Clip, index: Optional[int] = None) -> None:
        self.checkpoint()
        if index is None:
            index = len(self.timeline)
        index = max(0, min(index, len(self.timeline)))
        self.timeline.insert(index, clip)
        self.selected_indices = {index}
        self.playhead = clip_start(self.timeline, index)
        self._after_timeline_change()

    def remove_selected(self) -> None:
        indices = self.selected_clips()
        if not indices:
            self.message.emit("没有可删除的片段")
            return
        self.checkpoint()
        for index in reversed(indices):
            del self.timeline[index]
        self.selected_indices.clear()
        self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
        self._after_timeline_change()
        self.message.emit("已删除片段")

    def select_only(self, index: int) -> None:
        if 0 <= index < len(self.timeline):
            self.selected_indices = {index}
            if self.timeline:
                self.selected_action = self.timeline[index].action
        else:
            self.selected_indices.clear()
        self.selection_changed.emit()

    def toggle_selection(self, index: int) -> None:
        if not (0 <= index < len(self.timeline)):
            return
        if index in self.selected_indices:
            self.selected_indices.remove(index)
        else:
            self.selected_indices.add(index)
        self.selection_changed.emit()

    def set_selection(self, indices) -> None:
        self.selected_indices = {i for i in indices if 0 <= i < len(self.timeline)}
        self.selection_changed.emit()

    def move_selected(self, target_insert: int) -> None:
        indices = self.selected_clips()
        if not indices:
            return
        first, last = indices[0], indices[-1]
        target = max(0, min(target_insert, len(self.timeline)))
        if first <= target <= last + 1:
            return
        self.checkpoint()
        moving = [self.timeline[i] for i in indices]
        for index in reversed(indices):
            del self.timeline[index]
            if index < target:
                target -= 1
        target = max(0, min(target, len(self.timeline)))
        for offset, clip in enumerate(moving):
            self.timeline.insert(target + offset, clip)
        self.selected_indices = set(range(target, target + len(moving)))
        self.playhead = clip_start(self.timeline, target)
        self._after_timeline_change()
        self.message.emit(f"已移动 {len(moving)} 个片段")

    def update_clip_duration_live(self, index: int, duration: float) -> None:
        if 0 <= index < len(self.timeline):
            self.timeline[index].duration = clamp(duration, 0.05, 3600)
            self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
            self.timeline_changed.emit()

    def update_transition_duration_live(self, index: int, duration: float) -> None:
        if 0 <= index < len(self.timeline):
            clip = self.timeline[index]
            clip.transition_enabled = True
            clip.transition_duration = clamp(duration, 0.0, max(0.0, clip.duration))
            self.timeline_changed.emit()

    def finish_live_edit(self, message: str = "") -> None:
        self.selected_indices = {i for i in self.selected_indices if 0 <= i < len(self.timeline)}
        self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
        self.timeline_changed.emit()
        self.selection_changed.emit()
        if message:
            self.message.emit(message)
        self._schedule_autosave()

    def copy_selected(self) -> None:
        indices = self.selected_clips()
        if not indices:
            self.message.emit("请先选择片段")
            return
        self.clipboard = [self.timeline[i].copy() for i in indices]
        self.message.emit(f"已复制 {len(self.clipboard)} 个片段")

    def cut_selected(self) -> None:
        indices = self.selected_clips()
        if not indices:
            self.message.emit("请先选择片段")
            return
        self.clipboard = [self.timeline[i].copy() for i in indices]
        self.checkpoint()
        for index in reversed(indices):
            del self.timeline[index]
        self.selected_indices.clear()
        self._after_timeline_change()
        self.message.emit(f"已剪切 {len(self.clipboard)} 个片段")

    def paste(self) -> None:
        if not self.clipboard:
            self.message.emit("剪贴板没有片段")
            return
        index = insertion_index_at(self.timeline, self.playhead)
        self.checkpoint()
        self.selected_indices.clear()
        for offset, clip in enumerate(self.clipboard):
            self.timeline.insert(index + offset, clip.copy())
            self.selected_indices.add(index + offset)
        self.playhead = clip_start(self.timeline, index)
        self._after_timeline_change()
        self.message.emit(f"已粘贴 {len(self.clipboard)} 个片段")

    def delete_selected(self) -> None:
        self.remove_selected()

    def set_clip_duration(self, index: int, duration: float) -> None:
        if 0 <= index < len(self.timeline):
            self.checkpoint("clip-duration")
            self.timeline[index].duration = clamp(duration, 0.05, 3600)
            self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
            self._after_timeline_change()

    def split_at_playhead(self) -> None:
        index = self.clip_at()
        if index < 0 or not self.timeline:
            return
        clip = self.timeline[index]
        local = self.playhead - clip_start(self.timeline, index)
        if local <= 0.05 or local >= clip.duration - 0.05:
            self.message.emit("播放头不在片段内部")
            return
        self.checkpoint()
        right = clip.copy()
        clip.duration = local
        right.duration = max(0.05, right.duration - local)
        self.timeline.insert(index + 1, right)
        self.selected_indices = {index + 1}
        self._after_timeline_change()
        self.message.emit("已在播放头分割片段")

    def trim_left(self) -> None:
        index = self.clip_at()
        if index < 0 or not self.timeline:
            return
        start = clip_start(self.timeline, index)
        local = self.playhead - start
        if local <= 0.05:
            return
        self.checkpoint()
        self.timeline[index].duration = max(0.05, self.timeline[index].duration - local)
        self.playhead = start
        self._after_timeline_change()

    def trim_right(self) -> None:
        index = self.clip_at()
        if index < 0 or not self.timeline:
            return
        start = clip_start(self.timeline, index)
        local = self.playhead - start
        if local <= 0.05:
            return
        self.checkpoint()
        self.timeline[index].duration = local
        self._after_timeline_change()

    def trim_timeline_left(self) -> None:
        if not self.timeline:
            return
        self.checkpoint()
        while self.timeline and clip_start(self.timeline, 1) <= self.playhead:
            del self.timeline[0]
            self.selected_indices = {max(0, i - 1) for i in self.selected_indices if i > 0}
        if self.timeline:
            local = self.playhead
            self.timeline[0].duration = max(0.05, self.timeline[0].duration - local)
        self.playhead = 0
        self._after_timeline_change()

    def trim_timeline_right(self) -> None:
        if not self.timeline:
            return
        self.checkpoint()
        total = 0.0
        out = []
        for clip in self.timeline:
            if total >= self.playhead:
                break
            remain = self.playhead - total
            if remain < clip.duration:
                copy_clip = clip.copy()
                copy_clip.duration = max(0.05, remain)
                out.append(copy_clip)
                total += copy_clip.duration
                break
            out.append(clip)
            total += clip.duration
        self.timeline = out
        self.selected_indices = {i for i in self.selected_indices if i < len(out)}
        self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
        self._after_timeline_change()

    def _after_timeline_change(self) -> None:
        self.selected_indices = {i for i in self.selected_indices if 0 <= i < len(self.timeline)}
        if self.selected_indices:
            last = max(self.selected_indices)
            self.selected_action = self.timeline[last].action
        self.playhead = clamp(self.playhead, 0, max(0, self.total_duration() - 0.001))
        self.timeline_changed.emit()
        self.selection_changed.emit()
        self._schedule_autosave()

    # ------------------------------------------------------------------
    # playback / pose
    # ------------------------------------------------------------------

    def toggle_play(self) -> None:
        if not self.timeline:
            if self.loaded and self.preview_action:
                self.playing = False
                self.message.emit("时间轴为空，请把动作拖进时间轴")
            return
        self.playing = not self.playing
        self.playing_changed.emit()
        self.message.emit("开始播放时间线" if self.playing else "已暂停时间线")

    def tick(self, delta: float) -> bool:
        if not self.playing or not self.timeline:
            return False
        total = self.total_duration()
        self.playhead += max(0.0, delta)
        if total > 0 and self.playhead >= total:
            self.playhead %= total
        index = self.clip_at()
        if 0 <= index < len(self.timeline):
            self.selected_action = self.timeline[index].action
        return True

    def seek(self, seconds: float) -> None:
        self.playhead = clamp(seconds, 0, max(0, self.total_duration() - 0.001))
        index = self.clip_at()
        if 0 <= index < len(self.timeline):
            self.selected_action = self.timeline[index].action

    def pose_action_time(self) -> Tuple[str, float, float]:
        """返回 (当前动作, 动作内时间, 进入当前片段的时长)。"""
        if not self.timeline:
            return self.preview_action, 0.0, 0.0
        index = self.clip_at()
        if index < 0:
            return self.preview_action, 0.0, 0.0
        clip = self.timeline[index]
        start = clip_start(self.timeline, index)
        local = max(0.0, self.playhead - start)
        action_time = clip.start_offset + local * max(0.0, clip.speed)
        return clip.action, action_time, local

    # ------------------------------------------------------------------
    # project / autosave
    # ------------------------------------------------------------------

    def capture_project(self, name: Optional[str] = None) -> ProjectState:
        state = ProjectState()
        state.project_id = self.project_id
        state.name = name if name is not None else self.project_name
        state.scan_roots = list(self.scan_roots)
        state.active_root = self.active_root
        state.role_name = self.selected_role_entry.name if self.selected_role_entry else ""
        state.skin = self.current_skin
        state.timeline = [c.copy() for c in self.timeline]
        state.hidden_slots = list(self.hidden_slots)
        state.export = self.export.copy()
        return state

    def apply_project(self, state: ProjectState) -> None:
        self.export = state.export.copy()
        self._role_defaults_applied = True
        self.scan_roots = list(state.scan_roots)
        self.active_root = state.active_root or (self.scan_roots[0] if self.scan_roots else "")
        self.project_id = state.project_id
        self.project_name = state.name
        self._pending_restore = state
        self.selected_role_entry = None
        self._refresh_roles()

    def new_project(self) -> None:
        self.project_id = uuid.uuid4().hex[:12]
        self.project_name = ""
        self.timeline = []
        self.selected_indices.clear()
        self.playhead = 0.0
        self.hidden_slots.clear()
        self.message.emit("已新建工程方案")
        self.timeline_changed.emit()
        self.selection_changed.emit()
        self._schedule_autosave()

    def save_project(self, name: str) -> None:
        if not name.strip():
            name = self.selected_role_entry.name + " 方案" if self.selected_role_entry else "新方案"
        state = self.capture_project(name.strip())
        ok, pid = services.save_project(state, self.project_id)
        if ok:
            self.project_id = pid
            self.project_name = name.strip()
            self.message.emit(f"已保存方案：{name.strip()}")
            self.project_changed.emit()
            self._schedule_autosave()
        else:
            self.message.emit("保存方案失败")

    def _schedule_autosave(self) -> None:
        # 由 MainWindow 定时 flush；这里只标记 dirty
        self._last_autosave = 0

    def flush_autosave(self) -> None:
        if not self.loaded and not self.timeline:
            return
        state = self.capture_project()
        services.save_autosave(state)

    def shutdown(self) -> None:
        try:
            self.flush_autosave()
        except Exception:
            pass
        services.dispose_role(self.loaded)
        self.loaded = None
