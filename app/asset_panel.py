from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPen
from PySide6.QtWidgets import (QButtonGroup, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QPushButton, QSizePolicy, QSplitter,
                               QSplitterHandle, QStackedWidget, QVBoxLayout,
                               QWidget)

from . import theme
from .icons import icon
from .lists import AssetList, ACTION_MIME, KIND_ROLE, TITLE_ROLE, color_for, make_item
from .model import RoleEntry
from .state import EditorState


def _search_box(placeholder: str) -> QLineEdit:
    box = QLineEdit()
    box.setPlaceholderText(placeholder)
    box.setClearButtonEnabled(True)
    box.addAction(icon("search", 15, theme.TEXT3), QLineEdit.LeadingPosition)
    box.setFixedHeight(30)
    return box


class _AssetHandle(QSplitterHandle):
    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.SplitVCursor)
        self.setToolTip("拖动调整角色区与动作区的高度")

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        cx = self.width() // 2
        cy = self.height() // 2
        color = theme.accent_qcolor(200) if self.underMouse() else QColor(255, 255, 255, 58)
        p.setPen(QPen(color, 1.2))
        p.drawLine(cx - 18, cy, cx + 18, cy)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        for dx in (-18, 18):
            p.drawEllipse(QPoint(cx + dx, cy), 1.4 if self.underMouse() else 1.1,
                          1.4 if self.underMouse() else 1.1)
        p.end()


class _AssetSplitter(QSplitter):
    def createHandle(self) -> QSplitterHandle:
        return _AssetHandle(self.orientation(), self)


