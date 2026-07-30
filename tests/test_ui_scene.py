from __future__ import annotations

import math
from dataclasses import replace
from time import perf_counter

import pytest
from PySide6.QtCore import QLineF, QPointF, QRectF, Qt

from scheimpflug_optimeter.ui.scene import (
    LensMechanicalSnapshot,
    OpticsGraphicsScene,
    OpticsGraphicsView,
    Point2D,
    SceneSnapshot,
    build_lens_body_section,
)


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
        alpha_deg=30.0,
        beta_deg=45.0,
        baseline_mm=38.0,
        v_mm=200.0,
        object_principal_plane=lens,
        image_principal_plane=lens,
        principal_planes_coincident=True,
        valid=valid,
        warnings=() if valid else ("센서 범위를 벗어났습니다.",),
    )


def lens_mechanics() -> LensMechanicalSnapshot:
    return LensMechanicalSnapshot(
        lens_id="edmund-58-206",
        sku="58-206",
        drawing_id="DWG 58206",
        overall_length_mm=20.68,
        outer_diameter_mm=14.0,
        front_housing_length_mm=7.60,
        threaded_section_length_mm=13.08,
        thread_major_diameter_mm=12.0,
        first_surface_recess_mm=0.30,
        object_principal_from_first_surface_mm=5.57,
        image_principal_from_last_surface_mm=-12.71,
        supplier_verified=True,
    )


def workbook_snapshot() -> SceneSnapshot:
    """A dense workbook-style scene with both remote intersections."""

    point = Point2D
    return replace(
        snapshot(),
        emitter=point(0.0, 0.0),
        laser_endpoints=(point(0.0, 0.0), point(0.0, 205.0)),
        target_near=point(0.0, 205.0),
        target_nominal=point(0.0, 205.0),
        target_far=point(0.0, -1165.0),
        working_distance_endpoints=(point(0.0, 0.0), point(0.0, 205.0)),
        range_endpoints=(point(0.0, 205.0), point(0.0, -1165.0)),
        lens_center=point(55.0, 190.0),
        lens_endpoints=(point(51.0, 184.0), point(59.0, 196.0)),
        image_center=point(67.0, 184.0),
        sensor_endpoints=(point(64.0, 180.0), point(70.0, 188.0)),
        proxy_sensor_endpoints=(point(63.0, 179.0), point(71.0, 189.0)),
        optical_axis_endpoints=(point(0.0, 205.0), point(67.0, 184.0)),
        chief_rays=(
            (
                point(0.0, 205.0),
                point(55.0, 190.0),
                point(64.0, 180.0),
            ),
            (
                point(0.0, -1165.0),
                point(55.0, 190.0),
                point(70.0, 188.0),
            ),
        ),
        scheimpflug_point=point(-1200.0, 900.0),
        working_distance_mm=205.0,
        measurement_range_mm=1370.0,
        w_mm=70.0,
        r_mm=80.0,
        lo_mm=57.0,
        fp_mm=14.0,
        focal_length_mm=11.2,
        alpha_deg=14.27,
        beta_deg=75.73,
        baseline_mm=52.13954828,
        v_mm=205.0,
        object_principal_plane=point(55.0, 190.0),
        image_principal_plane=point(55.0, 190.0),
        principal_planes_coincident=True,
        workbook_mode=True,
    )


def fitted_scene(qtbot, value: SceneSnapshot):
    scene = OpticsGraphicsScene()
    view = OpticsGraphicsView(scene)
    qtbot.addWidget(view)
    view.resize(1000, 720)
    view.show()
    qtbot.wait(1)
    scene.set_snapshot(value)
    view.fit_scene()
    scene.relayout_labels()
    return scene, view


