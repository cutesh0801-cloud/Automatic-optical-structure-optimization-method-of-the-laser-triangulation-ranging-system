from __future__ import annotations

import json

import cv2
import numpy as np
import pytest
from PySide6.QtCore import Qt

from scheimpflug_optimeter.calibration import CalibrationGate, IntrinsicCalibration
from scheimpflug_optimeter.camera import MockCameraBackend
from scheimpflug_optimeter.ui import calibration_tab
from scheimpflug_optimeter.ui.calibration_tab import CalibrationMeasurementWidget


def _small_mock_widget(qtbot) -> CalibrationMeasurementWidget:
    widget = CalibrationMeasurementWidget()
    qtbot.addWidget(widget)
    widget.resolution_width_spin.setValue(160)
    widget.resolution_height_spin.setValue(120)
    widget.roi_width_spin.setValue(160)
    widget.roi_height_spin.setValue(120)
    return widget


def test_mock_calibration_measurement_and_export(qtbot, tmp_path) -> None:
    widget = _small_mock_widget(qtbot)
    calibration_spy: list[object] = []
    measurement_spy: list[object] = []
    widget.calibration_ready.connect(calibration_spy.append)
    widget.measurement_ready.connect(measurement_spy.append)

    qtbot.mouseClick(widget.mock_button, Qt.MouseButton.LeftButton)
    assert widget.calibration_record is not None
    assert widget.calibration_record.intrinsic.gate is CalibrationGate.PASS
    assert calibration_spy

    camera = MockCameraBackend(
        width_px=160,
        height_px=120,
        stripe_x_px=80.2,
        noise_std=0.25,
    )
    camera.connect()
    widget.set_camera_frame(camera.software_trigger())
    qtbot.mouseClick(widget.measure_button, Qt.MouseButton.LeftButton)

    assert widget.cross_section is not None
    assert np.count_nonzero(widget.cross_section.valid_mask) == 120
    assert measurement_spy
    csv_path, metadata_path = widget.export_measurement(tmp_path / "section.csv")
    assert csv_path.exists()
    assert metadata_path.exists()
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["valid_point_count"] == 120


def test_calibration_json_roundtrip_and_identity_mismatch_block(qtbot, tmp_path) -> None:
    source = _small_mock_widget(qtbot)
    source.run_mock_calibration()
    calibration_path = source.save_calibration(tmp_path / "calibration.json")

    loaded = CalibrationMeasurementWidget()
    qtbot.addWidget(loaded)
    record = loaded.load_calibration(calibration_path)
    assert record.identity.camera_model == "acA1300-60gm"
    assert record.intrinsic.gate is CalibrationGate.PASS

    camera = MockCameraBackend(width_px=160, height_px=120, noise_std=0.0)
    camera.connect()
    loaded.set_camera_frame(camera.software_trigger())
    loaded.camera_serial_edit.setText("DIFFERENT-SERIAL")
    with pytest.raises(RuntimeError, match="calibration does not match"):
        loaded.run_measurement()


def test_csv_plane_and_newton_fit_update_status(qtbot, tmp_path) -> None:
    widget = _small_mock_widget(qtbot)
    widget.run_mock_calibration()
    rng = np.random.default_rng(5)
    xy = rng.uniform(-20, 20, size=(80, 2))
    z = 0.25 * xy[:, 0] - 0.1 * xy[:, 1] + 100
    plane_path = tmp_path / "plane.csv"
    np.savetxt(plane_path, np.column_stack((xy, z)), delimiter=",")
    plane_fit = widget.import_laser_plane_csv(plane_path)
    assert plane_fit.rms_residual_mm < 1e-10
    assert "RMS" in widget.laser_plane_status_label.text()

    pixels = np.linspace(100, 900, 30)
    ranges = 1.0 / (2e-6 * pixels + 0.002)
    newton_path = tmp_path / "newton.csv"
    np.savetxt(newton_path, np.column_stack((pixels, ranges)), delimiter=",")
    newton = widget.import_newton_csv(newton_path)
    assert newton.a_per_mm_px == pytest.approx(2e-6, rel=1e-6)
    assert "a=" in widget.newton_status_label.text()


def test_checkerboard_import_auto_runs_after_fifteen_valid_images(
    qtbot,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = _small_mock_widget(qtbot)
    paths = []
    for index in range(15):
        path = tmp_path / f"board-{index}.png"
        cv2.imwrite(str(path), np.zeros((120, 160), dtype=np.uint8))
        paths.append(path)

    corner_count = widget.board_columns_spin.value() * widget.board_rows_spin.value()
    corners = np.column_stack(
        (
            np.linspace(20, 140, corner_count),
            np.linspace(15, 105, corner_count),
        )
    ).astype(np.float32)
    monkeypatch.setattr(
        calibration_tab,
        "detect_checkerboard",
        lambda _image, _pattern: corners.copy(),
    )
    called: dict[str, int] = {}

    def fake_calibration(object_points, image_points, image_size_px):
        called["views"] = len(image_points)
        return IntrinsicCalibration(
            camera_matrix=np.asarray([[250.0, 0.0, 79.5], [0.0, 250.0, 59.5], [0.0, 0.0, 1.0]]),
            distortion_coefficients=np.zeros(5),
            rms_reprojection_error_px=0.2,
            per_view_error_px=np.full(len(image_points), 0.2),
            image_size_px=image_size_px,
            view_count=len(object_points),
            coverage_quadrants=(True, True, True, True),
            gate=CalibrationGate.PASS,
        )

    monkeypatch.setattr(calibration_tab, "calibrate_intrinsics", fake_calibration)
    result = widget.import_checkerboard_images(paths)

    assert result is not None
    assert called["views"] == 15
    assert result.gate is CalibrationGate.PASS
    assert "PASS" in widget.checkerboard_status_label.text()


def test_manual_focus_assist_reports_directional_fft_contrast(qtbot) -> None:
    widget = _small_mock_widget(qtbot)
    vertical_ronchi = np.tile((np.arange(160) % 2) * 255, (120, 1)).astype(np.uint8)
    widget.set_camera_frame(vertical_ronchi)
    focus_spy: list[object] = []
    widget.focus_assist_ready.connect(focus_spy.append)

    qtbot.mouseClick(widget.focus_button, Qt.MouseButton.LeftButton)
    result = focus_spy[-1]

    assert result.horizontal_contrast > 0.9
    assert result.vertical_contrast == pytest.approx(0.0)
    assert "수직 방향 대비가 낮습니다" in result.guidance
    assert "H=" in widget.focus_result_label.text()
