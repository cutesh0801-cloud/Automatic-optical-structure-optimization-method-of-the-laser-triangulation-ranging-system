from __future__ import annotations

import json
import math
import subprocess
import sys
from dataclasses import FrozenInstanceError
from importlib.resources import files

import pytest

from scheimpflug_optimeter.models import (
    DesignInput,
    DesignMode,
    Point2D,
    SensorProfile,
    WorkbookDesignInput,
)
from scheimpflug_optimeter.optics import (
    OpticalInputError,
    build_scene_geometry,
    image_coordinate_mm,
    image_sensitivity,
    solve_alpha,
    solve_canonical_design,
    solve_workbook_design,
)


def test_domain_models_are_frozen_and_sensor_units_are_explicit():
    sensor = SensorProfile("sensor", "Test", 1282, 1026, 5.3)

    assert sensor.width_mm == pytest.approx(6.7946)
    assert sensor.height_mm == pytest.approx(5.4378)
    assert sensor.length_mm("height") == pytest.approx(5.4378)
    assert sensor.length_mm("width") == pytest.approx(6.7946)
    with pytest.raises(FrozenInstanceError):
        sensor.width_px = 1  # type: ignore[misc]
    with pytest.raises(ValueError, match="axis"):
        sensor.length_mm("diagonal")


def test_workbook_a_s1_golden_vector_and_diagnostics():
    solution = solve_workbook_design(
        WorkbookDesignInput(
            v_mm=205.0,
            d_mm=100.0,
            sensor_length_mm=5.4378,
            alpha_deg=14.27,
        )
    )

    assert solution.mode is DesignMode.WORKBOOK
    assert solution.valid
    assert solution.beta_deg == pytest.approx(75.73)
    assert solution.baseline_mm == pytest.approx(52.13954827543338, rel=1e-12)
    assert solution.width_exact_mm == pytest.approx(54.858448275433375, rel=1e-12)
    assert solution.rear_exact_mm == pytest.approx(105.0)
    assert solution.fp_mm == pytest.approx(12.8519608569, rel=1e-10)
    assert solution.lo_mm == pytest.approx(198.674710025, rel=1e-10)
    assert solution.total_optical_length_mm == pytest.approx(211.526670882, rel=1e-10)
    assert solution.focal_length_mm == pytest.approx(12.0710999982, rel=1e-10)
    assert solution.ray_intercept_s_mm == pytest.approx(1165.9442466162743, rel=1e-12)
    assert solution.diagnostic("scheimpflug_residual_mm") == pytest.approx(0.0, abs=1e-12)
    assert solution.diagnostic("right_triangle_residual_mm2") == pytest.approx(0.0, abs=1e-10)


def test_workbook_a_s1_scene_coordinates_and_invariants():
    solution = solve_workbook_design(WorkbookDesignInput(205.0, 100.0, 5.4378, 14.27))
    scene = build_scene_geometry(solution)

    assert scene.emitter == Point2D(0.0, 205.0)
    assert scene.target_center == Point2D(0.0, 0.0)
    assert scene.image_center.x_mm == pytest.approx(52.13954827543338)
    assert scene.image_center.z_mm == pytest.approx(205.0)
    assert scene.lens_center.x_mm == pytest.approx(48.97164783649976)
    assert scene.lens_center.z_mm == pytest.approx(192.54458733415268)
    assert scene.sensor_near.x_mm == pytest.approx(54.858448275433375)
    assert scene.sensor_far.x_mm == pytest.approx(49.42064827543338)
    assert scene.ray_intercept == Point2D(0.0, pytest.approx(-1165.9442466162743))
    assert scene.target_center.distance_to(scene.lens_center) == pytest.approx(solution.lo_mm)
    assert scene.lens_center.distance_to(scene.image_center) == pytest.approx(solution.fp_mm)
    assert scene.scheimpflug_intersection is not None
    assert scene.scheimpflug_intersection.x_mm == pytest.approx(0.0, abs=1e-10)
    assert scene.scheimpflug_intersection.z_mm == pytest.approx(205.0, abs=1e-10)
    assert scene.target_far == scene.ray_intercept
    assert scene.target_far.z_mm == pytest.approx(-solution.ray_intercept_s_mm)
    assert scene.target_near.z_mm > scene.target_center.z_mm
    for target, sensor in (
        (scene.target_near, scene.sensor_near),
        (scene.target_far, scene.sensor_far),
    ):
        target_to_lens = (
            scene.lens_center.x_mm - target.x_mm,
            scene.lens_center.z_mm - target.z_mm,
        )
        lens_to_sensor = (
            sensor.x_mm - scene.lens_center.x_mm,
            sensor.z_mm - scene.lens_center.z_mm,
        )
        cross = target_to_lens[0] * lens_to_sensor[1] - target_to_lens[1] * lens_to_sensor[0]
        assert cross == pytest.approx(0.0, abs=1e-10)


