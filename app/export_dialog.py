from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import List, Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QProgressBar, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from . import services, theme
from .dialogs import BaseDialog
from .export import ExportManager, ExportSnapshot, ExportWorker
from .icons import icon
from .model import (FORMATS, FPS_CHOICES, QUALITY_NAMES, Clip, ExportSettings,
                    now_millis, total_duration)
from .state import EditorState
from .widgets import ToggleSwitch

PRESETS = [
    ("PNG 透明帧 30", {"format": "PNG", "quality": 2, "fps": 30, "transparent": True, "lossy": False}),
    ("MP4 均衡 30", {"format": "MP4", "quality": 2, "fps": 30, "transparent": False, "lossy": False}),
    ("WebM 透明 30", {"format": "WebM", "quality": 2, "fps": 30, "transparent": True, "lossy": False}),
    ("GIF 透明 24", {"format": "GIF", "quality": 1, "fps": 24, "transparent": True, "lossy": True}),
    ("MOV 透明高清 60", {"format": "MOV", "quality": 3, "fps": 60, "transparent": True, "lossy": False}),
]


def build_snapshot(state: EditorState, name: str) -> Optional[ExportSnapshot]:
    if not state.loaded or not state.selected_role_entry or not state.timeline:
        return None
    entry = state.selected_role_entry
    return ExportSnapshot(
        id="job-" + uuid.uuid4().hex[:12],
        name=name or f"{entry.name} {state.export.format}",
        created=now_millis(),
        role_name=entry.name,
        role_folder=entry.folder,
        atlas=entry.atlas,
        skeleton=entry.skeleton,
        unityfs=entry.unityfs,
        skin=state.current_skin,
        clips=[c.copy() for c in state.timeline],
        hidden=sorted(state.hidden_slots),
        export=state.export.copy(),
    )


