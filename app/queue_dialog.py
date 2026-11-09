from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QVBoxLayout, QWidget)

from . import services, theme
from .dialogs import BaseDialog
from .export import ExportManager, ExportSnapshot
from .icons import icon
from .lists import AssetList, make_item, color_for
from .state import EditorState


class QueueDialog(BaseDialog):
    def __init__(self, state: EditorState, manager: ExportManager, parent=None):
        super().__init__("导出队列", "任务保存在本机，完成后自动移除", "queue", parent, 680, 560)
        self.state = state
        self.manager = manager
        self.jobs: List[dict] = services.load_queue()
        self.queue_running = False
        self._active_job = None
        self.head = QLabel("")
        self.head.setProperty("kind", "faint")
        self.body.addWidget(self.head)
        self.list = AssetList()
        self.body.addWidget(self.list, 1)
        self.remove_button = QPushButton("移除选中")
        self.remove_button.setProperty("kind", "secondary")
        self.remove_button.setFixedHeight(32)
        self.remove_button.clicked.connect(self._remove)
        self.clear_button = QPushButton("清空")
        self.clear_button.setProperty("kind", "ghost")
        self.clear_button.setFixedHeight(32)
        self.clear_button.clicked.connect(self._clear)
        self.run_button = QPushButton("开始队列")
        self.run_button.setProperty("kind", "primary")
        self.run_button.setFixedHeight(32)
        self.run_button.setIcon(icon("play", 15, "#FFFFFF"))
        self.run_button.clicked.connect(self._toggle_run)
        self.footer.addWidget(self.remove_button)
        self.footer.addWidget(self.clear_button)
        self.footer.addStretch(1)
        self.footer.addWidget(self.run_button)
        self.add_close_button()
        manager.finished.connect(self._on_manager_finished)
        state.queue_changed.connect(self._on_queue_changed)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._active_job is None:
            self.jobs = services.load_queue()
        self.refresh()

    def _on_queue_changed(self) -> None:
        stored = services.load_queue()
        if self._active_job is None:
            self.jobs = stored
        else:
            known = {job.get("id") for job in self.jobs if isinstance(job, dict)}
            for job in stored:
                if isinstance(job, dict) and job.get("id") not in known:
                    self.jobs.append(job)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        for i, job in enumerate(self.jobs):
            snap = ExportSnapshot.from_dict(job)
            item = make_item(snap.name or f"任务 {i + 1}",
                             subtitle=f"{snap.export.format} · {snap.export.fps} FPS · {snap.total_duration():.2f}s",
                             dot=color_for(snap.role_name), tag=f"#{i + 1}", data=i)
            self.list.addItem(item)
        if not self.jobs:
            self.list.addItem(make_item("队列为空，可在导出窗口中加入任务", muted=True))
        if self.queue_running:
            active = "运行中"
        elif self._active_job is not None:
            active = "当前任务执行中"
        elif self.jobs:
            active = "已暂停"
        else:
            active = "队列空闲"
        self.head.setText(f"{active}  ·  共 {len(self.jobs)} 个任务")
        self.run_button.setText("暂停队列" if self.queue_running else "开始队列")
        self.run_button.setIcon(icon("pause" if self.queue_running else "play", 15, "#FFFFFF"))

    def _toggle_run(self) -> None:
        if self.queue_running:
            self.queue_running = False
            self.refresh()
            return
        if self.manager.is_exporting():
            QMessageBox.information(self, "导出队列", "当前已有导出任务，请稍候。")
            return
        if not self.jobs:
            QMessageBox.information(self, "导出队列", "队列为空。")
            return
        self.queue_running = True
        self._start_next()

    def _start_next(self) -> None:
        if not self.queue_running or self.manager.is_exporting():
            self.refresh()
            return
        if not self.jobs:
            self.queue_running = False
            self.refresh()
            self.state.message.emit("导出队列已全部完成")
            return
        job = self.jobs[0]
        snap = ExportSnapshot.from_dict(job)
        try:
            self.manager.start(snap)
        except Exception as exc:
            self.queue_running = False
            self.state.message.emit(f"队列启动失败：{exc}")
            self.refresh()
            return
        self._active_job = job
        self.refresh()

    def _on_manager_finished(self, ok: bool, message: str, path: str) -> None:
        job = self._active_job
        if job is None:
            self.refresh()
            return
        self._active_job = None
        if ok:
            try:
                self.jobs.remove(job)
            except ValueError:
                pass
            services.save_queue(self.jobs)
            self.state.queue_changed.emit()
        else:
            self.queue_running = False
            self.state.message.emit(f"队列任务失败：{message}")
        self.refresh()
        if self.queue_running:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(300, self._start_next)

    def _remove(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        index = item.data(Qt.UserRole + 7)
        if isinstance(index, int) and 0 <= index < len(self.jobs):
            if self.jobs[index] is self._active_job:
                self.state.message.emit("正在导出的任务不能移除")
                return
            self.jobs.pop(index)
            services.save_queue(self.jobs)
            self.state.queue_changed.emit()
            self.refresh()

    def _clear(self) -> None:
        if not self.jobs:
            return
        if self._active_job is not None:
            self.state.message.emit("正在导出中，暂时不能清空队列")
            return
        if QMessageBox.question(self, "清空队列", "确定清空全部导出任务？") != QMessageBox.Yes:
            return
        self.jobs.clear()
        services.save_queue(self.jobs)
        self.state.queue_changed.emit()
        self.refresh()