def test_workbook_rejects_zero_sensor_length_instead_of_silent_l_zero():
    with pytest.raises(OpticalInputError, match="sensor_length_mm"):
        solve_workbook_design(WorkbookDesignInput(205.0, 100.0, 0.0, 14.27))
    with pytest.raises(OpticalInputError, match="source cell for L is missing"):
        solve_workbook_design(WorkbookDesignInput(205.0, 100.0, None, 14.27))


def test_workbook_marks_angles_outside_its_low_root_design_branch_invalid():
    solution = solve_workbook_design(WorkbookDesignInput(205.0, 100.0, 5.4378, 89.0))

    assert not solution.valid
    assert {item.code for item in solution.violations} == {"alpha_low_root_domain"}


def test_all_complete_sanitized_workbook_vectors_regress_at_1e_9():
    fixture = json.loads(
        files("scheimpflug_optimeter.data")
        .joinpath("workbook_regression.json")
        .read_text(encoding="utf-8")
    )

    assert fixture["source_included_in_repository"] is False
    assert fixture["schema_version"] == 2
    assert fixture["scenario_counts"] == {
        "total": 16,
        "runnable": 4,
        "blocked_missing_sensor_length": 12,
    }
    assert len(fixture["complete_cases"]) == 4
    assert len(fixture["excluded_incomplete_cases"]) == 12
    all_cases = fixture["complete_cases"] + fixture["excluded_incomplete_cases"]
    assert len({case["id"] for case in all_cases}) == 16
    assert {case["missing_source_cell"] for case in fixture["excluded_incomplete_cases"]} == {
        "W24",
        "AB24",
        "AG24",
        "W53",
        "AB53",
        "AG53",
    }
    assert fixture["formula_contract"]["ray_intercept_s_mm"].startswith("half_sensor_mm * lo_mm")
    assert any(item["cells"] == "M34" for item in fixture["unresolved_items"])
    tolerance = fixture["regression_tolerance"]
    for case in fixture["complete_cases"]:
        values = case["input"]
        expected = case["expected"]
        solution = solve_workbook_design(WorkbookDesignInput(**values))
        actual = {
            "beta_deg": solution.beta_deg,
            "baseline_mm": solution.baseline_mm,
            "width_mm": solution.width_exact_mm,
            "rear_mm": solution.rear_exact_mm,
            "lo_mm": solution.lo_mm,
            "fp_mm": solution.fp_mm,
            "total_mm": solution.total_optical_length_mm,
            "ray_intercept_s_mm": solution.ray_intercept_s_mm,
            "f_derived_mm": solution.focal_length_mm,
        }
        for field, actual_value in actual.items():
            assert actual_value == pytest.approx(
                expected[field],
                rel=tolerance["relative"],
                abs=tolerance["absolute"],
            ), f"{case['id']}::{field}"
        assert solution.diagnostic("focal_length_literal_mm") == expected["workbook_f_literal_mm"]
        assert solution.diagnostic("focal_length_derived_mm") == pytest.approx(
            expected["f_derived_mm"],
            rel=tolerance["relative"],
            abs=tolerance["absolute"],
        )
        assert solution.diagnostic("alpha_equation_residual_at_reference") == pytest.approx(
            expected["alpha_reference_residual"],
            rel=tolerance["relative"],
            abs=tolerance["absolute"],
        )
        assert solution.diagnostic("rm_cmos_distance_mm") == values["rm_cmos_distance_mm"]
        assert solution.diagnostic("fov_mm") == values["fov_mm"]

    for case in fixture["excluded_incomplete_cases"]:
        assert case["input"]["sensor_length_mm"] is None
        with pytest.raises(OpticalInputError, match="source cell for L is missing"):
            solve_workbook_design(WorkbookDesignInput(**case["input"]))


