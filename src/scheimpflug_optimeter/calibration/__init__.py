"""Calibration algorithms and persisted calibration identities."""

from .identity import (
    CalibrationMismatchError,
    HardwareIdentity,
    assert_calibration_matches,
    calibration_mismatches,
)
from .intrinsic import (
    CalibrationGate,
    IntrinsicCalibration,
    assess_checkerboard_coverage,
    calibrate_intrinsics,
    detect_checkerboard,
)
from .laser_plane import LaserPlane, LaserPlaneFit, fit_laser_plane
from .models import CalibrationRecord
from .newton import NewtonRangeCalibration, fit_newton_range
from .thick_lens import (
    ThickLensFit,
    ThickLensParameters,
    effective_calibration_matrix,
    fit_thick_lens,
    project_points_thick_lens,
    thick_lens_matrix,
    tilt_matrix,
)

__all__ = [
    "CalibrationGate",
    "CalibrationMismatchError",
    "CalibrationRecord",
    "HardwareIdentity",
    "IntrinsicCalibration",
    "LaserPlane",
    "LaserPlaneFit",
    "NewtonRangeCalibration",
    "ThickLensFit",
    "ThickLensParameters",
    "assert_calibration_matches",
    "assess_checkerboard_coverage",
    "calibrate_intrinsics",
    "calibration_mismatches",
    "detect_checkerboard",
    "effective_calibration_matrix",
    "fit_laser_plane",
    "fit_newton_range",
    "fit_thick_lens",
    "project_points_thick_lens",
    "thick_lens_matrix",
    "tilt_matrix",
]
