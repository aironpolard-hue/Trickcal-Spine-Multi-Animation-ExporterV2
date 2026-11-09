from __future__ import annotations

import time
import traceback

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QCursor, QFontMetrics, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMessageBox, QPushButton, QSizePolicy, QSpinBox,
                               QSplitter, QTextEdit, QVBoxLayout, QWidget)

from . import services, theme
from .action_preview import ActionPreview
from .asset_panel import AssetPanel
from .dialogs import FolderDialog, HelpDialog, ProjectDialog, SettingsDialog, StepDialog
from .export import ExportManager
from .icons import icon
from .inspector import InspectorPanel
from .model import APP_NAME, APP_VERSION
from .stage import StagePanel
from .state import EditorState
from .timeline import TimelinePanel
from .widgets import ElidedLabel, Toast
from .win_chrome import apply_dark_title_bar


class MainWindow(QMainWindow):
    def __init__(self, state: EditorState):
        super().__init__()
        self.state = state
        self.setWindowTitle(f"{APP_NAME} · 排编工坊")
        self.setWindowIcon(QIcon(str(services.PROJECT_ROOT / "assets" / "icon.png")))
        self.resize(1536, 920)
        self.setMinimumSize(1180, 720)
        self._toast = None
        self._last_tick = time.perf_counter()
        self.export_manager = ExportManager(self)
        self.progress_dialog = None
        self._dialogs = {}
        self._build()
        self._connect()
        self._update_chrome()
        self._update_status_info()
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(16)
        self._play_timer.timeout.connect(self._on_tick)
        self._play_timer.start()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setInterval(5000)
        self._autosave_timer.timeout.connect(self._autosave)
        self._autosave_timer.start()
        self._sizes_set = False
        self.export_manager.started.connect(self._on_export_started)
        self.export_manager.finished.connect(self._on_export_finished)

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_topbar())

        content = QWidget()
        content_lay = QHBoxLayout(content)
        content_lay.setContentsMargins(10, 8, 10, 4)
        content_lay.setSpacing(0)
        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setHandleWidth(8)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: transparent; }}"
            f"QSplitter::handle:hover {{ background: rgba(255,255,255,0.05); }}"
        )
        self.asset_panel = AssetPanel(self.state)
        self.center_splitter = QSplitter(Qt.Vertical)
        self.center_splitter.setHandleWidth(8)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setStyleSheet(
            f"QSplitter::handle {{ background: transparent; }}"
            f"QSplitter::handle:hover {{ background: rgba(255,255,255,0.05); }}"
        )
        self.stage_panel = StagePanel(self.state)
        self.timeline_panel = TimelinePanel(self.state)
        self.center_splitter.addWidget(self.stage_panel)
        self.center_splitter.addWidget(self.timeline_panel)
        self.inspector_panel = InspectorPanel(self.state)
        self.main_splitter.addWidget(self.asset_panel)
        self.main_splitter.addWidget(self.center_splitter)
        self.main_splitter.addWidget(self.inspector_panel)
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        content_lay.addWidget(self.main_splitter)
        root.addWidget(content, 1)
        root.addWidget(self._build_statusbar())
        self._toast = Toast(self)
        self.action_preview = ActionPreview(self.state, self)

    def _build_topbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(54)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)
        self.project_button = QPushButton("未命名方案")
        self.project_button.setProperty("kind", "secondary")
        self.project_button.setIcon(icon("folder-open", 15, theme.TEXT2))
        self.project_button.setFixedHeight(32)
        self.project_button.setMinimumWidth(210)
        self.project_button.setToolTip("工程方案 · 保存与载入 (Ctrl+S)")
        lay.addWidget(self.project_button)
        lay.addStretch(1)
        self.queue_button = QPushButton("队列")
        self.queue_button.setProperty("kind", "ghost")
        self.queue_button.setIcon(icon("queue", 16, theme.TEXT2))
        self.queue_button.setFixedHeight(32)
        lay.addWidget(self.queue_button)
        self.help_button = self._tool_button("keyboard", "快捷键与帮助 (F1)")
        self.settings_button = self._tool_button("settings", "设置")
        lay.addWidget(self.help_button)
        lay.addWidget(self.settings_button)
        lay.addSpacing(4)
        self.export_button = QPushButton("导出")
        self.export_button.setProperty("kind", "primary")
        self.export_button.setIcon(icon("export", 16, "#FFFFFF"))
        self.export_button.setFixedHeight(34)
        self.export_button.setMinimumWidth(104)
        lay.addWidget(self.export_button)
        return bar

    def _tool_button(self, name: str, tooltip: str) -> QPushButton:
        b = QPushButton()
        b.setProperty("kind", "tool")
        b.setIcon(icon(name, 18, theme.TEXT2))
        b.setFixedSize(32, 32)
        b.setToolTip(tooltip)
        return b

    def _build_statusbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(28)
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {theme.ACCENT}; font-size: 9px;")
        lay.addWidget(dot)
        self.status_label = ElidedLabel("", self, theme.TEXT2, 11)
        self.status_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.status_label, 1)
        save_dot = QLabel("●")
        save_dot.setStyleSheet(f"color: {theme.GREEN}; font-size: 9px;")
        lay.addWidget(save_dot)
        save_label = QLabel("自动保存")
        save_label.setProperty("kind", "faint")
        lay.addWidget(save_label)
        self.info_label = QLabel("")
        self.info_label.setProperty("kind", "faint")
        lay.addWidget(self.info_label)
        version = QLabel(f"v{APP_VERSION}")
        version.setProperty("kind", "faint")
        lay.addWidget(version)
        return bar

    # ------------------------------------------------------------------
    # wiring
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        s = self.state
        self._shortcuts = []
        for keys, handler in (
            ("Ctrl+Z", s.undo),
            ("Ctrl+Shift+Z", s.redo),
            ("Ctrl+Y", s.redo),
            ("Ctrl+C", s.copy_selected),
            ("Ctrl+X", s.cut_selected),
            ("Ctrl+V", s.paste),
            ("Ctrl+S", self.open_project_dialog),
            ("F1", self.open_help_dialog),
        ):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(handler)
            self._shortcuts.append(shortcut)
        s.message.connect(self._on_message)
        s.roles_changed.connect(self._update_chrome)
        s.role_ready.connect(self._on_role_ready)
        s.role_failed.connect(self._update_chrome)
        s.timeline_changed.connect(self._update_chrome)
        s.selection_changed.connect(self._update_chrome)
        s.skin_changed.connect(self._update_chrome)
        s.project_changed.connect(self._update_chrome)
        s.settings_changed.connect(self._update_chrome)
        s.queue_changed.connect(self._update_chrome)
        self.project_button.clicked.connect(self.open_project_dialog)
        self.queue_button.clicked.connect(self.open_queue_dialog)
        self.help_button.clicked.connect(self.open_help_dialog)
        self.settings_button.clicked.connect(self.open_settings_dialog)
        self.export_button.clicked.connect(self.open_export_dialog)
        self.asset_panel.choose_folder_requested.connect(self.open_folder_dialog)
        self.asset_panel.action_hovered.connect(self._on_action_hovered)
        self.asset_panel.action_list.itemClicked.connect(
            lambda _item: self.action_preview.hide_preview())
        self.asset_panel.action_list.itemDoubleClicked.connect(
            lambda _item: self.action_preview.hide_preview())
        self.stage_panel.choose_folder_requested.connect(self.open_folder_dialog)
        self.stage_panel.rescan_requested.connect(s.rescan)
        self.stage_panel.inspector_stage_requested.connect(self.inspector_panel.open_stage)
        self.inspector_panel.pick_mode_requested.connect(self.stage_panel.canvas.set_pick_mode)
        self.stage_panel.canvas.pick_mode_changed.connect(self.inspector_panel.set_pick_state)
        self.stage_panel.canvas.edited.connect(self._on_stage_edited)
        self.inspector_panel.edit_changed.connect(self._on_inspector_edited)
        self.timeline_panel.step_settings_requested.connect(self.open_step_dialog)

    def _on_role_ready(self) -> None:
        self.stage_panel.refresh_model()
        self.inspector_panel.refresh_all()
        self._update_chrome()

    def _on_stage_edited(self) -> None:
        self.inspector_panel.refresh_stage()
        self.stage_panel.canvas.update()

    def _on_inspector_edited(self) -> None:
        self.stage_panel.canvas.update()
        self.state._last_autosave = 0

    def _on_export_started(self, snapshot) -> None:
        try:
            from .export_dialog import ExportProgressDialog
        except Exception:
            traceback.print_exc()
            self.state.message.emit("导出进度窗口加载失败，详情见 app.log")
            return
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog.deleteLater()
        self.progress_dialog = ExportProgressDialog(self.export_manager.worker,
                                                    self.export_manager, self)
        self._center_dialog(self.progress_dialog)
        self.progress_dialog.show()
        self.progress_dialog.raise_()
        self.progress_dialog.activateWindow()
        self._update_chrome()

    def _on_export_finished(self, ok: bool, message: str, path: str) -> None:
        self.state.message.emit(message)
        self._update_chrome()

    def _on_action_hovered(self, action) -> None:
        preview = getattr(self, "action_preview", None)
        if preview is None:
            return
        if not isinstance(action, str) or not action:
            preview.hover("", QPoint())
            return
        local = self.mapFromGlobal(QCursor.pos())
        panel_right = self.asset_panel.mapTo(
            self, QPoint(self.asset_panel.width(), 0)).x()
        preview.hover(action, QPoint(panel_right + 12, local.y()))

    def _on_message(self, message: str) -> None:
        self.status_label.setText(message)
        low = message or ""
        if any(word in low for word in ("失败", "错误", "无法")):
            self._show_toast(low, "error")
        elif any(word in low for word in ("完成", "已保存", "已恢复")):
            self._show_toast(low, "success")

    def _show_toast(self, text: str, kind: str) -> None:
        if self._toast is None:
            return
        self._toast.show_message(text[:120], kind)
        self._toast.move(self.width() - self._toast.width() - 22,
                         self.height() - self._toast.height() - 44)
        self._toast.raise_()

    # ------------------------------------------------------------------
    # chrome
    # ------------------------------------------------------------------

    def _update_chrome(self) -> None:
        name = self.state.project_name or "未命名方案"
        metrics = QFontMetrics(self.project_button.font())
        self.project_button.setText(metrics.elidedText(name, Qt.ElideRight, 150))
        try:
            count = len(services.load_queue())
        except Exception:
            count = 0
        self.queue_button.setText("队列" if count == 0 else f"队列 {count}")
        has_content = bool(self.state.timeline) and self.state.loaded is not None
        self.export_button.setEnabled(True)
        if self.export_manager.is_exporting():
            self.export_button.setText("导出中…")
        else:
            self.export_button.setText("导出")
        self.export_button.setToolTip("导出时间线" if has_content else "时间轴为空，先添加片段再导出")
        self._update_status_info()

    def _update_status_info(self) -> None:
        s = self.state
        role = s.loaded.entry.name if s.loaded else "未选择角色"
        actions = len(s.loaded.actions) if s.loaded else 0
        info = f"{role}  ·  {actions} 动作  ·  {len(s.timeline)} 片段  ·  {s.total_duration():.2f}s"
        if info != self.info_label.text():
            self.info_label.setText(info)

    # ------------------------------------------------------------------
    # timeline / playback
    # ------------------------------------------------------------------

    def _on_tick(self) -> None:
        now = time.perf_counter()
        delta = min(0.05, now - self._last_tick)
        self._last_tick = now
        if self.state.playing:
            if self.state.tick(delta):
                self.timeline_panel.refresh()
        if self.state.playing:
            self.stage_panel.canvas.update()

    def _autosave(self) -> None:
        if self.state._loading:
            return
        if self.state.loaded is None and not self.state.timeline:
            return
        try:
            self.state.flush_autosave()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # keyboard
    # ------------------------------------------------------------------

    def _text_focus(self) -> bool:
        widget = QApplication.focusWidget()
        return isinstance(widget, (QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QComboBox))

    def keyPressEvent(self, event) -> None:
        if self._text_focus():
            return super().keyPressEvent(event)
        key = event.key()
        s = self.state
        if key == Qt.Key_Space:
            s.toggle_play()
            return
        if key == Qt.Key_Delete or key == Qt.Key_Backspace:
            s.remove_selected()
            return
        if key == Qt.Key_Escape:
            s.set_selection([])
            return
        if key == Qt.Key_Left:
            s.seek(s.playhead - 0.1)
            s.selection_changed.emit()
            return
        if key == Qt.Key_Right:
            s.seek(s.playhead + 0.1)
            s.selection_changed.emit()
            return
        if key == Qt.Key_Home:
            s.seek(0)
            s.selection_changed.emit()
            return
        if key == Qt.Key_End:
            s.seek(s.total_duration())
            s.selection_changed.emit()
            return
        text = event.text().upper()
        sc = s.settings.shortcuts
        if text and text == sc.get("trim_right", "W"):
            s.trim_right()
        elif text and text == sc.get("split_right", "S"):
            s.split_at_playhead()
        elif text and text == sc.get("trim_left", "Q"):
            s.trim_left()
        elif text and text == sc.get("split_left", "A"):
            s.split_at_playhead()
        elif text and text == sc.get("trim_timeline_left", "E"):
            s.trim_timeline_left()
        elif text and text == sc.get("trim_timeline_right", "R"):
            s.trim_timeline_right()
        else:
            super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # dialogs
    # ------------------------------------------------------------------

    def _center_dialog(self, dialog, offset: int = 0) -> None:
        geo = dialog.frameGeometry()
        center = self.frameGeometry().center()
        if offset:
            center = center + QPoint(offset, offset)
        geo.moveCenter(center)
        dialog.move(geo.topLeft())

    def _show_dialog(self, key: str, factory):
        preview = getattr(self, "action_preview", None)
        if preview is not None:
            preview.hide_preview()
        dialog = self._dialogs.get(key)
        if dialog is None:
            try:
                dialog = factory()
            except Exception:
                traceback.print_exc()
                QMessageBox.critical(self, "窗口打开失败",
                                     "窗口加载失败，详情已写入日志 app.log。\n\n"
                                     + traceback.format_exc(limit=4))
                return None
            self._dialogs[key] = dialog
            dialog.finished.connect(self._update_chrome)
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
            return dialog
        if not dialog.property("placed"):
            dialog.setProperty("placed", True)
            visible = sum(1 for item in self._dialogs.values()
                          if item is not dialog and item.isVisible())
            self._center_dialog(dialog, min(visible, 5) * 26)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QTimer.singleShot(0, dialog.activateWindow)
        return dialog

    def open_folder_dialog(self) -> None:
        self._show_dialog("folder", lambda: FolderDialog(self.state, self))

    def open_project_dialog(self) -> None:
        self._show_dialog("project", lambda: ProjectDialog(self.state, self))

    def open_settings_dialog(self) -> None:
        self._show_dialog("settings", lambda: SettingsDialog(self.state, self))
        self._update_chrome()

    def open_help_dialog(self) -> None:
        self._show_dialog("help", lambda: HelpDialog(self))

    def open_step_dialog(self) -> None:
        if not self.state.selected_indices:
            self.state.message.emit("请先选择片段")
            return
        self._show_dialog("step", lambda: StepDialog(self.state, self))

    def open_queue_dialog(self) -> None:
        from .queue_dialog import QueueDialog
        self._show_dialog("queue", lambda: QueueDialog(self.state, self.export_manager, self))

    def open_export_dialog(self) -> None:
        if self.export_manager.is_exporting():
            if self.progress_dialog is not None:
                self.progress_dialog.show()
                self.progress_dialog.raise_()
                self.progress_dialog.activateWindow()
            return
        from .export_dialog import ExportDialog
        self._show_dialog("export", lambda: ExportDialog(self.state, self.export_manager, self))

    # ------------------------------------------------------------------
    # window
    # ------------------------------------------------------------------

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sizes_set:
            self._sizes_set = True
            QTimer.singleShot(0, self._apply_sizes)
        QTimer.singleShot(80, lambda: apply_dark_title_bar(self))

    def _apply_sizes(self) -> None:
        width = self.main_splitter.width()
        left = 306
        right = 306
        center = max(380, width - left - right - 16)
        self.main_splitter.setSizes([left, center, right])
        height = self.center_splitter.height()
        self.center_splitter.setSizes([max(300, height - 300), 290])

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowDeactivate:
            preview = getattr(self, "action_preview", None)
            if preview is not None:
                preview.hide_preview()
        super().changeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        preview = getattr(self, "action_preview", None)
        if preview is not None and preview.isVisible():
            preview.hide_preview()
        if self._toast and self._toast.isVisible():
            self._toast.move(self.width() - self._toast.width() - 22,
                             self.height() - self._toast.height() - 44)

    def closeEvent(self, event) -> None:
        try:
            self.export_manager.cancel()
            worker = self.export_manager.worker
            if worker is not None:
                worker.wait(2500)
        except Exception:
            pass
        try:
            self.action_preview.shutdown()
        except Exception:
            pass
        try:
            self.state.shutdown()
        except Exception:
            pass
        event.accept()