def test_workbook_path_defers_scipy_until_solve_alpha_is_called():
    script = """
import json
import math
import sys

from scheimpflug_optimeter.models import WorkbookDesignInput
from scheimpflug_optimeter.optics import solve_alpha, solve_workbook_design

solution = solve_workbook_design(WorkbookDesignInput(205.0, 100.0, 5.4378, 14.27))
before = {
    "numpy": "numpy" in sys.modules,
    "scipy": "scipy" in sys.modules,
    "scipy_optimize": "scipy.optimize" in sys.modules,
}
alpha_deg = solve_alpha(12.0, 205.0)
alpha = math.radians(alpha_deg)
after = {
    "numpy": "numpy" in sys.modules,
    "scipy": "scipy" in sys.modules,
    "scipy_optimize": "scipy.optimize" in sys.modules,
}
print(json.dumps({
    "before": before,
    "after": after,
    "focal_length_mm": solution.focal_length_mm,
    "residual": math.sin(alpha) ** 2 * math.cos(alpha) - 12.0 / 205.0,
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["before"] == {
        "numpy": False,
        "scipy": False,
        "scipy_optimize": False,
    }
    assert result["after"] == {
        "numpy": True,
        "scipy": True,
        "scipy_optimize": True,
    }
    assert result["focal_length_mm"] == pytest.approx(12.0710999982, rel=1e-10)
    assert result["residual"] == pytest.approx(0.0, abs=1e-14)


@pytest.mark.parametrize(
    ("v_mm", "focal_mm", "expected_alpha_deg"),
    (
        (205.0, 12.0, 14.22559441035571),
        (200.0, 17.5, 17.638634967645924),
    ),
)
def test_solve_alpha_low_root_has_small_residual(v_mm, focal_mm, expected_alpha_deg):
    alpha_deg = solve_alpha(focal_mm, v_mm)
    alpha = math.radians(alpha_deg)

    assert alpha_deg == pytest.approx(expected_alpha_deg, abs=1e-11)
    assert math.sin(alpha) ** 2 * math.cos(alpha) - focal_mm / v_mm == pytest.approx(0.0, abs=1e-14)


def test_solve_alpha_enforces_the_low_root_domain():
    maximum_ratio = 2.0 / (3.0 * math.sqrt(3.0))
    with pytest.raises(OpticalInputError, match="f/V"):
        solve_alpha(maximum_ratio * 100.0, 100.0)
    with pytest.raises(OpticalInputError):
        solve_alpha(0.0, 100.0)


@pytest.mark.parametrize(
    (
        "d_mm",
        "range_mm",
        "alpha_deg",
        "beta_deg",
        "focal_mm",
        "expected_lo",
        "expected_fp",
        "expected_l",
        "expected_w",
        "expected_r",
        "expected_sensitivity",
    ),
    (
        (
            22.5,
            5.0,
            41.260,
            20.0,
            29.6165,
            41.904,
            101.001,
            23.794,
            104.674,
            90.646,
            3.49623,
        ),
        (
            50.0,
            20.0,
            31.671,
            24.539,
            39.8403,
            69.324,
            93.675,
            37.271,
            101.069,
            99.089,
            1.02868,
        ),
        (
            150.0,
            80.0,
            17.126,
            30.258,
            57.5065,
            166.377,
            87.882,
            28.167,
            85.237,
            102.521,
            0.169094,
        ),
    ),
)
def test_canonical_solver_reproduces_2022_paper_table_2(
    d_mm,
    range_mm,
    alpha_deg,
    beta_deg,
    focal_mm,
    expected_lo,
    expected_fp,
    expected_l,
    expected_w,
    expected_r,
    expected_sensitivity,
):
    solution = solve_canonical_design(
        DesignInput(
            d_mm=d_mm,
            range_mm=range_mm,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            focal_length_mm=focal_mm,
            sensor_length_mm=200.0,
            pixel_pitch_um=5.0,
            max_width_mm=200.0,
            max_rear_mm=200.0,
        )
    )

    assert solution.valid
    assert solution.lo_mm == pytest.approx(expected_lo, abs=0.005)
    assert solution.fp_mm == pytest.approx(expected_fp, abs=0.005)
    assert solution.required_sensor_length_mm == pytest.approx(expected_l, abs=0.005)
    assert solution.width_proxy_mm == pytest.approx(expected_w, abs=0.005)
    assert solution.rear_proxy_mm == pytest.approx(expected_r, abs=0.005)
    assert solution.sensitivity_sensor_mm_per_object_mm == pytest.approx(
        expected_sensitivity, rel=5e-5
    )
    assert solution.width_exact_mm >= solution.width_proxy_mm
    assert solution.rear_exact_mm >= solution.rear_proxy_mm


def test_canonical_mapping_and_scene_use_exact_asymmetric_endpoints():
    request = DesignInput(
        50.0,
        20.0,
        31.671,
        24.539,
        focal_length_mm=39.8403,
        sensor_length_mm=200.0,
        pixel_pitch_um=5.0,
        max_width_mm=200.0,
        max_rear_mm=200.0,
    )
    solution = solve_canonical_design(request)
    scene = build_scene_geometry(solution)

    assert solution.x_near_mm == pytest.approx(
        image_coordinate_mm(
            -10.0,
            alpha_deg=request.alpha_deg,
            beta_deg=request.beta_deg,
            lo_mm=solution.lo_mm,
            fp_mm=solution.fp_mm,
        )
    )
    assert solution.x_far_mm == pytest.approx(
        image_coordinate_mm(
            10.0,
            alpha_deg=request.alpha_deg,
            beta_deg=request.beta_deg,
            lo_mm=solution.lo_mm,
            fp_mm=solution.fp_mm,
        )
    )
    assert solution.sensitivity == pytest.approx(
        image_sensitivity(
            10.0,
            alpha_deg=request.alpha_deg,
            beta_deg=request.beta_deg,
            lo_mm=solution.lo_mm,
            fp_mm=solution.fp_mm,
        )
    )
    assert scene.target_center.distance_to(scene.lens_center) == pytest.approx(solution.lo_mm)
    assert scene.lens_center.distance_to(scene.image_center) == pytest.approx(solution.fp_mm)
    assert scene.sensor_near.distance_to(scene.sensor_far) == pytest.approx(
        solution.required_sensor_length_mm
    )
    assert scene.scheimpflug_intersection is not None
    assert scene.scheimpflug_intersection.x_mm == pytest.approx(0.0, abs=1e-10)


def test_canonical_invalid_constraints_are_explicit_and_geometry_is_not_stale():
    solution = solve_canonical_design(
        DesignInput(
            20.0,
            50.0,
            50.0,
            45.0,
            focal_length_mm=12.0,
            sensor_length_mm=1.0,
            pixel_pitch_um=5.0,
            max_width_mm=5.0,
            max_rear_mm=5.0,
        )
    )
    codes = {violation.code for violation in solution.violations}

    assert not solution.valid
    assert "non_positive_near_distance" in codes
    assert "angle_sum_limit" in codes
    assert "sensor_length" in codes or "range_mapping_singular" in codes