class AssetPanel(QFrame):
    choose_folder_requested = Signal()
    action_hovered = Signal(object)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Panel")
        self.setMinimumWidth(270)
        self.setMaximumWidth(380)
        self._role_query = ""
        self._action_query = ""
        self._build()
        self._connect()
        self.refresh_all()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(4)
        icon_label = QLabel()
        icon_label.setPixmap(icon("layers", 16, theme.TEXT3).pixmap(16, 16))
        header.addWidget(icon_label)
        title = QLabel("资源库")
        title.setProperty("kind", "medium")
        header.addWidget(title)
        header.addStretch(1)
        self.scan_button = QPushButton()
        self.scan_button.setProperty("kind", "tool")
        self.scan_button.setIcon(icon("refresh", 17, theme.TEXT2))
        self.scan_button.setFixedSize(28, 28)
        self.scan_button.setToolTip("重新扫描当前路径")
        self.add_button = QPushButton()
        self.add_button.setProperty("kind", "tool")
        self.add_button.setIcon(icon("folder-plus", 17, theme.TEXT2))
        self.add_button.setFixedSize(28, 28)
        self.add_button.setToolTip("添加或切换资源文件夹")
        header.addWidget(self.scan_button)
        header.addWidget(self.add_button)
        root.addLayout(header)
        root.addSpacing(6)

        self.path_button = QPushButton("assets")
        self.path_button.setProperty("kind", "ghost")
        self.path_button.setIcon(icon("folder", 15, theme.TEXT3))
        self.path_button.setFixedHeight(32)
        self.path_button.setStyleSheet("QPushButton { text-align: left; padding-left: 9px; }")
        self.path_button.setToolTip("管理扫描路径")
        root.addWidget(self.path_button)
        root.addSpacing(7)

        role_head = QHBoxLayout()
        role_head.setSpacing(6)
        role_title = QLabel("角色")
        role_title.setProperty("kind", "cap")
        self.role_count = QLabel("0")
        self.role_count.setProperty("kind", "faint")
        role_head.addWidget(role_title)
        role_head.addWidget(self.role_count)
        role_head.addStretch(1)
        root.addLayout(role_head)
        self.role_search = _search_box("搜索角色…")
        root.addWidget(self.role_search)
        root.addSpacing(3)
        self.role_list = AssetList()
        self.role_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        upper = QWidget()
        upper.setMinimumHeight(110)
        upper_lay = QVBoxLayout(upper)
        upper_lay.setContentsMargins(0, 0, 0, 0)
        upper_lay.setSpacing(0)
        upper_lay.addWidget(self.role_list)

        lower = QWidget()
        lower.setMinimumHeight(190)
        lower_lay = QVBoxLayout(lower)
        lower_lay.setContentsMargins(0, 2, 0, 0)
        lower_lay.setSpacing(0)

        tabs = QHBoxLayout()
        tabs.setContentsMargins(0, 2, 0, 2)
        tabs.setSpacing(0)
        self.action_tab = QPushButton("动作")
        self.action_tab.setProperty("kind", "tab")
        self.action_tab.setCheckable(True)
        self.action_tab.setChecked(True)
        self.skin_tab = QPushButton("皮肤")
        self.skin_tab.setProperty("kind", "tab")
        self.skin_tab.setCheckable(True)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        self.tab_group.addButton(self.action_tab, 0)
        self.tab_group.addButton(self.skin_tab, 1)
        tabs.addWidget(self.action_tab)
        tabs.addWidget(self.skin_tab)
        tabs.addStretch(1)
        lower_lay.addLayout(tabs)

        self.stack = QStackedWidget()
        self.stack.setContentsMargins(0, 0, 0, 0)
        action_page = QWidget()
        ap = QVBoxLayout(action_page)
        ap.setContentsMargins(0, 2, 0, 0)
        ap.setSpacing(3)
        self.action_search = _search_box("搜索动作…")
        ap.addWidget(self.action_search)
        self.action_list = AssetList()
        self.action_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ap.addWidget(self.action_list, 1)
        self.stack.addWidget(action_page)
        skin_page = QWidget()
        sp = QVBoxLayout(skin_page)
        sp.setContentsMargins(0, 2, 0, 0)
        sp.setSpacing(3)
        self.skin_list = AssetList()
        sp.addWidget(self.skin_list, 1)
        self.stack.addWidget(skin_page)
        lower_lay.addWidget(self.stack, 1)

        self.asset_splitter = _AssetSplitter(Qt.Vertical)
        self.asset_splitter.setHandleWidth(12)
        self.asset_splitter.setChildrenCollapsible(False)
        self.asset_splitter.addWidget(upper)
        self.asset_splitter.addWidget(lower)
        self.asset_splitter.setStretchFactor(0, 1)
        self.asset_splitter.setStretchFactor(1, 1)
        root.addWidget(self.asset_splitter, 1)
        self._split_ready = False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._split_ready:
            self._split_ready = True
            QTimer.singleShot(0, self._init_split_sizes)

    def _init_split_sizes(self) -> None:
        height = self.asset_splitter.height()
        if height > 240:
            self.asset_splitter.setSizes([int(height * 0.52), int(height * 0.48)])

    def _connect(self) -> None:
        self.scan_button.clicked.connect(self.state.rescan)
        self.add_button.clicked.connect(self.choose_folder_requested)
        self.path_button.clicked.connect(self.choose_folder_requested)
        self.role_search.textChanged.connect(self._on_role_filter)
        self.action_search.textChanged.connect(self._on_action_filter)
        self.role_list.itemClicked.connect(self._on_role_clicked)
        self.action_list.itemClicked.connect(self._on_action_clicked)
        self.action_list.itemDoubleClicked.connect(lambda item: self._add_action(item))
        self.action_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.action_list.customContextMenuRequested.connect(self._action_context_menu)
        self.skin_list.itemClicked.connect(self._on_skin_clicked)
        self.tab_group.idClicked.connect(self._switch_tab)
        self.state.roles_changed.connect(self.refresh_roles)
        self.state.role_loading.connect(lambda _name: self.refresh_roles())
        self.state.role_ready.connect(self.refresh_all)
        self.state.role_failed.connect(lambda _e: self.refresh_all())
        self.state.skin_changed.connect(self.refresh_skins)
        self.state.scan_changed.connect(self.refresh_path)
        self.action_list.itemEntered.connect(self._on_action_entered)
        self.action_list.viewport().installEventFilter(self)

    # ------------------------------------------------------------------
    # refresh
    # ------------------------------------------------------------------

    def refresh_path(self) -> None:
        active = self.state.active_root or (self.state.scan_roots[0] if self.state.scan_roots else "")
        name = Path(active).name if active else "assets"
        metrics = QFontMetrics(self.path_button.font())
        self.path_button.setText(metrics.elidedText(name + "  ▾", Qt.ElideRight, self.path_button.width() - 32))
        self.path_button.setToolTip(active)

    def refresh_all(self) -> None:
        self.refresh_path()
        self.refresh_roles()
        self.refresh_actions()
        self.refresh_skins()

    def refresh_roles(self) -> None:
        self.refresh_path()
        query = self._role_query.lower()
        roles = [r for r in self.state.roles if query in r.name.lower()]
        self.role_list.clear()
        self.role_count.setText(str(len(self.state.roles)))
        selected_key = self.state.selected_role_entry.unique_key if self.state.selected_role_entry else None
        for entry in roles:
            item = make_item(entry.name, dot=color_for(entry.name), data=entry,
                             tooltip=entry.atlas,
                             tag="载入中" if (self.state.selected_role_entry == entry and self.state._loading) else "")
            self.role_list.addItem(item)
            if selected_key and entry.unique_key == selected_key:
                item.setSelected(True)
        if not roles:
            text = "没有匹配的角色" if self._role_query else ("还没有角色" if not self.state.roles else "暂无内容")
            self.role_list.addItem(make_item(text, kind="plain", muted=True))
            self.role_list.item(0).setFlags(Qt.NoItemFlags)
        if selected_key:
            for i in range(self.role_list.count()):
                item = self.role_list.item(i)
                entry = item.data(Qt.UserRole + 7)
                if isinstance(entry, RoleEntry) and entry.unique_key == selected_key:
                    self.role_list.scrollToItem(item)
                    break

    def refresh_actions(self) -> None:
        self.action_list.clear()
        loaded = self.state.loaded
        if loaded is None:
            self.action_tab.setText("动作")
            self.action_list.addItem(make_item(
                "正在读取角色…" if self.state._loading else "先选择一个角色",
                muted=True))
            self.action_list.item(0).setFlags(Qt.NoItemFlags)
            return
        actions = loaded.actions
        query = self._action_query.lower()
        filtered = [a for a in actions if query in a.lower()]
        self.action_tab.setText(f"动作 {len(actions)}")
        for action in filtered:
            duration = loaded.durations.get(action, 1.5)
            item = make_item(action, dot=color_for(action), kind="action",
                             tag=f"{duration:.1f}s", trailing="plus", data=action)
            self.action_list.addItem(item)
            if action == self.state.selected_action:
                item.setSelected(True)
        if not filtered:
            text = "没有匹配的动作" if query else "这个角色还没有动作"
            self.action_list.addItem(make_item(text, muted=True))
            self.action_list.item(0).setFlags(Qt.NoItemFlags)

    def refresh_skins(self) -> None:
        self.skin_list.clear()
        loaded = self.state.loaded
        if loaded is None:
            self.skin_tab.setText("皮肤")
            self.skin_list.addItem(make_item(
                "正在读取角色…" if self.state._loading else "先选择一个角色", muted=True))
            self.skin_list.item(0).setFlags(Qt.NoItemFlags)
            return
        self.skin_tab.setText(f"皮肤 {len(loaded.skins)}")
        for skin in loaded.skins:
            selected = skin == self.state.current_skin
            item = make_item(skin, dot=color_for(skin), data=skin,
                             tag="当前" if selected else "", muted=not selected)
            self.skin_list.addItem(item)
            if selected:
                item.setSelected(True)
        if not loaded.skins:
            self.skin_list.addItem(make_item("没有内部皮肤", muted=True))
            self.skin_list.item(0).setFlags(Qt.NoItemFlags)

    def _switch_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(0 if index == 0 else 1)

    # ------------------------------------------------------------------
    # filters / clicks
    # ------------------------------------------------------------------

    def _on_role_filter(self, text: str) -> None:
        self._role_query = text.strip()
        self.refresh_roles()

    def _on_action_filter(self, text: str) -> None:
        self._action_query = text.strip()
        self.refresh_actions()

    def _on_role_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(Qt.UserRole + 7)
        if isinstance(entry, RoleEntry):
            self.state.select_role(entry)

    def _on_action_clicked(self, item: QListWidgetItem) -> None:
        action = item.data(Qt.UserRole + 7)
        if isinstance(action, str) and action:
            self.state.set_action(action)

    def _on_skin_clicked(self, item: QListWidgetItem) -> None:
        skin = item.data(Qt.UserRole + 7)
        if isinstance(skin, str) and skin:
            self.state.set_skin(skin)

    def _add_action(self, item: QListWidgetItem) -> None:
        action = item.data(Qt.UserRole + 7)
        if isinstance(action, str) and action:
            self.state.add_action(action)

    def _action_context_menu(self, pos: QPoint) -> None:
        item = self.action_list.itemAt(pos)
        if item is None:
            return
        action = item.data(Qt.UserRole + 7)
        if not isinstance(action, str) or not action:
            return
        menu = QMenu(self)
        menu.addAction(icon("plus"), "添加到播放头", lambda: self.state.add_action(action))
        menu.addAction(icon("download"), "添加到末尾",
                       lambda: self.state.add_action(action, len(self.state.timeline)))
        menu.exec(self.action_list.mapToGlobal(pos))

    def _on_action_entered(self, item: QListWidgetItem) -> None:
        action = item.data(Qt.UserRole + 7)
        self.action_hovered.emit(action if isinstance(action, str) else None)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.action_list.viewport() and event.type() == QEvent.Leave:
            self.action_hovered.emit(None)
        return super().eventFilter(obj, event)
