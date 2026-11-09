from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics
from PySide6.QtWidgets import (QColorDialog, QDoubleSpinBox, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox,
                               QStackedWidget, QTabBar, QVBoxLayout, QWidget)

from . import theme
from .icons import icon
from .lists import AssetList, make_item, color_for
from .state import EditorState


# NoButtons + styled QSpinBox collapses the internal line edit to 1px in Qt.
# Keep the native spin buttons for layout and hide them visually instead.
_SPIN_BUTTON_HIDE = (
    "QSpinBox::up-button, QSpinBox::down-button,"
    "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {"
    " width: 0px; height: 0px; border: none; background: transparent; }"
)


class InspectorPanel(QFrame):
    edit_changed = Signal()
    pick_mode_requested = Signal(bool)

    def __init__(self, state: EditorState, parent=None):
        super().__init__(parent)
        self.state = state
        self.setObjectName("Panel")
        self.setMinimumWidth(270)
        self.setMaximumWidth(400)
        self._collapsed: set[str] = set()
        self._query = ""
        self._syncing = False
        self._build()
        self._connect()
        self.refresh_all()

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(0)
        header = QHBoxLayout()
        header.setSpacing(6)
        icon_label = QLabel()
        icon_label.setPixmap(icon("sliders", 16, theme.TEXT3).pixmap(16, 16))
        header.addWidget(icon_label)
        title = QLabel("检查器")
        title.setProperty("kind", "medium")
        header.addWidget(title)
        header.addStretch(1)
        root.addLayout(header)
        root.addSpacing(4)

        self.tabs = QTabBar()
        self.tabs.setDrawBase(False)
        self.tabs.setExpanding(False)
        self.tabs.addTab("部件")
        self.tabs.addTab("舞台")
        self.tabs.setStyleSheet(
            f"QTabBar {{ background: {theme.SURFACE2}; border-radius: 9px; padding: 2px; }}"
            f"QTabBar::tab {{ border-radius: 7px; padding: 5px 18px; margin: 2px; border: none; }}"
            f"QTabBar::tab:selected {{ background: {theme.ACCENT_SOFT}; color: {theme.ACCENT_TEXT}; }}"
        )
        root.addWidget(self.tabs)
        root.addSpacing(5)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_parts())
        self.stack.addWidget(self._build_stage())
        root.addWidget(self.stack, 1)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

    def _build_parts(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(5)
        row = QHBoxLayout()
        row.setSpacing(5)
        self.hidden_label = QLabel("隐藏 0")
        self.hidden_label.setProperty("kind", "faint")
        row.addWidget(self.hidden_label)
        row.addStretch(1)
        self.pick_button = QPushButton("点选")
        self.pick_button.setProperty("kind", "chip")
        self.pick_button.setCheckable(True)
        self.pick_button.setIcon(icon("target", 13, theme.TEXT2))
        self.pick_button.setFixedHeight(25)
        self.reset_button = QPushButton("重置")
        self.reset_button.setProperty("kind", "ghost")
        self.reset_button.setIcon(icon("refresh", 13, theme.TEXT2))
        self.reset_button.setFixedHeight(25)
        row.addWidget(self.pick_button)
        row.addWidget(self.reset_button)
        lay.addLayout(row)
        self.part_search = QLineEdit()
        self.part_search.setPlaceholderText("搜索部件…")
        self.part_search.setClearButtonEnabled(True)
        self.part_search.addAction(icon("search", 15, theme.TEXT3), QLineEdit.LeadingPosition)
        self.part_search.setFixedHeight(30)
        lay.addWidget(self.part_search)
        self.part_list = AssetList()
        self.part_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.part_list, 1)
        return page

    def _build_stage(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(2, 6, 4, 12)
        lay.setSpacing(10)

        lay.addWidget(self._section("画布尺寸", "舞台决定预览与导出比例"))
        presets = QHBoxLayout()
        presets.setSpacing(6)
        for label, w, h in (("720p", 1280, 720), ("900p", 1440, 900), ("1080p", 1920, 1080)):
            btn = QPushButton(label)
            btn.setProperty("kind", "chip")
            btn.setFixedHeight(27)
            btn.clicked.connect(lambda _=False, ww=w, hh=h: self._apply_stage_size(ww, hh))
            presets.addWidget(btn)
        lay.addLayout(presets)
        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self.stage_w = self._spin(320, 3840, 0)
        self.stage_h = self._spin(200, 2160, 0)
        size_row.addWidget(self._labeled("宽度", self.stage_w))
        size_row.addWidget(self._labeled("高度", self.stage_h))
        lay.addLayout(size_row)

        lay.addWidget(self._section("背景颜色", "只影响画布，不会改动素材"))
        color_row = QHBoxLayout()
        color_row.setSpacing(8)
        self.color_swatch = QPushButton()
        self.color_swatch.setFixedSize(28, 28)
        self.color_swatch.setCursor(Qt.PointingHandCursor)
        self.color_swatch.clicked.connect(self._choose_color)
        color_row.addWidget(self.color_swatch)
        self.color_hex = QLabel("#1F212E")
        self.color_hex.setProperty("kind", "faint")
        color_row.addWidget(self.color_hex)
        color_row.addStretch(1)
        for swatch in ("#1F212E", "#0B0E15", "#222A3A", "#E9EDF7", "#000000", "#2A1F2E"):
            b = QPushButton()
            b.setFixedSize(20, 20)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton {{ background: {swatch}; border-radius: 10px; border: 1px solid {theme.LINE3}; }}")
            b.clicked.connect(lambda _=False, c=swatch: self._set_bg(c))
            color_row.addWidget(b)
        lay.addLayout(color_row)

        lay.addWidget(self._section("角色位置", "也可以直接拖动舞台上的角色"))
        role_row = QHBoxLayout()
        role_row.setSpacing(6)
        self.role_x = self._dspin(-10000, 10000, 1)
        self.role_y = self._dspin(-10000, 10000, 1)
        role_row.addWidget(self._labeled("X", self.role_x))
        role_row.addWidget(self._labeled("Y", self.role_y))
        lay.addLayout(role_row)
        scale_row = QHBoxLayout()
        scale_row.setSpacing(6)
        self.role_scale = self._dspin(0.01, 25, 2, 0.05)
        scale_row.addWidget(self._labeled("缩放", self.role_scale))
        center = QPushButton("居中")
        center.setProperty("kind", "ghost")
        center.setFixedHeight(30)
        center.setIcon(icon("target", 14, theme.TEXT2))
        center.clicked.connect(self._center_role)
        reset = QPushButton("重置")
        reset.setProperty("kind", "ghost")
        reset.setFixedHeight(30)
        reset.setIcon(icon("refresh", 14, theme.TEXT2))
        reset.clicked.connect(self._reset_role)
        scale_row.addWidget(center)
        scale_row.addWidget(reset)
        lay.addLayout(scale_row)

        lay.addWidget(self._section("导出区域", "黄色框就是最终画面范围"))
        reg1 = QHBoxLayout()
        reg1.setSpacing(6)
        self.reg_x = self._dspin(0, 100000, 1)
        self.reg_y = self._dspin(0, 100000, 1)
        reg1.addWidget(self._labeled("X", self.reg_x))
        reg1.addWidget(self._labeled("Y", self.reg_y))
        lay.addLayout(reg1)
        reg2 = QHBoxLayout()
        reg2.setSpacing(6)
        self.reg_w = self._dspin(40, 100000, 1)
        self.reg_h = self._dspin(40, 100000, 1)
        reg2.addWidget(self._labeled("宽度", self.reg_w))
        reg2.addWidget(self._labeled("高度", self.reg_h))
        lay.addLayout(reg2)
        reset_region = QPushButton("恢复默认区域")
        reset_region.setProperty("kind", "ghost")
        reset_region.setFixedHeight(30)
        reset_region.setIcon(icon("refresh", 14, theme.TEXT2))
        reset_region.clicked.connect(self._reset_region)
        lay.addWidget(reset_region)
        lay.addStretch(1)
        scroll.setWidget(content)
        self.stage_content = content
        return scroll

    def _section(self, title: str, subtitle: str) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(1)
        t = QLabel(title)
        t.setProperty("kind", "medium")
        s = QLabel(subtitle)
        s.setProperty("kind", "faint")
        l.addWidget(t)
        l.addWidget(s)
        return w

    def _spin(self, lo: int, hi: int, decimals: int) -> QSpinBox:
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setFixedHeight(30)
        box.setStyleSheet(_SPIN_BUTTON_HIDE)
        return box

    def _dspin(self, lo: float, hi: float, decimals: int, step: float = 1.0) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(lo, hi)
        box.setDecimals(decimals)
        box.setSingleStep(step)
        box.setFixedHeight(30)
        box.setStyleSheet(_SPIN_BUTTON_HIDE)
        return box

    def _labeled(self, text: str, widget: QWidget) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(3)
        label = QLabel(text)
        label.setProperty("kind", "faint")
        l.addWidget(label)
        l.addWidget(widget)
        return w

    # ------------------------------------------------------------------
    # connect / refresh
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self.part_search.textChanged.connect(self._on_part_filter)
        self.part_list.itemClicked.connect(self._on_part_clicked)
        self.pick_button.clicked.connect(self._toggle_pick)
        self.reset_button.clicked.connect(self._reset_parts)
        self.stage_w.valueChanged.connect(self._on_stage_size)
        self.stage_h.valueChanged.connect(self._on_stage_size)
        self.role_x.valueChanged.connect(self._on_role_transform)
        self.role_y.valueChanged.connect(self._on_role_transform)
        self.role_scale.valueChanged.connect(self._on_role_transform)
        self.reg_x.valueChanged.connect(self._on_region)
        self.reg_y.valueChanged.connect(self._on_region)
        self.reg_w.valueChanged.connect(self._on_region)
        self.reg_h.valueChanged.connect(self._on_region)
        self.state.role_ready.connect(self.refresh_all)
        self.state.skin_changed.connect(self.refresh_parts)
        self.state.parts_changed.connect(self.refresh_parts)
        self.state.timeline_changed.connect(self.refresh_parts)

    def refresh_all(self) -> None:
        self.refresh_parts()
        self.refresh_stage()

    def open_stage(self, focus_role: bool) -> None:
        self.tabs.setCurrentIndex(1)
        self.refresh_stage()

    def open_parts(self) -> None:
        self.tabs.setCurrentIndex(0)
        self.refresh_parts()

    def set_pick_state(self, value: bool) -> None:
        self.pick_button.setChecked(value)
        self.pick_button.setText("点选中" if value else "点选")

    def refresh_parts(self) -> None:
        self.part_list.clear()
        self.hidden_label.setText(f"隐藏 {len(self.state.hidden_slots)}")
        loaded = self.state.loaded
        if loaded is None:
            self.part_list.addItem(make_item(
                "正在读取角色…" if self.state._loading else "先选择一个角色", muted=True))
            self.part_list.item(0).setFlags(Qt.NoItemFlags)
            self.pick_button.setEnabled(False)
            return
        self.pick_button.setEnabled(True)
        query = self._query.lower()
        groups = loaded.groups
        shown = 0
        for group, slots in groups:
            if query:
                matches = [s for s in slots if query in s.lower()]
                if not matches:
                    continue
                group_items = matches
                expanded = True
            else:
                group_items = slots
                expanded = group not in self._collapsed
            header = make_item(group, kind="group", tag=str(len(slots)), data=expanded)
            self.part_list.addItem(header)
            if expanded:
                for slot in group_items:
                    hidden = slot in self.state.hidden_slots
                    item = make_item(slot, kind="part", inset=13, muted=hidden,
                                     trailing="eye-off" if hidden else "eye", data=slot)
                    self.part_list.addItem(item)
            shown += 1
        if shown == 0:
            text = "没有匹配的部件" if query else "这个角色没有部件"
            self.part_list.addItem(make_item(text, muted=True))
            self.part_list.item(0).setFlags(Qt.NoItemFlags)

    def _on_part_filter(self, text: str) -> None:
        self._query = text.strip()
        self.refresh_parts()

    def _on_part_clicked(self, item) -> None:
        kind = item.data(Qt.UserRole + 5)
        data = item.data(Qt.UserRole + 7)
        if kind == "group":
            group = str(item.data(Qt.UserRole + 1))
            if group in self._collapsed:
                self._collapsed.remove(group)
            else:
                self._collapsed.add(group)
            self.refresh_parts()
        elif kind == "part" and isinstance(data, str):
            self.state.toggle_slot(data)
            self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh_parts)

    def _toggle_pick(self) -> None:
        self.pick_mode_requested.emit(self.pick_button.isChecked())

    def _reset_parts(self) -> None:
        self.state.reset_hidden_slots()
        self._schedule_refresh()

    # ----- stage form -------------------------------------------------

    def refresh_stage(self) -> None:
        self._syncing = True
        exp = self.state.export
        self.stage_w.setValue(int(round(exp.stage_w)))
        self.stage_h.setValue(int(round(exp.stage_h)))
        self.role_x.setValue(exp.role_x)
        self.role_y.setValue(exp.role_y)
        self.role_scale.setValue(exp.role_scale)
        self.reg_x.setValue(exp.region[0])
        self.reg_y.setValue(exp.region[1])
        self.reg_w.setValue(exp.region[2])
        self.reg_h.setValue(exp.region[3])
        c = QColor.fromRgbF(exp.bg[0] / 255, exp.bg[1] / 255, exp.bg[2] / 255)
        self.color_swatch.setStyleSheet(
            f"QPushButton {{ background: {c.name()}; border-radius: 8px; border: 1px solid {theme.LINE3}; }}")
        self.color_hex.setText(c.name().upper())
        self._syncing = False

    def _on_stage_size(self) -> None:
        if self._syncing:
            return
        self.state.export.stage_w = float(self.stage_w.value())
        self.state.export.stage_h = float(self.stage_h.value())
        self.state.export.keep_inside()
        self.edit_changed.emit()

    def _apply_stage_size(self, w: int, h: int) -> None:
        self._syncing = True
        self.stage_w.setValue(w)
        self.stage_h.setValue(h)
        self._syncing = False
        self._on_stage_size()

    def _on_role_transform(self) -> None:
        if self._syncing:
            return
        exp = self.state.export
        exp.role_x = self.role_x.value()
        exp.role_y = self.role_y.value()
        exp.role_scale = self.role_scale.value()
        exp.keep_inside()
        self.edit_changed.emit()

    def _on_region(self) -> None:
        if self._syncing:
            return
        exp = self.state.export
        exp.region = (self.reg_x.value(), self.reg_y.value(), self.reg_w.value(), self.reg_h.value())
        exp.keep_inside()
        self._syncing = True
        self.reg_x.setValue(exp.region[0])
        self.reg_y.setValue(exp.region[1])
        self.reg_w.setValue(exp.region[2])
        self.reg_h.setValue(exp.region[3])
        self._syncing = False
        self.edit_changed.emit()

    def _choose_color(self) -> None:
        bg = self.state.export.bg
        color = QColorDialog.getColor(QColor(int(bg[0]), int(bg[1]), int(bg[2])), self, "选择背景颜色")
        if color.isValid():
            self._set_bg(color.name())

    def _set_bg(self, value: str) -> None:
        c = QColor(value)
        if not c.isValid():
            return
        self.state.export.bg = (c.red(), c.green(), c.blue())
        self.refresh_stage()
        self.edit_changed.emit()

    def _center_role(self) -> None:
        exp = self.state.export
        exp.role_x = exp.region[0] + exp.region[2] / 2
        exp.role_y = exp.region[1] + exp.region[3] * 0.55
        exp.keep_inside()
        self.refresh_stage()
        self.edit_changed.emit()

    def _reset_role(self) -> None:
        exp = self.state.export
        exp.role_x = exp.stage_w / 2
        exp.role_y = exp.stage_h * 0.6
        exp.role_scale = 0.8
        exp.keep_inside()
        self.refresh_stage()
        self.edit_changed.emit()

    def _reset_region(self) -> None:
        exp = self.state.export
        exp.region = (exp.stage_w * 0.18, exp.stage_h * 0.1, exp.stage_w * 0.64, exp.stage_h * 0.8)
        exp.keep_inside()
        self.refresh_stage()
        self.edit_changed.emit()
