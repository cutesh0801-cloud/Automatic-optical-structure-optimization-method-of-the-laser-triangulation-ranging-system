"""As-built Newton range calibration."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares


@dataclass(frozen=True, slots=True)
class NewtonRangeCalibration:
    """Linear inverse-range model ``1 / R = a * pixel + b``."""

    a_per_mm_px: float
    b_per_mm: float
    rms_inverse_range_per_mm: float
    sample_count: int

    def range_mm(
        self,
        pixel_coordinate_px: NDArray[np.floating] | float,
    ) -> NDArray[np.float64]:
        pixels = np.asarray(pixel_coordinate_px, dtype=np.float64)
        denominator = self.a_per_mm_px * pixels + self.b_per_mm
        result = np.full_like(denominator, np.nan, dtype=np.float64)
        valid = denominator > np.finfo(float).eps
        result[valid] = 1.0 / denominator[valid]
        return result

    def pixel_coordinate_px(
        self,
        range_mm: NDArray[np.floating] | float,
    ) -> NDArray[np.float64]:
        ranges = np.asarray(range_mm, dtype=np.float64)
        if np.any(ranges <= 0):
            raise ValueError("range values must be positive")
        if abs(self.a_per_mm_px) <= np.finfo(float).eps:
            raise ZeroDivisionError("Newton calibration slope is zero")
        return (1.0 / ranges - self.b_per_mm) / self.a_per_mm_px

    def to_dict(self) -> dict[str, object]:
        return {
            "a_per_mm_px": self.a_per_mm_px,
            "b_per_mm": self.b_per_mm,
            "rms_inverse_range_per_mm": self.rms_inverse_range_per_mm,
            "sample_count": self.sample_count,
        }


def fit_newton_range(
    pixel_coordinate_px: NDArray[np.floating],
    range_mm: NDArray[np.floating],
    *,
    loss: str = "soft_l1",
) -> NewtonRangeCalibration:
    """Robustly fit an as-built inverse-distance correction."""

    pixels = np.asarray(pixel_coordinate_px, dtype=np.float64).reshape(-1)
    ranges = np.asarray(range_mm, dtype=np.float64).reshape(-1)
    if len(pixels) != len(ranges) or len(pixels) < 3:
        raise ValueError("at least three matched pixel/range samples are required")
    if not np.all(np.isfinite(pixels)) or not np.all(np.isfinite(ranges)):
        raise ValueError("calibration samples must be finite")
    if np.any(ranges <= 0) or np.ptp(pixels) <= np.finfo(float).eps:
        raise ValueError("ranges must be positive and pixel positions must vary")
    inverse_range = 1.0 / ranges
    initial = np.polyfit(pixels, inverse_range, 1)
    initial_residual = initial[0] * pixels + initial[1] - inverse_range
    residual_median = float(np.median(initial_residual))
    scale = max(
        1.4826 * float(np.median(np.abs(initial_residual - residual_median))),
        1e-12,
    )
    result = least_squares(
        lambda coefficients: coefficients[0] * pixels + coefficients[1] - inverse_range,
        initial,
        loss=loss,
        f_scale=scale,
    )
    if not result.success:
        raise RuntimeError(f"Newton range fit failed: {result.message}")
    residuals = result.x[0] * pixels + result.x[1] - inverse_range
    return NewtonRangeCalibration(
        a_per_mm_px=float(result.x[0]),
        b_per_mm=float(result.x[1]),
        rms_inverse_range_per_mm=float(np.sqrt(np.mean(residuals**2))),
        sample_count=len(pixels),
    )
