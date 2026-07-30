"""Pure numerical solvers for legacy and canonical Scheimpflug designs."""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Literal

from scipy.optimize import brentq

from scheimpflug_optimeter.models import (
    ConstraintViolation,
    DesignInput,
    DesignMode,
    DesignSolution,
    LensProfile,
    SensorImagingMetrics,
    SensorProfile,
    WorkbookDesignInput,
)

_MAX_LOW_ROOT_DEG = math.degrees(math.atan(math.sqrt(2.0)))
_MAX_ALPHA_RATIO = 2.0 / (3.0 * math.sqrt(3.0))
_ANGLE_SUM_LIMIT_DEG = 89.5
_DENOMINATOR_REL_TOL = 1e-12


class OpticalInputError(ValueError):
    """Raised when required input cannot form a meaningful calculation."""


def _require_finite_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise OpticalInputError(f"{name} must be a finite positive value.")


def _require_finite(name: str, value: float) -> None:
    if not math.isfinite(value):
        raise OpticalInputError(f"{name} must be finite.")


def solve_alpha(focal_length_mm: float, v_mm: float) -> float:
    """Solve the low-angle root of ``sin²(alpha) cos(alpha) = f / V``.

    Returns:
        Alpha in degrees in the open interval
        ``(0, 54.735610317...)``.
    """

    _require_finite_positive("focal_length_mm", focal_length_mm)
    _require_finite_positive("v_mm", v_mm)
    ratio = focal_length_mm / v_mm
    if not 0.0 < ratio < _MAX_ALPHA_RATIO:
        raise OpticalInputError(
            "focal_length_mm / v_mm must satisfy "
            f"0 < f/V < {_MAX_ALPHA_RATIO:.15f}; received {ratio:.15g}."
        )

    upper = math.atan(math.sqrt(2.0))

    def residual(alpha_rad: float) -> float:
        return math.sin(alpha_rad) ** 2 * math.cos(alpha_rad) - ratio

    alpha = brentq(residual, 0.0, upper, xtol=1e-14, rtol=1e-14)
    return math.degrees(alpha)


def image_coordinate_mm(
    object_offset_mm: float,
    *,
    alpha_deg: float,
    beta_deg: float,
    lo_mm: float,
    fp_mm: float,
) -> float:
    """Map a signed object-range offset to a signed sensor coordinate."""

    values = (object_offset_mm, alpha_deg, beta_deg, lo_mm, fp_mm)
    if not all(math.isfinite(value) for value in values):
        raise OpticalInputError("Image-coordinate inputs must be finite.")
    _require_finite_positive("lo_mm", lo_mm)
    _require_finite_positive("fp_mm", fp_mm)
    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    denominator = lo_mm * math.sin(beta) + object_offset_mm * math.sin(alpha + beta)
    scale = max(
        1.0,
        abs(lo_mm * math.sin(beta)),
        abs(object_offset_mm * math.sin(alpha + beta)),
    )
    if abs(denominator) <= _DENOMINATOR_REL_TOL * scale:
        raise OpticalInputError("Object-to-image mapping is singular at this range position.")
    return object_offset_mm * fp_mm * math.sin(alpha) / denominator


def image_sensitivity(
    object_offset_mm: float,
    *,
    alpha_deg: float,
    beta_deg: float,
    lo_mm: float,
    fp_mm: float,
) -> float:
    """Return ``dx/ds`` in sensor-mm per object-mm."""

    values = (object_offset_mm, alpha_deg, beta_deg, lo_mm, fp_mm)
    if not all(math.isfinite(value) for value in values):
        raise OpticalInputError("Sensitivity inputs must be finite.")
    _require_finite_positive("lo_mm", lo_mm)
    _require_finite_positive("fp_mm", fp_mm)
    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    denominator = lo_mm * math.sin(beta) + object_offset_mm * math.sin(alpha + beta)
    scale = max(
        1.0,
        abs(lo_mm * math.sin(beta)),
        abs(object_offset_mm * math.sin(alpha + beta)),
    )
    if abs(denominator) <= _DENOMINATOR_REL_TOL * scale:
        raise OpticalInputError("Image sensitivity is singular at this range position.")
    numerator = fp_mm * math.sin(alpha) * lo_mm * math.sin(beta)
    return numerator / denominator**2


