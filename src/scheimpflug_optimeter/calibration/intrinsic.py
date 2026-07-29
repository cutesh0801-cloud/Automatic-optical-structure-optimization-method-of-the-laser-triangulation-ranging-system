"""OpenCV Brown-model intrinsic calibration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np
from numpy.typing import NDArray


class CalibrationGate(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class IntrinsicCalibration:
    camera_matrix: NDArray[np.float64]
    distortion_coefficients: NDArray[np.float64]
    rms_reprojection_error_px: float
    per_view_error_px: NDArray[np.float64]
    image_size_px: tuple[int, int]
    view_count: int
    coverage_quadrants: tuple[bool, bool, bool, bool]
    gate: CalibrationGate

    @property
    def accepted(self) -> bool:
        return self.gate is not CalibrationGate.FAIL

    def to_dict(self) -> dict[str, object]:
        return {
            "camera_matrix": self.camera_matrix.tolist(),
            "distortion_coefficients": self.distortion_coefficients.tolist(),
            "rms_reprojection_error_px": self.rms_reprojection_error_px,
            "per_view_error_px": self.per_view_error_px.tolist(),
            "image_size_px": list(self.image_size_px),
            "view_count": self.view_count,
            "coverage_quadrants": list(self.coverage_quadrants),
            "gate": self.gate.value,
        }


def detect_checkerboard(
    image: NDArray[np.generic],
    pattern_size: tuple[int, int],
) -> NDArray[np.float32] | None:
    """Detect and sub-pixel refine inner checkerboard corners."""

    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    elif image.ndim == 2:
        gray = image
    else:
        raise ValueError("image must be grayscale or BGR")
    if pattern_size[0] < 2 or pattern_size[1] < 2:
        raise ValueError("checkerboard pattern must be at least 2x2 inner corners")
    found, corners = cv2.findChessboardCorners(
        gray,
        pattern_size,
        cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE,
    )
    if not found:
        return None
    criteria = (
        cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_MAX_ITER,
        40,
        1e-3,
    )
    refined = cv2.cornerSubPix(
        gray,
        corners.astype(np.float32),
        (5, 5),
        (-1, -1),
        criteria,
    )
    return refined.reshape(-1, 2)


def assess_checkerboard_coverage(
    image_points: Sequence[NDArray[np.floating]],
    image_size_px: tuple[int, int],
) -> tuple[bool, bool, bool, bool]:
    """Report whether checkerboard centers cover every image quadrant."""

    width, height = image_size_px
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")
    covered = [False, False, False, False]
    for points in image_points:
        array = np.asarray(points, dtype=np.float64).reshape(-1, 2)
        if array.size == 0:
            continue
        center_x, center_y = np.mean(array, axis=0)
        index = (1 if center_x >= width / 2 else 0) + (2 if center_y >= height / 2 else 0)
        covered[index] = True
    return tuple(covered)  # type: ignore[return-value]


def calibrate_intrinsics(
    object_points: Sequence[NDArray[np.floating]],
    image_points: Sequence[NDArray[np.floating]],
    image_size_px: tuple[int, int],
    *,
    min_views: int = 15,
    pass_rms_px: float = 0.5,
    fail_rms_px: float = 1.0,
    flags: int = 0,
) -> IntrinsicCalibration:
    """Calibrate a Brown camera model and apply the v0.1 quality gate."""

    if len(object_points) != len(image_points):
        raise ValueError("object_points and image_points must have equal view counts")
    if len(object_points) < min_views:
        raise ValueError(f"at least {min_views} checkerboard views are required")
    if pass_rms_px <= 0 or fail_rms_px <= pass_rms_px:
        raise ValueError("RMS thresholds must satisfy 0 < pass < fail")
    width, height = image_size_px
    if width <= 0 or height <= 0:
        raise ValueError("image dimensions must be positive")

    objects: list[NDArray[np.float32]] = []
    images: list[NDArray[np.float32]] = []
    for index, (object_view, image_view) in enumerate(
        zip(object_points, image_points, strict=True)
    ):
        obj = np.asarray(object_view, dtype=np.float32).reshape(-1, 3)
        img = np.asarray(image_view, dtype=np.float32).reshape(-1, 2)
        if len(obj) < 4 or len(obj) != len(img):
            raise ValueError(f"view {index} needs at least four matched points")
        if not np.all(np.isfinite(obj)) or not np.all(np.isfinite(img)):
            raise ValueError(f"view {index} contains non-finite points")
        objects.append(obj)
        images.append(img.reshape(-1, 1, 2))

    rms, camera_matrix, distortion, rotations, translations = cv2.calibrateCamera(
        objects,
        images,
        image_size_px,
        None,
        None,
        flags=flags,
    )
    per_view = np.empty(len(objects), dtype=np.float64)
    for index, (obj, observed, rotation, translation) in enumerate(
        zip(objects, images, rotations, translations, strict=True)
    ):
        projected, _ = cv2.projectPoints(
            obj,
            rotation,
            translation,
            camera_matrix,
            distortion,
        )
        delta = observed.reshape(-1, 2) - projected.reshape(-1, 2)
        per_view[index] = float(np.sqrt(np.mean(np.sum(delta**2, axis=1))))

    coverage = assess_checkerboard_coverage(images, image_size_px)
    if rms <= pass_rms_px and all(coverage):
        gate = CalibrationGate.PASS
    elif rms > fail_rms_px:
        gate = CalibrationGate.FAIL
    else:
        gate = CalibrationGate.WARNING
    return IntrinsicCalibration(
        camera_matrix=np.asarray(camera_matrix, dtype=np.float64),
        distortion_coefficients=np.asarray(distortion, dtype=np.float64).reshape(-1),
        rms_reprojection_error_px=float(rms),
        per_view_error_px=per_view,
        image_size_px=image_size_px,
        view_count=len(objects),
        coverage_quadrants=coverage,
        gate=gate,
    )
