from __future__ import annotations

import ctypes
import sys

from PySide6.QtGui import QColor


def _colorref(hex_color: str) -> int:
    color = QColor(hex_color)
    return color.red() | (color.green() << 8) | (color.blue() << 16)


def apply_dark_title_bar(widget, caption: str = "#090D16",
                         border: str = "#19202D", text: str = "#E9EDF7") -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        func = ctypes.windll.dwmapi.DwmSetWindowAttribute
        func.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
        func.restype = ctypes.c_long

        dark = ctypes.c_int(1)
        func(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))

        for attribute, value in (
            (34, _colorref(border)),
            (35, _colorref(caption)),
            (36, _colorref(text)),
        ):
            color = ctypes.c_uint(value)
            func(hwnd, attribute, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass
