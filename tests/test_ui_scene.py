from __future__ import annotations

from dataclasses import replace
from time import perf_counter

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt

from scheimpflug_optimeter.ui.scene import (
    OpticsGraphicsScene,
    OpticsGraphicsView,
    Point2D,
    SceneSnapshot,
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
        valid=valid,
        warnings=() if valid else ("센서 범위를 벗어났습니다.",),
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
        range_label="레이저 교차 거리 s",
        target_nominal_label="워크북 기준면",
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
    assert len(rects) >= 12
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
    for name, rect in rects.items():
        assert not any(
            scene._line_intersects_rect(line, rect.adjusted(-2.0, -2.0, 2.0, 2.0))
            for line in obstacles
        ), name


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
    assert "범례" in scene.labels["legend"].text()
    assert scene.scheimpflug_remote_arrow.isVisible()
    assert not scene.scheimpflug_marker.isVisible()
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


def test_zoomed_out_key_geometry_keeps_minimum_screen_presence(qtbot):
    scene, view = fitted_scene(qtbot, snapshot())
    physical_lines = {
        "laser": QLineF(scene.laser_line.line()),
        "lens": QLineF(scene.lens_line.line()),
        "sensor": QLineF(scene.sensor_line.line()),
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
    assert all(scene.labels[name].font().pointSizeF() >= 10.5 for name in scene._callout_names)

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
