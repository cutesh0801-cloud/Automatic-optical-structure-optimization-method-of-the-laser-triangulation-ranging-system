"""Public optical design optimization API."""

from __future__ import annotations

from collections.abc import Callable

from scheimpflug_optimeter.models import (
    OptimizationAlgorithm,
    OptimizationRequest,
    OptimizationResult,
)

from .mpso import optimize_mpso
from .scipy_de import optimize_scipy


def optimize_design(
    request: OptimizationRequest,
    *,
    progress: Callable[[float, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> OptimizationResult:
    """Dispatch to the selected deterministic optimization implementation."""

    try:
        algorithm = OptimizationAlgorithm(request.algorithm)
    except ValueError as error:
        raise ValueError(f"Unsupported optimization algorithm: {request.algorithm!r}") from error
    if algorithm is OptimizationAlgorithm.SCIPY:
        return optimize_scipy(request, progress=progress, cancelled=cancelled)
    return optimize_mpso(request, progress=progress, cancelled=cancelled)


__all__ = ["optimize_design", "optimize_mpso", "optimize_scipy"]