def _normalize_sensor_axis(axis: str) -> Literal["width", "height"]:
    normalized = axis.lower()
    if normalized in {"width", "horizontal", "x", "long"}:
        return "width"
    if normalized in {"height", "vertical", "y", "short"}:
        return "height"
    raise OpticalInputError(f"Unsupported sensor axis: {axis!r}")


def _catalog_sensor(sensor_id: str) -> SensorProfile:
    from scheimpflug_optimeter.hardware import get_sensor

    try:
        return get_sensor(sensor_id)
    except KeyError as error:
        raise OpticalInputError(str(error)) from error


def calculate_sensor_imaging_metrics(
    sensor: SensorProfile,
    *,
    sensor_axis: str,
    alpha_deg: float,
    beta_deg: float,
    lo_mm: float,
    fp_mm: float,
    calculation_sensor_length_mm: float | None = None,
) -> SensorImagingMetrics:
    """Calculate full-active-sensor object coverage without camera I/O.

    The selected range axis is inverted from the same nonlinear mapping used
    by :func:`image_coordinate_mm`::

        s(x) = x lo sin(beta) / (fp sin(alpha) - x sin(alpha + beta))

    The orthogonal field is evaluated at the reference object plane with
    magnification ``fp / lo``.  A full active axis that touches or crosses the
    inverse-mapping pole has no finite range FOV and is reported as invalid.
    """

    _require_finite("alpha_deg", alpha_deg)
    _require_finite("beta_deg", beta_deg)
    _require_finite_positive("lo_mm", lo_mm)
    _require_finite_positive("fp_mm", fp_mm)
    if not 0.0 < alpha_deg < 90.0:
        raise OpticalInputError("alpha_deg must be between 0 and 90 degrees.")
    if not 0.0 < beta_deg < 90.0:
        raise OpticalInputError("beta_deg must be between 0 and 90 degrees.")
    if calculation_sensor_length_mm is not None:
        _require_finite_positive("calculation_sensor_length_mm", calculation_sensor_length_mm)

    axis = _normalize_sensor_axis(sensor_axis)
    active_length = sensor.length_mm(axis)
    active_pixels = sensor.width_px if axis == "width" else sensor.height_px
    orthogonal_length = sensor.height_mm if axis == "width" else sensor.width_mm
    orthogonal_pixels = sensor.height_px if axis == "width" else sensor.width_px
    pitch_mm = sensor.pixel_pitch_um / 1000.0
    half_length = active_length / 2.0

    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    image_numerator = fp_mm * math.sin(alpha)
    object_numerator = lo_mm * math.sin(beta)
    coupling = math.sin(alpha + beta)
    endpoint_denominators = (
        image_numerator + half_length * coupling,
        image_numerator - half_length * coupling,
    )
    denominator_scale = max(
        1.0,
        abs(image_numerator),
        abs(half_length * coupling),
    )
    singular_limit = _DENOMINATOR_REL_TOL * denominator_scale
    crosses_mapping_pole = (
        abs(endpoint_denominators[0]) <= singular_limit
        or abs(endpoint_denominators[1]) <= singular_limit
        or endpoint_denominators[0] * endpoint_denominators[1] <= 0.0
    )

    magnification = abs(fp_mm / lo_mm)
    orthogonal_fov = orthogonal_length / magnification
    orthogonal_sampling = orthogonal_fov / orthogonal_pixels
    center_sensitivity = abs(pitch_mm * object_numerator / image_numerator)
    warnings: list[str] = []
    mismatch_tolerance = max(1e-9, active_length * 1e-9)
    if (
        calculation_sensor_length_mm is not None
        and abs(calculation_sensor_length_mm - active_length) > mismatch_tolerance
    ):
        warnings.append(
            "The calculation sensor length differs from the selected profile's "
            f"{axis} active length ({calculation_sensor_length_mm:.6g} mm vs "
            f"{active_length:.6g} mm). Camera metrics use the profile dimension."
        )

    if crosses_mapping_pole:
        invalid_reason = (
            "The selected active sensor axis reaches or crosses the inverse "
            "object-to-image mapping pole; a finite full-sensor range FOV is undefined."
        )
        horizontal_fov = orthogonal_fov if axis == "height" else None
        vertical_fov = orthogonal_fov if axis == "width" else None
        horizontal_sampling = orthogonal_sampling if axis == "height" else None
        vertical_sampling = orthogonal_sampling if axis == "width" else None
        return SensorImagingMetrics(
            sensor=sensor,
            sensor_axis=axis,
            valid=False,
            horizontal_fov_mm=horizontal_fov,
            vertical_fov_mm=vertical_fov,
            horizontal_sampling_mm_per_px=horizontal_sampling,
            vertical_sampling_mm_per_px=vertical_sampling,
            range_min_offset_mm=None,
            range_max_offset_mm=None,
            range_sensitivity_near_mm_per_px=None,
            range_sensitivity_center_mm_per_px=center_sensitivity,
            range_sensitivity_far_mm_per_px=None,
            range_sensitivity_worst_mm_per_px=None,
            invalid_reason=invalid_reason,
            warnings=tuple(warnings),
        )

    sensor_coordinates = (-half_length, half_length)
    object_offsets = tuple(
        coordinate * object_numerator / (image_numerator - coordinate * coupling)
        for coordinate in sensor_coordinates
    )
    range_min = min(object_offsets)
    range_max = max(object_offsets)
    range_fov = range_max - range_min
    range_average_sampling = range_fov / active_pixels

    def distance_per_pixel(object_offset_mm: float) -> float:
        sensitivity = abs(
            image_sensitivity(
                object_offset_mm,
                alpha_deg=alpha_deg,
                beta_deg=beta_deg,
                lo_mm=lo_mm,
                fp_mm=fp_mm,
            )
        )
        return pitch_mm / sensitivity

    near_sensitivity = distance_per_pixel(range_min)
    far_sensitivity = distance_per_pixel(range_max)
    worst_sensitivity = max(near_sensitivity, center_sensitivity, far_sensitivity)
    if axis == "width":
        horizontal_fov = range_fov
        vertical_fov = orthogonal_fov
        horizontal_sampling = range_average_sampling
        vertical_sampling = orthogonal_sampling
    else:
        horizontal_fov = orthogonal_fov
        vertical_fov = range_fov
        horizontal_sampling = orthogonal_sampling
        vertical_sampling = range_average_sampling

    return SensorImagingMetrics(
        sensor=sensor,
        sensor_axis=axis,
        valid=True,
        horizontal_fov_mm=horizontal_fov,
        vertical_fov_mm=vertical_fov,
        horizontal_sampling_mm_per_px=horizontal_sampling,
        vertical_sampling_mm_per_px=vertical_sampling,
        range_min_offset_mm=range_min,
        range_max_offset_mm=range_max,
        range_sensitivity_near_mm_per_px=near_sensitivity,
        range_sensitivity_center_mm_per_px=center_sensitivity,
        range_sensitivity_far_mm_per_px=far_sensitivity,
        range_sensitivity_worst_mm_per_px=worst_sensitivity,
        warnings=tuple(warnings),
    )


