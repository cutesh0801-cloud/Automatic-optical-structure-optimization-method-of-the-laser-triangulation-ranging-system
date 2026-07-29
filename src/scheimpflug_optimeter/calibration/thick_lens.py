"""Scheimpflug thick-lens matrix composition and robust fitting.

The implementation keeps the two matrices separate and composes them as
``K_f = B @ A``.  This avoids the sign transcription error that can arise when
copying the paper's expanded equation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import least_squares


@dataclass(frozen=True, slots=True)
class ThickLensParameters:
    focal_length_mm: float
    principal_x_px: float
    principal_y_px: float
    tilt_x_rad: float
    tilt_y_rad: float
    principal_plane_offset_mm: float
    pixel_pitch_x_mm: float
    pixel_pitch_y_mm: float

    def __post_init__(self) -> None:
        if self.focal_length_mm <= 0:
            raise ValueError("focal length must be positive")
        if self.pixel_pitch_x_mm <= 0 or self.pixel_pitch_y_mm <= 0:
            raise ValueError("pixel pitches must be positive")
        values = np.asarray(self.as_vector(), dtype=np.float64)
        if not np.all(np.isfinite(values)):
            raise ValueError("thick-lens parameters must be finite")

    def as_vector(self) -> NDArray[np.float64]:
        return np.asarray(
            [
                self.focal_length_mm,
                self.principal_x_px,
                self.principal_y_px,
                self.tilt_x_rad,
                self.tilt_y_rad,
                self.principal_plane_offset_mm,
            ],
            dtype=np.float64,
        )

    @classmethod
    def from_vector(
        cls,
        vector: NDArray[np.floating],
        *,
        pixel_pitch_x_mm: float,
        pixel_pitch_y_mm: float,
    ) -> ThickLensParameters:
        values = np.asarray(vector, dtype=np.float64).reshape(-1)
        if len(values) != 6:
            raise ValueError("thick-lens parameter vector must have six values")
        return cls(
            *map(float, values),
            pixel_pitch_x_mm=float(pixel_pitch_x_mm),
            pixel_pitch_y_mm=float(pixel_pitch_y_mm),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "focal_length_mm": self.focal_length_mm,
            "principal_x_px": self.principal_x_px,
            "principal_y_px": self.principal_y_px,
            "tilt_x_rad": self.tilt_x_rad,
            "tilt_y_rad": self.tilt_y_rad,
            "principal_plane_offset_mm": self.principal_plane_offset_mm,
            "pixel_pitch_x_mm": self.pixel_pitch_x_mm,
            "pixel_pitch_y_mm": self.pixel_pitch_y_mm,
        }


@dataclass(frozen=True, slots=True)
class ThickLensFit:
    parameters: ThickLensParameters
    rms_reprojection_error_px: float
    max_reprojection_error_px: float
    success: bool
    message: str
    evaluations: int


def tilt_matrix(tilt_x_rad: float, tilt_y_rad: float) -> NDArray[np.float64]:
    """Return ``A = R_y(tilt_y) @ R_x(tilt_x)``."""

    cx, sx = np.cos(tilt_x_rad), np.sin(tilt_x_rad)
    cy, sy = np.cos(tilt_y_rad), np.sin(tilt_y_rad)
    rotation_x = np.asarray([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    rotation_y = np.asarray([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    return rotation_y @ rotation_x


def thick_lens_matrix(parameters: ThickLensParameters) -> NDArray[np.float64]:
    """Return the pixel-scaled thick-lens projection matrix ``B``."""

    fx = parameters.focal_length_mm / parameters.pixel_pitch_x_mm
    fy = parameters.focal_length_mm / parameters.pixel_pitch_y_mm
    return np.asarray(
        [
            [fx, 0.0, parameters.principal_x_px],
            [0.0, fy, parameters.principal_y_px],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def effective_calibration_matrix(parameters: ThickLensParameters) -> NDArray[np.float64]:
    """Compose the unexpanded effective matrix exactly as ``B @ A``."""

    matrix_a = tilt_matrix(parameters.tilt_x_rad, parameters.tilt_y_rad)
    matrix_b = thick_lens_matrix(parameters)
    return matrix_b @ matrix_a


def project_points_thick_lens(
    points_camera_mm: NDArray[np.floating],
    parameters: ThickLensParameters,
) -> NDArray[np.float64]:
    """Project known 3-D camera-frame points through the tilted thick lens."""

    points = np.asarray(points_camera_mm, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError("points_camera_mm must have shape (N, 3)")
    if not np.all(np.isfinite(points)):
        raise ValueError("3-D points must be finite")
    matrix_a = tilt_matrix(parameters.tilt_x_rad, parameters.tilt_y_rad)
    optical_axis_camera = matrix_a.T @ np.asarray([0.0, 0.0, 1.0])
    principal_origin = parameters.principal_plane_offset_mm * optical_axis_camera
    directions = points - principal_origin
    homogeneous = (effective_calibration_matrix(parameters) @ directions.T).T
    valid = homogeneous[:, 2] > np.finfo(float).eps
    result = np.full((len(points), 2), np.nan, dtype=np.float64)
    result[valid] = homogeneous[valid, :2] / homogeneous[valid, 2, None]
    return result


def fit_thick_lens(
    points_camera_mm: NDArray[np.floating],
    image_points_px: NDArray[np.floating],
    initial: ThickLensParameters,
    *,
    lower_bounds: NDArray[np.floating] | None = None,
    upper_bounds: NDArray[np.floating] | None = None,
    loss: str = "soft_l1",
    f_scale_px: float = 1.0,
) -> ThickLensFit:
    """Fit six thick-lens parameters while keeping Brown distortion fixed upstream."""

    points = np.asarray(points_camera_mm, dtype=np.float64)
    image_points = np.asarray(image_points_px, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or image_points.shape != (len(points), 2):
        raise ValueError("expected matched (N,3) object and (N,2) image points")
    if len(points) < 8 or not np.all(np.isfinite(points)) or not np.all(np.isfinite(image_points)):
        raise ValueError("at least eight finite thick-lens correspondences are required")
    if f_scale_px <= 0:
        raise ValueError("f_scale_px must be positive")

    if lower_bounds is None:
        lower = np.asarray(
            [
                np.finfo(float).eps,
                -np.inf,
                -np.inf,
                np.deg2rad(-45.0),
                np.deg2rad(-45.0),
                -np.inf,
            ]
        )
    else:
        lower = np.asarray(lower_bounds, dtype=np.float64).reshape(6)
    if upper_bounds is None:
        upper = np.asarray([np.inf, np.inf, np.inf, np.deg2rad(45.0), np.deg2rad(45.0), np.inf])
    else:
        upper = np.asarray(upper_bounds, dtype=np.float64).reshape(6)
    if np.any(lower >= upper):
        raise ValueError("every lower bound must be less than its upper bound")

    def residual(vector: NDArray[np.float64]) -> NDArray[np.float64]:
        candidate = ThickLensParameters.from_vector(
            vector,
            pixel_pitch_x_mm=initial.pixel_pitch_x_mm,
            pixel_pitch_y_mm=initial.pixel_pitch_y_mm,
        )
        predicted = project_points_thick_lens(points, candidate)
        if not np.all(np.isfinite(predicted)):
            return np.full(image_points.size, 1e9)
        return (predicted - image_points).reshape(-1)

    result = least_squares(
        residual,
        initial.as_vector(),
        bounds=(lower, upper),
        loss=loss,
        f_scale=f_scale_px,
        x_scale="jac",
        max_nfev=5_000,
    )
    fitted = ThickLensParameters.from_vector(
        result.x,
        pixel_pitch_x_mm=initial.pixel_pitch_x_mm,
        pixel_pitch_y_mm=initial.pixel_pitch_y_mm,
    )
    errors = (project_points_thick_lens(points, fitted) - image_points).reshape(-1, 2)
    magnitudes = np.linalg.norm(errors, axis=1)
    return ThickLensFit(
        parameters=fitted,
        rms_reprojection_error_px=float(np.sqrt(np.mean(magnitudes**2))),
        max_reprojection_error_px=float(np.max(magnitudes)),
        success=bool(result.success),
        message=str(result.message),
        evaluations=int(result.nfev),
    )
