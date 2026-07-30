from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from scheimpflug_optimeter.hardware import CAMERAS, get_lens
from scheimpflug_optimeter.models import DesignInput, DesignMode, WorkbookDesignInput
from scheimpflug_optimeter.optics import (
    OpticalInputError,
    calculate_sensor_imaging_metrics,
    image_sensitivity,
    solve_canonical_design,
    solve_workbook_design,
)


def _expected_range_axis(
    *,
    sensor_length_mm: float,
    sensor_pixels: int,
    pitch_mm: float,
    alpha_deg: float,
    beta_deg: float,
    lo_mm: float,
    fp_mm: float,
) -> tuple[float, float, float, float, float, float]:
    """Independent exact inverse-map expectations for a full active axis."""

    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    image_term = fp_mm * math.sin(alpha)
    object_term = lo_mm * math.sin(beta)
    coupling = math.sin(alpha + beta)
    half = sensor_length_mm / 2.0
    coordinates = (-half, half)
    offsets = tuple(
        coordinate * object_term / (image_term - coordinate * coupling)
        for coordinate in coordinates
    )
    range_min, range_max = min(offsets), max(offsets)

    def local_mm_per_px(coordinate: float) -> float:
        return pitch_mm * image_term * object_term / (image_term - coordinate * coupling) ** 2

    near = local_mm_per_px(-half)
    center = pitch_mm * object_term / image_term
    far = local_mm_per_px(half)
    return (
        range_min,
        range_max,
        (range_max - range_min) / sensor_pixels,
        near,
        center,
        max(near, center, far),
    )


@pytest.mark.parametrize("camera_id", tuple(CAMERAS))
@pytest.mark.parametrize("axis", ("width", "height"))
@pytest.mark.parametrize("mode", (DesignMode.WORKBOOK, DesignMode.CANONICAL))
def test_all_basler_profiles_report_exact_fov_sampling_and_range_sensitivity(
    camera_id: str,
    axis: str,
    mode: DesignMode,
):
    camera = CAMERAS[camera_id]
    sensor = camera.sensor
    active_length = sensor.length_mm(axis)
    active_pixels = sensor.width_px if axis == "width" else sensor.height_px
    cross_length = sensor.height_mm if axis == "width" else sensor.width_mm
    cross_pixels = sensor.height_px if axis == "width" else sensor.width_px

    if mode is DesignMode.WORKBOOK:
        solution = solve_workbook_design(
            WorkbookDesignInput(
                v_mm=205.0,
                d_mm=100.0,
                sensor_length_mm=active_length,
                alpha_deg=25.0,
                sensor_id=sensor.id,
                sensor_axis=axis,
            )
        )
    else:
        solution = solve_canonical_design(
            DesignInput(
                d_mm=200.0,
                range_mm=2.0,
                alpha_deg=25.0,
                beta_deg=25.0,
                lens_id="edmund-33-879",
                sensor_id=sensor.id,
                sensor_axis=axis,
                max_width_mm=500.0,
                max_rear_mm=500.0,
            ),
            lens=get_lens("edmund-33-879"),
            sensor=sensor,
        )

    metrics = solution.sensor_metrics
    assert metrics is not None
    assert metrics.valid
    assert metrics.sensor is sensor
    assert metrics.sensor_axis == axis
    assert metrics.resolution_px == (sensor.width_px, sensor.height_px)
    assert metrics.dimensions_mm == pytest.approx((sensor.width_mm, sensor.height_mm))
    assert metrics.invalid_reason is None
    assert not metrics.warnings

    expected = _expected_range_axis(
        sensor_length_mm=active_length,
        sensor_pixels=active_pixels,
        pitch_mm=sensor.pixel_pitch_um / 1000.0,
        alpha_deg=solution.alpha_deg,
        beta_deg=solution.beta_deg,
        lo_mm=solution.lo_mm,
        fp_mm=solution.fp_mm,
    )
    range_min, range_max, average_sampling, near, center, worst = expected
    cross_fov = cross_length * solution.lo_mm / solution.fp_mm
    cross_sampling = cross_fov / cross_pixels

    assert metrics.range_min_offset_mm == pytest.approx(range_min, rel=1e-12)
    assert metrics.range_max_offset_mm == pytest.approx(range_max, rel=1e-12)
    assert metrics.range_fov_mm == pytest.approx(range_max - range_min, rel=1e-12)
    assert metrics.range_sensitivity_near_mm_per_px == pytest.approx(near, rel=1e-12)
    assert metrics.range_sensitivity_center_mm_per_px == pytest.approx(center, rel=1e-12)
    assert metrics.range_sensitivity_worst_mm_per_px == pytest.approx(worst, rel=1e-12)

    if axis == "width":
        assert metrics.horizontal_fov_mm == pytest.approx(range_max - range_min, rel=1e-12)
        assert metrics.vertical_fov_mm == pytest.approx(cross_fov, rel=1e-12)
        assert metrics.horizontal_sampling_mm_per_px == pytest.approx(average_sampling, rel=1e-12)
        assert metrics.vertical_sampling_mm_per_px == pytest.approx(cross_sampling, rel=1e-12)
    else:
        assert metrics.horizontal_fov_mm == pytest.approx(cross_fov, rel=1e-12)
        assert metrics.vertical_fov_mm == pytest.approx(range_max - range_min, rel=1e-12)
        assert metrics.horizontal_sampling_mm_per_px == pytest.approx(cross_sampling, rel=1e-12)
        assert metrics.vertical_sampling_mm_per_px == pytest.approx(average_sampling, rel=1e-12)

    if mode is DesignMode.WORKBOOK:
        assert solution.distance_per_pixel_mm == pytest.approx(worst, rel=1e-12)
        assert solution.distance_per_sensor_mm == pytest.approx(
            worst / (sensor.pixel_pitch_um / 1000.0), rel=1e-12
        )
    else:
        request_half_range = solution.request.range_mm / 2.0
        expected_requested_worst = max(
            (
                sensor.pixel_pitch_um
                / 1000.0
                / abs(
                    image_sensitivity(
                        offset,
                        alpha_deg=solution.alpha_deg,
                        beta_deg=solution.beta_deg,
                        lo_mm=solution.lo_mm,
                        fp_mm=solution.fp_mm,
                    )
                )
            )
            for offset in (-request_half_range, request_half_range)
        )
        assert solution.distance_per_pixel_mm == pytest.approx(expected_requested_worst, rel=1e-12)


