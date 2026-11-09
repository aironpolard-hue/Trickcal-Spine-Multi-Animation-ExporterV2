from __future__ import annotations

from pathlib import Path
from typing import Dict

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

ASSETS = Path(__file__).resolve().parent.parent / "assets"

BG = "#070A11"
BG2 = "#090D16"
SURFACE = "#0D121C"
SURFACE2 = "#121927"
SURFACE3 = "#182133"
SURFACE4 = "#1F2A3F"
CANVAS = "#05070C"
LINE = "#19202D"
LINE2 = "#232C3D"
LINE3 = "#303B52"
TEXT = "#E9EDF7"
TEXT2 = "#9DA8BE"
TEXT3 = "#66738B"
TEXT4 = "#455066"
GREEN = "#40D999"
AMBER = "#F5B94D"
RED = "#FF6E6E"
CYAN = "#5AD7E6"
ROSE = "#F279A5"

ACCENT = "#6B7CFF"
ACCENT_HOVER = "#8D9BFF"
ACCENT_PRESSED = "#5868E5"
ACCENT_SOFT = "rgba(107,124,255,0.16)"
ACCENT_TEXT = "#B8C2FF"

FONT_FAMILY = "Microsoft YaHei UI"
FONT_SIZE = 13


def _mix_hex(color: str, other: str, t: float) -> str:
    a = QColor(color)
    b = QColor(other)
    r = round(a.red() + (b.red() - a.red()) * t)
    g = round(a.green() + (b.green() - a.green()) * t)
    bl = round(a.blue() + (b.blue() - a.blue()) * t)
    return f"#{r:02X}{g:02X}{bl:02X}"


def accent_qcolor(alpha: int = 255) -> QColor:
    c = QColor(ACCENT)
    c.setAlpha(alpha)
    return c


def rgba(hex_color: str, alpha: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha:.3f})"


def load_fonts() -> None:
    global FONT_FAMILY
    available = set(QFontDatabase.families())
    for preferred in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans SC",
                      "Segoe UI Variable Text", "Segoe UI"):
        if preferred in available:
            FONT_FAMILY = preferred
            return
    for name in ("font.ttf", "SourceHanSansSC-Regular.otf", "NotoSansSC-Regular.otf"):
        path = ASSETS / name
        if not path.is_file():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                FONT_FAMILY = families[0]
                return


def set_accent(color: str) -> None:
    global ACCENT, ACCENT_HOVER, ACCENT_PRESSED, ACCENT_SOFT, ACCENT_TEXT
    c = QColor(color)
    if not c.isValid():
        return
    ACCENT = c.name().upper()
    ACCENT_HOVER = _mix_hex(ACCENT, "#FFFFFF", 0.22)
    ACCENT_PRESSED = _mix_hex(ACCENT, "#000000", 0.18)
    ACCENT_SOFT = rgba(ACCENT, 0.16)
    ACCENT_TEXT = _mix_hex(ACCENT, "#FFFFFF", 0.46)


def apply(app: QApplication, font_size: int = 13) -> None:
    global FONT_SIZE
    FONT_SIZE = font_size
    app.setFont(QFont(FONT_FAMILY, 10))
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE2))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE3))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE2))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE3))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT4))
    app.setPalette(pal)
    app.setStyleSheet(build_qss(font_size))


