from __future__ import annotations

import subprocess
import sys
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
    widget.resize(1000, 720)
    widget.show()
    widget.set_geometry(value or snapshot())
    if widget.canvas is None:
        pytest.skip("Matplotlib Qt backend is unavailable")
    return widget


def visible_canvas_text(widget: ThreeDWidget) -> list[str]:
    from matplotlib.text import Text

    return [
        artist.get_text()
        for artist in widget.axes.findobj(Text)
        if artist.get_visible() and artist.get_text().strip()
    ]


def test_3d_import_does_not_eagerly_load_numerical_or_plotting_stacks():
    script = """
import sys
import scheimpflug_optimeter.ui.three_d
assert "numpy" not in sys.modules
assert "scipy" not in sys.modules
assert "matplotlib" not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_3d_scene_uses_shapes_without_canvas_text(qtbot):
    widget = rendered_widget(qtbot)
    widget.canvas.draw()

    expected_components = {
        "target_plane",
        "lens_plane",
        "sensor_plane",
        "camera_body",
        "sensor_body",
        "lens",
        "laser_emitter",
        "laser_beam",
        "optical_axis",
        "chief_rays",
        "scheimpflug_line",
    }
    assert expected_components <= set(widget._components)
    assert {
        "laser_plane",
        "ideal_focus_plane",
        "hinge_line",
        "object_plane",
    }.isdisjoint(widget._components)
    for name in ("target_plane", "lens_plane", "sensor_plane"):
        # Each plane remains identifiable by an edged translucent face and normal.
        assert len(widget._components[name]) >= 2
    assert widget.axes.get_legend() is None
    assert visible_canvas_text(widget) == []
    assert widget.axes.get_xlabel() == ""
    assert widget.axes.get_ylabel() == ""
    assert widget.axes.get_zlabel() == ""
    assert all(not label.get_text() for label in widget.axes.get_xticklabels())
    assert all(not label.get_text() for label in widget.axes.get_yticklabels())
    assert all(not label.get_text() for label in widget.axes.get_zticklabels())
    assert "WD=" in widget.status_card.text()
    assert "γ=" not in widget.status_card.text()
    assert "δ=" not in widget.status_card.text()
    assert "레이저 평면" not in widget.scene_key.text()
    assert "Laser plane" not in widget.scene_key.text()
    assert "레이저 중심 광선" in widget.scene_key.text()
    assert widget.scene_key.accessibleDescription()
    assert (
        widget._components["laser_beam"][0].get_color()
        != widget._components["scheimpflug_line"][0].get_color()
    )

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
    assert any(term in widget.status_card.text() for term in ("광학 헤드", "Optical head"))


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
    assert any(term in widget.status_card.text() for term in ("전체 구조", "Full assembly"))

    qtbot.mouseClick(widget.head_button, Qt.MouseButton.LeftButton)
    restored_head_span = widget.axes.get_xlim3d()[1] - widget.axes.get_xlim3d()[0]
    assert restored_head_span == pytest.approx(head_span, rel=1e-12)
    assert widget._view_mode == "head"
    assert any(term in widget.status_card.text() for term in ("광학 헤드", "Optical head"))

    widget.axes.view_init(elev=2.0, azim=3.0)
    qtbot.mouseClick(widget.view_button, Qt.MouseButton.LeftButton)
    assert widget.axes.elev == pytest.approx(24.0)
    assert widget.axes.azim == pytest.approx(-56.0)

    widget.set_geometry(None)
    assert not widget.head_button.isEnabled()
    assert not widget.fit_button.isEnabled()
    assert not widget.view_button.isEnabled()
    widget.canvas.draw()
    assert visible_canvas_text(widget) == []
    assert any(
        term in widget.status_card.text()
        for term in ("설계 입력을 기다리는 중", "Waiting for a valid design")
    )


def test_remote_workbook_beam_clipping_moves_detail_to_status_card(qtbot):
    value = replace(
        snapshot(),
        laser_endpoints=(Point2D(0.0, 0.0), Point2D(0.0, -5000.0)),
        measurement_range_mm=5000.0,
        workbook_mode=True,
    )
    widget = rendered_widget(qtbot, value)

    assert widget._snapshot is value
    assert widget._beam_was_clipped
    assert len(widget._components["laser_beam"]) == 1
    assert "Z=-5000.0 mm" in widget.status_card.text()
    widget.canvas.draw()
    assert visible_canvas_text(widget) == []
    z_span = widget.axes.get_zlim3d()[1] - widget.axes.get_zlim3d()[0]
    assert z_span < 1000.0
