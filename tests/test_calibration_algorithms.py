from __future__ import annotations

import cv2
import numpy as np
import pytest

from scheimpflug_optimeter.calibration import (
    CalibrationGate,
    CalibrationMismatchError,
    HardwareIdentity,
    ThickLensParameters,
    assert_calibration_matches,
    calibrate_intrinsics,
    calibration_mismatches,
    effective_calibration_matrix,
    fit_laser_plane,
    fit_newton_range,
    fit_thick_lens,
    project_points_thick_lens,
    thick_lens_matrix,
    tilt_matrix,
)
from scheimpflug_optimeter.camera import Roi


def test_hardware_identity_blocks_wrong_roi_and_serial() -> None:
    calibrated = HardwareIdentity(
        "40123456",
        "acA1300-60gm",
        "#33-879",
        Roi(0, 0, 1282, 1026),
        (1282, 1026),
    )
    current = HardwareIdentity(
        "40999999",
        "acA1300-60gm",
        "#33-879",
        Roi(0, 0, 640, 480),
        (640, 480),
    )
    mismatches = calibration_mismatches(calibrated, current)
    assert len(mismatches) == 3
    with pytest.raises(CalibrationMismatchError) as error:
        assert_calibration_matches(calibrated, current)
    assert len(error.value.mismatches) == 3


def test_robust_laser_plane_fit_rejects_outliers() -> None:
    rng = np.random.default_rng(4)
    xy = rng.uniform(-50, 50, size=(180, 2))
    z = 2.0 * xy[:, 0] - 0.5 * xy[:, 1] + 10.0 + rng.normal(0, 0.01, len(xy))
    points = np.column_stack((xy, z))
    outlier_indices = rng.choice(len(points), size=18, replace=False)
    points[outlier_indices, 2] += rng.uniform(5, 20, len(outlier_indices))

    fitted = fit_laser_plane(points)
    expected_normal = np.asarray([-2.0, 0.5, 1.0])
    expected_normal /= np.linalg.norm(expected_normal)

    assert abs(float(np.dot(fitted.plane.normal, expected_normal))) > 0.999999
    assert fitted.rms_residual_mm < 0.02
    assert np.count_nonzero(~fitted.inlier_mask[outlier_indices]) >= 17


def test_newton_range_fit_is_robust_and_invertible() -> None:
    rng = np.random.default_rng(7)
    pixels = np.linspace(200, 1_000, 60)
    expected_a = 2.1e-6
    expected_b = 0.00125
    inverse_range = expected_a * pixels + expected_b
    ranges = 1.0 / inverse_range
    ranges += rng.normal(0, 0.015, len(ranges))
    ranges[5] += 30.0

    fitted = fit_newton_range(pixels, ranges)

    assert fitted.a_per_mm_px == pytest.approx(expected_a, rel=2e-3)
    assert fitted.b_per_mm == pytest.approx(expected_b, rel=2e-3)
    test_range = fitted.range_mm(500.0)
    roundtrip = fitted.pixel_coordinate_px(test_range)
    assert float(roundtrip) == pytest.approx(500.0, abs=1e-9)


def test_thick_lens_composition_and_synthetic_fit() -> None:
    true_parameters = ThickLensParameters(
        focal_length_mm=16.0,
        principal_x_px=640.3,
        principal_y_px=480.2,
        tilt_x_rad=np.deg2rad(2.5),
        tilt_y_rad=np.deg2rad(10.0),
        principal_plane_offset_mm=-1.8,
        pixel_pitch_x_mm=0.0053,
        pixel_pitch_y_mm=0.0053,
    )
    assert np.allclose(
        effective_calibration_matrix(true_parameters),
        thick_lens_matrix(true_parameters)
        @ tilt_matrix(true_parameters.tilt_x_rad, true_parameters.tilt_y_rad),
    )
    rng = np.random.default_rng(11)
    points = np.column_stack(
        (
            rng.uniform(-35, 35, 120),
            rng.uniform(-25, 25, 120),
            rng.uniform(250, 500, 120),
        )
    )
    observed = project_points_thick_lens(points, true_parameters)
    initial = ThickLensParameters(
        focal_length_mm=15.7,
        principal_x_px=638.0,
        principal_y_px=482.0,
        tilt_x_rad=np.deg2rad(2.0),
        tilt_y_rad=np.deg2rad(9.5),
        principal_plane_offset_mm=-1.0,
        pixel_pitch_x_mm=0.0053,
        pixel_pitch_y_mm=0.0053,
    )

    fitted = fit_thick_lens(points, observed, initial)

    assert fitted.success
    assert fitted.rms_reprojection_error_px < 1e-5
    assert fitted.parameters.focal_length_mm == pytest.approx(16.0, abs=1e-4)


def test_intrinsic_calibration_quality_gate_with_synthetic_views() -> None:
    columns, rows = 7, 6
    grid = np.zeros((columns * rows, 3), dtype=np.float32)
    grid[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * 20.0
    matrix = np.asarray([[800.0, 0.0, 320.0], [0.0, 805.0, 240.0], [0.0, 0.0, 1.0]])
    distortion = np.zeros(5)
    object_views: list[np.ndarray] = []
    image_views: list[np.ndarray] = []
    translations = [
        (-180.0, -130.0),
        (50.0, -130.0),
        (-180.0, 80.0),
        (50.0, 80.0),
    ]
    for index in range(16):
        tx, ty = translations[index % 4]
        rotation = np.asarray(
            [
                np.deg2rad(-5 + index * 0.6),
                np.deg2rad(3 - index * 0.3),
                np.deg2rad(-2 + index * 0.25),
            ]
        )
        translation = np.asarray([tx, ty, 650.0 + 8 * index])
        projected, _ = cv2.projectPoints(grid, rotation, translation, matrix, distortion)
        object_views.append(grid.copy())
        image_views.append(projected.reshape(-1, 2).astype(np.float32))

    result = calibrate_intrinsics(object_views, image_views, (640, 480))

    assert result.gate is CalibrationGate.PASS
    assert result.rms_reprojection_error_px < 1e-3
    assert all(result.coverage_quadrants)


def test_intrinsic_calibration_requires_fifteen_views() -> None:
    points_3d = np.zeros((6, 3), dtype=np.float32)
    points_2d = np.zeros((6, 2), dtype=np.float32)
    with pytest.raises(ValueError, match="at least 15"):
        calibrate_intrinsics([points_3d] * 14, [points_2d] * 14, (640, 480))
