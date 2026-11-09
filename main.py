from __future__ import annotations

import faulthandler
import os
import sys
import time
import traceback
from pathlib import Path


def _prepare_log() -> tuple[object, Path]:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home())
    folder = Path(base) / "SpineStudioV2"
    log_path = folder / "app.log"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        if log_path.is_file() and log_path.stat().st_size > 2 * 1024 * 1024:
            old = folder / "app.old.log"
            old.unlink(missing_ok=True)
            log_path.replace(old)
        stream = log_path.open("a", encoding="utf-8", buffering=1)
        stream.write(f"\n--- Spine Studio {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        stream.flush()
        faulthandler.enable(stream)
        sys.stdout = stream
        sys.stderr = stream
        return stream, log_path
    except Exception:
        return None, log_path


_LOG_STREAM, LOG_PATH = _prepare_log()

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon, QSurfaceFormat
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import services, theme
    from app.main_window import MainWindow
    from app.state import EditorState
except Exception:
    traceback.print_exc()
    if _LOG_STREAM is not None:
        _LOG_STREAM.flush()
    raise


def _install_excepthook() -> None:
    def _hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb)
        if _LOG_STREAM is not None:
            _LOG_STREAM.flush()

    sys.excepthook = _hook


def main() -> int:
    _install_excepthook()
    try:
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        fmt.setStencilBufferSize(8)
        fmt.setSamples(4)
        fmt.setSwapInterval(1)
        QSurfaceFormat.setDefaultFormat(fmt)
        QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)
        app = QApplication(sys.argv)
        app.setApplicationName("Spine Studio")
        app.setApplicationDisplayName("")
        app.setOrganizationName("SpineStudio")
        app.setWindowIcon(QIcon(str(services.PROJECT_ROOT / "assets" / "icon.png")))
        settings = services.load_settings()
        theme.load_fonts()
        theme.set_accent(settings.accent)
        theme.apply(app, settings.font_size)
        state = EditorState()
        window = MainWindow(state)
        window.show()
        return app.exec()
    except Exception:
        traceback.print_exc()
        if _LOG_STREAM is not None:
            _LOG_STREAM.flush()
        try:
            QMessageBox.critical(
                None, "Spine Studio",
                f"启动失败，详情已写入日志：\n{LOG_PATH}\n\n{traceback.format_exc(limit=8)}",
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
