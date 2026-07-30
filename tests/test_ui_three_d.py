from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt

from scheimpflug_optimeter.ui.scene import Point2D, SceneSnapshot
from scheimpflug_optimeter.ui.three_d import ThreeDWidget


def snapshot() -> SceneSnapshot:
    lens_center = Point2D(60.0, 120.0)
    image_center = Point2D(75.0, 90.0)
    sensor_near = Point2D(78.535533906, 86.464466094)
    sensor_far = Point2D(71.464466094, 93.535533906)
    return SceneSnapshot(
        emitter=Point2D(0.0, 0.0),
        laser_endpoints=(Point2D(0.0, 0.0), Point2D(0.0, 210.0)),
        target_near=Point2D(0.0, 190.0),
        target_nominal=Point2D(0.0, 200.0),
        target_far=Point2D(0.0, 210.0),
        working_distance_endpoints=(Point2D(0.0, 0.0), Point2D(0.0, 200.0)),
        range_endpoints=(Point2D(0.0, 190.0), Point2D(0.0, 210.0)),
        lens_center=lens_center,
        lens_endpoints=(Point2D(51.05572809, 115.527864045), Point2D(68.94427191, 124.472135955)),
        image_center=image_center,
        sensor_endpoints=(sensor_near, sensor_far),
        proxy_sensor_endpoints=None,
        optical_axis_endpoints=(Point2D(0.0, 200.0), image_center),
        chief_rays=(
            (Point2D(0.0, 190.0), lens_center, sensor_near),
            (Point2D(0.0, 210.0), lens_center, sensor_far),
        ),
        scheimpflug_point=Point2D(42.0, 111.0),
        working_distance_mm=200.0,
        measurement_range_mm=20.0,
        w_mm=80.0,
        r_mm=45.0,
        lo_mm=100.0,
        fp_mm=33.541019662,
        focal_length_mm=25.0,
    )


def rendered_widget(qtbot, value: SceneSnapshot | None = None) -> ThreeDWidget:
    widget = ThreeDWidget()
    qtbot.addWidget(widget)
    if widget.canvas is None:
        pytest.skip("Matplotlib Qt backend is unavailable")
    widget.resize(1000, 720)
    widget.show()
    widget.set_geometry(
        value or snapshot(),
        alpha_deg=26.565051177,
        beta_deg=18.0,
        magnification=0.33541019662,
    )
    return widget


def test_3d_scene_exposes_equipment_planes_normals_lines_and_legend(qtbot):
    widget = rendered_widget(qtbot)

    expected_components = {
        "object_plane",
        "lens_plane",
        "ideal_focus_plane",
        "sensor_plane",
        "laser_plane",
        "camera_body",
        "sensor_body",
        "lens",
        "laser_emitter",
        "laser_beam",
        "optical_axis",
        "chief_rays",
        "scheimpflug_line",
        "hinge_line",
        "legend",
    }
    assert expected_components <= set(widget._components)
    for name in (
        "object_plane",
        "lens_plane",
        "ideal_focus_plane",
        "sensor_plane",
        "laser_plane",
    ):
        # One edged translucent face, one normal, and a leader-backed label.
        assert len(widget._components[name]) >= 4
    assert widget.axes.get_legend() is not None
    assert len(widget.axes.get_legend().get_texts()) == 7
    assert "γ=" in widget.axes.get_title()
    assert "δ=" in widget.axes.get_title()
    assert widget.axes.get_xlabel().startswith("X")
    assert widget.axes.get_ylabel().startswith("Y")
    assert widget.axes.get_zlabel().startswith("Z")

    spans = (
        widget.axes.get_xlim3d()[1] - widget.axes.get_xlim3d()[0],
        widget.axes.get_ylim3d()[1] - widget.axes.get_ylim3d()[0],
        widget.axes.get_zlim3d()[1] - widget.axes.get_zlim3d()[0],
    )
    assert spans[0] == pytest.approx(spans[1], rel=1e-12)
    assert spans[1] == pytest.approx(spans[2], rel=1e-12)
    assert widget.axes.elev == pytest.approx(24.0)
    assert widget.axes.azim == pytest.approx(-56.0)
    assert widget._view_mode == "head"
    assert widget.head_button.isChecked()
    assert widget._head_note.get_visible()


def test_3d_fit_and_default_view_controls_restore_readable_state(qtbot):
    widget = rendered_widget(qtbot)
    head_span = widget.axes.get_xlim3d()[1] - widget.axes.get_xlim3d()[0]

    widget.axes.set_xlim3d(-1.0, 1.0)
    widget.axes.set_ylim3d(-2.0, 2.0)
    widget.axes.set_zlim3d(-3.0, 3.0)
    qtbot.mouseClick(widget.fit_button, Qt.MouseButton.LeftButton)
    spans = (
        widget.axes.get_xlim3d()[1] - widget.axes.get_xlim3d()[0],
        widget.axes.get_ylim3d()[1] - widget.axes.get_ylim3d()[0],
        widget.axes.get_zlim3d()[1] - widget.axes.get_zlim3d()[0],
    )
    assert spans[0] > 100.0
    assert spans[0] == pytest.approx(spans[1], rel=1e-12)
    assert spans[1] == pytest.approx(spans[2], rel=1e-12)
    assert spans[0] > head_span
    assert widget._view_mode == "full"
    assert widget.fit_button.isChecked()
    assert not widget._head_note.get_visible()

    qtbot.mouseClick(widget.head_button, Qt.MouseButton.LeftButton)
    restored_head_span = widget.axes.get_xlim3d()[1] - widget.axes.get_xlim3d()[0]
    assert restored_head_span == pytest.approx(head_span, rel=1e-12)
    assert widget._view_mode == "head"
    assert widget._head_note.get_visible()

    widget.axes.view_init(elev=2.0, azim=3.0)
    qtbot.mouseClick(widget.view_button, Qt.MouseButton.LeftButton)
    assert widget.axes.elev == pytest.approx(24.0)
    assert widget.axes.azim == pytest.approx(-56.0)

    widget.set_geometry(None, alpha_deg=0.0, beta_deg=0.0)
    assert not widget.head_button.isEnabled()
    assert not widget.fit_button.isEnabled()
    assert not widget.view_button.isEnabled()


def test_remote_workbook_beam_is_annotated_without_destroying_fit(qtbot):
    value = replace(
        snapshot(),
        laser_endpoints=(Point2D(0.0, 0.0), Point2D(0.0, -5000.0)),
        measurement_range_mm=5000.0,
        workbook_mode=True,
    )
    widget = rendered_widget(qtbot, value)

    assert widget._snapshot is value
    assert widget._beam_was_clipped
    assert len(widget._components["laser_beam"]) == 3
    z_span = widget.axes.get_zlim3d()[1] - widget.axes.get_zlim3d()[0]
    assert z_span < 1000.0