def assert_callouts_do_not_cover_each_other_or_key_lines(scene, view):
    rects = scene.visible_callout_rects()
    assert set(rects) == set(scene.PRIMARY_CALLOUTS)
    viewport = view.viewport().rect().adjusted(5, 5, -5, -5)
    for name, rect in rects.items():
        assert viewport.contains(rect.toAlignedRect()), name

    names = tuple(rects)
    for index, first_name in enumerate(names):
        for second_name in names[index + 1 :]:
            intersection = rects[first_name].intersected(rects[second_name])
            assert intersection.width() <= 0.1 or intersection.height() <= 0.1, (
                first_name,
                second_name,
                intersection,
            )

    transform, _, _ = scene._layout_transform()
    obstacles = scene._geometry_obstacles(transform)
    fixed_obstacles = scene._fixed_item_obstacles(transform)
    for name, rect in rects.items():
        assert not any(
            scene._line_intersects_rect(line, rect.adjusted(-2.0, -2.0, 2.0, 2.0))
            for line in obstacles
        ), name
        assert not any(rect.intersects(obstacle) for obstacle in fixed_obstacles), name


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
    assert "WD d" in texts
    assert "측정 범위 S" in texts
    assert "렌즈 평면" in texts
    assert "요청 범위의 설계 결상 구간" in texts
    assert "Scheimpflug" in texts
    assert "광학 외곽 W" in texts
    assert "후방 외곽 R" in texts
    assert "↓" in scene.labels["scheimpflug"].text()
    assert "아래 계속" in scene.labels["scheimpflug"].text()
    assert set(scene._callout_specs) == set(scene.PRIMARY_CALLOUTS)
    assert set(scene.labels) == {*scene.PRIMARY_CALLOUTS, "invalid"}
    assert scene.scheimpflug_remote_arrow.isVisible()
    assert not scene.scheimpflug_marker.isVisible()
    assert scene.proxy_sensor_line.isVisible()
    assert "I±L/2" in scene.proxy_sensor_line.toolTip()
    assert "lo = 58.300 mm" in scene.labels["lens"].toolTip()
    assert "fp = 15.300 mm" in scene.labels["lens"].toolTip()
    assert "f = 12.000 mm" in scene.labels["lens"].toolTip()
    for glyph in (
        scene.laser_emitter_glyph,
        scene.lens_glyph,
        scene.camera_body_glyph,
    ):
        assert glyph.isVisible()
        assert "개념 표시" in glyph.toolTip()
    assert scene.principal_h_marker.isVisible()
    assert not scene.principal_h_prime_marker.isVisible()
    assert "H′" in scene.principal_h_marker.toolTip()
    assert "α=30.000°" in scene.labels["lens"].text()
    assert "β=45.000°" in scene.labels["lens"].text()
    assert all(
        arrow.isVisible() and arrow.line().length() > 0.0
        for arrows in scene.dimension_arrowheads.values()
        for arrow in arrows
    )
    assert all(scene.label_backgrounds[name].isVisible() for name in scene._callout_specs)
    assert any(leader.isVisible() for leader in scene.label_leaders.values())
    assert scene.optical_head_rect().height() < scene.sceneRect().height()

    png = tmp_path / "layout.png"
    svg = tmp_path / "layout.svg"
    assert scene.export_png(png).exists()
    assert scene.export_svg(svg).exists()
    assert png.stat().st_size > 0
    assert "<svg" in svg.read_text(encoding="utf-8")


def test_verified_lens_body_is_back_calculated_from_h_without_guessing_h_prime():
    value = replace(snapshot(), lens_mechanics=lens_mechanics())

    section = build_lens_body_section(value)

    assert section is not None
    front_to_h = math.hypot(
        section.object_principal_plane.x_mm - section.front_housing.x_mm,
        section.object_principal_plane.z_mm - section.front_housing.z_mm,
    )
    body_length = math.hypot(
        section.rear_housing.x_mm - section.front_housing.x_mm,
        section.rear_housing.z_mm - section.front_housing.z_mm,
    )
    assert front_to_h == pytest.approx(5.87)
    assert body_length == pytest.approx(20.68)

    scene = OpticsGraphicsScene()
    scene.set_snapshot(value)
    assert "#58-206 외형" in scene.labels["lens"].text()
    assert "DWG 58206" in scene.lens_glyph.toolTip()
    assert "역산" in scene.lens_glyph.toolTip()
    assert "H′ 공급사 값" in scene.labels["lens"].toolTip()


