"""Reproducible, explicitly specified modified particle swarm optimizer."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from scheimpflug_optimeter.hardware import LENSES
from scheimpflug_optimeter.models import (
    ConstraintViolation,
    OptimizationAlgorithm,
    OptimizationCandidate,
    OptimizationRequest,
    OptimizationResult,
)

from .evaluator import DesignEvaluator, Evaluation, candidate_sort_key

ProgressCallback = Callable[[float, str], None]
CancelCallback = Callable[[], bool]


def _is_better(candidate: Evaluation, incumbent: Evaluation) -> bool:
    return candidate.deb_key < incumbent.deb_key


def _angles(normalized: np.ndarray, request: OptimizationRequest) -> tuple[float, float]:
    alpha = request.alpha_bounds_deg[0] + normalized[0] * (
        request.alpha_bounds_deg[1] - request.alpha_bounds_deg[0]
    )
    beta = request.beta_bounds_deg[0] + normalized[1] * (
        request.beta_bounds_deg[1] - request.beta_bounds_deg[0]
    )
    return float(alpha), float(beta)


def _evaluate_population(
    positions: np.ndarray,
    request: OptimizationRequest,
    evaluator: DesignEvaluator,
) -> list[Evaluation]:
    return [evaluator(*_angles(position, request)) for position in positions]


def _deduplicate_violations(
    values: list[tuple[ConstraintViolation, ...]],
) -> tuple[ConstraintViolation, ...]:
    unique: dict[str, ConstraintViolation] = {}
    for group in values:
        for violation in group:
            unique.setdefault(violation.code, violation)
    return tuple(unique.values())


def optimize_mpso(
    request: OptimizationRequest,
    *,
    progress: ProgressCallback | None = None,
    cancelled: CancelCallback | None = None,
) -> OptimizationResult:
    """Optimize with the documented v0.1 interpretation of paper M-PSO.

    Boundary handling clamps normalized positions to ``[0, 1]`` and zeroes the
    velocity component that crossed a boundary.  This is intentionally
    explicit because the source paper does not fully specify that operation.
    """

    lens_ids = request.lens_ids or tuple(LENSES)
    if not lens_ids:
        raise ValueError("At least one lens id is required.")
    if request.mpso_particles < 2 or request.max_iterations <= 0:
        raise ValueError("M-PSO requires at least two particles and one iteration.")
    if not 0.0 <= request.mpso_mutation_probability <= 1.0:
        raise ValueError("Mutation probability must lie in [0, 1].")
    alpha_low, alpha_high = request.alpha_bounds_deg
    beta_low, beta_high = request.beta_bounds_deg
    if not alpha_low < alpha_high or not beta_low < beta_high:
        raise ValueError("Optimization bounds must be increasing.")

    candidates: list[OptimizationCandidate] = []
    infeasible: list[tuple[ConstraintViolation, ...]] = []
    total_evaluations = 0
    completed_iterations = 0
    was_cancelled = False

    for lens_index, lens_id in enumerate(lens_ids):
        if cancelled is not None and cancelled():
            was_cancelled = True
            break
        rng = np.random.default_rng(request.seed + lens_index * 1009)
        count = request.mpso_particles
        positions = rng.uniform(0.0, 1.0, size=(count, 2))
        velocities = rng.uniform(-1.0, 4.0, size=(count, 2))
        evaluator = DesignEvaluator(request, lens_id)
        evaluations = _evaluate_population(positions, request, evaluator)
        personal_positions = positions.copy()
        personal_best = list(evaluations)
        global_index = min(range(count), key=lambda index: personal_best[index].deb_key)
        global_position = personal_positions[global_index].copy()
        global_best = personal_best[global_index]
        significant_reference = global_best.objective
        stagnation = 0

        for iteration in range(request.max_iterations):
            if cancelled is not None and cancelled():
                was_cancelled = True
                break
            progress_ratio = iteration / max(request.max_iterations - 1, 1)
            inertia = 0.9 + (0.2 - 0.9) * progress_ratio
            random_personal = rng.random((count, 2))
            random_global = rng.random((count, 2))
            velocities = (
                inertia * velocities
                + 2.5 * random_personal * (personal_positions - positions)
                + 2.5 * random_global * (global_position - positions)
            )
            velocities = np.clip(velocities, -1.0, 4.0)
            proposed = positions + velocities
            crossed = (proposed < 0.0) | (proposed > 1.0)
            positions = np.clip(proposed, 0.0, 1.0)
            velocities[crossed] = 0.0
            evaluations = _evaluate_population(positions, request, evaluator)

            for index, evaluation in enumerate(evaluations):
                if _is_better(evaluation, personal_best[index]):
                    personal_best[index] = evaluation
                    personal_positions[index] = positions[index]
            new_global_index = min(range(count), key=lambda index: personal_best[index].deb_key)
            new_global = personal_best[new_global_index]
            if _is_better(new_global, global_best):
                previous_objective = global_best.objective
                global_best = new_global
                global_position = personal_positions[new_global_index].copy()
                if global_best.valid and np.isfinite(global_best.objective):
                    reference = (
                        significant_reference
                        if np.isfinite(significant_reference)
                        else previous_objective
                    )
                    relative_improvement = (
                        (reference - global_best.objective) / max(abs(reference), 1e-12)
                        if np.isfinite(reference)
                        else 1.0
                    )
                    if relative_improvement >= request.mpso_stagnation_delta:
                        significant_reference = global_best.objective
                        stagnation = 0
                    else:
                        stagnation += 1
                else:
                    stagnation += 1
            else:
                stagnation += 1

            radius = float(
                np.max(np.linalg.norm(positions - global_position, axis=1)) / np.sqrt(2.0)
            )
            if (
                stagnation >= request.mpso_stagnation_iterations
                and radius < request.mpso_radius_threshold
            ):
                mutation_mask = rng.random(count) < request.mpso_mutation_probability
                closest = int(np.argmin(np.linalg.norm(positions - global_position, axis=1)))
                mutation_mask[closest] = False
                mutated_indices = np.flatnonzero(mutation_mask)
                if len(mutated_indices):
                    positions[mutated_indices] = rng.uniform(
                        0.0, 1.0, size=(len(mutated_indices), 2)
                    )
                    velocities[mutated_indices] = rng.uniform(
                        -1.0, 4.0, size=(len(mutated_indices), 2)
                    )
                    refreshed = _evaluate_population(positions[mutated_indices], request, evaluator)
                    for local_index, particle_index in enumerate(mutated_indices):
                        personal_positions[particle_index] = positions[particle_index]
                        personal_best[particle_index] = refreshed[local_index]
                stagnation = 0

            completed_iterations = max(completed_iterations, iteration + 1)
            if progress is not None:
                overall = (lens_index + (iteration + 1) / request.max_iterations) / len(lens_ids)
                progress(overall, f"M-PSO {lens_id}")

        total_evaluations += evaluator.evaluations
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
        algorithm=OptimizationAlgorithm.MPSO,
        candidates=tuple(candidates),
        seed=request.seed,
        iterations=completed_iterations,
        evaluations=total_evaluations,
        cancelled=was_cancelled,
        infeasible_reasons=_deduplicate_violations(infeasible),
        metadata=(("paper_bit_identical", False), ("boundary_rule", "clamp_zero_velocity")),
    )
