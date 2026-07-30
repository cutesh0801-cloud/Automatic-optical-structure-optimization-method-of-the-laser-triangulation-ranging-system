from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QMainWindow, QWidget

from scheimpflug_optimeter.app import APPLICATION_STYLE, create_application
from scheimpflug_optimeter.typography import (
    BASE_FONT_POINT_SIZE,
    MAX_FONT_POINT_SIZE,
    MIN_FONT_POINT_SIZE,
    RESIZE_DEBOUNCE_MS,
    ResponsiveTypography,
    coerce_user_font_scale,
    graphics_view_font_scale,
    read_user_font_scale,
    responsive_font_point_size,
    scaled_application_style,
)
from scheimpflug_optimeter.ui.scene import OpticsGraphicsScene, OpticsGraphicsView


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 1.0),
        ("125%", 1.25),
        (125, 1.25),
        (1.2, 1.2),
        (0.1, 0.75),
        (900, 1.5),
        ("invalid", 1.0),
        (math.nan, 1.0),
    ],
)
def test_user_font_scale_accepts_legacy_formats_and_clamps(raw, expected):
    assert coerce_user_font_scale(raw) == pytest.approx(expected)


def test_existing_font_scale_setting_is_read_without_mutation(tmp_path):
    settings = QSettings(str(tmp_path / "typography.ini"), QSettings.Format.IniFormat)
    settings.setValue("ui/fontScale", "115%")
    settings.sync()

    assert read_user_font_scale(settings) == pytest.approx(1.15)
    assert settings.value("ui/fontScale") == "115%"


def test_responsive_formula_is_continuous_monotonic_and_clamped():
    small = responsive_font_point_size(1100, 700, 96)
    reference = responsive_font_point_size(1500, 920, 96)
    large = responsive_font_point_size(2200, 1400, 96)
    dense = responsive_font_point_size(2200, 1400, 192)

    assert MIN_FONT_POINT_SIZE <= small < reference < large < dense <= MAX_FONT_POINT_SIZE
    assert reference == pytest.approx(BASE_FONT_POINT_SIZE)
    assert responsive_font_point_size(100, 100, 72, 0.1) == MIN_FONT_POINT_SIZE
    assert responsive_font_point_size(8000, 5000, 400, 4.0) == MAX_FONT_POINT_SIZE
    assert responsive_font_point_size(1501, 920, 96) > reference


def test_type_hierarchy_scales_from_the_unmodified_style():
    scaled = scaled_application_style(APPLICATION_STYLE, 1.25)

    assert "font-size: 22.50px;" in scaled
    assert "font-size: 16.25px;" in scaled
    assert "font-size: 18px;" in APPLICATION_STYLE
    assert "font-size: 13px;" in APPLICATION_STYLE


def test_graphics_view_scale_uses_continuous_viewport_clamp():
    narrow = graphics_view_font_scale(360, 700)
    reference = graphics_view_font_scale(760, 700)
    wide = graphics_view_font_scale(1200, 900)

    assert 0.86 <= narrow < reference < wide <= 1.12
    assert reference == pytest.approx(1.0)


def test_resize_events_are_debounced_and_update_global_typography(qtbot):
    application = create_application([])
    manager = application._responsive_typography
    assert isinstance(manager, ResponsiveTypography)
    window = QWidget()
    qtbot.addWidget(window)
    window.resize(1100, 700)
    window.show()

    qtbot.waitUntil(lambda: not manager.debounce_timer.isActive(), timeout=2_000)
    small_size = application.font().pointSizeF()
    window.resize(1500, 920)
    window.resize(1900, 1100)
    assert manager.debounce_timer.isActive()
    assert manager.debounce_timer.interval() == RESIZE_DEBOUNCE_MS
    qtbot.waitUntil(lambda: not manager.debounce_timer.isActive(), timeout=2_000)
    large_size = application.font().pointSizeF()

    assert MIN_FONT_POINT_SIZE <= small_size < large_size <= MAX_FONT_POINT_SIZE
    assert application.property("responsiveFontScale") == pytest.approx(
        large_size / BASE_FONT_POINT_SIZE
    )
    assert application.property("responsiveFontPointSize") == pytest.approx(large_size)

    manager.apply_metrics(1500, 920, 96)


def test_small_tool_window_cannot_shrink_visible_main_window_typography(qtbot):
    application = create_application([])
    manager = application._responsive_typography
    main_window = QMainWindow()
    main_window.resize(1900, 1100)
    qtbot.addWidget(main_window)
    main_window.show()
    tool = QWidget(main_window, Qt.WindowType.Tool)
    tool.resize(280, 180)
    qtbot.addWidget(tool)
    tool.show()

    manager.schedule(tool)
    qtbot.waitUntil(lambda: not manager.debounce_timer.isActive(), timeout=2_000)

    assert manager._resolve_window() is main_window
    assert application.font().pointSizeF() == pytest.approx(
        responsive_font_point_size(main_window.width(), main_window.height(), 96),
        abs=0.15,
    )
    manager.apply_metrics(1500, 920, 96)


def test_graphics_labels_scale_with_largest_visible_view_without_compounding(qtbot):
    application = create_application([])
    manager = application._responsive_typography
    scene = OpticsGraphicsScene()
    narrow_view = OpticsGraphicsView(scene)
    narrow_view.resize(400, 520)
    qtbot.addWidget(narrow_view)
    narrow_view.show()
    qtbot.waitUntil(lambda: not manager.debounce_timer.isActive(), timeout=2_000)

    manager.apply_metrics(1100, 700, 96)
    downscaled = scene.labels["wd"].font().pointSizeF()
    assert manager.debounce_timer.isActive() is False

    wide_view = OpticsGraphicsView(scene)
    wide_view.resize(1100, 820)
    qtbot.addWidget(wide_view)
    wide_view.show()
    qtbot.waitUntil(lambda: not manager.debounce_timer.isActive(), timeout=2_000)
    manager.apply_metrics(1900, 1100, 144)
    upscaled = scene.labels["wd"].font().pointSizeF()
    manager.apply_metrics(1900, 1100, 144)
    repeated = scene.labels["wd"].font().pointSizeF()

    assert upscaled > downscaled
    assert repeated == pytest.approx(upscaled)
    wide_view.hide()
    manager.apply_metrics(1900, 1100, 144)
    assert scene.labels["wd"].font().pointSizeF() < upscaled

    narrow_view.resize(430, 520)
    assert manager.debounce_timer.isActive()
    manager.apply_metrics(1500, 920, 96)