def build_qss(font_size: int = 13) -> str:
    body = font_size
    small = max(10, font_size - 2)
    return f"""
    * {{
        font-family: "{FONT_FAMILY}";
        font-size: {body}px;
        color: {TEXT};
        outline: none;
    }}
    QMainWindow, QDialog {{
        background: {BG};
    }}
    QWidget {{
        background: transparent;
    }}
    QLabel {{
        background: transparent;
        color: {TEXT};
    }}
    QLabel[kind="title"] {{ font-size: {body + 3}px; font-weight: 600; }}
    QLabel[kind="medium"] {{ font-size: {body + 1}px; font-weight: 600; }}
    QLabel[kind="small"] {{ font-size: {small}px; color: {TEXT2}; }}
    QLabel[kind="muted"] {{ font-size: {small}px; color: {TEXT3}; }}
    QLabel[kind="faint"] {{ font-size: {small}px; color: {TEXT4}; }}
    QLabel[kind="accent"] {{ font-size: {small}px; color: {ACCENT_TEXT}; }}
    QLabel[kind="cap"] {{ font-size: {small}px; color: {TEXT3}; font-weight: 600; }}
    QLabel[kind="stat"] {{ font-size: {body + 1}px; font-weight: 600; }}

    QFrame#Panel {{
        background: {SURFACE};
        border: 1px solid {LINE2};
        border-radius: 12px;
    }}
    QFrame#DialogSurface {{
        background: {SURFACE};
        border: none;
    }}
    QFrame#TopBar {{
        background: {BG2};
        border-bottom: 1px solid {LINE};
    }}
    QFrame#StatusBar {{
        background: {BG2};
        border-top: 1px solid {LINE};
    }}
    QFrame#DividerV {{ background: {LINE2}; max-width: 1px; min-width: 1px; }}
    QFrame#DividerH {{ background: {LINE}; max-height: 1px; min-height: 1px; }}
    QFrame#Card {{
        background: {SURFACE2};
        border: 1px solid {LINE2};
        border-radius: 10px;
    }}
    QFrame#Rail {{
        background: {SURFACE};
        border: 1px solid {LINE2};
        border-radius: 12px;
    }}

    QPushButton {{
        background: {SURFACE2};
        border: 1px solid {LINE2};
        border-radius: 8px;
        padding: 6px 12px;
        color: {TEXT2};
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {SURFACE3}; border-color: {LINE3}; color: {TEXT}; }}
    QPushButton:pressed {{ background: {SURFACE4}; }}
    QPushButton:disabled {{ color: {TEXT4}; background: {rgba(SURFACE2, 0.5)}; border-color: {rgba(LINE2, 0.6)}; }}
    QPushButton[kind="primary"] {{
        background: {ACCENT}; border: 1px solid {ACCENT_HOVER}; color: #FFFFFF; font-weight: 600;
    }}
    QPushButton[kind="primary"]:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton[kind="primary"]:pressed {{ background: {ACCENT_PRESSED}; }}
    QPushButton[kind="primary"]:disabled {{ background: {rgba(ACCENT, 0.35)}; border-color: {rgba(ACCENT, 0.3)}; color: rgba(255,255,255,0.55); }}
    QPushButton[kind="ghost"] {{
        background: transparent; border: 1px solid transparent; color: {TEXT3};
    }}
    QPushButton[kind="ghost"]:hover {{ background: rgba(255,255,255,0.05); color: {TEXT}; }}
    QPushButton[kind="ghost"]:checked {{ background: {ACCENT_SOFT}; color: {ACCENT_TEXT}; border-color: {rgba(ACCENT,0.5)}; }}
    QPushButton[kind="danger"] {{
        background: rgba(255,110,110,0.10); border: 1px solid rgba(255,110,110,0.30); color: {RED};
    }}
    QPushButton[kind="danger"]:hover {{ background: rgba(255,110,110,0.18); }}
    QPushButton[kind="chip"] {{
        background: {SURFACE2}; border: 1px solid {LINE2}; border-radius: 13px;
        padding: 3px 11px; color: {TEXT2}; font-size: {small}px;
    }}
    QPushButton[kind="chip"]:hover {{ background: {SURFACE3}; color: {TEXT}; }}
    QPushButton[kind="chip"]:checked {{
        background: {ACCENT_SOFT}; border-color: {rgba(ACCENT,0.55)}; color: {ACCENT_TEXT};
    }}
    QPushButton[kind="tool"] {{
        background: transparent; border: none; border-radius: 7px; padding: 4px;
    }}
    QPushButton[kind="tool"]:hover {{ background: rgba(255,255,255,0.06); }}
    QPushButton[kind="tab"] {{
        background: transparent; border: none; border-bottom: 2px solid transparent;
        border-radius: 0; color: {TEXT3}; padding: 6px 12px;
    }}
    QPushButton[kind="tab"]:hover {{ color: {TEXT}; }}
    QPushButton[kind="tab"]:checked {{ color: {ACCENT_TEXT}; border-bottom: 2px solid {ACCENT}; }}

    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
        background: {SURFACE2};
        border: 1px solid {LINE2};
        border-radius: 8px;
        padding: 5px 9px;
        color: {TEXT};
        selection-background-color: {ACCENT};
        min-height: 20px;
    }}
    QLineEdit:hover, QSpinBox:hover, QDoubleSpinBox:hover, QComboBox:hover {{ border-color: {LINE3}; }}
    QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
        border-color: {ACCENT}; background: {SURFACE};
    }}
    QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {{
        color: {TEXT4}; border-color: {rgba(LINE2,0.6)}; background: {rgba(SURFACE2,0.45)};
    }}
    QLineEdit[search="true"] {{ padding-left: 30px; }}

    QComboBox::drop-down {{ border: none; width: 22px; }}
    QComboBox QAbstractItemView {{
        background: {SURFACE2}; border: 1px solid {LINE2}; border-radius: 8px;
        selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT}; padding: 4px;
    }}

    QCheckBox {{ color: {TEXT2}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 34px; height: 18px; border-radius: 9px; background: {SURFACE4};
        border: 1px solid {LINE3};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT}; border-color: {ACCENT_HOVER};
        image: none;
    }}

    QListWidget, QTreeWidget, QTableWidget {{
        background: transparent; border: none; outline: none;
        alternate-background-color: transparent;
    }}
    QListWidget::item, QTreeWidget::item {{ border: none; padding: 0; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{ background: transparent; }}

    QScrollBar:vertical {{
        background: transparent; width: 8px; margin: 2px 0;
    }}
    QScrollBar::handle:vertical {{
        background: rgba(255,255,255,0.16); border-radius: 4px; min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.30); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{
        background: transparent; height: 8px; margin: 0 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: rgba(255,255,255,0.16); border-radius: 4px; min-width: 28px;
    }}
    QScrollBar::handle:horizontal:hover {{ background: rgba(255,255,255,0.30); }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}

    QSplitter::handle {{ background: transparent; }}
    QSplitter::handle:hover {{ background: rgba(255,255,255,0.05); }}
    QSplitter::handle:pressed {{ background: {rgba(ACCENT,0.35)}; }}

    QTabBar::tab {{
        background: transparent; color: {TEXT3}; border: none; padding: 6px 14px;
        border-bottom: 2px solid transparent;
    }}
    QTabBar::tab:hover {{ color: {TEXT}; }}
    QTabBar::tab:selected {{ color: {ACCENT_TEXT}; border-bottom: 2px solid {ACCENT}; }}

    QMenu {{
        background: {SURFACE2}; border: 1px solid {LINE2}; border-radius: 8px; padding: 5px;
    }}
    QMenu::item {{
        padding: 6px 22px 6px 12px; border-radius: 5px; color: {TEXT2};
    }}
    QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {TEXT}; }}
    QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}

    QToolTip {{
        background: {SURFACE3}; color: {TEXT}; border: 1px solid {LINE3};
        border-radius: 6px; padding: 6px 8px; font-size: {small}px;
    }}
    QSlider::groove:horizontal {{
        height: 4px; background: {SURFACE4}; border-radius: 2px;
    }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
        background: #FFFFFF;
    }}
    QSlider::handle:horizontal:hover {{ background: {ACCENT_HOVER}; }}

    QProgressBar {{
        background: {SURFACE4}; border: none; border-radius: 5px; height: 8px; text-align: center;
    }}
    QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

    QTextEdit {{
        background: {SURFACE2}; border: 1px solid {LINE2}; border-radius: 8px; padding: 8px;
    }}

    QFrame#SeparatorH {{ background: {LINE}; max-height: 1px; min-height: 1px; }}
    """
