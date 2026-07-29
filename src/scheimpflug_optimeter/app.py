"""Scheimpflug OptiMeter desktop application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from .ui import MainWindow

APPLICATION_STYLE = """
QMainWindow, QWidget {
    background: #f4f6f8;
    color: #15202b;
}
QMenuBar, QMenu, QToolBar, QStatusBar {
    background: #ffffff;
}
QGroupBox {
    border: 1px solid #cfd7df;
    border-radius: 5px;
    margin-top: 9px;
    padding-top: 8px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QDoubleSpinBox, QSpinBox, QComboBox, QTreeWidget, QListWidget {
    background: #ffffff;
    border: 1px solid #bdc8d2;
    border-radius: 3px;
    padding: 4px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #aebac5;
    border-radius: 4px;
    padding: 6px 10px;
}
QPushButton:hover {
    border-color: #1473e6;
    color: #0d5fbd;
}
QPushButton:disabled {
    color: #87939e;
    background: #e8ecef;
}
QLabel#panelTitle {
    font-size: 16px;
    font-weight: 700;
    color: #0d3c61;
    padding: 3px 0 8px 0;
}
QTabBar::tab {
    background: #e6ebef;
    border: 1px solid #c8d0d8;
    padding: 8px 18px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #0d5fbd;
}
"""


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process QApplication, creating it only once for tests/tools."""

    existing = QApplication.instance()
    if existing is not None:
        return existing
    QCoreApplication.setOrganizationName("Scheimpflug OptiMeter")
    QCoreApplication.setApplicationName("Scheimpflug OptiMeter")
    QCoreApplication.setApplicationVersion("0.1.0")
    application = QApplication(list(argv) if argv is not None else sys.argv)
    application.setStyle("Fusion")
    application.setStyleSheet(APPLICATION_STYLE)
    font = QFont()
    font.setFamilies(["Malgun Gothic", "Noto Sans CJK KR", "Segoe UI"])
    font.setPointSize(9)
    application.setFont(font)
    application.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    return application


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop application."""

    application = create_application(argv)
    window = MainWindow()
    window.show()
    return application.exec()


__all__ = ["create_application", "main"]