def test_invalid_scene_is_red_dashed_and_stale_scene_can_be_hidden(qtbot):
    scene = OpticsGraphicsScene()
    scene.set_snapshot(snapshot(valid=False))

    assert scene.invalid_overlay.isVisible()
    assert scene.labels["invalid"].isVisible()
    assert "센서 범위" in scene.labels["invalid"].text()
    assert scene.sensor_line.pen().color() == scene.COLORS["invalid"]
    assert scene.sensor_line.pen().style() == Qt.PenStyle.DashLine
    assert scene.sensor_line.pen().isCosmetic()
    assert scene.sensor_plane_marker.pen().color() == scene.COLORS["invalid"]
    assert scene.sensor_plane_marker.pen().isCosmetic()

    scene.set_snapshot(snapshot(valid=True))
    assert not scene.invalid_overlay.isVisible()
    assert scene.sensor_line.pen().color() == scene.COLORS["sensor"]
    assert scene.sensor_line.pen().style() == Qt.PenStyle.SolidLine

    scene.set_invalid_message("계산 분모가 0에 가깝습니다.")
    assert scene._snapshot is None
    assert not scene.sensor_line.isVisible()
    assert scene.labels["invalid"].isVisible()


def test_callouts_avoid_collisions_and_key_lines_in_two_representative_scenes(qtbot):
    for value in (snapshot(), workbook_snapshot()):
        scene, view = fitted_scene(qtbot, value)
        assert_callouts_do_not_cover_each_other_or_key_lines(scene, view)


def test_clean_callout_candidate_does_not_run_unused_fallback_scoring(monkeypatch):
    scene = OpticsGraphicsScene()
    first = QRectF(20.0, 20.0, 40.0, 18.0)
    second = QRectF(70.0, 20.0, 40.0, 18.0)
    calls = []

    def score(candidate, **_):
        calls.append(candidate)
        return 0.0 if candidate == second else 1.0

    monkeypatch.setattr(scene, "_callout_score", score)
    selected = scene._select_callout_rect(
        (first, second),
        anchor=QPointF(0.0, 0.0),
        viewport_rect=QRectF(0.0, 0.0, 200.0, 100.0),
        placed=[],
        obstacles=(),
    )
    assert selected == first
    assert calls == []

    selected = scene._select_callout_rect(
        (first, second),
        anchor=QPointF(0.0, 0.0),
        viewport_rect=QRectF(0.0, 0.0, 10.0, 10.0),
        placed=[],
        obstacles=(),
    )
    assert selected == second
    assert calls == [first, second]


def test_line_rectangle_broad_phase_preserves_intersection_results():
    rect = QRectF(10.0, 10.0, 20.0, 20.0)

    assert OpticsGraphicsScene._line_intersects_rect(
        QLineF(0.0, 20.0, 40.0, 20.0),
        rect,
    )
    assert OpticsGraphicsScene._line_intersects_rect(
        QLineF(20.0, 0.0, 20.0, 40.0),
        rect,
    )
    assert OpticsGraphicsScene._line_intersects_rect(
        QLineF(0.0, 0.0, 10.0, 10.0),
        rect,
    )
    assert not OpticsGraphicsScene._line_intersects_rect(
        QLineF(-40.0, -30.0, -10.0, -5.0),
        rect,
    )


