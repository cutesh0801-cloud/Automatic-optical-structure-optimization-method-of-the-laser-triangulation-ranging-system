"""Explicit hardware compatibility checks with no guessed specifications."""

from __future__ import annotations

from scheimpflug_optimeter.models import (
    CameraProfile,
    CompatibilityCheck,
    CompatibilityReport,
    CompatibilityStatus,
    DesignInput,
    DesignSolution,
    LensProfile,
)


def _unknown(code: str, label: str, field: str) -> CompatibilityCheck:
    return CompatibilityCheck(
        code,
        label,
        CompatibilityStatus.UNKNOWN,
        f"No verified {field} is stored; confirm it from the current datasheet.",
    )


def _mount_check(camera: CameraProfile, lens: LensProfile) -> CompatibilityCheck:
    camera_mount = camera.mount.upper()
    lens_mount = lens.mount.upper().replace("×", "X")
    if "ACCESSORY" in camera_mount and "S" in camera_mount and "M12" in lens_mount:
        return CompatibilityCheck(
            "mount",
            "Mount / adapter",
            CompatibilityStatus.WARNING,
            "Install and verify the camera's S-mount accessory before assembly.",
        )
    if ("S" in camera_mount.split("/") or camera_mount == "S") and "M12" in lens_mount:
        return CompatibilityCheck(
            "mount",
            "Mount / adapter",
            CompatibilityStatus.PASS,
            "The selected camera profile includes an S-mount configuration for M12x0.5.",
        )
    if camera_mount == "C" and "M12" in lens_mount:
        adapter = (
            "A #53-675-class C-to-M12 adapter is required; it does not provide Scheimpflug tilt."
            if camera.id == "basler-aca1300-60gm"
            else "A verified C-to-M12 adapter is required."
        )
        return CompatibilityCheck(
            "mount",
            "Mount / adapter",
            CompatibilityStatus.WARNING,
            adapter,
        )
    return CompatibilityCheck(
        "mount",
        "Mount / adapter",
        CompatibilityStatus.FAIL,
        f"{camera.mount} and {lens.mount} have no catalogued direct or adapter route.",
    )


