from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import spine_core

from .model import (
    APP_DIR_NAME, Clip, ExportSettings, LoadedRole, ProjectState, RoleEntry,
    Settings, app_data_dir, autosave_file, group_slots, now_millis, project_dir,
    queue_file, read_json, safe_float, settings_file, unityfs_cache_dir,
    write_json_atomic,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

_LOAD_LOCK = threading.Lock()
_SCAN_LOCK = threading.Lock()


class RoleLoadError(RuntimeError):
    pass


def _read_header(path: Path, size: int = 8) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(size)
    except OSError:
        return b""


def is_unityfs(path: Path) -> bool:
    return _read_header(path) == b"UnityFS\x00"


def _base_name(name: str, suffix: str) -> str:
    if name.lower().endswith(suffix):
        return name[: -len(suffix)]
    return name


def scan_roles(roots: Iterable[str], max_depth: int = 6,
               progress: Optional[Callable[[str], None]] = None) -> List[RoleEntry]:
    seen: set[Tuple[str, str]] = set()
    roles: List[RoleEntry] = []
    for root_value in roots:
        root_text = (root_value or "").strip()
        if not root_text:
            continue
        root = Path(root_text)
        if not root.is_dir():
            continue
        if progress:
            progress(str(root))
        _scan_folder(root, root, 0, max_depth, seen, roles)
    roles.sort(key=lambda r: (r.name.lower(), r.atlas.lower()))
    return roles


def _scan_folder(folder: Path, root: Path, depth: int, max_depth: int,
                 seen: set, out: List[RoleEntry]) -> None:
    if depth > max_depth:
        return
    try:
        entries = list(folder.iterdir())
    except OSError:
        return
    atlases: Dict[str, Path] = {}
    skeletons: Dict[str, Path] = {}
    json_skeletons: Dict[str, Path] = {}
    for child in entries:
        if child.is_dir():
            continue
        lower = child.name.lower()
        if lower.endswith(".atlas") or lower.endswith(".atlas.bytes"):
            key = _base_name(child.name, ".atlas.bytes" if lower.endswith(".atlas.bytes") else ".atlas").lower()
            atlases[key] = child
        elif lower.endswith(".skel") or lower.endswith(".skel.bytes"):
            key = _base_name(child.name, ".skel.bytes" if lower.endswith(".skel.bytes") else ".skel").lower()
            skeletons[key] = child
        elif lower.endswith(".skel.json"):
            key = _base_name(child.name, ".skel.json").lower()
            json_skeletons[key] = child
        elif lower.endswith(".json") and not lower.endswith(".atlas.json"):
            key = _base_name(child.name, ".json").lower()
            json_skeletons.setdefault(key, child)

    pair_count = len(atlases)
    for key, atlas in atlases.items():
        skeleton = skeletons.get(key) or json_skeletons.get(key)
        if skeleton is None:
            continue
        unityfs = is_unityfs(atlas) or is_unityfs(skeleton)
        unique = (str(atlas.resolve()).lower(), str(skeleton.resolve()).lower())
        if unique in seen:
            continue
        seen.add(unique)
        base_stem = atlas.name
        for suffix in (".atlas.bytes", ".atlas"):
            if base_stem.lower().endswith(suffix):
                base_stem = base_stem[: -len(suffix)]
                break
        if pair_count == 1 and folder.name.lower() == base_stem.lower():
            leaf = folder.name
        else:
            leaf = base_stem
        name = leaf
        if folder.parent != root and folder.parent.name:
            name = f"{folder.parent.name}/{leaf}"
        out.append(RoleEntry(name, str(folder), str(atlas), str(skeleton), unityfs,
                             str(folder.parent)))

    for child in entries:
        if child.is_dir() and not child.name.startswith("."):
            _scan_folder(child, root, depth + 1, max_depth, seen, out)


def resolve_role_assets(entry: RoleEntry) -> Tuple[Path, Path, Path]:
    folder = Path(entry.folder)
    atlas = Path(entry.atlas)
    skeleton = Path(entry.skeleton)
    if not folder.is_dir():
        raise RoleLoadError(f"角色目录不存在：{folder}")
    if not atlas.is_file() or not skeleton.is_file():
        raise RoleLoadError(f"资源文件缺失：{atlas.name} / {skeleton.name}")
    if not entry.unityfs:
        return folder, atlas, skeleton
    try:
        from unityfs_spine_reader import prepare
    except Exception as exc:
        raise RoleLoadError(f"UnityFS 读取器不可用：{exc}") from exc
    try:
        target = prepare(folder, atlas, skeleton, unityfs_cache_dir())
    except Exception as exc:
        raise RoleLoadError(f"读取 UnityFS 失败：{exc}") from exc
    atlas_out = target / atlas.name
    skeleton_out = target / skeleton.name
    if not atlas_out.is_file():
        candidates = sorted(target.glob("*.atlas"))
        if not candidates:
            raise RoleLoadError("UnityFS 缓存缺少 atlas")
        atlas_out = candidates[0]
    if not skeleton_out.is_file():
        candidates = sorted(target.glob("*.skel")) + sorted(target.glob("*.json"))
        if not candidates:
            raise RoleLoadError("UnityFS 缓存缺少骨架")
        skeleton_out = candidates[0]
    return target, atlas_out, skeleton_out


def load_role(entry: RoleEntry, preferred_skin: str = "") -> LoadedRole:
    with _LOAD_LOCK:
        folder, atlas_path, skeleton_path = resolve_role_assets(entry)
        try:
            model = spine_core.load_model(str(skeleton_path), str(atlas_path), scale=1.0)
        except Exception as exc:
            raise RoleLoadError(f"加载 Spine 失败：{exc}") from exc
        skins = model.skin_names
        skin = preferred_skin if preferred_skin in skins else model.default_skin_name
        if skin:
            try:
                model.set_skin(skin)
            except Exception:
                pass
        actions = list(model.animation_names)
        durations = {name: max(0.01, model.get_animation_duration(name)) for name in actions}
        slots = list(model.slot_names)
        groups = group_slots(slots)
        reference = None
        try:
            if actions:
                model.set_animation(actions[0], True)
                model.update(0.0)
            else:
                model.set_to_setup_pose()
                model.update(0.0)
            reference = model.collect_bounds()
        except Exception:
            reference = None
        return LoadedRole(
            entry=entry,
            model=model,
            atlas_dir=atlas_path.parent,
            pages=list(model.pages),
            actions=actions,
            durations=durations,
            skins=skins,
            slots=slots,
            groups=groups,
            reference_bounds=reference,
        )


def dispose_role(role: Optional[LoadedRole]) -> None:
    if role is None:
        return
    try:
        role.model.dispose()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------

def load_settings() -> Settings:
    return Settings.from_dict(read_json(settings_file()) or {})


def save_settings(settings: Settings) -> None:
    write_json_atomic(settings_file(), settings.to_dict())


def load_autosave() -> Optional[ProjectState]:
    data = read_json(autosave_file())
    if not data:
        return None
    state = ProjectState.from_dict(data)
    return state if state.role_name or state.timeline else None


def save_autosave(state: ProjectState) -> None:
    state.saved_at = now_millis()
    write_json_atomic(autosave_file(), state.to_dict())


def list_projects() -> List[Tuple[ProjectState, Path]]:
    result: List[Tuple[ProjectState, Path]] = []
    for path in sorted(project_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        data = read_json(path)
        if not data:
            continue
        state = ProjectState.from_dict(data)
        state.project_id = state.project_id or path.stem
        state.name = state.name or path.stem
        result.append((state, path))
    return result


def save_project(state: ProjectState, project_id: str = "") -> Tuple[bool, str]:
    state.saved_at = now_millis()
    state.project_id = project_id or state.project_id or uuid.uuid4().hex[:12]
    path = project_dir() / f"{state.project_id}.json"
    ok = write_json_atomic(path, state.to_dict())
    return ok, state.project_id


def delete_project(project_id: str) -> bool:
    path = project_dir() / f"{project_id}.json"
    try:
        path.unlink()
        return True
    except OSError:
        return False


def preset_file() -> Path:
    return app_data_dir() / "presets.json"


def load_custom_preset() -> Optional[Dict]:
    data = read_json(preset_file())
    return data if isinstance(data, dict) else None


def save_custom_preset(data: Dict) -> None:
    write_json_atomic(preset_file(), data)


def load_queue() -> List[Dict]:
    data = read_json(queue_file())
    if not isinstance(data, dict):
        return []
    jobs = data.get("jobs")
    return jobs if isinstance(jobs, list) else []


def save_queue(jobs: List[Dict]) -> None:
    write_json_atomic(queue_file(), {"schemaVersion": 1, "jobs": jobs})
