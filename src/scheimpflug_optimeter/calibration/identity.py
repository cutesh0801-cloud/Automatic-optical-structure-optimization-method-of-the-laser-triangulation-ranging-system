"""Calibration-to-hardware binding and mismatch checks."""

from __future__ import annotations

from dataclasses import dataclass

from scheimpflug_optimeter.camera import Roi


class CalibrationMismatchError(RuntimeError):
    """Raised when calibration belongs to different acquisition hardware."""

    def __init__(self, mismatches: tuple[str, ...]) -> None:
        self.mismatches = mismatches
        super().__init__("calibration does not match current hardware: " + "; ".join(mismatches))


@dataclass(frozen=True, slots=True)
class HardwareIdentity:
    """Fields which materially change triangulation and therefore require recalibration."""

    camera_serial: str
    camera_model: str
    lens_sku: str
    roi: Roi
    resolution_px: tuple[int, int]
    sensor_orientation: str = "normal"

    def __post_init__(self) -> None:
        if not self.camera_serial.strip() or not self.camera_model.strip():
            raise ValueError("camera serial and model are required")
        if not self.lens_sku.strip():
            raise ValueError("lens_sku is required")
        if self.resolution_px[0] <= 0 or self.resolution_px[1] <= 0:
            raise ValueError("resolution must contain positive width and height")
        if self.sensor_orientation not in {"normal", "flip_x", "flip_y", "rotate_180"}:
            raise ValueError(f"unsupported sensor orientation: {self.sensor_orientation}")

    def to_dict(self) -> dict[str, object]:
        return {
            "camera_serial": self.camera_serial,
            "camera_model": self.camera_model,
            "lens_sku": self.lens_sku,
            "roi": {
                "x_px": self.roi.x_px,
                "y_px": self.roi.y_px,
                "width_px": self.roi.width_px,
                "height_px": self.roi.height_px,
            },
            "resolution_px": list(self.resolution_px),
            "sensor_orientation": self.sensor_orientation,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> HardwareIdentity:
        roi_value = value["roi"]
        if not isinstance(roi_value, dict):
            raise ValueError("roi must be an object")
        resolution = value["resolution_px"]
        if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
            raise ValueError("resolution_px must have two entries")
        return cls(
            camera_serial=str(value["camera_serial"]),
            camera_model=str(value["camera_model"]),
            lens_sku=str(value["lens_sku"]),
            roi=Roi(
                int(roi_value["x_px"]),
                int(roi_value["y_px"]),
                int(roi_value["width_px"]),
                int(roi_value["height_px"]),
            ),
            resolution_px=(int(resolution[0]), int(resolution[1])),
            sensor_orientation=str(value.get("sensor_orientation", "normal")),
        )


def calibration_mismatches(
    calibrated: HardwareIdentity,
    current: HardwareIdentity,
) -> tuple[str, ...]:
    """Return all safety-relevant differences instead of failing on the first one."""

    mismatches: list[str] = []
    fields = (
        ("camera serial", calibrated.camera_serial, current.camera_serial),
        ("camera model", calibrated.camera_model, current.camera_model),
        ("lens SKU", calibrated.lens_sku, current.lens_sku),
        ("ROI", calibrated.roi, current.roi),
        ("resolution", calibrated.resolution_px, current.resolution_px),
        (
            "sensor orientation",
            calibrated.sensor_orientation,
            current.sensor_orientation,
        ),
    )
    for label, expected, actual in fields:
        if expected != actual:
            mismatches.append(f"{label}: calibrated={expected!r}, current={actual!r}")
    return tuple(mismatches)


def assert_calibration_matches(
    calibrated: HardwareIdentity,
    current: HardwareIdentity,
) -> None:
    """Block measurement if any hardware identity field changed."""

    mismatches = calibration_mismatches(calibrated, current)
    if mismatches:
        raise CalibrationMismatchError(mismatches)
