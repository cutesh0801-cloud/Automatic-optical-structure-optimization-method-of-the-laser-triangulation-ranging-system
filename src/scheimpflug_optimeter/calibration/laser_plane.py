"""Robust laser-plane fitting."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class LaserPlane:
    """Plane ``normal · point + offset_mm = 0`` in measurement coordinates."""

    normal: NDArray[np.float64]
    offset_mm: float

    def __post_init__(self) -> None:
        normal = np.asarray(self.normal, dtype=np.float64)
        if normal.shape != (3,) or not np.all(np.isfinite(normal)):
            raise ValueError("plane normal must be a finite 3-vector")
        magnitude = float(np.linalg.norm(normal))
        if magnitude <= np.finfo(float).eps:
            raise ValueError("plane normal must be non-zero")
        normalized = normal / magnitude
        object.__setattr__(self, "normal", normalized)
        object.__setattr__(self, "offset_mm", float(self.offset_mm) / magnitude)

    def signed_distance_mm(
        self,
        points_mm: NDArray[np.floating],
    ) -> NDArray[np.float64]:
        points = np.asarray(points_mm, dtype=np.float64)
        if points.shape[-1] != 3:
            raise ValueError("points must end with three coordinates")
        return points @ self.normal + self.offset_mm

    def to_dict(self) -> dict[str, object]:
        return {"normal": self.normal.tolist(), "offset_mm": self.offset_mm}


@dataclass(frozen=True, slots=True)
class LaserPlaneFit:
    plane: LaserPlane
    inlier_mask: NDArray[np.bool_]
    rms_residual_mm: float
    max_residual_mm: float
    iterations: int


def fit_laser_plane(
    points_mm: NDArray[np.floating],
    *,
    mad_sigma: float = 3.5,
    max_iterations: int = 12,
    minimum_threshold_mm: float = 1e-5,
    preferred_normal: NDArray[np.floating] | None = None,
) -> LaserPlaneFit:
    """Fit by SVD while iteratively rejecting absolute-distance MAD outliers."""

    points = np.asarray(points_mm, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points_mm must have shape (N, 3)")
    if len(points) < 3 or not np.all(np.isfinite(points)):
        raise ValueError("at least three finite points are required")
    if mad_sigma <= 0 or max_iterations <= 0 or minimum_threshold_mm <= 0:
        raise ValueError("robust fitting parameters must be positive")

    inliers = np.ones(len(points), dtype=bool)
    previous: NDArray[np.bool_] | None = None
    iteration = 0
    for _iteration in range(1, max_iterations + 1):
        iteration = _iteration
        if np.count_nonzero(inliers) < 3:
            raise ValueError("outlier rejection left fewer than three plane points")
        plane = _svd_plane(points[inliers], preferred_normal)
        absolute = np.abs(plane.signed_distance_mm(points))
        inlier_distances = absolute[inliers]
        median = float(np.median(inlier_distances))
        mad = float(np.median(np.abs(inlier_distances - median)))
        robust_sigma = 1.4826 * mad
        threshold = max(minimum_threshold_mm, median + mad_sigma * robust_sigma)
        updated = absolute <= threshold
        if np.count_nonzero(updated) < 3:
            break
        if previous is not None and np.array_equal(updated, inliers):
            inliers = updated
            break
        previous = inliers
        inliers = updated

    plane = _svd_plane(points[inliers], preferred_normal)
    residuals = np.abs(plane.signed_distance_mm(points[inliers]))
    return LaserPlaneFit(
        plane=plane,
        inlier_mask=inliers,
        rms_residual_mm=float(np.sqrt(np.mean(residuals**2))),
        max_residual_mm=float(np.max(residuals)),
        iterations=iteration,
    )


def _svd_plane(
    points: NDArray[np.float64],
    preferred_normal: NDArray[np.floating] | None,
) -> LaserPlane:
    center = np.mean(points, axis=0)
    _, singular_values, vh = np.linalg.svd(points - center, full_matrices=False)
    if len(singular_values) < 2 or singular_values[-2] <= np.finfo(float).eps:
        raise ValueError("plane points are collinear or coincident")
    normal = vh[-1]
    if preferred_normal is not None:
        preferred = np.asarray(preferred_normal, dtype=np.float64)
        if preferred.shape != (3,) or np.linalg.norm(preferred) == 0:
            raise ValueError("preferred_normal must be a non-zero 3-vector")
        if np.dot(normal, preferred) < 0:
            normal = -normal
    else:
        largest_component = int(np.argmax(np.abs(normal)))
        if normal[largest_component] < 0:
            normal = -normal
    return LaserPlane(normal, -float(np.dot(normal, center)))
