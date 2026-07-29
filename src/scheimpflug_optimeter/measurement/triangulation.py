"""Pixel-ray and calibrated laser-plane intersection."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from scheimpflug_optimeter.calibration import LaserPlane

from .models import CrossSection, StripeResult


def pixels_to_camera_rays(
    pixels_xy: NDArray[np.floating],
    camera_matrix: NDArray[np.floating],
    *,
    distortion_coefficients: NDArray[np.floating] | None = None,
) -> NDArray[np.float64]:
    """Convert pixel coordinates to normalized camera-frame ray directions."""

    pixels = np.asarray(pixels_xy, dtype=np.float64)
    matrix = np.asarray(camera_matrix, dtype=np.float64)
    if pixels.ndim != 2 or pixels.shape[1] != 2:
        raise ValueError("pixels_xy must have shape (N, 2)")
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("camera_matrix must be a finite 3x3 matrix")
    if abs(np.linalg.det(matrix)) <= np.finfo(float).eps:
        raise ValueError("camera_matrix must be invertible")
    if distortion_coefficients is not None:
        distortion = np.asarray(distortion_coefficients, dtype=np.float64).reshape(-1)
        normalized = cv2.undistortPoints(
            pixels.reshape(-1, 1, 2),
            matrix,
            distortion,
        ).reshape(-1, 2)
        rays = np.column_stack((normalized, np.ones(len(normalized))))
    else:
        homogeneous = np.column_stack((pixels, np.ones(len(pixels))))
        rays = np.linalg.solve(matrix, homogeneous.T).T
    norms = np.linalg.norm(rays, axis=1)
    valid = norms > np.finfo(float).eps
    result = np.full_like(rays, np.nan)
    result[valid] = rays[valid] / norms[valid, None]
    return result


def ray_plane_intersections(
    ray_origins_mm: NDArray[np.floating],
    ray_directions: NDArray[np.floating],
    plane: LaserPlane,
    *,
    require_forward: bool = True,
    denominator_epsilon: float = 1e-12,
) -> tuple[NDArray[np.float64], NDArray[np.bool_]]:
    """Intersect a vectorized set of rays with a calibrated laser plane."""

    origins = np.asarray(ray_origins_mm, dtype=np.float64)
    directions = np.asarray(ray_directions, dtype=np.float64)
    if directions.ndim != 2 or directions.shape[1] != 3:
        raise ValueError("ray_directions must have shape (N, 3)")
    if origins.shape == (3,):
        origins = np.broadcast_to(origins, directions.shape)
    if origins.shape != directions.shape:
        raise ValueError("ray_origins_mm must be one 3-vector or match ray directions")
    if denominator_epsilon <= 0:
        raise ValueError("denominator_epsilon must be positive")
    denominator = directions @ plane.normal
    numerator = -(origins @ plane.normal + plane.offset_mm)
    scale = np.full(len(directions), np.nan, dtype=np.float64)
    valid = np.isfinite(denominator) & (np.abs(denominator) > denominator_epsilon)
    scale[valid] = numerator[valid] / denominator[valid]
    if require_forward:
        valid &= scale > 0
    points = np.full_like(directions, np.nan)
    points[valid] = origins[valid] + scale[valid, None] * directions[valid]
    return points, valid


def triangulate_cross_section(
    stripe: StripeResult,
    camera_matrix: NDArray[np.floating],
    laser_plane: LaserPlane,
    *,
    distortion_coefficients: NDArray[np.floating] | None = None,
    rotation_camera_to_measurement: NDArray[np.floating] | None = None,
    translation_camera_origin_mm: NDArray[np.floating] | None = None,
    minimum_confidence: float = 0.2,
    metadata: dict[str, Any] | None = None,
) -> CrossSection:
    """Triangulate all accepted stripe pixels into the measurement coordinate frame."""

    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be between zero and one")
    rotation = (
        np.eye(3, dtype=np.float64)
        if rotation_camera_to_measurement is None
        else np.asarray(rotation_camera_to_measurement, dtype=np.float64)
    )
    translation = (
        np.zeros(3, dtype=np.float64)
        if translation_camera_origin_mm is None
        else np.asarray(translation_camera_origin_mm, dtype=np.float64)
    )
    if rotation.shape != (3, 3) or translation.shape != (3,):
        raise ValueError("extrinsics must be a 3x3 rotation and 3-vector translation")
    if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-7):
        raise ValueError("rotation_camera_to_measurement must be orthonormal")
    if np.linalg.det(rotation) < 0.999999:
        raise ValueError("rotation_camera_to_measurement must be a proper rotation")

    pixels = stripe.pixels_xy
    finite_pixels = np.all(np.isfinite(pixels), axis=1)
    safe_pixels = pixels.copy()
    safe_pixels[~finite_pixels] = 0.0
    camera_rays = pixels_to_camera_rays(
        safe_pixels,
        camera_matrix,
        distortion_coefficients=distortion_coefficients,
    )
    measurement_rays = (rotation @ camera_rays.T).T
    points, geometric_valid = ray_plane_intersections(
        translation,
        measurement_rays,
        laser_plane,
    )
    valid = (
        stripe.valid_mask
        & finite_pixels
        & (stripe.confidence >= minimum_confidence)
        & geometric_valid
    )
    points[~valid] = np.nan
    return CrossSection(
        pixels_xy=pixels,
        points_mm=points,
        confidence=stripe.confidence.copy(),
        valid_mask=valid,
        metadata=dict(metadata or {}),
    )
