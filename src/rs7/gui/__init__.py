"""Desktop GUI (PySide6). Start with ``rs7-gui``, ``rs7 gui`` or ``python -m rs7.gui``."""

from __future__ import annotations

import sys


def main(port: str | None = None) -> None:
    from PySide6.QtWidgets import QApplication

    from .window import MainWindow

    if port is None and len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        port = sys.argv[1]
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("RS-7 Control")
    window = MainWindow(port)
    window.show()
    app.exec()


__all__ = ["main"]