def solve_workbook_design(
    request: WorkbookDesignInput,
    *,
    sensor: SensorProfile | None = None,
) -> DesignSolution:
    """Reproduce the thin-lens formulas in ``구조설계_rev.1.xlsx``.

    The compatibility solver intentionally keeps the workbook convention
    ``beta = 90° - alpha`` and its centred sensor package.  Missing or zero
    sensor length is rejected instead of silently propagating ``L = 0``.
    """

    _require_finite_positive("v_mm", request.v_mm)
    _require_finite("d_mm", request.d_mm)
    if request.sensor_length_mm is None:
        raise OpticalInputError(
            "sensor_length_mm is required; the workbook source cell for L is missing."
        )
    _require_finite_positive("sensor_length_mm", request.sensor_length_mm)
    _require_finite("alpha_deg", request.alpha_deg)
    for name, value in (
        ("focal_length_literal_mm", request.focal_length_literal_mm),
        ("rm_cmos_distance_mm", request.rm_cmos_distance_mm),
        ("fov_mm", request.fov_mm),
    ):
        if value is not None:
            _require_finite_positive(name, value)
    if request.alpha_reference_deg is not None:
        _require_finite("alpha_reference_deg", request.alpha_reference_deg)
    if not 0.0 < request.alpha_deg < 90.0:
        raise OpticalInputError("alpha_deg must be between 0 and 90 degrees.")

    alpha = math.radians(request.alpha_deg)
    beta_deg = 90.0 - request.alpha_deg
    beta = math.radians(beta_deg)
    baseline = request.v_mm * math.tan(alpha)
    half_sensor = request.sensor_length_mm / 2.0
    width = baseline + half_sensor
    rear = request.v_mm - request.d_mm
    fp = baseline * math.cos(beta)
    lo = request.v_mm * math.cos(alpha)
    total = fp + lo

    violations: list[ConstraintViolation] = []
    if request.alpha_deg >= _MAX_LOW_ROOT_DEG:
        violations.append(
            ConstraintViolation(
                "alpha_low_root_domain",
                (
                    "alpha_deg is outside the workbook's low-root domain "
                    f"(0, {_MAX_LOW_ROOT_DEG:.12f} degrees)."
                ),
                amount=request.alpha_deg,
                limit=_MAX_LOW_ROOT_DEG,
            )
        )
    if rear < 0:
        violations.append(
            ConstraintViolation(
                "negative_rear",
                "d_mm exceeds V, producing a negative rear envelope.",
                amount=-rear,
                limit=0.0,
            )
        )

    denominator = fp * math.sin(alpha) - half_sensor * math.sin(alpha + beta)
    denominator_scale = max(
        1.0,
        abs(fp * math.sin(alpha)),
        abs(half_sensor * math.sin(alpha + beta)),
    )
    ray_intercept: float | None
    if abs(denominator) <= _DENOMINATOR_REL_TOL * denominator_scale:
        ray_intercept = None
        violations.append(
            ConstraintViolation(
                "sensor_edge_ray_singular",
                "The sensor-edge ray is parallel to the laser axis.",
                amount=abs(denominator),
                limit=_DENOMINATOR_REL_TOL * denominator_scale,
            )
        )
    else:
        ray_intercept = half_sensor * lo * math.sin(beta) / denominator

    if lo <= 0 or fp <= 0:
        violations.append(
            ConstraintViolation(
                "non_positive_conjugate",
                "Object and image conjugate distances must be positive.",
                amount=min(lo, fp),
                limit=0.0,
            )
        )

    focal = 1.0 / (1.0 / lo + 1.0 / fp) if lo > 0 and fp > 0 else math.nan
    focal_residual = 1.0 / lo + 1.0 / fp - 1.0 / focal if focal > 0 else math.nan
    scheimpflug_residual = lo * math.tan(alpha) - fp * math.tan(beta)
    triangle_residual = baseline**2 + request.v_mm**2 - total**2
    cos_alpha = math.cos(alpha)
    cos_beta = math.cos(beta)
    diagnostics: list[tuple[str, float]] = [
        ("focal_equation_residual", focal_residual),
        ("scheimpflug_residual_mm", scheimpflug_residual),
        ("right_triangle_residual_mm2", triangle_residual),
        ("tan_alpha", math.tan(alpha)),
        ("tan_beta", math.tan(beta)),
        ("cos_alpha", cos_alpha),
        ("cos_beta", cos_beta),
        ("cos_alpha_from_triangle", request.v_mm / total),
        ("cos_beta_from_triangle", baseline / total),
        ("lo_tan_alpha_mm", lo * math.tan(alpha)),
        ("fp_tan_beta_mm", fp * math.tan(beta)),
        ("sensor_edge_denominator_mm", denominator),
        ("max_low_root_deg", _MAX_LOW_ROOT_DEG),
    ]
    if request.focal_length_literal_mm is not None:
        literal_focal = request.focal_length_literal_mm
        alpha_equation_residual = (
            math.sin(alpha) ** 2 * math.cos(alpha) - literal_focal / request.v_mm
        )
        diagnostics.extend(
            (
                ("focal_length_literal_mm", literal_focal),
                ("focal_length_derived_mm", focal),
                ("focal_literal_minus_derived_mm", literal_focal - focal),
                ("alpha_equation_residual_at_input", alpha_equation_residual),
            )
        )
        try:
            solved_alpha_deg = solve_alpha(literal_focal, request.v_mm)
        except OpticalInputError:
            solved_alpha_deg = math.nan
        diagnostics.append(("alpha_solved_deg", solved_alpha_deg))
        if math.isfinite(solved_alpha_deg):
            diagnostics.append(
                ("alpha_input_minus_solved_deg", request.alpha_deg - solved_alpha_deg)
            )
    if request.alpha_reference_deg is not None:
        reference_alpha = math.radians(request.alpha_reference_deg)
        diagnostics.extend(
            (
                ("alpha_reference_deg", request.alpha_reference_deg),
                (
                    "alpha_input_minus_reference_deg",
                    request.alpha_deg - request.alpha_reference_deg,
                ),
                (
                    "alpha_equation_residual_at_reference",
                    (
                        math.sin(reference_alpha) ** 2 * math.cos(reference_alpha)
                        - (
                            request.focal_length_literal_mm / request.v_mm
                            if request.focal_length_literal_mm is not None
                            else math.nan
                        )
                    ),
                ),
            )
        )
    if request.rm_cmos_distance_mm is not None:
        diagnostics.append(("rm_cmos_distance_mm", request.rm_cmos_distance_mm))
    if request.fov_mm is not None:
        diagnostics.append(("fov_mm", request.fov_mm))

    selected_sensor = sensor if sensor is not None else _catalog_sensor(request.sensor_id)
    sensor_metrics = calculate_sensor_imaging_metrics(
        selected_sensor,
        sensor_axis=request.sensor_axis,
        alpha_deg=request.alpha_deg,
        beta_deg=beta_deg,
        lo_mm=lo,
        fp_mm=fp,
        calculation_sensor_length_mm=request.sensor_length_mm,
    )
    warnings = list(sensor_metrics.warnings)
    if not sensor_metrics.valid and sensor_metrics.invalid_reason is not None:
        warnings.append(sensor_metrics.invalid_reason)
    worst_distance_per_pixel = sensor_metrics.range_sensitivity_worst_mm_per_px
    if worst_distance_per_pixel is None:
        min_sensitivity = 0.0
        distance_per_sensor = math.inf
    else:
        pixel_pitch_mm = selected_sensor.pixel_pitch_um / 1000.0
        distance_per_sensor = worst_distance_per_pixel / pixel_pitch_mm
        min_sensitivity = 1.0 / distance_per_sensor

    return DesignSolution(
        mode=DesignMode.WORKBOOK,
        request=request,
        valid=not violations,
        focal_length_mm=focal,
        alpha_deg=request.alpha_deg,
        beta_deg=beta_deg,
        lo_mm=lo,
        fp_mm=fp,
        total_optical_length_mm=total,
        required_sensor_length_mm=request.sensor_length_mm,
        sensor_length_available_mm=request.sensor_length_mm,
        x_near_mm=-half_sensor,
        x_far_mm=half_sensor,
        width_exact_mm=width,
        rear_exact_mm=rear,
        width_proxy_mm=width,
        rear_proxy_mm=rear,
        sensitivity_sensor_mm_per_object_mm=min_sensitivity,
        distance_per_sensor_mm=distance_per_sensor,
        distance_per_pixel_mm=worst_distance_per_pixel,
        ray_intercept_s_mm=ray_intercept,
        baseline_mm=baseline,
        violations=tuple(violations),
        warnings=tuple(warnings),
        diagnostics=tuple(diagnostics),
        sensor_metrics=sensor_metrics,
    )