class ExportDialog(BaseDialog):
    def __init__(self, state: EditorState, manager: ExportManager, parent=None):
        super().__init__("导出", "渲染完整时间线，片段切换自动混合", "export", parent, 860, 740)
        self.state = state
        self.manager = manager
        self._syncing = False
        self._format_group = QButtonGroup(self)
        self._format_group.setExclusive(True)
        self._format_buttons = {}
        self._quality_group = QButtonGroup(self)
        self._quality_group.setExclusive(True)
        self._quality_buttons = {}

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(2, 2, 8, 2)
        lay.setSpacing(12)

        summary = QFrame()
        summary.setObjectName("Card")
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(14, 10, 14, 10)
        self.res_value = QLabel("")
        self.fps_value = QLabel("")
        self.frames_value = QLabel("")
        self.duration_value = QLabel("")
        for label, value in (("分辨率", self.res_value), ("帧率", self.fps_value),
                             ("预计帧数", self.frames_value), ("时长", self.duration_value)):
            col = QVBoxLayout()
            l = QLabel(label)
            l.setProperty("kind", "faint")
            value.setProperty("kind", "stat")
            col.addWidget(l)
            col.addWidget(value)
            sl.addLayout(col, 1)
        lay.addWidget(summary)

        row = QHBoxLayout()
        preset_label = QLabel("预设")
        preset_label.setProperty("kind", "faint")
        self.preset_combo = QComboBox()
        for name, data in PRESETS:
            self.preset_combo.addItem(name, dict(data))
        custom = services.load_custom_preset()
        if custom:
            self.preset_combo.addItem(custom.get("name", "我的预设"), custom)
        self.preset_combo.addItem("自定义", None)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        save_preset = QPushButton("保存当前")
        save_preset.setProperty("kind", "ghost")
        save_preset.setFixedHeight(28)
        save_preset.clicked.connect(self._save_preset)
        row.addWidget(preset_label)
        row.addWidget(self.preset_combo, 1)
        row.addWidget(save_preset)
        lay.addLayout(row)

        lay.addWidget(self._section("输出格式", "选择导出文件类型"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(7)
        grid.setVerticalSpacing(7)
        for i, (key, label, ext, kind) in enumerate(FORMATS):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setProperty("kind", "chip")
            b.setMinimumHeight(46)
            b.setIcon(icon(kind, 16, theme.TEXT2))
            b.setToolTip(ext)
            b.clicked.connect(lambda _=False, k=key: self._select_format(k))
            self._format_group.addButton(b, i)
            self._format_buttons[key] = b
            grid.addWidget(b, i // 4, i % 4)
        lay.addLayout(grid)

        lay.addWidget(self._section("画质与帧率", "视频质量同时影响体积与清晰度"))
        qrow = QHBoxLayout()
        qrow.setSpacing(6)
        for i, name in enumerate(QUALITY_NAMES):
            b = QPushButton(name)
            b.setCheckable(True)
            b.setProperty("kind", "chip")
            b.setFixedHeight(30)
            b.clicked.connect(lambda _=False, idx=i: self._select_quality(idx))
            self._quality_group.addButton(b, i)
            self._quality_buttons[i] = b
            qrow.addWidget(b)
        qrow.addStretch(1)
        lay.addLayout(qrow)

        frow = QHBoxLayout()
        frow.setSpacing(8)
        fps_label = QLabel("帧率")
        fps_label.setProperty("kind", "faint")
        self.fps_combo = QComboBox()
        for value in FPS_CHOICES:
            self.fps_combo.addItem(str(value), value)
        self.fps_combo.addItem("自定义", -1)
        self.fps_combo.currentIndexChanged.connect(self._on_fps_changed)
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setFixedWidth(84)
        self.fps_spin.valueChanged.connect(self._on_custom_fps)
        frow.addWidget(fps_label)
        frow.addWidget(self.fps_combo)
        frow.addWidget(self.fps_spin)
        frow.addStretch(1)
        lay.addLayout(frow)

        lay.addWidget(self._section("选项", "部分选项仅对特定格式生效"))
        option_row = QHBoxLayout()
        option_row.setSpacing(8)
        self.transparent_switch = ToggleSwitch(False)
        self.transparent_label = QLabel("透明背景")
        self.transparent_sub = QLabel("")
        self.lossy_switch = ToggleSwitch(False)
        self.lossy_label = QLabel("有损压缩")
        self.lossy_sub = QLabel("")
        self.transparent_switch.toggled.connect(self._on_transparent)
        self.lossy_switch.toggled.connect(self._on_lossy)
        option_row.addWidget(self._option_card(self.transparent_switch, self.transparent_label,
                                               self.transparent_sub))
        option_row.addWidget(self._option_card(self.lossy_switch, self.lossy_label, self.lossy_sub))
        lay.addLayout(option_row)

        lay.addWidget(self._section("输出位置", "每次导出都会自动创建独立目录"))
        out_row = QHBoxLayout()
        self.output_edit = QLineEdit(state.export.output_dir)
        self.output_edit.editingFinished.connect(self._on_output)
        browse = QPushButton("浏览")
        browse.setProperty("kind", "secondary")
        browse.setFixedHeight(32)
        browse.setIcon(icon("folder-open", 14, theme.TEXT2))
        browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.output_edit, 1)
        out_row.addWidget(browse)
        lay.addLayout(out_row)

        lay.addWidget(self._section("渲染进程", "当前版本使用安全单进程渲染；多进程会后续启用"))
        wrow = QHBoxLayout()
        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 100)
        self.workers_spin.setValue(max(1, min(100, state.export.workers)))
        self.workers_spin.valueChanged.connect(self._on_workers)
        wrow.addWidget(QLabel("进程数"))
        wrow.addWidget(self.workers_spin)
        wrow.addStretch(1)
        lay.addLayout(wrow)
        lay.addStretch(1)
        scroll.setWidget(content)
        self.body.addWidget(scroll, 1)

        reset = QPushButton("恢复默认")
        reset.setProperty("kind", "ghost")
        reset.setFixedHeight(32)
        reset.clicked.connect(self._reset)
        self.footer.addWidget(reset)
        self.footer.addStretch(1)
        queue = QPushButton("加入队列")
        queue.setProperty("kind", "secondary")
        queue.setFixedHeight(32)
        queue.setIcon(icon("queue", 15, theme.TEXT2))
        queue.clicked.connect(self._enqueue)
        self.start_button = QPushButton("开始导出")
        self.start_button.setProperty("kind", "primary")
        self.start_button.setFixedHeight(32)
        self.start_button.setIcon(icon("export", 15, "#FFFFFF"))
        self.start_button.clicked.connect(self._start)
        self.footer.addWidget(queue)
        self.footer.addWidget(self.start_button)
        self.add_close_button()
        state.timeline_changed.connect(self.summary_update)
        state.settings_changed.connect(self.summary_update)
        self._sync()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync()

    def _section(self, title: str, subtitle: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        s = QLabel(subtitle)
        s.setProperty("kind", "faint")
        l.addWidget(t)
        l.addWidget(s)
        return w

    def _option_card(self, switch: ToggleSwitch, label: QLabel, sub: QLabel) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 9, 12, 9)
        col = QVBoxLayout()
        col.setSpacing(1)
        label.setStyleSheet("font-weight: 500;")
        sub.setProperty("kind", "faint")
        sub.setWordWrap(True)
        col.addWidget(label)
        col.addWidget(sub)
        lay.addLayout(col, 1)
        lay.addWidget(switch)
        return card

    def _sync(self) -> None:
        self._syncing = True
        exp = self.state.export
        for key, button in self._format_buttons.items():
            button.setChecked(key == exp.format)
        for idx, button in self._quality_buttons.items():
            button.setChecked(idx == exp.quality)
        fps_index = FPS_CHOICES.index(exp.fps) if exp.fps in FPS_CHOICES else len(FPS_CHOICES)
        self.fps_combo.setCurrentIndex(fps_index)
        self.fps_spin.setValue(exp.fps)
        self.fps_spin.setEnabled(fps_index == len(FPS_CHOICES))
        self.transparent_switch.setCheckedSilently(exp.transparent_enabled())
        self.lossy_switch.setCheckedSilently(exp.lossy)
        self.transparent_switch.setEnabled(exp.supports_transparent())
        self.lossy_switch.setEnabled(exp.supports_lossy())
        self.transparent_label.setStyleSheet(
            "font-weight: 500;" if exp.supports_transparent() else f"font-weight:500;color:{theme.TEXT4};")
        self.lossy_label.setStyleSheet(
            "font-weight: 500;" if exp.supports_lossy() else f"font-weight:500;color:{theme.TEXT4};")
        self.transparent_sub.setText("保留透明通道" if exp.supports_transparent() else "当前格式不支持透明")
        self.lossy_sub.setText("更小的体积，画质略有损失" if exp.supports_lossy() else "当前格式不支持有损压缩")
        if not self.output_edit.hasFocus():
            self.output_edit.setText(exp.output_dir)
        self._sync_preset()
        self.summary_update()
        self._syncing = False

    def _preset_values(self):
        exp = self.state.export
        return {
            "format": exp.format, "quality": exp.quality, "fps": exp.fps,
            "transparent": exp.transparent, "lossy": exp.lossy,
        }

    def _sync_preset(self) -> None:
        current = self._preset_values()
        match = self.preset_combo.count() - 1
        for index in range(self.preset_combo.count()):
            data = self.preset_combo.itemData(index)
            if not isinstance(data, dict):
                continue
            if all(current[key] == data.get(key) for key in current):
                match = index
                break
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(match)
        self.preset_combo.blockSignals(False)

    def summary_update(self) -> None:
        exp = self.state.export
        exp.keep_inside()
        total = total_duration(self.state.timeline)
        fps = exp.fps
        frames = max(1, int(np.ceil(total * fps)))
        self.res_value.setText(f"{exp.width()} × {exp.height()}")
        self.fps_value.setText(f"{fps} FPS")
        self.frames_value.setText(f"{frames} 帧")
        self.duration_value.setText(f"{total:.2f} s")
        has = bool(self.state.timeline) and self.state.loaded is not None
        self.start_button.setEnabled(has)
        self.start_button.setToolTip("时间轴为空或未选择角色" if not has else "")

    def _select_format(self, key: str) -> None:
        if self._syncing:
            return
        self.state.export.format = key
        if not self.state.export.supports_transparent():
            self.state.export.transparent = False
        self._sync()

    def _select_quality(self, index: int) -> None:
        if self._syncing:
            return
        self.state.export.quality = index
        self._sync()

    def _on_fps_changed(self, index: int) -> None:
        if self._syncing:
            return
        if index < len(FPS_CHOICES):
            self.state.export.fps = FPS_CHOICES[index]
            self.fps_spin.setEnabled(False)
        else:
            self.state.export.fps = self.fps_spin.value()
            self.fps_spin.setEnabled(True)
        self._sync_preset()
        self.summary_update()

    def _on_custom_fps(self, value: int) -> None:
        if self._syncing:
            return
        if self.fps_combo.currentIndex() == len(FPS_CHOICES):
            self.state.export.fps = value
            self._sync_preset()
            self.summary_update()

    def _on_transparent(self, value: bool) -> None:
        if self._syncing:
            return
        self.state.export.transparent = value
        self._sync_preset()

    def _on_lossy(self, value: bool) -> None:
        if self._syncing:
            return
        self.state.export.lossy = value
        self._sync_preset()

    def _on_output(self) -> None:
        self.state.export.output_dir = self.output_edit.text().strip() or "export-output"

    def _on_workers(self, value: int) -> None:
        self.state.export.workers = value

    def _browse_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择导出目录", self.output_edit.text())
        if path:
            self.output_edit.setText(path)
            self._on_output()

    def _apply_preset(self, index: int) -> None:
        if self._syncing:
            return
        data = self.preset_combo.itemData(index)
        if not isinstance(data, dict):
            return
        self.state.export.format = data.get("format", self.state.export.format)
        self.state.export.quality = int(data.get("quality", self.state.export.quality))
        self.state.export.fps = int(data.get("fps", self.state.export.fps))
        self.state.export.transparent = bool(data.get("transparent", False))
        self.state.export.lossy = bool(data.get("lossy", False))
        self._sync()

    def _save_preset(self) -> None:
        data = {"name": "我的预设", **self._preset_values()}
        services.save_custom_preset(data)
        existing = self.preset_combo.findText("我的预设")
        if existing < 0:
            self.preset_combo.insertItem(self.preset_combo.count() - 1, "我的预设", data)
        else:
            self.preset_combo.setItemData(existing, data)
        self._sync_preset()
        self.state.message.emit("已保存“我的预设”")

    def _reset(self) -> None:
        self.state.export = ExportSettings()
        self._sync()

    def _start(self) -> None:
        self._on_output()
        name = f"{self.state.selected_role_entry.name} {self.state.export.format}" \
            if self.state.selected_role_entry else "导出"
        snap = build_snapshot(self.state, name)
        if snap is None:
            QMessageBox.information(self, "无法导出", "请先选择角色并在时间轴中添加片段。")
            return
        try:
            self.manager.start(snap)
        except RuntimeError as exc:
            QMessageBox.information(self, "导出", str(exc))
            return
        self.state.message.emit(f"已开始导出：{snap.name}")
        self.accept()

    def _enqueue(self) -> None:
        self._on_output()
        name = f"{self.state.selected_role_entry.name} {self.state.export.format}" \
            if self.state.selected_role_entry else "导出"
        snap = build_snapshot(self.state, name)
        if snap is None:
            QMessageBox.information(self, "导出队列", "请先选择角色并在时间轴中添加片段。")
            return
        jobs = services.load_queue()
        jobs.append(snap.to_dict())
        services.save_queue(jobs)
        self.state.queue_changed.emit()
        self.state.message.emit(f"已加入导出队列：{snap.name}")
        self.accept()


class ExportProgressDialog(BaseDialog):
    def __init__(self, worker: ExportWorker, manager: ExportManager, parent=None):
        super().__init__("导出进度", "正在后台渲染时间线", "export", parent, 480, 300)
        self.setModal(False)
        self.worker = worker
        self.manager = manager
        self.status = QLabel("正在准备资源…")
        self.status.setProperty("kind", "small")
        self.status.setWordWrap(True)
        self.body.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.body.addWidget(self.bar)
        self.frames = QLabel("0 / 0 帧")
        self.frames.setProperty("kind", "faint")
        self.body.addWidget(self.frames)
        self.path_label = QLabel("")
        self.path_label.setProperty("kind", "faint")
        self.path_label.setWordWrap(True)
        self.body.addWidget(self.path_label)
        self.body.addStretch(1)
        self.cancel_button = QPushButton("停止导出")
        self.cancel_button.setProperty("kind", "danger")
        self.cancel_button.setFixedHeight(32)
        self.cancel_button.clicked.connect(self.manager.cancel)
        self.open_button = QPushButton("打开目录")
        self.open_button.setProperty("kind", "secondary")
        self.open_button.setFixedHeight(32)
        self.open_button.setIcon(icon("folder-open", 15, theme.TEXT2))
        self.open_button.clicked.connect(self._open_folder)
        self.open_button.hide()
        self.footer.addWidget(self.cancel_button)
        self.footer.addStretch(1)
        self.footer.addWidget(self.open_button)
        self.close_button = self.add_close_button()
        self.close_button.setText("收起")
        self.close_button.clicked.disconnect()
        self.close_button.clicked.connect(self.hide)
        worker.signals.progress.connect(self._on_progress)
        worker.signals.finished.connect(self._on_finished)
        self._path = ""

    def _on_progress(self, done: int, total: int, message: str) -> None:
        self.status.setText(message)
        self.frames.setText(f"{done} / {total} 帧")
        self.bar.setValue(0 if total <= 0 else int(done * 100 / total))

    def _on_finished(self, ok: bool, message: str, path: str) -> None:
        self._path = path
        self.status.setText(message)
        self.bar.setValue(100 if ok else self.bar.value())
        self.cancel_button.hide()
        if path:
            self.path_label.setText(path)
            self.open_button.show()
        self.close_button.setText("关闭")
        self.close_button.clicked.disconnect()
        self.close_button.clicked.connect(self.accept)

    def _open_folder(self) -> None:
        if self._path:
            try:
                os.startfile(self._path)
            except Exception:
                pass