def test_remote_geometry_is_ray_clipped_without_expanding_the_scene(qtbot):
    scene, _ = fitted_scene(qtbot, workbook_snapshot())

    assert scene.sceneRect().height() < 500.0
    assert scene.range_remote_arrow.isVisible()
    assert scene.scheimpflug_remote_arrow.isVisible()
    assert not scene.proxy_sensor_line.isVisible()
    assert "기준 거리 V = 205.000 mm" in scene.labels["wd"].text()
    assert "워킹 디스턴스 d = 205.000 mm" in scene.labels["wd"].text()
    assert "R=V−d" in scene.labels["wd"].toolTip()
    assert "광선 교차 거리 |s|" in scene.labels["range"].text()
    assert "아래 계속 ↓" in scene.labels["range"].text()
    assert "왼쪽 계속 ←" in scene.labels["scheimpflug"].text()
    assert scene.labels["sensor"].text() == "CMOS · 입력 이미지 구간 L"
    assert "CMOS 틸트 입력이 아닙니다" in scene.labels["sensor"].toolTip()
    assert "b = 52.140 mm" in scene.labels["w"].text()
    assert "W=b+L/2" in scene.labels["w"].text()
    assert "R=V−d" in scene.labels["r"].text()
    assert "-1165.000 mm" in scene.labels["range"].toolTip()
    assert "-1200.000 mm" in scene.labels["scheimpflug"].toolTip()
    for arrow in (scene.range_remote_arrow, scene.scheimpflug_remote_arrow):
        point = arrow.scenePos()
        rect = scene.sceneRect()
        distance_to_boundary = min(
            abs(point.x() - rect.left()),
            abs(point.x() - rect.right()),
            abs(point.y() - rect.top()),
            abs(point.y() - rect.bottom()),
        )
        assert distance_to_boundary < 1e-6

    local_intersection = Point2D(58.0, 176.0)
    scene.set_snapshot(
        replace(snapshot(), scheimpflug_point=local_intersection),
    )
    assert scene.scheimpflug_marker.isVisible()
    assert not scene.scheimpflug_remote_arrow.isVisible()
    assert scene.scheimpflug_marker.pos().x() == pytest_approx(local_intersection.x_mm)
    assert scene.scheimpflug_marker.pos().y() == pytest_approx(-local_intersection.z_mm)


def test_remote_classification_uses_local_working_area_in_canonical_mode(qtbot):
    value = snapshot()
    remote = Point2D(0.0, -5000.0)
    far_ray = value.chief_rays[1]
    scene, view = fitted_scene(
        qtbot,
        replace(
            value,
            laser_endpoints=(value.emitter, remote),
            target_far=remote,
            range_endpoints=(value.target_nominal, remote),
            chief_rays=(
                value.chief_rays[0],
                (remote, far_ray[1], far_ray[2]),
            ),
            measurement_range_mm=5200.0,
        ),
    )

    assert scene.sceneRect().height() < 500.0
    assert scene.range_remote_arrow.isVisible()
    assert "아래 계속 ↓" in scene.labels["range"].text()
    lens_device = view.mapFromScene(QPointF(value.lens_center.x_mm, -value.lens_center.z_mm))
    sensor_device = view.mapFromScene(QPointF(value.image_center.x_mm, -value.image_center.z_mm))
    assert QLineF(lens_device, sensor_device).length() > 20.0


def test_remote_direction_text_follows_the_actual_vector():
    origin = Point2D(10.0, 20.0)
    cases = (
        (Point2D(100.0, 21.0), ("→", "오른쪽")),
        (Point2D(-100.0, 21.0), ("←", "왼쪽")),
        (Point2D(11.0, 100.0), ("↑", "위")),
        (Point2D(11.0, -100.0), ("↓", "아래")),
    )
    for target, expected in cases:
        assert OpticsGraphicsScene._remote_direction(origin, target) == expected


