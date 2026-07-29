"""Versioned persisted calibration record."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import numpy as np
from numpy.typing import NDArray

from .identity import HardwareIdentity
from .intrinsic import IntrinsicCalibration
from .laser_plane import LaserPlane
from .newton import NewtonRangeCalibration
from .thick_lens import ThickLensParameters


@dataclass(frozen=True, slots=True)
class CalibrationRecord:
    """All calibration state needed to turn pixels into measurement points."""

    identity: HardwareIdentity
    intrinsic: IntrinsicCalibration
    thick_lens: ThickLensParameters
    laser_plane: LaserPlane
    rotation_camera_to_measurement: NDArray[np.float64]
    translation_camera_origin_mm: NDArray[np.float64]
    newton_range: NewtonRangeCalibration | None = None
    quality_metrics: dict[str, float] = field(default_factory=dict)
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    schema_version: int = 1

    def __post_init__(self) -> None:
        rotation = np.asarray(self.rotation_camera_to_measurement, dtype=np.float64)
        translation = np.asarray(self.translation_camera_origin_mm, dtype=np.float64)
        if self.schema_version != 1:
            raise ValueError(f"unsupported calibration schema: {self.schema_version}")
        if rotation.shape != (3, 3) or translation.shape != (3,):
            raise ValueError("calibration extrinsics have invalid dimensions")
        if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-7):
            raise ValueError("calibration rotation must be orthonormal")
        if np.linalg.det(rotation) < 0.999999:
            raise ValueError("calibration rotation must be proper")
        if not all(np.isfinite(value) for value in self.quality_metrics.values()):
            raise ValueError("quality metrics must be finite")
        object.__setattr__(self, "rotation_camera_to_measurement", rotation)
        object.__setattr__(self, "translation_camera_origin_mm", translation)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "created_at_utc": self.created_at_utc,
            "identity": self.identity.to_dict(),
            "intrinsic": self.intrinsic.to_dict(),
            "thick_lens": self.thick_lens.to_dict(),
            "laser_plane": self.laser_plane.to_dict(),
            "rotation_camera_to_measurement": self.rotation_camera_to_measurement.tolist(),
            "translation_camera_origin_mm": self.translation_camera_origin_mm.tolist(),
            "newton_range": None if self.newton_range is None else self.newton_range.to_dict(),
            "quality_metrics": dict(self.quality_metrics),
        }
