from __future__ import annotations

import time

import pytest

from scheimpflug_optimeter.camera import (
    BaslerCameraBackend,
    CameraBackend,
    CameraConfig,
    CameraStateError,
    CameraUnavailableError,
    MockCameraBackend,
    Roi,
    basler,
)


def test_mock_camera_supports_trigger_and_latest_only_stream() -> None:
    camera = MockCameraBackend(width_px=160, height_px=120, noise_std=0.0)
    assert isinstance(camera, CameraBackend)
    device = camera.connect("acA1300-60gm (simulated)")
    assert device.serial == "MOCK-ACA1300-0001"
    camera.configure(
        CameraConfig(
            exposure_us=1_500,
            frame_rate_hz=60,
            roi=Roi(10, 20, 80, 60),
        )
    )

    triggered = camera.software_trigger()
    assert triggered.image.shape == (60, 80)
    camera.start()
    time.sleep(0.05)
    latest = camera.latest_frame(timeout_s=0.2)
    camera.stop()

    assert latest is not None
    assert latest.frame_id > triggered.frame_id
    assert latest.image.shape == (60, 80)
    assert not camera.running


def test_mock_camera_rejects_invalid_state_and_selector() -> None:
    camera = MockCameraBackend(width_px=32, height_px=24)
    with pytest.raises(CameraStateError):
        camera.start()
    with pytest.raises(CameraUnavailableError):
        camera.connect("not-this-camera")
    camera.connect()
    camera.start()
    with pytest.raises(CameraStateError):
        camera.configure(CameraConfig())
    camera.disconnect()


def test_basler_sdk_is_loaded_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_sdk(_name: str):
        raise ImportError("not installed")

    monkeypatch.setattr(basler.importlib, "import_module", missing_sdk)
    backend = BaslerCameraBackend()
    with pytest.raises(CameraUnavailableError, match="pypylon"):
        backend.enumerate_devices()
