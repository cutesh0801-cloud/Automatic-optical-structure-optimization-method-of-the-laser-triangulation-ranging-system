"""Scheimpflug OptiMeter desktop application entry point."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from importlib.resources import files

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont, QIcon, QPixmap
from PySide6.QtWidgets import QApplication

from . import __version__
from .typography import BASE_FONT_POINT_SIZE, ResponsiveTypography
from .ui import MainWindow

APPLICATION_STYLE = """
QMainWindow, QWidget {
    background: #f5f7fa;
    color: #17212b;
}
QMenuBar, QMenu, QToolBar, QStatusBar {
    background: #ffffff;
}
QMenuBar {
    border-bottom: 1px solid #d5dde5;
}
QMenuBar::item {
    padding: 7px 10px;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #e7f1fc;
    color: #084b8a;
}
QToolBar {
    border: 0;
    border-bottom: 1px solid #d5dde5;
    spacing: 4px;
    padding: 5px 8px;
}
QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 5px;
    min-height: 28px;
    padding: 4px 9px;
}
QToolButton:hover {
    background: #e7f1fc;
    border-color: #9bc2e8;
    color: #084b8a;
}
QToolButton:focus {
    border: 2px solid #0b63ce;
}
QStatusBar {
    border-top: 1px solid #d5dde5;
    min-height: 27px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #cbd5df;
    border-radius: 7px;
    margin-top: 14px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #173b5e;
}
QDoubleSpinBox, QSpinBox, QComboBox, QTreeWidget, QListWidget, QTableWidget {
    background: #ffffff;
    border: 1px solid #aebbc8;
    border-radius: 5px;
    padding: 5px 7px;
    selection-background-color: #0b63ce;
    selection-color: #ffffff;
}
QDoubleSpinBox, QSpinBox, QComboBox {
    min-height: 28px;
}
QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus,
QTreeWidget:focus, QListWidget:focus, QTableWidget:focus {
    border: 2px solid #0b63ce;
}
QComboBox::drop-down {
    border: 0;
    width: 24px;
}
QHeaderView::section {
    background: #e9eef4;
    color: #23384d;
    border: 0;
    border-bottom: 1px solid #bcc8d4;
    padding: 7px;
    font-weight: 700;
}
QTreeWidget, QListWidget, QTableWidget {
    alternate-background-color: #f4f7fa;
}
QTreeWidget::item, QListWidget::item {
    min-height: 25px;
    padding: 2px 4px;
}
QTableWidget::item {
    padding: 5px 7px;
}
QPushButton {
    background: #ffffff;
    border: 1px solid #99a9b8;
    border-radius: 5px;
    min-height: 29px;
    padding: 5px 11px;
}
QPushButton:hover {
    background: #e7f1fc;
    border-color: #0b63ce;
    color: #084b8a;
}
QPushButton:focus {
    border: 2px solid #0b63ce;
}
QPushButton[role="primary"] {
    background: #0b63ce;
    border-color: #0b63ce;
    color: #ffffff;
    font-weight: 700;
}
QPushButton[role="primary"]:hover {
    background: #084f9f;
}
QPushButton:disabled {
    color: #6f7d89;
    background: #e5e9ed;
    border-color: #c8d0d7;
}
QLabel#panelTitle {
    font-size: 18px;
    font-weight: 700;
    color: #123c61;
    padding: 2px 0 5px 0;
}
QLabel#modeHelp {
    background: #f7f9fb;
    border: 0;
    border-left: 3px solid #8aa0b5;
    border-radius: 3px;
    color: #415466;
    padding: 7px 9px;
}
QLabel#solutionSummary {
    background: #edf3f8;
    border-left: 5px solid #657b8f;
    border-radius: 4px;
    color: #243746;
    font-size: 13px;
    font-weight: 700;
    padding: 9px 10px;
}
QLabel#solutionSummary[state="valid"] {
    background: #e8f5ee;
    border-left-color: #147a49;
    color: #0d5834;
}
QLabel#solutionSummary[state="warning"] {
    background: #fff4dc;
    border-left-color: #a96300;
    color: #734500;
}
QLabel#solutionSummary[state="error"] {
    background: #fdebea;
    border-left-color: #b42318;
    color: #7a1b15;
}
QFrame#sceneToolbar {
    background: #ffffff;
    border: 1px solid #d3dce5;
    border-radius: 6px;
}
QLabel#workspaceTitle {
    color: #173b5e;
    font-weight: 700;
}
QLabel#sceneKey {
    color: #526577;
    padding: 1px 4px;
}
QLabel#performanceBadge {
    background: transparent;
    border: 0;
    color: #415466;
    padding: 2px 4px;
}
QLabel#performanceBadge[state="valid"] {
    color: #0d5834;
}
QLabel#performanceBadge[state="warning"],
QLabel#performanceBadge[state="error"] {
    color: #7a1b15;
}
QLabel#sensorComparisonDescription {
    color: #415466;
}
QLabel#sensorSensitivityNotice {
    background: #e9f3fd;
    border: 1px solid #9fc5e8;
    border-radius: 6px;
    color: #163f63;
    padding: 10px;
}
QLabel#sensorComparisonSummary {
    background: #edf3f8;
    border-left: 5px solid #0b63ce;
    border-radius: 4px;
    color: #173b5e;
    padding: 9px 10px;
}
QLabel#sensorComparisonSummary[state="warning"] {
    background: #fff4dc;
    border-left-color: #a96300;
    color: #734500;
}
QTableWidget#sensorComparisonTable {
    gridline-color: #d5dde5;
}
QLabel#calculationStatus {
    border-radius: 4px;
    padding: 3px 8px;
    font-weight: 600;
}
QLabel#calculationStatus[state="ready"] {
    color: #415466;
}
QLabel#calculationStatus[state="valid"] {
    color: #0d5834;
}
QLabel#calculationStatus[state="warning"] {
    color: #734500;
}
QLabel#calculationStatus[state="error"] {
    color: #7a1b15;
}
QTabBar::tab {
    background: #e6ebef;
    border: 1px solid #c8d0d8;
    min-width: 180px;
    padding: 10px 20px;
}
QTabBar::tab:selected {
    background: #ffffff;
    color: #084b8a;
    font-weight: 700;
}
QTabBar::tab:focus {
    border: 2px solid #0b63ce;
}
QSplitter::handle {
    background: #d8e0e8;
}
QSplitter::handle:hover {
    background: #8fb7dc;
}
"""


def _load_application_icon(resource_name: str = "app_icon.png") -> QIcon:
    """Load the bundled icon without making a cosmetic resource startup-critical."""

    try:
        payload = files("scheimpflug_optimeter.assets").joinpath(resource_name).read_bytes()
    except Exception:
        return QIcon()
    pixmap = QPixmap()
    if not pixmap.loadFromData(payload, "PNG"):
        return QIcon()
    return QIcon(pixmap)


def create_application(argv: Sequence[str] | None = None) -> QApplication:
    """Return the process QApplication, creating it only once for tests/tools."""

    QCoreApplication.setOrganizationName("Scheimpflug OptiMeter")
    QCoreApplication.setApplicationName("Scheimpflug OptiMeter")
    QCoreApplication.setApplicationVersion(__version__)
    existing = QApplication.instance()
    if existing is None:
        application = QApplication(list(argv) if argv is not None else sys.argv)
    else:
        application = existing
    application.setStyle("Fusion")
    font = QFont()
    font.setFamilies(["Malgun Gothic", "Segoe UI Variable", "Noto Sans CJK KR"])
    font.setPointSizeF(BASE_FONT_POINT_SIZE)
    typography = getattr(application, "_responsive_typography", None)
    if not isinstance(typography, ResponsiveTypography):
        typography = ResponsiveTypography(application, font, APPLICATION_STYLE)
        application._responsive_typography = typography
    typography.refresh(base_font=font, base_style=APPLICATION_STYLE)
    application.setAttribute(Qt.ApplicationAttribute.AA_DontShowIconsInMenus, False)
    icon = _load_application_icon()
    if not icon.isNull():
        application.setWindowIcon(icon)
    return application


def main(argv: Sequence[str] | None = None) -> int:
    """Launch the desktop application."""

    application = create_application(argv)
    window = MainWindow()
    if not application.windowIcon().isNull():
        window.setWindowIcon(application.windowIcon())
    window.show()
    return application.exec()


__all__ = ["create_application", "main"]
