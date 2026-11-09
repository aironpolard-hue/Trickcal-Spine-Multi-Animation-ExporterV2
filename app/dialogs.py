from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog,
                               QComboBox, QDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

from . import services, theme
from .icons import icon
from .lists import AssetList, make_item, color_for
from .model import Clip, ProjectState, safe_float
from .state import EditorState
from .win_chrome import apply_dark_title_bar


class BaseDialog(QDialog):
    def __init__(self, title: str, subtitle: str, icon_name: str, parent=None,
                 width: int = 620, height: int = 520):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.resize(width, height)
        self.setMinimumSize(min(width, 460), min(height, 360))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.panel = QFrame()
        self.panel.setObjectName("DialogSurface")
        outer.addWidget(self.panel)
        inner = QVBoxLayout(self.panel)
        inner.setContentsMargins(18, 16, 18, 14)
        inner.setSpacing(0)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(9)
        inner.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setContentsMargins(0, 14, 0, 0)
        self.footer.setSpacing(8)
        inner.addLayout(self.footer)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dark_title_bar(self)

    def add_close_button(self) -> QPushButton:
        button = QPushButton("关闭")
        button.setProperty("kind", "ghost")
        button.setFixedHeight(32)
        button.clicked.connect(self.accept)
        self.footer.addWidget(button)
        return button

    def add_primary(self, text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.setProperty("kind", "primary")
        button.setFixedHeight(32)
        button.clicked.connect(slot)
        self.footer.addWidget(button)
        return button


class FolderDialog(BaseDialog):
    def __init__(self, state: EditorState, parent=None):
        super().__init__("资源文件夹", "管理扫描路径", "folder", parent, 640, 520)
        self.state = state
        intro = QLabel("支持普通 Spine 目录与原游戏 UnityFS 目录。切换路径后会立即重新扫描角色。")
        intro.setProperty("kind", "faint")
        intro.setWordWrap(True)
        self.body.addWidget(intro)
        row = QHBoxLayout()
        self.path_edit = QLineEdit(state.active_root)
        self.path_edit.setPlaceholderText("输入或粘贴文件夹路径…")
        self.path_edit.returnPressed.connect(self._add_path)
        add = QPushButton("添加并扫描")
        add.setProperty("kind", "primary")
        add.setFixedHeight(32)
        add.clicked.connect(self._add_path)
        row.addWidget(self.path_edit, 1)
        row.addWidget(add)
        self.body.addLayout(row)
        row2 = QHBoxLayout()
        browse = QPushButton("选择文件夹…")
        browse.setProperty("kind", "secondary")
        browse.setIcon(icon("folder-open", 15, theme.TEXT2))
        browse.clicked.connect(self._browse)
        rescan = QPushButton("重新扫描")
        rescan.setProperty("kind", "ghost")
        rescan.setIcon(icon("refresh", 15, theme.TEXT2))
        rescan.clicked.connect(self.state.rescan)
        row2.addWidget(browse)
        row2.addWidget(rescan)
        row2.addStretch(1)
        self.body.addLayout(row2)
        head = QHBoxLayout()
        label = QLabel("已添加路径")
        label.setProperty("kind", "cap")
        head.addWidget(label)
        head.addStretch(1)
        remove = QPushButton("删除选中")
        remove.setProperty("kind", "ghost")
        remove.setIcon(icon("trash", 14, theme.TEXT2))
        remove.clicked.connect(self._remove_selected)
        head.addWidget(remove)
        self.body.addLayout(head)
        self.roots = AssetList()
        self.roots.setMinimumHeight(200)
        self.roots.itemClicked.connect(self._select_root)
        self.body.addWidget(self.roots, 1)
        self.footer.addStretch(1)
        self.add_close_button()
        self.add_primary("完成", self.accept)
        self.state.scan_changed.connect(self.refresh)
        self.state.roles_changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.roots.clear()
        active = self.state.active_root
        if not self.path_edit.hasFocus():
            self.path_edit.setText(active)
        for path in self.state.scan_roots:
            selected = path == active
            item = make_item(Path(path).name or path, subtitle=path, data=path,
                             dot=QColor(theme.GREEN if selected else theme.TEXT4),
                             tag="当前" if selected else "", tooltip=path)
            self.roots.addItem(item)
            if selected:
                self.roots.setCurrentItem(item)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _select_root(self, item) -> None:
        path = item.data(Qt.UserRole + 7)
        if isinstance(path, str):
            self.state.select_scan_root(path)
            self.path_edit.setText(path)
            self.refresh()

    def _add_path(self) -> None:
        if self.state.add_scan_root(self.path_edit.text()):
            self.refresh()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择 Spine 资源文件夹", self.path_edit.text())
        if path:
            self.path_edit.setText(path)
            self._add_path()

    def _remove_selected(self) -> None:
        item = self.roots.currentItem()
        if item is None:
            selected = self.roots.selectedItems()
            item = selected[0] if selected else None
        if item is None:
            self.state.message.emit("请先选择一个扫描路径")
            return
        path = item.data(Qt.UserRole + 7)
        if not isinstance(path, str):
            return
        if len(self.state.scan_roots) <= 1:
            QMessageBox.information(self, "扫描路径", "至少保留一个扫描路径。")
            return
        self.state.remove_scan_root(path)
        self.refresh()


class StepDialog(BaseDialog):
    def __init__(self, state: EditorState, parent=None):
        super().__init__("片段设置", "修改会同步到所有选中片段", "sliders", parent, 480, 500)
        self.state = state
        self.hint = QLabel("")
        self.hint.setProperty("kind", "faint")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)
        self.duration = self._line("片段时长")
        self.start = self._line("起始时间")
        self.speed = self._line("播放倍速")
        self.transition = QCheckBox("启用过渡效果")
        self.transition.toggled.connect(self._on_transition)
        self.t_duration = self._line("过渡时长")
        self.t_speed = self._line("过渡速度")
        for widget in (self.duration[0], self.start[0], self.speed[0]):
            self.body.addLayout(widget)
        self.body.addWidget(self.transition)
        for widget in (self.t_duration[0], self.t_speed[0]):
            self.body.addLayout(widget)
        self.body.addStretch(1)
        delete = QPushButton("删除片段")
        delete.setProperty("kind", "danger")
        delete.setFixedHeight(32)
        delete.clicked.connect(self._delete)
        restore = QPushButton("恢复默认")
        restore.setProperty("kind", "ghost")
        restore.setFixedHeight(32)
        restore.clicked.connect(self._restore)
        self.footer.addWidget(delete)
        self.footer.addWidget(restore)
        self.footer.addStretch(1)
        apply = QPushButton("应用")
        apply.setProperty("kind", "primary")
        apply.setFixedHeight(32)
        apply.clicked.connect(self._apply)
        self.footer.addWidget(apply)
        self.add_close_button()
        self.refresh()
        state.selection_changed.connect(self.refresh)

    def _line(self, label: str):
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setProperty("kind", "small")
        lab.setFixedWidth(78)
        edit = QLineEdit()
        edit.setPlaceholderText("—")
        edit.setFixedHeight(30)
        row.addWidget(lab)
        row.addWidget(edit, 1)
        return row, edit

    def _common(self, attr: str):
        clips = [self.state.timeline[i] for i in self.state.selected_clips()]
        if not clips:
            return None
        value = getattr(clips[0], attr)
        for clip in clips[1:]:
            if abs(getattr(clip, attr) - value) > 1e-4:
                return None
        return value

    def refresh(self) -> None:
        indices = self.state.selected_clips()
        self.hint.setText(f"已选择 {len(indices)} 个片段。不同值显示为 —，输入后统一应用。")
        for edit, attr, fmt in (
            (self.duration[1], "duration", "{:.3f}"),
            (self.start[1], "start_offset", "{:.3f}"),
            (self.speed[1], "speed", "{:.3f}"),
            (self.t_duration[1], "transition_duration", "{:.3f}"),
            (self.t_speed[1], "transition_speed", "{:.3f}"),
        ):
            if edit.hasFocus():
                continue
            value = self._common(attr)
            edit.setText("" if value is None else fmt.format(value))
        enabled = self._common("transition_enabled")
        self.transition.blockSignals(True)
        self.transition.setChecked(bool(enabled))
        self.transition.setText("启用过渡效果" if enabled is not None else "启用过渡效果（混合状态）")
        self.transition.blockSignals(False)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _apply(self) -> None:
        indices = self.state.selected_clips()
        if not indices:
            return
        self.state.checkpoint()
        for i in indices:
            clip = self.state.timeline[i]
            try:
                if self.duration[1].text().strip():
                    clip.duration = max(0.05, float(self.duration[1].text()))
                if self.start[1].text().strip():
                    clip.start_offset = max(0.0, float(self.start[1].text()))
                if self.speed[1].text().strip():
                    clip.speed = max(0.0, float(self.speed[1].text()))
                if self.t_duration[1].text().strip():
                    clip.transition_duration = max(0.0, float(self.t_duration[1].text()))
                if self.t_speed[1].text().strip():
                    clip.transition_speed = max(0.0, float(self.t_speed[1].text()))
            except ValueError:
                pass
        self.state.finish_live_edit("片段设置已应用")
        self.refresh()

    def _on_transition(self, checked: bool) -> None:
        for i in self.state.selected_clips():
            self.state.timeline[i].transition_enabled = checked
        self.state.timeline_changed.emit()

    def _delete(self) -> None:
        self.state.remove_selected()
        self.accept()

    def _restore(self) -> None:
        for i in self.state.selected_clips():
            clip = self.state.timeline[i]
            clip.start_offset = 0.0
            clip.speed = 1.0
            clip.transition_enabled = True
            clip.transition_duration = 0.2
            clip.transition_speed = 1.0
        self.state.timeline_changed.emit()
        self.refresh()


