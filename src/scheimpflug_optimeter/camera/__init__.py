"""Camera acquisition boundaries.

The package deliberately exposes one small backend protocol.  Importing it never
imports pypylon; the optional Basler SDK is loaded only when a Basler operation is
requested.
"""

from .backend import (
    CameraBackend,
    CameraConfig,
    CameraDevice,
    CameraError,
    CameraFrame,
    CameraStateError,
    CameraUnavailableError,
    Roi,
)
from .basler import BaslerCameraBackend
from .mock import MockCameraBackend

__all__ = [
    "BaslerCameraBackend",
    "CameraBackend",
    "CameraConfig",
    "CameraDevice",
    "CameraError",
    "CameraFrame",
    "CameraStateError",
    "CameraUnavailableError",
    "MockCameraBackend",
    "Roi",
]
