from __future__ import annotations

import pytest

from scheimpflug_optimeter.models import (
    OptimizationAlgorithm,
    OptimizationRequest,
)
from scheimpflug_optimeter.optimization import (
    optimize_design,
    optimize_mpso,
    optimize_scipy,
)


def small_request(**changes) -> OptimizationRequest:
    values = {
        "d_mm": 200.0,
        "range_mm": 2.0,
        "sensor_id": "basler-aca1300-60gm-sensor",
        "sensor_axis": "height",
        "lens_ids": ("edmund-33-879",),
        "max_width_mm": 500.0,
        "max_rear_mm": 500.0,
        "seed": 2026,
        "max_iterations": 5,
        "scipy_population_multiplier": 4,
        "mpso_particles": 12,
        "tolerance": 1e-5,
    }
    values.update(changes)
    return OptimizationRequest(**values)


def test_scipy_optimizer_returns_valid_ranked_candidate_and_progress():
    updates: list[tuple[float, str]] = []
    result = optimize_scipy(
        small_request(),
        progress=lambda fraction, message: updates.append((fraction, message)),
    )

    assert result.algorithm is OptimizationAlgorithm.SCIPY
    assert not result.cancelled
    assert result.best is not None
    assert result.best.lens_id == "edmund-33-879"
    assert result.best.solution.valid
    assert result.best.objective_mm_per_pixel > 0
    assert 15.0 <= result.best.solution.alpha_deg <= 45.0
    assert 20.0 <= result.best.solution.beta_deg <= 55.0
    assert result.best.solution.alpha_deg + result.best.solution.beta_deg < 89.5
    assert result.evaluations > 0
    assert updates[-1] == (1.0, "Optimization complete")


def test_scipy_optimizer_is_reproducible_for_same_seed():
    first = optimize_scipy(small_request(max_iterations=3))
    second = optimize_scipy(small_request(max_iterations=3))

    assert first.best is not None and second.best is not None
    assert first.best.solution.alpha_deg == pytest.approx(second.best.solution.alpha_deg, abs=1e-12)
    assert first.best.solution.beta_deg == pytest.approx(second.best.solution.beta_deg, abs=1e-12)
    assert first.best.objective_mm_per_pixel == pytest.approx(
        second.best.objective_mm_per_pixel, abs=1e-15
    )


def test_mpso_is_reproducible_and_records_non_bit_identical_interpretation():
    request = small_request(algorithm="mpso")
    first = optimize_mpso(request)
    second = optimize_mpso(request)

    assert first.algorithm is OptimizationAlgorithm.MPSO
    assert first.best is not None and second.best is not None
    assert first.best.solution.alpha_deg == second.best.solution.alpha_deg
    assert first.best.solution.beta_deg == second.best.solution.beta_deg
    assert first.best.objective_mm_per_pixel == second.best.objective_mm_per_pixel
    assert dict(first.metadata)["paper_bit_identical"] is False
    assert dict(first.metadata)["boundary_rule"] == "clamp_zero_velocity"


def test_dispatch_and_immediate_cancellation():
    request = small_request(algorithm=OptimizationAlgorithm.MPSO)
    result = optimize_design(request, cancelled=lambda: True)

    assert result.algorithm is OptimizationAlgorithm.MPSO
    assert result.cancelled
    assert result.candidates == ()
    assert result.evaluations == 0


def test_scipy_cancellation_interrupts_evaluations_and_skips_polish():
    calls = 0

    def cancelled():
        nonlocal calls
        calls += 1
        return calls > 20

    result = optimize_scipy(small_request(max_iterations=100), cancelled=cancelled)

    assert result.cancelled
    assert result.evaluations < 100


def test_infeasible_design_returns_reasons_not_a_penalty_as_a_result():
    result = optimize_scipy(
        small_request(
            d_mm=20.0,
            range_mm=100.0,
            max_width_mm=1.0,
            max_rear_mm=1.0,
            max_iterations=2,
            scipy_population_multiplier=3,
        )
    )

    assert result.candidates == ()
    assert result.infeasible_reasons
    codes = {violation.code for violation in result.infeasible_reasons}
    assert "non_positive_near_distance" in codes
    assert "mechanical_width" in codes or "range_mapping_singular" in codes


def test_unknown_algorithm_and_invalid_bounds_fail_loudly():
    with pytest.raises(ValueError, match="Unsupported"):
        optimize_design(small_request(algorithm="unknown"))
    with pytest.raises(ValueError, match="bounds"):
        optimize_scipy(small_request(alpha_bounds_deg=(45.0, 15.0)))