def test_zoomed_out_key_geometry_keeps_minimum_screen_presence(qtbot):
    scene, view = fitted_scene(qtbot, snapshot())
    physical_lines = {
        "laser": QLineF(scene.laser_line.line()),
        "lens": QLineF(scene.lens_line.line()),
        "sensor": QLineF(scene.sensor_line.line()),
    }

    def device_rect(item):
        transform = item.deviceTransform(view.viewportTransform())
        return transform.mapRect(item.boundingRect())

    glyph_rects_before = {
        name: device_rect(getattr(scene, name))
        for name in (
            "laser_emitter_glyph",
            "lens_glyph",
            "camera_body_glyph",
        )
    }
    view.resetTransform()
    view.scale(0.02, 0.02)
    scene.relayout_labels()

    def device_line_length(item):
        transform = item.deviceTransform(view.viewportTransform())
        return QLineF(
            transform.map(item.line().p1()),
            transform.map(item.line().p2()),
        ).length()

    for item in (scene.laser_line, scene.lens_line, scene.sensor_line):
        assert item.pen().isCosmetic()
    assert device_line_length(scene.lens_line) < 1.0
    assert device_line_length(scene.sensor_line) < 1.0
    assert device_line_length(scene.lens_plane_marker) == pytest_approx(20.0)
    assert device_line_length(scene.sensor_plane_marker) == pytest_approx(24.0)
    for name, before in glyph_rects_before.items():
        after = device_rect(getattr(scene, name))
        assert after.width() == pytest_approx(before.width())
        assert after.height() == pytest_approx(before.height())

    emitter_transform = scene.emitter_marker.deviceTransform(view.viewportTransform())
    emitter_rect = emitter_transform.mapRect(scene.emitter_marker.rect())
    assert emitter_rect.width() == pytest_approx(10.0)
    assert emitter_rect.height() == pytest_approx(10.0)
    assert scene.near_ray_before.zValue() < scene.laser_line.zValue()
    assert scene.laser_line.zValue() < scene.lens_line.zValue()
    assert scene.lens_line.zValue() < scene.sensor_line.zValue()
    assert scene.sensor_line.zValue() < scene.sensor_plane_marker.zValue()
    assert scene.laser_line.line() == physical_lines["laser"]
    assert scene.lens_line.line() == physical_lines["lens"]
    assert scene.sensor_line.line() == physical_lines["sensor"]


def test_equal_scale_minimum_size_and_scroll_relayout(qtbot):
    class CountingScene(OpticsGraphicsScene):
        def __init__(self):
            self.relayout_count = 0
            super().__init__()

        def relayout_labels(self):
            self.relayout_count += 1
            super().relayout_labels()

    scene = CountingScene()
    view = OpticsGraphicsView(scene)
    qtbot.addWidget(view)
    view.resize(1000, 720)
    view.show()
    qtbot.wait(1)
    scene.set_snapshot(snapshot())
    view.fit_scene()

    transform = view.transform()
    assert abs(transform.m11()) == pytest_approx(abs(transform.m22()))
    assert transform.m12() == pytest_approx(0.0)
    assert transform.m21() == pytest_approx(0.0)
    assert view.minimumWidth() == 400
    assert view.minimumHeight() == 360
    assert all(scene.labels[name].font().pointSizeF() >= 11.5 for name in scene._callout_names)

    view.scale(1.2, 1.2)
    qtbot.wait(1)
    scene.relayout_labels()
    before_count = scene.relayout_count
    before_rects = scene.visible_callout_rects()
    scrollbar = view.verticalScrollBar()
    assert scrollbar.minimum() < scrollbar.maximum()
    target = max(scrollbar.minimum(), scrollbar.value() - 40)
    assert target != scrollbar.value()
    geometry_before = scene.laser_line.line()
    scrollbar.setValue(target)
    qtbot.waitUntil(lambda: scene.relayout_count > before_count)
    after_rects = scene.visible_callout_rects()

    assert geometry_before == scene.laser_line.line()
    assert any(
        abs(after_rects[name].y() - before_rects[name].y()) > 0.1
        for name in before_rects.keys() & after_rects.keys()
    )
    names = tuple(after_rects)
    assert not any(
        after_rects[first].intersects(after_rects[second])
        for index, first in enumerate(names)
        for second in names[index + 1 :]
    )


def test_scene_snapshot_update_p95_is_below_100_ms(qtbot):
    scene, _ = fitted_scene(qtbot, snapshot())
    for _ in range(3):
        scene.set_snapshot(snapshot())

    durations = []
    for _ in range(30):
        started = perf_counter()
        scene.set_snapshot(snapshot())
        durations.append(perf_counter() - started)

    percentile_95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert percentile_95 < 0.100


def pytest_approx(value):
    # Local import keeps this module's production-like imports minimal.
    import pytest

    return pytest.approx(value, rel=1e-12, abs=1e-12)
