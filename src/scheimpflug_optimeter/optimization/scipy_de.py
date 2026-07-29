"""SciPy differential-evolution product optimizer."""

from __future__ import annotations

from collections.abc import Callable

from scipy.optimize import differential_evolution

from scheimpflug_optimeter.hardware import LENSES
from scheimpflug_optimeter.models import (
    ConstraintViolation,
    OptimizationAlgorithm,
    OptimizationCandidate,
    OptimizationRequest,
    OptimizationResult,
)

from .evaluator import DesignEvaluator, candidate_sort_key, penalty_value

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


class _OptimizationCancelled(Exception):
    """Internal fast exit that also prevents SciPy's polish phase."""


def _lens_ids(request: OptimizationRequest) -> tuple[str, ...]:
    return request.lens_ids or tuple(LENSES)


def _deduplicate_violations(
    values: list[tuple[ConstraintViolation, ...]],
) -> tuple[ConstraintViolation, ...]:
    unique: dict[str, ConstraintViolation] = {}
    for group in values:
        for violation in group:
            unique.setdefault(violation.code, violation)
    return tuple(unique.values())


def optimize_scipy(
    request: OptimizationRequest,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> OptimizationResult:
    """Optimize each discrete lens with deterministic differential evolution."""

    lens_ids = _lens_ids(request)
    if not lens_ids:
        raise ValueError("At least one lens id is required.")
    if request.max_iterations <= 0 or request.scipy_population_multiplier <= 0:
        raise ValueError("Iteration and population settings must be positive.")
    alpha_low, alpha_high = request.alpha_bounds_deg
    beta_low, beta_high = request.beta_bounds_deg
    if not alpha_low < alpha_high or not beta_low < beta_high:
        raise ValueError("Optimization bounds must be increasing.")

    candidates: list[OptimizationCandidate] = []
    infeasible: list[tuple[ConstraintViolation, ...]] = []
    total_evaluations = 0
    maximum_iterations = 0
    was_cancelled = False

    for lens_index, lens_id in enumerate(lens_ids):
        if cancelled is not None and cancelled():
            was_cancelled = True
            break
        evaluator = DesignEvaluator(request, lens_id)
        generation = 0

        def objective(vector: object, evaluator: DesignEvaluator = evaluator) -> float:
            if cancelled is not None and cancelled():
                raise _OptimizationCancelled
            alpha, beta = vector  # type: ignore[misc]
            return penalty_value(evaluator(float(alpha), float(beta)))

        def callback(
            _xk: object,
            _convergence: float,
            lens_index: int = lens_index,
            lens_id: str = lens_id,
        ) -> bool:
            nonlocal generation
            generation += 1
            if progress is not None:
                completed = (lens_index + min(generation / request.max_iterations, 1.0)) / len(
                    lens_ids
                )
                progress(completed, f"Optimizing {lens_id}")
            return cancelled is not None and cancelled()

        result = None
        try:
            result = differential_evolution(
                objective,
                bounds=(request.alpha_bounds_deg, request.beta_bounds_deg),
                seed=request.seed + lens_index,
                popsize=request.scipy_population_multiplier,
                maxiter=request.max_iterations,
                tol=request.tolerance,
                polish=True,
                callback=callback,
                updating="immediate",
                workers=1,
            )
        except _OptimizationCancelled:
            was_cancelled = True
        total_evaluations += evaluator.evaluations
        maximum_iterations = max(
            maximum_iterations, int(result.nit) if result is not None else generation
        )
        was_cancelled = was_cancelled or (cancelled is not None and cancelled())
        best = evaluator.best_valid
        if best is not None and best.solution is not None:
            candidates.append(
                OptimizationCandidate(
                    lens_id=lens_id,
                    solution=best.solution,
                    objective_mm_per_pixel=best.objective,
                    evaluations=evaluator.evaluations,
                )
            )
        elif evaluator.best_invalid is not None:
            infeasible.append(evaluator.best_invalid.violations)
        if was_cancelled:
            break

    candidates.sort(key=lambda item: candidate_sort_key(item.solution))
    if progress is not None and not was_cancelled:
        progress(1.0, "Optimization complete")
    return OptimizationResult(
        algorithm=OptimizationAlgorithm.SCIPY,
        candidates=tuple(candidates),
        seed=request.seed,
        iterations=maximum_iterations,
        evaluations=total_evaluations,
        cancelled=was_cancelled,
        infeasible_reasons=_deduplicate_violations(infeasible),
    )
