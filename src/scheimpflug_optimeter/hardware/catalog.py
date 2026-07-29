"""Load immutable, source-attributed camera and lens catalog entries."""

from __future__ import annotations

import json
from importlib.resources import files
from types import MappingProxyType
from typing import Any

from scheimpflug_optimeter.models import CameraProfile, LensProfile, SensorProfile


def _read_catalog(filename: str) -> dict[str, Any]:
    resource = files("scheimpflug_optimeter.data").joinpath(filename)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Unsupported hardware catalog schema in {filename}.")
    return payload


def _load_cameras() -> tuple[dict[str, CameraProfile], dict[str, SensorProfile]]:
    payload = _read_catalog("cameras.json")
    verified_on = str(payload["verified_on"])
    cameras: dict[str, CameraProfile] = {}
    sensors: dict[str, SensorProfile] = {}
    for item in payload["cameras"]:
        sensor = SensorProfile(**item["sensor"])
        profile = CameraProfile(
            id=item["id"],
            manufacturer=item["manufacturer"],
            model=item["model"],
            interface=item["interface"],
            mount=item["mount"],
            max_fps=float(item["max_fps"]),
            sensor=sensor,
            notes=tuple(item.get("notes", ())),
            source_url=item.get("source_url"),
            verified_on=verified_on,
        )
        cameras[profile.id] = profile
        sensors[sensor.id] = sensor
    return cameras, sensors


def _load_lenses() -> dict[str, LensProfile]:
    payload = _read_catalog("lenses.json")
    verified_on = str(payload["verified_on"])
    lenses: dict[str, LensProfile] = {}
    for item in payload["lenses"]:
        profile = LensProfile(
            **item,
            verified_on=verified_on,
        )
        lenses[profile.id] = profile
    return lenses


_camera_values, _sensor_values = _load_cameras()
_lens_values = _load_lenses()

CAMERAS = MappingProxyType(_camera_values)
SENSORS = MappingProxyType(_sensor_values)
LENSES = MappingProxyType(_lens_values)


def get_camera(camera_id: str) -> CameraProfile:
    """Resolve a camera id and give a useful error for an unknown id."""

    try:
        return CAMERAS[camera_id]
    except KeyError as error:
        choices = ", ".join(CAMERAS)
        raise KeyError(f"Unknown camera id {camera_id!r}; expected one of: {choices}") from error


def get_sensor(sensor_or_camera_id: str) -> SensorProfile:
    """Resolve either a sensor id or its owning camera id."""

    if sensor_or_camera_id in SENSORS:
        return SENSORS[sensor_or_camera_id]
    if sensor_or_camera_id in CAMERAS:
        return CAMERAS[sensor_or_camera_id].sensor
    choices = ", ".join((*SENSORS, *CAMERAS))
    raise KeyError(f"Unknown sensor/camera id {sensor_or_camera_id!r}; expected one of: {choices}")


def get_lens(lens_id: str) -> LensProfile:
    """Resolve a lens id and give a useful error for an unknown id."""

    try:
        return LENSES[lens_id]
    except KeyError as error:
        choices = ", ".join(LENSES)
        raise KeyError(f"Unknown lens id {lens_id!r}; expected one of: {choices}") from error


def create_custom_camera_profile(
    *,
    profile_id: str,
    model: str,
    width_px: int,
    height_px: int,
    pixel_pitch_um: float,
    interface: str,
    mount: str,
    max_fps: float,
    manufacturer: str = "Custom",
    color_mode: str = "mono",
) -> CameraProfile:
    """Create a validated, project-local camera profile.

    Custom profiles are intentionally not inserted into the process-global
    static catalog.  A project owns the returned immutable value and can
    serialize it without hidden catalog mutation.
    """

    if color_mode not in {"mono", "color"}:
        raise ValueError("color_mode must be 'mono' or 'color'.")
    sensor = SensorProfile(
        id=f"{profile_id}-sensor",
        name=f"{model} active sensor",
        width_px=width_px,
        height_px=height_px,
        pixel_pitch_um=pixel_pitch_um,
        color_mode=color_mode,  # type: ignore[arg-type]
    )
    return CameraProfile(
        id=profile_id,
        manufacturer=manufacturer,
        model=model,
        interface=interface,
        mount=mount,
        max_fps=max_fps,
        sensor=sensor,
        notes=("User-defined project profile; verify every value against the device.",),
    )