def _resolved_profiles(
    request: DesignInput,
    lens: LensProfile | None,
    sensor: SensorProfile | None,
) -> tuple[float, float, float | None, LensProfile | None, SensorProfile | None]:
    if lens is None and request.focal_length_mm is None:
        from scheimpflug_optimeter.hardware import get_lens

        lens = get_lens(request.lens_id)
    if sensor is None and (request.sensor_length_mm is None or request.pixel_pitch_um is None):
        from scheimpflug_optimeter.hardware import get_sensor

        sensor = get_sensor(request.sensor_id)

    focal = (
        request.focal_length_mm
        if request.focal_length_mm is not None
        else lens.focal_length_mm
        if lens is not None
        else None
    )
    sensor_length = (
        request.sensor_length_mm
        if request.sensor_length_mm is not None
        else sensor.length_mm(request.sensor_axis)
        if sensor is not None
        else None
    )
    pixel_pitch = (
        request.pixel_pitch_um
        if request.pixel_pitch_um is not None
        else sensor.pixel_pitch_um
        if sensor is not None
        else None
    )
    if focal is None or sensor_length is None:
        raise OpticalInputError("A focal length and sensor length are required.")
    return focal, sensor_length, pixel_pitch, lens, sensor


def _sample_sensitivities(
    offsets: Iterable[float],
    *,
    alpha_deg: float,
    beta_deg: float,
    lo_mm: float,
    fp_mm: float,
) -> list[float]:
    return [
        image_sensitivity(
            offset,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            lo_mm=lo_mm,
            fp_mm=fp_mm,
        )
        for offset in offsets
    ]


