"""Deterministic synthetic camera for development and CI."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import numpy as np
from numpy.typing import NDArray

from .backend import (
    CameraConfig,
    CameraDevice,
    CameraFrame,
    CameraStateError,
    CameraUnavailableError,
    Roi,
)


class MockCameraBackend:
    """Generate noisy Mono8 frames containing a sub-pixel Gaussian laser stripe.

    Only the newest frame is retained.  This mirrors Basler's
    ``GrabStrategy_LatestImageOnly`` and prevents latency from accumulating.
    """

    def __init__(
        self,
        *,
        width_px: int = 1282,
        height_px: int = 1026,
        stripe_x_px: float | None = None,
        stripe_slope_px_per_row: float = 0.025,
        stripe_sigma_px: float = 1.15,
        background_level: float = 18.0,
        peak_level: float = 205.0,
        noise_std: float = 1.5,
        seed: int = 2026,
    ) -> None:
        if width_px <= 0 or height_px <= 0:
            raise ValueError("frame dimensions must be positive")
        if stripe_sigma_px <= 0 or noise_std < 0:
            raise ValueError("stripe_sigma_px must be positive and noise_std non-negative")
        self._sensor_width = width_px
        self._sensor_height = height_px
        self._stripe_x = stripe_x_px if stripe_x_px is not None else (width_px - 1) / 2
        self._stripe_slope = stripe_slope_px_per_row
        self._stripe_sigma = stripe_sigma_px
        self._background = background_level
        self._peak = peak_level
        self._noise_std = noise_std
        self._rng = np.random.default_rng(seed)
        self._device_info = CameraDevice(
            serial="MOCK-ACA1300-0001",
            model="acA1300-60gm (simulated)",
            vendor="Basler/Mock",
            transport="Synthetic",
        )
        self._device: CameraDevice | None = None
        self._config = CameraConfig(
            frame_rate_hz=30.0,
            roi=Roi(0, 0, width_px, height_px),
        )
        self._frame_id = 0
        self._latest: CameraFrame | None = None
        self._connected = False
        self._running = False
        self._lock = threading.Lock()
        self._generation_lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def running(self) -> bool:
        return self._running

    @property
    def device(self) -> CameraDevice | None:
        return self._device

    @property
    def config(self) -> CameraConfig:
        return self._config

    def enumerate_devices(self) -> tuple[CameraDevice, ...]:
        return (self._device_info,)

    def connect(self, selector: str | None = None) -> CameraDevice:
        if selector and selector not in self._device_info.selector_labels:
            raise CameraUnavailableError(f"mock camera not found: {selector}")
        self._connected = True
        self._device = self._device_info
        return self._device_info

    def disconnect(self) -> None:
        self.stop()
        with self._condition:
            self._connected = False
            self._device = None
            self._latest = None

    def configure(self, config: CameraConfig) -> CameraConfig:
        if self.running:
            raise CameraStateError("stop acquisition before changing camera settings")
        roi = config.roi or Roi(0, 0, self._sensor_width, self._sensor_height)
        if roi.x_px + roi.width_px > self._sensor_width:
            raise ValueError("ROI exceeds sensor width")
        if roi.y_px + roi.height_px > self._sensor_height:
            raise ValueError("ROI exceeds sensor height")
        self._config = replace(config, roi=roi)
        return self._config

    def start(self) -> None:
        if not self.connected:
            raise CameraStateError("connect the camera before starting acquisition")
        if self.running:
            return
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(
            target=self._acquisition_loop,
            name="mock-camera-acquisition",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self.running:
            return
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._running = False

    def latest_frame(self, timeout_s: float = 0.0) -> CameraFrame | None:
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        with self._condition:
            if self._latest is None and timeout_s:
                self._condition.wait_for(lambda: self._latest is not None, timeout=timeout_s)
            return self._latest

    def software_trigger(self, timeout_s: float = 1.0) -> CameraFrame:
        del timeout_s
        if not self.connected or self._device is None:
            raise CameraStateError("connect the camera before triggering")
        with self._generation_lock:
            frame = self._make_frame()
        with self._condition:
            self._latest = frame
            self._condition.notify_all()
        return frame

    def expected_stripe_x(self, output_row_px: NDArray[np.floating] | float) -> NDArray[np.float64]:
        """Return the exact stripe position in the current ROI coordinate system."""

        roi = self._config.roi or Roi(0, 0, self._sensor_width, self._sensor_height)
        rows = np.asarray(output_row_px, dtype=np.float64)
        sensor_y = rows + roi.y_px
        center_y = (self._sensor_height - 1) / 2
        return self._stripe_x + self._stripe_slope * (sensor_y - center_y) - roi.x_px

    def _acquisition_loop(self) -> None:
        deadline = time.monotonic()
        while not self._stop_event.is_set():
            with self._generation_lock:
                frame = self._make_frame()
            with self._condition:
                self._latest = frame
                self._condition.notify_all()
            deadline += 1.0 / self._config.frame_rate_hz
            self._stop_event.wait(max(0.0, deadline - time.monotonic()))

    def _make_frame(self) -> CameraFrame:
        if self._device is None:
            raise CameraStateError("mock camera is disconnected")
        roi = self._config.roi or Roi(0, 0, self._sensor_width, self._sensor_height)
        y_sensor = np.arange(roi.y_px, roi.y_px + roi.height_px, dtype=np.float64)
        x_sensor = np.arange(roi.x_px, roi.x_px + roi.width_px, dtype=np.float64)
        center_y = (self._sensor_height - 1) / 2
        centers = self._stripe_x + self._stripe_slope * (y_sensor - center_y)
        squared_distance = (x_sensor[None, :] - centers[:, None]) ** 2
        stripe = self._peak * np.exp(-0.5 * squared_distance / self._stripe_sigma**2)
        noise = self._rng.normal(0.0, self._noise_std, size=stripe.shape)
        image = np.clip(self._background + stripe + noise, 0, 255).astype(np.uint8)
        self._frame_id += 1
        return CameraFrame(
            image=image,
            timestamp_ns=time.time_ns(),
            frame_id=self._frame_id,
            device=self._device,
        )