def test_full_sensor_mapping_pole_is_explicitly_invalid_not_infinite():
    camera = CAMERAS["basler-aca1300-60gm"]
    solution = solve_workbook_design(
        WorkbookDesignInput(
            v_mm=205.0,
            d_mm=100.0,
            sensor_length_mm=camera.sensor.width_mm,
            alpha_deg=14.27,
            sensor_id=camera.sensor.id,
            sensor_axis="width",
        )
    )

    metrics = solution.sensor_metrics
    assert metrics is not None
    assert solution.valid
    assert not solution.violations
    assert not metrics.valid
    assert metrics.invalid_reason is not None
    assert "mapping pole" in metrics.invalid_reason
    assert metrics.horizontal_fov_mm is None
    assert metrics.horizontal_sampling_mm_per_px is None
    assert metrics.range_fov_mm is None
    assert metrics.range_sensitivity_worst_mm_per_px is None
    assert solution.distance_per_pixel_mm is None
    assert metrics.invalid_reason in solution.warnings


def test_profile_mismatch_is_visible_and_metrics_remain_immutable():
    camera = CAMERAS["basler-aca1300-60gm"]
    solution = solve_workbook_design(
        WorkbookDesignInput(
            v_mm=205.0,
            d_mm=100.0,
            sensor_length_mm=3.0,
            alpha_deg=25.0,
            sensor_id=camera.sensor.id,
            sensor_axis="height",
        )
    )

    metrics = solution.sensor_metrics
    assert metrics is not None
    assert metrics.valid
    assert len(metrics.warnings) == 1
    assert "3 mm" in metrics.warnings[0]
    assert "5.4378 mm" in metrics.warnings[0]
    assert metrics.warnings[0] in solution.warnings
    with pytest.raises(FrozenInstanceError):
        metrics.valid = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"alpha_deg": 0.0}, "alpha_deg"),
        ({"alpha_deg": 90.0}, "alpha_deg"),
        ({"beta_deg": -1.0}, "beta_deg"),
        ({"beta_deg": 90.0}, "beta_deg"),
        ({"lo_mm": 0.0}, "lo_mm"),
        ({"fp_mm": -1.0}, "fp_mm"),
        ({"fp_mm": math.nan}, "fp_mm"),
        ({"calculation_sensor_length_mm": 0.0}, "calculation_sensor_length_mm"),
        ({"sensor_axis": "diagonal"}, "axis"),
    ),
)
def test_public_sensor_metrics_reject_invalid_angles_distances_and_axis(
    changes: dict[str, float | str],
    message: str,
):
    values: dict[str, object] = {
        "sensor_axis": "height",
        "alpha_deg": 25.0,
        "beta_deg": 25.0,
        "lo_mm": 24.0,
        "fp_mm": 24.0,
        "calculation_sensor_length_mm": None,
    }
    values.update(changes)

    with pytest.raises(OpticalInputError, match=message):
        calculate_sensor_imaging_metrics(
            CAMERAS["basler-aca1300-60gm"].sensor,
            **values,  # type: ignore[arg-type]
        )