def solve_canonical_design(
    request: DesignInput,
    *,
    lens: LensProfile | None = None,
    sensor: SensorProfile | None = None,
) -> DesignSolution:
    """Solve the canonical independent-alpha/beta thin-lens geometry."""

    _require_finite_positive("d_mm", request.d_mm)
    _require_finite_positive("range_mm", request.range_mm)
    _require_finite("alpha_deg", request.alpha_deg)
    _require_finite("beta_deg", request.beta_deg)
    _require_finite_positive("max_width_mm", request.max_width_mm)
    _require_finite_positive("max_rear_mm", request.max_rear_mm)
    focal, sensor_length, pixel_pitch_um, lens, sensor = _resolved_profiles(request, lens, sensor)
    _require_finite_positive("focal_length_mm", focal)
    _require_finite_positive("sensor_length_mm", sensor_length)
    if pixel_pitch_um is not None:
        _require_finite_positive("pixel_pitch_um", pixel_pitch_um)

    violations: list[ConstraintViolation] = []
    warnings: list[str] = []
    alpha_deg = request.alpha_deg
    beta_deg = request.beta_deg
    if not 0.0 < alpha_deg < 90.0:
        raise OpticalInputError("alpha_deg must be between 0 and 90 degrees.")
    if not 0.0 < beta_deg < 90.0:
        raise OpticalInputError("beta_deg must be between 0 and 90 degrees.")
    if request.range_mm >= 2.0 * request.d_mm:
        violations.append(
            ConstraintViolation(
                "non_positive_near_distance",
                "The requested range reaches or crosses the laser origin.",
                amount=request.range_mm / 2.0,
                limit=request.d_mm,
            )
        )
    if alpha_deg + beta_deg >= _ANGLE_SUM_LIMIT_DEG:
        violations.append(
            ConstraintViolation(
                "angle_sum_limit",
                f"alpha + beta must remain below {_ANGLE_SUM_LIMIT_DEG} degrees.",
                amount=alpha_deg + beta_deg,
                limit=_ANGLE_SUM_LIMIT_DEG,
            )
        )
    elif alpha_deg + beta_deg >= 85.0:
        warnings.append("alpha + beta is close to the numerical singularity.")

    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    tan_alpha = math.tan(alpha)
    tan_beta = math.tan(beta)
    if tan_alpha <= 0 or tan_beta <= 0:
        raise OpticalInputError("alpha and beta must produce positive tangents.")
    ratio = tan_beta / tan_alpha
    lo = focal * (1.0 + ratio)
    fp = focal * (1.0 + 1.0 / ratio)
    total = lo + fp

    near_offset = -request.range_mm / 2.0
    far_offset = request.range_mm / 2.0
    base_denominator = lo * math.sin(beta)
    range_term = far_offset * math.sin(alpha + beta)
    denominator_near = base_denominator - range_term
    denominator_far = base_denominator + range_term
    denominator_scale = max(1.0, abs(base_denominator), abs(range_term))
    singular_limit = _DENOMINATOR_REL_TOL * denominator_scale
    mapping_singular = (
        abs(denominator_near) <= singular_limit
        or abs(denominator_far) <= singular_limit
        or denominator_near * denominator_far <= 0
    )
    if mapping_singular:
        violations.append(
            ConstraintViolation(
                "range_mapping_singular",
                "The object range crosses a triangulation singularity.",
                amount=min(abs(denominator_near), abs(denominator_far)),
                limit=singular_limit,
            )
        )
        x_near = math.nan
        x_far = math.nan
        required_sensor = math.inf
        min_sensitivity = 0.0
        distance_per_sensor = math.inf
    else:
        x_near = image_coordinate_mm(
            near_offset,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            lo_mm=lo,
            fp_mm=fp,
        )
        x_far = image_coordinate_mm(
            far_offset,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            lo_mm=lo,
            fp_mm=fp,
        )
        required_sensor = abs(x_far - x_near)
        if x_far <= x_near:
            violations.append(
                ConstraintViolation(
                    "image_inversion",
                    "The mapped image endpoints are reversed.",
                    amount=x_near - x_far,
                    limit=0.0,
                )
            )
        # The numerator is constant and the valid denominator is positive and
        # affine over the range, so the minimum sensitivity is attained at an
        # endpoint.  Checking both endpoints is exact and keeps optimization
        # evaluations lightweight.
        offsets = (near_offset, far_offset)
        sensitivities = _sample_sensitivities(
            offsets,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            lo_mm=lo,
            fp_mm=fp,
        )
        min_sensitivity = min(abs(value) for value in sensitivities)
        distance_per_sensor = 1.0 / min_sensitivity if min_sensitivity > 0 else math.inf

    sin_alpha = math.sin(alpha)
    cos_alpha = math.cos(alpha)
    q_x = -math.sin(alpha + beta)
    q_z = math.cos(alpha + beta)
    lens_x = lo * sin_alpha
    lens_z = request.d_mm - lo * cos_alpha
    image_x = total * sin_alpha
    image_z = request.d_mm - total * cos_alpha
    if math.isfinite(x_near) and math.isfinite(x_far):
        endpoint_x = (image_x + x_near * q_x, image_x + x_far * q_x)
        endpoint_z = (image_z + x_near * q_z, image_z + x_far * q_z)
        width_exact = max(0.0, abs(lens_x), *(abs(value) for value in endpoint_x))
        rear_exact = max(0.0, -lens_z, -image_z, *(-value for value in endpoint_z))
    else:
        width_exact = math.inf
        rear_exact = math.inf
    half_required = required_sensor / 2.0
    width_proxy = (
        abs(image_x) + half_required * abs(q_x) if math.isfinite(half_required) else math.inf
    )
    rear_proxy = (
        max(0.0, -image_z) + half_required * abs(q_z) if math.isfinite(half_required) else math.inf
    )

    if required_sensor > sensor_length:
        violations.append(
            ConstraintViolation(
                "sensor_length",
                "The required image interval does not fit on the selected sensor axis.",
                amount=required_sensor - sensor_length,
                limit=sensor_length,
            )
        )
    elif required_sensor >= 0.9 * sensor_length:
        warnings.append("Required image length uses at least 90% of the selected sensor axis.")
    if width_exact > request.max_width_mm:
        violations.append(
            ConstraintViolation(
                "mechanical_width",
                "The exact transverse envelope exceeds the mechanical width limit.",
                amount=width_exact - request.max_width_mm,
                limit=request.max_width_mm,
            )
        )
    elif width_exact >= 0.9 * request.max_width_mm:
        warnings.append("Transverse envelope is within 10% of its mechanical limit.")
    if rear_exact > request.max_rear_mm:
        violations.append(
            ConstraintViolation(
                "mechanical_rear",
                "The exact rear envelope exceeds the mechanical rear limit.",
                amount=rear_exact - request.max_rear_mm,
                limit=request.max_rear_mm,
            )
        )
    elif rear_exact >= 0.9 * request.max_rear_mm:
        warnings.append("Rear envelope is within 10% of its mechanical limit.")
    if lo <= 0 or fp <= 0:
        violations.append(
            ConstraintViolation(
                "non_positive_conjugate",
                "Object and image conjugate distances must be positive.",
                amount=min(lo, fp),
                limit=0.0,
            )
        )

    if (
        lens is not None
        and sensor is not None
        and lens.image_circle_mm is not None
        and sensor.diagonal_mm > lens.image_circle_mm
    ):
        violations.append(
            ConstraintViolation(
                "image_circle",
                "The sensor diagonal exceeds the verified lens image circle.",
                amount=sensor.diagonal_mm - lens.image_circle_mm,
                limit=lens.image_circle_mm,
            )
        )

    distance_per_pixel = (
        distance_per_sensor * pixel_pitch_um / 1000.0
        if pixel_pitch_um is not None and math.isfinite(distance_per_sensor)
        else None
    )
    sensor_metrics = (
        calculate_sensor_imaging_metrics(
            sensor,
            sensor_axis=request.sensor_axis,
            alpha_deg=alpha_deg,
            beta_deg=beta_deg,
            lo_mm=lo,
            fp_mm=fp,
            calculation_sensor_length_mm=sensor_length,
        )
        if sensor is not None
        else None
    )
    if sensor_metrics is not None:
        warnings.extend(sensor_metrics.warnings)
        if not sensor_metrics.valid and sensor_metrics.invalid_reason is not None:
            warnings.append(sensor_metrics.invalid_reason)
    if width_exact > width_proxy + 1e-9 or rear_exact > rear_proxy + 1e-9:
        warnings.append(
            "Exact asymmetric image endpoints exceed the paper's centred package proxy."
        )

    focal_residual = 1.0 / lo + 1.0 / fp - 1.0 / focal
    scheimpflug_residual = lo * math.tan(alpha) - fp * math.tan(beta)
    return DesignSolution(
        mode=DesignMode.CANONICAL,
        request=request,
        valid=not violations,
        focal_length_mm=focal,
        alpha_deg=alpha_deg,
        beta_deg=beta_deg,
        lo_mm=lo,
        fp_mm=fp,
        total_optical_length_mm=total,
        required_sensor_length_mm=required_sensor,
        sensor_length_available_mm=sensor_length,
        x_near_mm=x_near,
        x_far_mm=x_far,
        width_exact_mm=width_exact,
        rear_exact_mm=rear_exact,
        width_proxy_mm=width_proxy,
        rear_proxy_mm=rear_proxy,
        sensitivity_sensor_mm_per_object_mm=min_sensitivity,
        distance_per_sensor_mm=distance_per_sensor,
        distance_per_pixel_mm=distance_per_pixel,
        baseline_mm=lens_x,
        violations=tuple(violations),
        warnings=tuple(warnings),
        diagnostics=(
            ("focal_equation_residual", focal_residual),
            ("scheimpflug_residual_mm", scheimpflug_residual),
            ("denominator_near", denominator_near),
            ("denominator_far", denominator_far),
            (
                "image_sensitivity_near",
                (
                    image_sensitivity(
                        near_offset,
                        alpha_deg=alpha_deg,
                        beta_deg=beta_deg,
                        lo_mm=lo,
                        fp_mm=fp,
                    )
                    if not mapping_singular
                    else 0.0
                ),
            ),
            (
                "image_sensitivity_far",
                (
                    image_sensitivity(
                        far_offset,
                        alpha_deg=alpha_deg,
                        beta_deg=beta_deg,
                        lo_mm=lo,
                        fp_mm=fp,
                    )
                    if not mapping_singular
                    else 0.0
                ),
            ),
        ),
        sensor_metrics=sensor_metrics,
    )
