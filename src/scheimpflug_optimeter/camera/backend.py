"""Backend-neutral camera types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
from numpy.typing import NDArray


class CameraError(RuntimeError):
    """Base error for acquisition failures."""


class CameraUnavailableError(CameraError):
    """Raised when a requested device or its SDK is unavailable."""


class CameraStateError(CameraError):
    """Raised when an operation is invalid for the current camera state."""


@dataclass(frozen=True, slots=True)
class Roi:
    """Sensor region of interest in pixels."""

    x_px: int
    y_px: int
    width_px: int
    height_px: int

    def __post_init__(self) -> None:
        if self.x_px < 0 or self.y_px < 0:
            raise ValueError("ROI offsets must be non-negative")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("ROI width and height must be positive")


@dataclass(frozen=True, slots=True)
class CameraConfig:
    """Camera settings shared by real and simulated backends."""

    exposure_us: float = 2_000.0
    gain_db: float = 0.0
    frame_rate_hz: float = 30.0
    roi: Roi | None = None
    pixel_format: str = "Mono8"

    def __post_init__(self) -> None:
        if self.exposure_us <= 0:
            raise ValueError("exposure_us must be positive")
        if self.gain_db < 0:
            raise ValueError("gain_db must be non-negative")
        if self.frame_rate_hz <= 0:
            raise ValueError("frame_rate_hz must be positive")
        if self.pixel_format != "Mono8":
            raise ValueError("v0.1 supports the Mono8 pixel format only")


@dataclass(frozen=True, slots=True)
class CameraDevice:
    """Stable camera identity returned during device discovery."""

    serial: str
    model: str
    vendor: str = "Basler"
    transport: str = ""

    @property
    def selector_labels(self) -> tuple[str, ...]:
        return (self.serial, self.model)


@dataclass(frozen=True, slots=True)
class CameraFrame:
    """An owned monochrome frame.

    Backends must copy SDK-owned buffers before constructing this value.
    """

    image: NDArray[np.uint8]
    timestamp_ns: int
    frame_id: int
    device: CameraDevice

    def __post_init__(self) -> None:
        if self.image.ndim != 2 or self.image.dtype != np.uint8:
            raise ValueError("CameraFrame.image must be a 2-D uint8 Mono8 array")


@runtime_checkable
class CameraBackend(Protocol):
    """Minimal acquisition contract used by the application."""

    @property
    def connected(self) -> bool: ...

    @property
    def running(self) -> bool: ...

    @property
    def device(self) -> CameraDevice | None: ...

    @property
    def config(self) -> CameraConfig: ...

    def enumerate_devices(self) -> tuple[CameraDevice, ...]: ...

    def connect(self, selector: str | None = None) -> CameraDevice: ...

    def disconnect(self) -> None: ...

    def configure(self, config: CameraConfig) -> CameraConfig: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def latest_frame(self, timeout_s: float = 0.0) -> CameraFrame | None: ...

    def software_trigger(self, timeout_s: float = 1.0) -> CameraFrame: ...