def evaluate_compatibility(
    camera: CameraProfile,
    lens: LensProfile,
    design: DesignInput | DesignSolution | None = None,
) -> CompatibilityReport:
    """Evaluate independent mount, optical, and mechanical assertions."""

    design_request = (
        design.request
        if isinstance(design, DesignSolution) and isinstance(design.request, DesignInput)
        else design
    )
    checks: list[CompatibilityCheck] = [_mount_check(camera, lens)]

    if lens.image_circle_mm is None:
        checks.append(_unknown("image_circle", "Image circle", "lens image circle"))
    elif camera.sensor.diagonal_mm <= lens.image_circle_mm:
        checks.append(
            CompatibilityCheck(
                "image_circle",
                "Image circle",
                CompatibilityStatus.PASS,
                (
                    f"Sensor diagonal {camera.sensor.diagonal_mm:.3f} mm fits inside "
                    f"{lens.image_circle_mm:.3f} mm."
                ),
            )
        )
    else:
        checks.append(
            CompatibilityCheck(
                "image_circle",
                "Image circle",
                CompatibilityStatus.FAIL,
                (
                    f"Sensor diagonal {camera.sensor.diagonal_mm:.3f} mm exceeds "
                    f"{lens.image_circle_mm:.3f} mm."
                ),
            )
        )

    if lens.resolution_lp_per_mm is None:
        checks.append(_unknown("pixel_sampling", "Pixel support", "lens resolution"))
    else:
        nyquist_lp_per_mm = 500.0 / camera.sensor.pixel_pitch_um
        status = (
            CompatibilityStatus.PASS
            if lens.resolution_lp_per_mm >= nyquist_lp_per_mm
            else CompatibilityStatus.WARNING
        )
        checks.append(
            CompatibilityCheck(
                "pixel_sampling",
                "Pixel support",
                status,
                (
                    f"Lens {lens.resolution_lp_per_mm:.1f} lp/mm versus sensor "
                    f"Nyquist {nyquist_lp_per_mm:.1f} lp/mm."
                ),
            )
        )

    if lens.working_distance_min_mm is None or lens.working_distance_max_mm is None:
        checks.append(_unknown("working_distance", "Working distance", "lens WD range"))
    elif not isinstance(design_request, DesignInput):
        checks.append(
            CompatibilityCheck(
                "working_distance",
                "Working distance",
                CompatibilityStatus.UNKNOWN,
                "Select a design before checking working distance.",
            )
        )
    else:
        in_range = (
            lens.working_distance_min_mm <= design_request.d_mm <= lens.working_distance_max_mm
        )
        checks.append(
            CompatibilityCheck(
                "working_distance",
                "Working distance",
                CompatibilityStatus.PASS if in_range else CompatibilityStatus.FAIL,
                (
                    f"Design WD {design_request.d_mm:.3f} mm; verified lens range "
                    f"{lens.working_distance_min_mm:.3f}-"
                    f"{lens.working_distance_max_mm:.3f} mm."
                ),
            )
        )

    if lens.wavelength_min_nm is None or lens.wavelength_max_nm is None:
        checks.append(_unknown("wavelength", "Laser wavelength", "coating wavelength range"))
    elif not isinstance(design_request, DesignInput) or design_request.laser_wavelength_nm is None:
        checks.append(
            CompatibilityCheck(
                "wavelength",
                "Laser wavelength",
                CompatibilityStatus.UNKNOWN,
                "Enter the laser wavelength before checking the coating range.",
            )
        )
    else:
        in_range = (
            lens.wavelength_min_nm <= design_request.laser_wavelength_nm <= lens.wavelength_max_nm
        )
        checks.append(
            CompatibilityCheck(
                "wavelength",
                "Laser wavelength",
                CompatibilityStatus.PASS if in_range else CompatibilityStatus.FAIL,
                (
                    f"Laser {design_request.laser_wavelength_nm:.1f} nm; "
                    "verified coating range "
                    f"{lens.wavelength_min_nm:.1f}-{lens.wavelength_max_nm:.1f} nm."
                ),
            )
        )

    if lens.overall_length_mm is None:
        checks.append(_unknown("intrusion", "Lens intrusion", "lens overall length"))
    else:
        checks.append(
            CompatibilityCheck(
                "intrusion",
                "Lens intrusion",
                CompatibilityStatus.WARNING,
                (
                    f"Lens length is {lens.overall_length_mm:.3f} mm, but M12 has no "
                    "standard flange distance; verify the assembled focus position."
                ),
            )
        )

    if lens.weight_g is None:
        checks.append(_unknown("weight", "Lens weight", "lens weight"))
    else:
        checks.append(
            CompatibilityCheck(
                "weight",
                "Lens weight",
                CompatibilityStatus.PASS,
                f"Catalogued lens weight: {lens.weight_g:.3f} g.",
            )
        )

    if isinstance(design_request, DesignInput) and design_request.max_sensor_tilt_deg is not None:
        tilt_ok = design_request.beta_deg <= design_request.max_sensor_tilt_deg
        checks.append(
            CompatibilityCheck(
                "tilt_mechanism",
                "Scheimpflug tilt",
                CompatibilityStatus.PASS if tilt_ok else CompatibilityStatus.FAIL,
                (
                    f"Required beta {design_request.beta_deg:.3f} degrees; "
                    f"mechanism limit {design_request.max_sensor_tilt_deg:.3f} degrees."
                ),
            )
        )
    else:
        checks.append(
            CompatibilityCheck(
                "tilt_mechanism",
                "Scheimpflug tilt",
                CompatibilityStatus.WARNING,
                "A separate tilt mechanism is required; no verified angle limit is set.",
            )
        )

    checks.append(
        CompatibilityCheck(
            "m12_flange",
            "M12 flange datum",
            CompatibilityStatus.WARNING,
            "M12x0.5 does not define a standard flange focal distance; verify as-built focus.",
        )
    )
    return CompatibilityReport(camera.id, lens.id, tuple(checks))
