"""Optional Basler pypylon backend."""

from __future__ import annotations

import importlib
import time
from typing import Any

import numpy as np

from .backend import (
    CameraConfig,
    CameraDevice,
    CameraError,
    CameraFrame,
    CameraStateError,
    CameraUnavailableError,
    Roi,
)


def _load_pylon() -> Any:
    """Load pypylon only when hardware functionality is requested."""

    try:
        return importlib.import_module("pypylon.pylon")
    except (ImportError, OSError) as exc:
        raise CameraUnavailableError(
            "Basler support requires pypylon and the matching pylon runtime. "
            "Install the optional 'camera' dependency and Basler pylon."
        ) from exc


class BaslerCameraBackend:
    """Basler backend using ``GrabStrategy_LatestImageOnly`` for live preview."""

    def __init__(self) -> None:
        self._camera: Any | None = None
        self._device: CameraDevice | None = None
        self._config = CameraConfig()
        self._frame_id = 0

    @property
    def connected(self) -> bool:
        return bool(self._camera is not None and self._camera.IsOpen())

    @property
    def running(self) -> bool:
        return bool(self._camera is not None and self._camera.IsGrabbing())

    @property
    def device(self) -> CameraDevice | None:
        return self._device

    @property
    def config(self) -> CameraConfig:
        return self._config

    def enumerate_devices(self) -> tuple[CameraDevice, ...]:
        pylon = _load_pylon()
        factory = pylon.TlFactory.GetInstance()
        return tuple(self._to_device_info(info) for info in factory.EnumerateDevices())

    def connect(self, selector: str | None = None) -> CameraDevice:
        if self.connected:
            connected_labels = self._device.selector_labels if self._device else ()
            if selector is None or selector in connected_labels:
                assert self._device is not None
                return self._device
            self.disconnect()
        pylon = _load_pylon()
        factory = pylon.TlFactory.GetInstance()
        devices = list(factory.EnumerateDevices())
        selected = next(
            (
                item
                for item in devices
                if selector is None
                or selector in (str(item.GetSerialNumber()), str(item.GetModelName()))
            ),
            None,
        )
        if selected is None:
            requested = selector or "first available Basler camera"
            raise CameraUnavailableError(f"Basler camera not found: {requested}")
        try:
            camera = pylon.InstantCamera(factory.CreateDevice(selected))
            camera.Open()
            self._camera = camera
            self._device = self._to_device_info(selected)
            self._set_enum("PixelFormat", "Mono8")
            self._set_enum("ExposureAuto", "Off")
            self._set_enum("GainAuto", "Off")
            return self._device
        except Exception as exc:
            self._camera = None
            self._device = None
            raise CameraError(f"failed to open Basler camera: {exc}") from exc

    def disconnect(self) -> None:
        camera = self._camera
        if camera is None:
            return
        try:
            self.stop()
            if camera.IsOpen():
                camera.Close()
        finally:
            self._camera = None
            self._device = None

    def configure(self, config: CameraConfig) -> CameraConfig:
        camera = self._require_camera()
        if camera.IsGrabbing():
            raise CameraStateError("stop acquisition before changing camera settings")
        self._set_enum("PixelFormat", "Mono8", required=True)
        self._set_enum("ExposureAuto", "Off")
        self._set_enum("GainAuto", "Off")
        self._set_float(("ExposureTime", "ExposureTimeAbs"), config.exposure_us)
        self._set_float(("Gain", "GainRaw"), config.gain_db)
        self._set_bool("AcquisitionFrameRateEnable", True)
        self._set_float(("AcquisitionFrameRate", "AcquisitionFrameRateAbs"), config.frame_rate_hz)
        roi = config.roi
        if roi is not None:
            self._apply_roi(roi)
        self._config = config
        return config

    def start(self) -> None:
        camera = self._require_camera()
        if camera.IsGrabbing():
            return
        pylon = _load_pylon()
        self._set_enum("TriggerMode", "Off")
        camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def stop(self) -> None:
        if self._camera is not None and self._camera.IsGrabbing():
            self._camera.StopGrabbing()

    def latest_frame(self, timeout_s: float = 0.0) -> CameraFrame | None:
        if timeout_s < 0:
            raise ValueError("timeout_s must be non-negative")
        camera = self._require_camera()
        if not camera.IsGrabbing():
            raise CameraStateError("start acquisition before requesting live frames")
        return self._retrieve(timeout_s)

    def software_trigger(self, timeout_s: float = 1.0) -> CameraFrame:
        if timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        camera = self._require_camera()
        pylon = _load_pylon()
        was_running = camera.IsGrabbing()
        if was_running:
            camera.StopGrabbing()
        try:
            self._set_enum("TriggerSelector", "FrameStart")
            self._set_enum("TriggerSource", "Software", required=True)
            self._set_enum("TriggerMode", "On", required=True)
            camera.StartGrabbingMax(1)
            timeout_ms = max(1, round(timeout_s * 1_000))
            if hasattr(camera, "WaitForFrameTriggerReady"):
                ready = camera.WaitForFrameTriggerReady(
                    timeout_ms,
                    pylon.TimeoutHandling_Return,
                )
                if not ready:
                    raise CameraError("camera did not become trigger-ready before timeout")
            camera.ExecuteSoftwareTrigger()
            frame = self._retrieve(timeout_s)
            if frame is None:
                raise CameraError("software trigger timed out")
            return frame
        finally:
            if camera.IsGrabbing():
                camera.StopGrabbing()
            self._set_enum("TriggerMode", "Off")
            if was_running:
                camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)

    def _retrieve(self, timeout_s: float) -> CameraFrame | None:
        pylon = _load_pylon()
        camera = self._require_camera()
        timeout_ms = max(1, round(timeout_s * 1_000)) if timeout_s else 1
        result = camera.RetrieveResult(timeout_ms, pylon.TimeoutHandling_Return)
        if result is None:
            return None
        try:
            if not result.GrabSucceeded():
                raise CameraError(
                    f"Basler grab failed ({result.GetErrorCode()}): {result.GetErrorDescription()}"
                )
            image = np.asarray(result.Array, dtype=np.uint8).copy()
            self._frame_id += 1
            assert self._device is not None
            timestamp = int(getattr(result, "TimeStamp", 0)) or time.time_ns()
            return CameraFrame(image, timestamp, self._frame_id, self._device)
        finally:
            result.Release()

    def _require_camera(self) -> Any:
        if not self.connected or self._camera is None:
            raise CameraStateError("connect a Basler camera first")
        return self._camera

    @staticmethod
    def _to_device_info(info: Any) -> CameraDevice:
        transport = ""
        if hasattr(info, "GetDeviceClass"):
            transport = str(info.GetDeviceClass())
        return CameraDevice(
            serial=str(info.GetSerialNumber()),
            model=str(info.GetModelName()),
            vendor=str(info.GetVendorName()) if hasattr(info, "GetVendorName") else "Basler",
            transport=transport,
        )

    def _node(self, name: str) -> Any | None:
        camera = self._require_camera()
        return getattr(camera, name, None)

    def _set_enum(self, name: str, value: str, *, required: bool = False) -> None:
        node = self._node(name)
        try:
            if node is None or (hasattr(node, "IsWritable") and not node.IsWritable()):
                if required:
                    raise CameraError(f"camera node is not writable: {name}")
                return
            node.SetValue(value)
        except CameraError:
            raise
        except Exception as exc:
            if required:
                raise CameraError(f"failed to set {name}={value}: {exc}") from exc

    def _set_bool(self, name: str, value: bool) -> None:
        node = self._node(name)
        if node is not None and (not hasattr(node, "IsWritable") or node.IsWritable()):
            node.SetValue(value)

    def _set_float(self, names: tuple[str, ...], value: float) -> None:
        for name in names:
            node = self._node(name)
            if node is None or (hasattr(node, "IsWritable") and not node.IsWritable()):
                continue
            minimum = float(node.GetMin()) if hasattr(node, "GetMin") else value
            maximum = float(node.GetMax()) if hasattr(node, "GetMax") else value
            node.SetValue(min(max(value, minimum), maximum))
            return

    def _apply_roi(self, roi: Roi) -> None:
        # Basler devices generally require offsets to be reset before increasing size.
        self._set_integer("OffsetX", 0)
        self._set_integer("OffsetY", 0)
        self._set_integer("Width", roi.width_px, required=True)
        self._set_integer("Height", roi.height_px, required=True)
        self._set_integer("OffsetX", roi.x_px, required=True)
        self._set_integer("OffsetY", roi.y_px, required=True)

    def _set_integer(self, name: str, value: int, *, required: bool = False) -> None:
        node = self._node(name)
        if node is None or (hasattr(node, "IsWritable") and not node.IsWritable()):
            if required:
                raise CameraError(f"camera node is not writable: {name}")
            return
        minimum = int(node.GetMin()) if hasattr(node, "GetMin") else value
        maximum = int(node.GetMax()) if hasattr(node, "GetMax") else value
        increment = int(node.GetInc()) if hasattr(node, "GetInc") else 1
        clamped = min(max(value, minimum), maximum)
        aligned = minimum + ((clamped - minimum) // max(increment, 1)) * max(increment, 1)
        try:
            node.SetValue(aligned)
        except Exception as exc:
            if required:
                raise CameraError(f"failed to set {name}={value}: {exc}") from exc
