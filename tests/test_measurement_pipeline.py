from __future__ import annotations

import json

import numpy as np
import pytest

from scheimpflug_optimeter.calibration import LaserPlane
from scheimpflug_optimeter.camera import MockCameraBackend
from scheimpflug_optimeter.measurement import extract_stripe, triangulate_cross_section


def test_synthetic_stripe_is_detected_to_better_than_point_one_pixel() -> None:
    camera = MockCameraBackend(
        width_px=320,
        height_px=180,
        stripe_x_px=143.37,
        stripe_slope_px_per_row=0.018,
        stripe_sigma_px=1.3,
        noise_std=0.35,
        seed=12,
    )
    camera.connect()
    frame = camera.software_trigger()

    stripe = extract_stripe(frame.image)
    expected = camera.expected_stripe_x(stripe.profile_indices_px)
    error = np.abs(stripe.coordinates_px[stripe.valid_mask] - expected[stripe.valid_mask])

    assert np.count_nonzero(stripe.valid_mask) > frame.image.shape[0] * 0.98
    assert float(np.mean(error)) < 0.1
    assert float(np.max(error)) < 0.2


def test_stripe_dark_subtraction_and_horizontal_orientation() -> None:
    height, width = 80, 100
    y = np.arange(height, dtype=np.float64)[:, None]
    center = 31.4
    image = 40 + 180 * np.exp(-0.5 * ((y - center) / 1.2) ** 2)
    image = np.broadcast_to(image, (height, width)).astype(np.uint8)
    dark = np.full_like(image, 35)

    stripe = extract_stripe(image, dark_frame=dark, orientation="horizontal")

    assert np.all(stripe.valid_mask)
    assert np.mean(np.abs(stripe.coordinates_px - center)) < 0.1
    assert np.allclose(stripe.pixels_xy[:, 0], np.arange(width))


def test_triangulation_intersects_forward_laser_plane_and_exports(tmp_path) -> None:
    camera = MockCameraBackend(
        width_px=100,
        height_px=60,
        stripe_x_px=50.0,
        stripe_slope_px_per_row=0.0,
        noise_std=0.0,
    )
    camera.connect()
    stripe = extract_stripe(camera.software_trigger().image)
    matrix = np.asarray([[100.0, 0.0, 50.0], [0.0, 100.0, 30.0], [0.0, 0.0, 1.0]])
    plane = LaserPlane(np.asarray([0.0, 0.0, 1.0]), -100.0)

    cross_section = triangulate_cross_section(
        stripe,
        matrix,
        plane,
        metadata={"camera_serial": "MOCK-ACA1300-0001", "units": "mm"},
    )

    assert np.count_nonzero(cross_section.valid_mask) == 60
    assert np.allclose(cross_section.valid_points_mm[:, 0], 0.0, atol=0.1)
    assert np.allclose(cross_section.valid_points_mm[:, 2], 100.0)
    csv_path = tmp_path / "section.csv"
    metadata_path = tmp_path / "section.json"
    cross_section.write_csv(csv_path)
    cross_section.write_metadata(metadata_path)
    assert len(csv_path.read_text(encoding="utf-8").splitlines()) == 61
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["units"] == "mm"


def test_backward_and_parallel_intersections_are_invalid() -> None:
    camera = MockCameraBackend(width_px=20, height_px=10, stripe_x_px=10, noise_std=0)
    camera.connect()
    stripe = extract_stripe(camera.software_trigger().image)
    matrix = np.asarray([[20.0, 0.0, 10.0], [0.0, 20.0, 5.0], [0.0, 0.0, 1.0]])
    behind_camera = LaserPlane(np.asarray([0.0, 0.0, 1.0]), 100.0)

    cross_section = triangulate_cross_section(stripe, matrix, behind_camera)

    assert not np.any(cross_section.valid_mask)
    assert np.all(np.isnan(cross_section.points_mm))


def test_invalid_dark_frame_shape_is_rejected() -> None:
    with pytest.raises(ValueError, match="dark_frame"):
        extract_stripe(np.zeros((10, 10)), dark_frame=np.zeros((9, 10)))
