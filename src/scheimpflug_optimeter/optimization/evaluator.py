"""Shared objective and constraint ordering for every optimizer."""

from __future__ import annotations

import math
from dataclasses import dataclass

from scheimpflug_optimeter.hardware import get_lens, get_sensor
from scheimpflug_optimeter.models import (
    ConstraintViolation,
    DesignInput,
    DesignSolution,
    OptimizationRequest,
)
from scheimpflug_optimeter.optics import OpticalInputError, solve_canonical_design


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Optimizer-facing representation of one angle pair."""

    alpha_deg: float
    beta_deg: float
    solution: DesignSolution | None
    objective: float
    violation: float
    violations: tuple[ConstraintViolation, ...]

    @property
    def valid(self) -> bool:
        return self.solution is not None and self.solution.valid

    @property
    def deb_key(self) -> tuple[float, ...]:
        if self.valid:
            return (0.0, self.objective)
        return (1.0, self.violation, self.objective)


def normalized_violation(violations: tuple[ConstraintViolation, ...]) -> float:
    """Return a unit-aware aggregate suitable for Deb constraint ordering."""

    total = 0.0
    for violation in violations:
        amount = abs(violation.amount) if violation.amount is not None else 1.0
        scale = abs(violation.limit) if violation.limit not in {None, 0.0} else 1.0
        if not math.isfinite(amount):
            amount = 1_000_000.0
        if not math.isfinite(scale):
            scale = 1.0
        total += max(amount / scale, 1e-12)
    return total if violations else 0.0


class DesignEvaluator:
    """Resolve fixed profiles once, then evaluate continuous angles cheaply."""

    def __init__(self, request: OptimizationRequest, lens_id: str) -> None:
        self.request = request
        self.lens = get_lens(lens_id)
        self.sensor = get_sensor(request.sensor_id)
        self.evaluations = 0
        self.best_valid: Evaluation | None = None
        self.best_invalid: Evaluation | None = None

    def __call__(self, alpha_deg: float, beta_deg: float) -> Evaluation:
        self.evaluations += 1
        design = DesignInput(
            d_mm=self.request.d_mm,
            range_mm=self.request.range_mm,
            alpha_deg=float(alpha_deg),
            beta_deg=float(beta_deg),
            lens_id=self.lens.id,
            sensor_id=self.sensor.id,
            sensor_axis=self.request.sensor_axis,
            max_width_mm=self.request.max_width_mm,
            max_rear_mm=self.request.max_rear_mm,
        )
        try:
            solution = solve_canonical_design(
                design,
                lens=self.lens,
                sensor=self.sensor,
            )
        except (OpticalInputError, ArithmeticError, OverflowError) as error:
            violations = (
                ConstraintViolation(
                    "numerical_error", str(error), amount=1_000_000_000.0, limit=1.0
                ),
            )
            result = Evaluation(
                float(alpha_deg),
                float(beta_deg),
                None,
                math.inf,
                normalized_violation(violations),
                violations,
            )
        else:
            objective = (
                solution.distance_per_pixel_mm
                if solution.distance_per_pixel_mm is not None
                else solution.distance_per_sensor_mm
            )
            if not math.isfinite(objective):
                objective = math.inf
            result = Evaluation(
                float(alpha_deg),
                float(beta_deg),
                solution,
                objective,
                normalized_violation(solution.violations),
                solution.violations,
            )

        if result.valid and (self.best_valid is None or result.deb_key < self.best_valid.deb_key):
            self.best_valid = result
        if not result.valid and (
            self.best_invalid is None or result.deb_key < self.best_invalid.deb_key
        ):
            self.best_invalid = result
        return result


def penalty_value(evaluation: Evaluation) -> float:
    """Scalar wrapper for optimizers without native constraint ordering."""

    if evaluation.valid:
        return evaluation.objective
    finite_objective = evaluation.objective if math.isfinite(evaluation.objective) else 1.0
    return 1_000_000.0 + evaluation.violation * 10_000.0 + finite_objective


def candidate_sort_key(solution: DesignSolution) -> tuple[float, float, float, float]:
    """Decision-complete tie breaking from the implementation plan."""

    objective = (
        solution.distance_per_pixel_mm
        if solution.distance_per_pixel_mm is not None
        else solution.distance_per_sensor_mm
    )
    return (
        objective,
        max(solution.width_exact_mm, solution.rear_exact_mm),
        solution.required_sensor_length_mm,
        solution.total_optical_length_mm,
    )
