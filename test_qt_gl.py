import sys
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication
from OpenGL.GL import *


class W(QOpenGLWidget):
    def initializeGL(self):
        print('initializeGL', flush=True)
        print(glGetString(GL_VERSION), flush=True)
        glClearColor(0.2, 0.3, 0.5, 1.0)
        print('init done', flush=True)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        print('paint', self.width(), self.height(), flush=True)


def main():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.AA_UseDesktopOpenGL)
    print('app', flush=True)
    app = QApplication(sys.argv)
    w = W()
    w.resize(600, 400)
    w.setWindowTitle('Qt GL minimal')
    w.show()
    QTimer.singleShot(3000, app.quit)
    print('exec', flush=True)
    app.exec()
    print('exit', flush=True)


main()