class ProjectDialog(BaseDialog):
    def __init__(self, state: EditorState, parent=None):
        super().__init__("工程方案", "保存或载入本机的编排方案", "save", parent, 620, 580)
        self.state = state
        self.projects: List[tuple[ProjectState, Path]] = []
        row = QHBoxLayout()
        self.name_edit = QLineEdit(state.project_name)
        self.name_edit.setPlaceholderText("方案名称…")
        save = QPushButton("保存为新方案")
        save.setProperty("kind", "primary")
        save.setFixedHeight(32)
        save.clicked.connect(self._save_new)
        row.addWidget(self.name_edit, 1)
        row.addWidget(save)
        self.body.addLayout(row)
        self.list = AssetList()
        self.list.setMinimumHeight(260)
        self.body.addWidget(self.list, 1)
        self.add_close_button()
        self.footer.addStretch(1)
        load = QPushButton("载入")
        load.setProperty("kind", "primary")
        load.setFixedHeight(32)
        load.clicked.connect(self._load)
        overwrite = QPushButton("覆盖当前")
        overwrite.setProperty("kind", "secondary")
        overwrite.setFixedHeight(32)
        overwrite.clicked.connect(self._overwrite)
        delete = QPushButton("删除")
        delete.setProperty("kind", "danger")
        delete.setFixedHeight(32)
        delete.clicked.connect(self._delete)
        refresh = QPushButton("刷新")
        refresh.setProperty("kind", "ghost")
        refresh.setFixedHeight(32)
        refresh.clicked.connect(self.refresh)
        self.footer.addWidget(refresh)
        self.footer.addWidget(delete)
        self.footer.addWidget(overwrite)
        self.footer.addWidget(load)
        self.refresh()

    def refresh(self) -> None:
        self.projects = services.list_projects()
        self.list.clear()
        active = self.state.project_id
        for state, path in self.projects:
            current = state.project_id == active
            item = make_item(state.name or path.stem,
                             subtitle=path.stem,
                             dot=QColor(theme.GREEN if current else theme.TEXT4),
                             tag="当前" if current else "",
                             data=(state, path))
            self.list.addItem(item)
            if current:
                item.setSelected(True)
        if not self.projects:
            self.list.addItem(make_item("还没有保存的方案", muted=True))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.name_edit.setText(self.state.project_name)
        self.refresh()

    def _save_new(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.information(self, "方案名称", "请输入方案名称。")
            return
        self.state.save_project(name)
        self.refresh()

    def _overwrite(self) -> None:
        self.state.save_project(self.name_edit.text().strip() or self.state.project_name)
        self.refresh()

    def _load(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole + 7)
        if isinstance(data, tuple) and len(data) == 2:
            state, _path = data
            self.state.apply_project(state)
            self.accept()

    def _delete(self) -> None:
        item = self.list.currentItem()
        if item is None:
            return
        data = item.data(Qt.UserRole + 7)
        if not isinstance(data, tuple):
            return
        state, _path = data
        if QMessageBox.question(self, "删除方案", f"确定删除方案“{state.name}”？") != QMessageBox.Yes:
            return
        services.delete_project(state.project_id)
        self.refresh()


class HelpDialog(BaseDialog):
    def __init__(self, parent=None):
        super().__init__("快捷键与帮助", "让编排更顺手的操作速查", "keyboard", parent, 760, 580)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        grid = QGridLayout(content)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        groups = [
            ("播放与浏览", [
                ("播放 / 暂停", "空格"), ("微调播放头", "← / →"),
                ("跳到开头 / 结尾", "Home / End"), ("缩放时间轴", "Ctrl + 滚轮"),
                ("横向滚动", "滚轮"),
            ]),
            ("编辑", [
                ("撤销 / 重做", "Ctrl + Z / Y"), ("复制 / 剪切 / 粘贴", "Ctrl + C / X / V"),
                ("删除选中片段", "Delete"), ("打开方案面板", "Ctrl + S"),
            ]),
            ("片段快捷操作", [
                ("当前片段删右半", "W"), ("当前片段右分割", "S"),
                ("当前片段删左半", "Q"), ("当前片段左分割", "A"),
                ("整条时间线删左", "E"), ("整条时间线删右", "R"),
            ]),
            ("鼠标", [
                ("拖动片段", "移动顺序"), ("拖动片段边缘", "调整时长"),
                ("拖动空白处", "框选片段"), ("双击动作 / 片段", "添加 / 设置"),
                ("右键", "上下文菜单"),
            ]),
        ]
        for col, (title, rows) in enumerate(groups):
            card = QFrame()
            card.setObjectName("Card")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(14, 12, 14, 12)
            lay.setSpacing(6)
            t = QLabel(title)
            t.setStyleSheet("font-weight: 600;")
            lay.addWidget(t)
            for label, key in rows:
                row = QHBoxLayout()
                l = QLabel(label)
                l.setProperty("kind", "faint")
                k = QLabel(key)
                k.setStyleSheet(
                    f"background: {theme.SURFACE4}; border: 1px solid {theme.LINE2};"
                    f"border-radius: 5px; padding: 2px 7px; color: {theme.TEXT2}; font-size: 11px;")
                row.addWidget(l)
                row.addStretch(1)
                row.addWidget(k)
                lay.addLayout(row)
            lay.addStretch(1)
            grid.addWidget(card, col // 2, col % 2)
        scroll.setWidget(content)
        self.body.addWidget(scroll, 1)
        self.footer.addStretch(1)
        self.add_close_button()
        self.add_primary("知道了", self.accept)


class SettingsDialog(BaseDialog):
    def __init__(self, state: EditorState, parent=None):
        super().__init__("设置", "主题、界面与快捷键", "settings", parent, 680, 560)
        self.state = state
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(12)

        lay.addWidget(self._section("主题色", "界面按钮、选中态与时间轴强调色"))
        swatches = QHBoxLayout()
        for color in ("#6B7CFF", "#8B5CF6", "#22C3D6", "#10B981", "#F5B94D", "#F25C77"):
            b = QPushButton()
            b.setFixedSize(26, 26)
            b.setStyleSheet(f"QPushButton {{ background: {color}; border-radius: 13px; border: 1px solid {theme.LINE3}; }}")
            b.clicked.connect(lambda _=False, c=color: self._set_accent(c))
            swatches.addWidget(b)
        custom = QPushButton("自定义…")
        custom.setProperty("kind", "ghost")
        custom.setFixedHeight(28)
        custom.clicked.connect(self._choose_accent)
        swatches.addWidget(custom)
        swatches.addStretch(1)
        lay.addLayout(swatches)
        font_row = QHBoxLayout()
        font_label = QLabel("界面字号")
        font_label.setProperty("kind", "small")
        self.font_combo = QComboBox()
        for size in (12, 13, 14, 15):
            self.font_combo.addItem(f"{size}px", size)
        self.font_combo.setCurrentIndex(max(0, min(3, state.settings.font_size - 12)))
        self.font_combo.currentIndexChanged.connect(self._set_font)
        font_row.addWidget(font_label)
        font_row.addWidget(self.font_combo)
        font_row.addStretch(1)
        lay.addLayout(font_row)

        lay.addWidget(self._section("动作预览", "鼠标悬停动作列表时浮窗的宽度"))
        preview_row = QHBoxLayout()
        self.preview_width = QSpinBox()
        self.preview_width.setRange(240, 380)
        self.preview_width.setSingleStep(20)
        self.preview_width.setSuffix(" px")
        self.preview_width.setValue(max(240, min(380, state.settings.preview_width)))
        self.preview_width.valueChanged.connect(self._set_preview_width)
        preview_row.addWidget(QLabel("预览宽度"))
        preview_row.addWidget(self.preview_width)
        preview_row.addStretch(1)
        lay.addLayout(preview_row)

        lay.addWidget(self._section("快捷键", "单字母或数字；留空使用默认"))
        form = QGridLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(7)
        keys = [
            ("trim_right", "当前片段删右半"), ("split_right", "当前片段右分割"),
            ("trim_left", "当前片段删左半"), ("split_left", "当前片段左分割"),
            ("trim_timeline_left", "整体时间线删左"), ("trim_timeline_right", "整体时间线删右"),
        ]
        self.shortcut_edits = {}
        for i, (key, label) in enumerate(keys):
            l = QLabel(label)
            l.setProperty("kind", "faint")
            edit = QLineEdit(state.settings.shortcuts.get(key, ""))
            edit.setMaxLength(1)
            edit.setFixedWidth(46)
            edit.setAlignment(Qt.AlignCenter)
            edit.textChanged.connect(lambda text, k=key: self._set_shortcut(k, text))
            self.shortcut_edits[key] = edit
            form.addWidget(l, i // 2, (i % 2) * 2)
            form.addWidget(edit, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(form)
        lay.addStretch(1)
        scroll.setWidget(content)
        self.body.addWidget(scroll, 1)
        reset = QPushButton("恢复默认")
        reset.setProperty("kind", "ghost")
        reset.setFixedHeight(32)
        reset.clicked.connect(self._reset)
        self.footer.addWidget(reset)
        self.footer.addStretch(1)
        self.add_close_button()
        self.add_primary("完成", self.accept)

    def _section(self, title: str, subtitle: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 4, 0, 0)
        l.setSpacing(1)
        t = QLabel(title)
        t.setStyleSheet("font-weight: 600;")
        s = QLabel(subtitle)
        s.setProperty("kind", "faint")
        l.addWidget(t)
        l.addWidget(s)
        return w

    def _set_accent(self, color: str) -> None:
        self.state.settings.accent = color
        theme.set_accent(color)
        app = QApplication.instance()
        if app:
            theme.apply(app, self.state.settings.font_size)
        services.save_settings(self.state.settings)
        self.state.settings_changed.emit()

    def _choose_accent(self) -> None:
        color = QColorDialog.getColor(QColor(theme.ACCENT), self, "选择主题颜色")
        if color.isValid():
            self._set_accent(color.name().upper())

    def _set_font(self, index: int) -> None:
        size = int(self.font_combo.itemData(index))
        self.state.settings.font_size = size
        app = QApplication.instance()
        if app:
            theme.apply(app, size)
        services.save_settings(self.state.settings)

    def _set_preview_width(self, value: int) -> None:
        self.state.settings.preview_width = value
        services.save_settings(self.state.settings)
        self.state.settings_changed.emit()

    def _set_shortcut(self, key: str, text: str) -> None:
        value = text.strip().upper()
        if value:
            self.state.settings.shortcuts[key] = value
        else:
            defaults = {"trim_right": "W", "split_right": "S", "trim_left": "Q",
                        "split_left": "A", "trim_timeline_left": "E", "trim_timeline_right": "R"}
            self.state.settings.shortcuts[key] = defaults[key]
        services.save_settings(self.state.settings)

    def _reset(self) -> None:
        from .model import Settings
        defaults = Settings()
        self.state.settings.accent = defaults.accent
        self.state.settings.font_size = defaults.font_size
        self.state.settings.shortcuts = dict(defaults.shortcuts)
        theme.set_accent(defaults.accent)
        app = QApplication.instance()
        if app:
            theme.apply(app, defaults.font_size)
        services.save_settings(self.state.settings)
        self.state.settings_changed.emit()
        self.accept()
