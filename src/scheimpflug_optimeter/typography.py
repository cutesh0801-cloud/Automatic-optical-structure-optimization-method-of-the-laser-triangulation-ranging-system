"""Responsive application typography driven by window size and display DPI."""

from __future__ import annotations

import math
import weakref
from typing import Any

from PySide6.QtCore import QEvent, QObject, QSettings, Qt, QTimer
from PySide6.QtGui import QFont, QScreen, QWindow
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsSimpleTextItem,
    QGraphicsTextItem,
    QGraphicsView,
    QMainWindow,
    QWidget,
)

BASE_FONT_POINT_SIZE = 11.0
MIN_FONT_POINT_SIZE = 9.5
MAX_FONT_POINT_SIZE = 15.0
REFERENCE_WINDOW_WIDTH = 1500.0
REFERENCE_WINDOW_HEIGHT = 920.0
REFERENCE_DPI = 96.0
REFERENCE_GRAPHICS_VIEW_WIDTH = 760.0
REFERENCE_GRAPHICS_VIEW_HEIGHT = 700.0
RESIZE_DEBOUNCE_MS = 75

_MIN_USER_SCALE = 0.75
_MAX_USER_SCALE = 1.50
_MIN_WINDOW_SCALE = 0.88
_MAX_WINDOW_SCALE = 1.18
_MIN_DPI_SCALE = 0.95
_MAX_DPI_SCALE = 1.12
_MIN_GRAPHICS_VIEW_SCALE = 0.86
_MAX_GRAPHICS_VIEW_SCALE = 1.12
_MIN_GRAPHICS_FONT_POINT_SIZE = 8.5
_MAX_GRAPHICS_FONT_POINT_SIZE = 16.0
_WIDGET_BASE_FONT_PROPERTY = "_scheimpflugBaseFontPointSize"
_GRAPHICS_BASE_FONT_DATA_ROLE = 0x534F
_SETTINGS_KEYS = ("fontScale", "ui/fontScale", "appearance/fontScale")
_RESPONSIVE_WINDOW_EVENT_TYPES = frozenset(
    {
        QEvent.Type.Resize,
        QEvent.Type.Show,
        QEvent.Type.WindowStateChange,
        QEvent.Type.ScreenChangeInternal,
        QEvent.Type.DevicePixelRatioChange,
    }
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return min(maximum, max(minimum, value))


def coerce_user_font_scale(value: Any) -> float:
    """Normalize legacy ratio/percentage settings to a safe multiplier."""

    if value is None or isinstance(value, bool):
        return 1.0
    try:
        text = str(value).strip()
        is_percentage = text.endswith("%")
        numeric = float(text.removesuffix("%").strip())
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(numeric) or numeric <= 0.0:
        return 1.0
    if is_percentage or numeric > 4.0:
        numeric /= 100.0
    return _clamp(numeric, _MIN_USER_SCALE, _MAX_USER_SCALE)


def read_user_font_scale(settings: QSettings | None = None) -> float:
    """Read the first supported fontScale key without modifying settings."""

    source = settings or QSettings("Scheimpflug OptiMeter", "Scheimpflug OptiMeter")
    for key in _SETTINGS_KEYS:
        if source.contains(key):
            return coerce_user_font_scale(source.value(key))
    return 1.0


def responsive_font_point_size(
    width: float,
    height: float,
    logical_dpi: float,
    user_scale: float = 1.0,
) -> float:
    """Return a continuous, clamped point size for the current UI metrics."""

    safe_width = max(1.0, float(width))
    safe_height = max(1.0, float(height))
    safe_dpi = logical_dpi if math.isfinite(logical_dpi) and logical_dpi > 0.0 else REFERENCE_DPI

    area_ratio = (safe_width * safe_height) / (REFERENCE_WINDOW_WIDTH * REFERENCE_WINDOW_HEIGHT)
    window_scale = _clamp(area_ratio**0.175, _MIN_WINDOW_SCALE, _MAX_WINDOW_SCALE)
    # Qt point fonts already account for DPI. This deliberately mild exponent only
    # compensates for dense screens without applying the display scale twice.
    dpi_scale = _clamp(
        (safe_dpi / REFERENCE_DPI) ** 0.18,
        _MIN_DPI_SCALE,
        _MAX_DPI_SCALE,
    )
    combined = window_scale * dpi_scale * coerce_user_font_scale(user_scale)
    return _clamp(
        BASE_FONT_POINT_SIZE * combined,
        MIN_FONT_POINT_SIZE,
        MAX_FONT_POINT_SIZE,
    )


def graphics_view_font_scale(width: float, height: float) -> float:
    """Return a mild local scale for 2D labels inside a graphics viewport."""

    safe_width = max(1.0, float(width))
    safe_height = max(1.0, float(height))
    area_ratio = (safe_width * safe_height) / (
        REFERENCE_GRAPHICS_VIEW_WIDTH * REFERENCE_GRAPHICS_VIEW_HEIGHT
    )
    return _clamp(
        area_ratio**0.16,
        _MIN_GRAPHICS_VIEW_SCALE,
        _MAX_GRAPHICS_VIEW_SCALE,
    )


def scaled_application_style(style: str, scale: float) -> str:
    """Scale the two deliberate type hierarchy sizes in the global style sheet."""

    return style.replace(
        "font-size: 18px;",
        f"font-size: {18.0 * scale:.2f}px;",
    ).replace(
        "font-size: 13px;",
        f"font-size: {13.0 * scale:.2f}px;",
    )


class ResponsiveTypography(QObject):
    """Debounced global font scaler for top-level window and DPI changes."""

    def __init__(
        self,
        application: QApplication,
        base_font: QFont,
        base_style: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent or application)
        self._application = application
        self._base_font = QFont(base_font)
        self._base_style = base_style
        self._user_scale = read_user_font_scale()
        self._applied_scale = 1.0
        self._pending_window: weakref.ReferenceType[QWidget | QWindow] | None = None
        self._monitored_screens: set[int] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(RESIZE_DEBOUNCE_MS)
        self._timer.timeout.connect(self.apply_pending)
        self._application.installEventFilter(self)
        self._application.screenAdded.connect(self._monitor_screen)
        self._application.screenRemoved.connect(lambda _screen: self.schedule())
        for screen in self._application.screens():
            self._monitor_screen(screen)

    @property
    def debounce_timer(self) -> QTimer:
        """Expose timer state for diagnostics and UI tests."""

        return self._timer

    @property
    def applied_scale(self) -> float:
        return self._applied_scale

    def refresh(
        self,
        *,
        base_font: QFont | None = None,
        base_style: str | None = None,
    ) -> None:
        """Reload user preference and apply it to the current top-level window."""

        if base_font is not None:
            self._base_font = QFont(base_font)
        if base_style is not None:
            self._base_style = base_style
        self._user_scale = read_user_font_scale()
        self.apply_pending()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        event_type = event.type()
        if event_type == QEvent.Type.Resize and isinstance(watched, QGraphicsView):
            self.schedule()
        elif (
            event_type in _RESPONSIVE_WINDOW_EVENT_TYPES
            and isinstance(watched, (QWidget, QWindow))
            and (isinstance(watched, QWindow) or watched.isWindow())
        ):
            self.schedule(watched)
        return super().eventFilter(watched, event)

    def schedule(self, window: QWidget | QWindow | None = None) -> None:
        """Restart the resize/DPI debounce window."""

        if window is not None:
            try:
                self._pending_window = weakref.ref(window)
            except TypeError:
                self._pending_window = None
        self._timer.start()

    def apply_pending(self) -> None:
        """Resolve current metrics and update all responsive fonts."""

        window = self._resolve_window()
        width, height, logical_dpi = self._window_metrics(window)
        self.apply_metrics(width, height, logical_dpi)

    def apply_metrics(self, width: float, height: float, logical_dpi: float) -> None:
        """Apply explicit metrics; useful for deterministic tests and tooling."""

        point_size = responsive_font_point_size(
            width,
            height,
            logical_dpi,
            self._user_scale,
        )
        scale = point_size / BASE_FONT_POINT_SIZE
        previous_scale = self._applied_scale
        self._capture_explicit_widget_fonts(previous_scale)

        font = QFont(self._base_font)
        font.setPointSizeF(point_size)
        self._application.setFont(font)
        self._application.setStyleSheet(scaled_application_style(self._base_style, scale))
        self._scale_explicit_widget_fonts(scale)
        self._scale_graphics_text(scale)

        self._applied_scale = scale
        self._application.setProperty("responsiveFontScale", scale)
        self._application.setProperty("responsiveFontPointSize", point_size)
        self._application.setProperty("responsiveUserFontScale", self._user_scale)

    def _resolve_window(self) -> QWidget | QWindow | None:
        pending: QWidget | QWindow | None = None
        if self._pending_window is not None:
            try:
                pending = self._pending_window()
            except RuntimeError:
                pending = None
            self._pending_window = None
        visible = [
            window
            for window in self._application.topLevelWidgets()
            if window.isVisible() and not window.isMinimized()
        ]
        main_windows = [window for window in visible if isinstance(window, QMainWindow)]
        candidates = main_windows or visible
        if candidates:
            return max(
                candidates,
                key=lambda window: window.width() * window.height(),
            )
        if isinstance(pending, QWindow) and pending.isVisible():
            return pending
        if isinstance(pending, QWidget) and pending.isVisible() and not pending.isMinimized():
            return pending
        return None

    def _window_metrics(
        self,
        window: QWidget | QWindow | None,
    ) -> tuple[float, float, float]:
        if window is None:
            width = REFERENCE_WINDOW_WIDTH
            height = REFERENCE_WINDOW_HEIGHT
            screen = self._application.primaryScreen()
        else:
            width = float(window.width())
            height = float(window.height())
            if isinstance(window, QWindow):
                screen = window.screen()
            else:
                handle = window.windowHandle()
                screen = handle.screen() if handle is not None else window.screen()
        logical_dpi = screen.logicalDotsPerInch() if screen is not None else REFERENCE_DPI
        return width, height, logical_dpi

    def _monitor_screen(self, screen: QScreen) -> None:
        identifier = id(screen)
        if identifier in self._monitored_screens:
            return
        self._monitored_screens.add(identifier)
        screen.logicalDotsPerInchChanged.connect(lambda _dpi: self.schedule())
        screen.geometryChanged.connect(lambda _geometry: self.schedule())

    def _capture_explicit_widget_fonts(self, previous_scale: float) -> None:
        divisor = previous_scale if previous_scale > 0.0 else 1.0
        for widget in self._application.allWidgets():
            if not widget.testAttribute(Qt.WidgetAttribute.WA_SetFont):
                continue
            if widget.property(_WIDGET_BASE_FONT_PROPERTY) is not None:
                continue
            point_size = widget.font().pointSizeF()
            if point_size > 0.0:
                widget.setProperty(_WIDGET_BASE_FONT_PROPERTY, point_size / divisor)

    def _scale_explicit_widget_fonts(self, scale: float) -> None:
        for widget in self._application.allWidgets():
            base = widget.property(_WIDGET_BASE_FONT_PROPERTY)
            if base is None:
                continue
            font = QFont(widget.font())
            font.setPointSizeF(float(base) * scale)
            widget.setFont(font)

    def _scale_graphics_text(self, scale: float) -> None:
        scenes: set[object] = set()
        for widget in self._application.allWidgets():
            if not isinstance(widget, QGraphicsView) or widget.scene() is None:
                continue
            scenes.add(widget.scene())
        for scene in scenes:
            visible_views = [view for view in scene.views() if view.isVisible()]
            if visible_views:
                largest_view = max(
                    visible_views,
                    key=lambda view: view.viewport().width() * view.viewport().height(),
                )
                viewport_scale = graphics_view_font_scale(
                    largest_view.viewport().width(),
                    largest_view.viewport().height(),
                )
            else:
                viewport_scale = 1.0
            for item in scene.items():
                if not isinstance(item, (QGraphicsSimpleTextItem, QGraphicsTextItem)):
                    continue
                base = item.data(_GRAPHICS_BASE_FONT_DATA_ROLE)
                if base is None:
                    base = item.font().pointSizeF()
                    if base <= 0.0:
                        continue
                    item.setData(_GRAPHICS_BASE_FONT_DATA_ROLE, base)
                font = QFont(item.font())
                font.setPointSizeF(
                    _clamp(
                        float(base) * scale * viewport_scale,
                        _MIN_GRAPHICS_FONT_POINT_SIZE,
                        _MAX_GRAPHICS_FONT_POINT_SIZE,
                    )
                )
                item.setFont(font)
        for scene in scenes:
            relayout = getattr(scene, "relayout_labels", None)
            if callable(relayout):
                relayout()
            scene.update()


__all__ = [
    "BASE_FONT_POINT_SIZE",
    "MAX_FONT_POINT_SIZE",
    "MIN_FONT_POINT_SIZE",
    "RESIZE_DEBOUNCE_MS",
    "ResponsiveTypography",
    "coerce_user_font_scale",
    "graphics_view_font_scale",
    "read_user_font_scale",
    "responsive_font_point_size",
    "scaled_application_style",
]
