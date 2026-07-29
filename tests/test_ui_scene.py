from __future__ import annotations

import math

from PySide6.QtCore import Qt

from scheimpflug_optimeter.ui.scene import (
    OpticsGraphicsScene,
    Point2D,
    SceneSnapshot,
)
from scheimpflug_optimeter.ui.three_d import full_focus_angles


def snapshot(*, valid: bool = True) -> SceneSnapshot:
    emitter = Point2D(0.0, 0.0)
    near = Point2D(0.0, 197.5)
    nominal = Point2D(0.0, 200.0)
    far = Point2D(0.0, 202.5)
    lens = Point2D(30.0, 150.0)
    image = Point2D(38.0, 137.0)
    sensor_near = Point2D(35.5, 135.5)
    sensor_far = Point2D(40.5, 138.5)
    return SceneSnapshot(
        emitter=emitter,
        laser_endpoints=(emitter, far),
        target_near=near,
        target_nominal=nominal,
        target_far=far,
        working_distance_endpoints=(emitter, nominal),
        range_endpoints=(near, far),
        lens_center=lens,
        lens_endpoints=(Point2D(25.0, 147.0), Point2D(35.0, 153.0)),
        image_center=image,
        sensor_endpoints=(sensor_near, sensor_far),
        proxy_sensor_endpoints=(
            Point2D(35.0, 135.2),
            Point2D(41.0, 138.8),
        ),
        optical_axis_endpoints=(nominal, image),
        chief_rays=(
            (near, lens, sensor_near),
            (far, lens, sensor_far),
        ),
        scheimpflug_point=Point2D(1000.0, -2000.0),
        working_distance_mm=200.0,
        measurement_range_mm=5.0,
        w_mm=42.0,
        r_mm=63.0,
        lo_mm=58.3,
        fp_mm=15.3,
        focal_length_mm=12.0,
        valid=valid,
        warnings=() if valid else ("센서 범위를 벗어났습니다.",),
    )


def test_scene_updates_reusable_items_and_required_labels(qtbot, tmp_path):
    scene = OpticsGraphicsScene()
    line_ids = {
        name: id(getattr(scene, name))
        for name in (
            "laser_line",
            "wd_dimension",
            "target_near_line",
            "target_nominal_line",
            "target_far_line",
            "lens_line",
            "optical_axis_line",
            "sensor_line",
            "near_ray_before",
            "far_ray_before",
        )
    }

    scene.set_snapshot(snapshot())
    scene.set_snapshot(snapshot())

    assert {name: id(getattr(scene, name)) for name in line_ids} == line_ids
    texts = " ".join(label.text() for label in scene.labels.values())
    assert "레이저 조사 직선" in texts
    assert "WD d" in texts
    assert "근거리" in texts
    assert "기준거리" in texts
    assert "원거리" in texts
    assert "렌즈 평면" in texts
    assert "실제 이미지/센서 평면" in texts
    assert "Scheimpflug 교점" in texts
    assert "W =" in texts
    assert "R =" in texts
    assert "↗" in scene.labels["scheimpflug"].text()
    assert scene.optical_head_rect().height() < scene.sceneRect().height()

    png = tmp_path / "layout.png"
    svg = tmp_path / "layout.svg"
    assert scene.export_png(png).exists()
    assert scene.export_svg(svg).exists()
    assert png.stat().st_size > 0
    assert "<svg" in svg.read_text(encoding="utf-8")


def test_invalid_scene_is_red_dashed_and_stale_scene_can_be_hidden(qtbot):
    scene = OpticsGraphicsScene()
    scene.set_snapshot(snapshot(valid=False))

    assert scene.invalid_overlay.isVisible()
    assert scene.labels["invalid"].isVisible()
    assert "센서 범위" in scene.labels["invalid"].text()
    assert scene.sensor_line.pen().color() == scene.COLORS["invalid"]
    assert scene.sensor_line.pen().style() == Qt.PenStyle.DashLine

    scene.set_snapshot(snapshot(valid=True))
    assert not scene.invalid_overlay.isVisible()
    assert scene.sensor_line.pen().color() == scene.COLORS["sensor"]
    assert scene.sensor_line.pen().style() == Qt.PenStyle.SolidLine

    scene.set_invalid_message("계산 분모가 0에 가깝습니다.")
    assert scene._snapshot is None
    assert not scene.sensor_line.isVisible()
    assert scene.labels["invalid"].isVisible()


def test_exact_full_focus_angles_match_equations():
    magnification = 0.42
    alpha_deg = 14.0
    beta_deg = 8.0

    gamma_deg, delta_deg = full_focus_angles(
        magnification,
        alpha_deg,
        beta_deg,
    )

    alpha = math.radians(alpha_deg)
    gamma = math.radians(gamma_deg)
    delta = math.radians(delta_deg)
    assert math.tan(gamma) == pytest_approx(magnification * math.tan(alpha))
    assert math.tan(delta) == pytest_approx(
        magnification * (math.cos(gamma) / math.cos(alpha)) * math.tan(math.radians(beta_deg))
    )


def pytest_approx(value):
    # Local import keeps this module's production-like imports minimal.
    import pytest

    return pytest.approx(value, rel=1e-12, abs=1e-12)
