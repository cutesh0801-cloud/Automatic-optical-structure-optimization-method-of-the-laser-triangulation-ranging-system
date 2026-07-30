"""Immutable domain models shared by the optical core and desktop UI.

All lengths are expressed in millimetres unless a field name explicitly states
another unit.  Angles exposed to callers use degrees; the numerical core
converts them to radians at its boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from math import hypot, isfinite
from typing import Any, Literal


class DesignMode(StrEnum):
    """Supported optical calculation modes."""

    WORKBOOK = "workbook"
    CANONICAL = "canonical"


class CompatibilityStatus(StrEnum):
    """Severity for one hardware compatibility assertion."""

    PASS = "pass"
    WARNING = "warning"
    FAIL = "fail"
    UNKNOWN = "unknown"


class OptimizationAlgorithm(StrEnum):
    """Available continuous optimizers."""

    SCIPY = "scipy"
    MPSO = "mpso"


@dataclass(frozen=True, slots=True)
class Point2D:
    """Point in the optical X/Z section."""

    x_mm: float
    z_mm: float

    def distance_to(self, other: Point2D) -> float:
        return hypot(self.x_mm - other.x_mm, self.z_mm - other.z_mm)


@dataclass(frozen=True, slots=True)
class SensorProfile:
    """Active sensor dimensions and sampling."""

    id: str
    name: str
    width_px: int
    height_px: int
    pixel_pitch_um: float
    color_mode: Literal["mono", "color"] = "mono"

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip():
            raise ValueError("Sensor id and name are required.")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("Sensor pixel dimensions must be positive.")
        if self.pixel_pitch_um <= 0:
            raise ValueError("Sensor pixel pitch must be positive.")

    @property
    def width_mm(self) -> float:
        return self.width_px * self.pixel_pitch_um / 1000.0

    @property
    def height_mm(self) -> float:
        return self.height_px * self.pixel_pitch_um / 1000.0

    @property
    def diagonal_mm(self) -> float:
        return hypot(self.width_mm, self.height_mm)

    def length_mm(self, axis: str) -> float:
        """Return the active length selected for triangulation."""

        normalized = axis.lower()
        if normalized in {"width", "horizontal", "x", "long"}:
            return self.width_mm
        if normalized in {"height", "vertical", "y", "short"}:
            return self.height_mm
        raise ValueError(f"Unsupported sensor axis: {axis!r}")


@dataclass(frozen=True, slots=True)
class CameraProfile:
    """Static camera catalog entry."""

    id: str
    manufacturer: str
    model: str
    interface: str
    mount: str
    max_fps: float
    sensor: SensorProfile
    notes: tuple[str, ...] = ()
    source_url: str | None = None
    verified_on: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.model.strip():
            raise ValueError("Camera id and model are required.")
        if self.max_fps <= 0:
            raise ValueError("Camera frame rate must be positive.")


@dataclass(frozen=True, slots=True)
class LensProfile:
    """Static lens catalog entry.

    Optional specifications deliberately remain ``None`` when the catalog
    source has not been verified.  Compatibility checks report these as
    unknown rather than inventing a value.
    """

    id: str
    manufacturer: str
    sku: str
    name: str
    focal_length_mm: float
    mount: str = "M12x0.5"
    image_circle_mm: float | None = None
    wavelength_min_nm: float | None = None
    wavelength_max_nm: float | None = None
    working_distance_min_mm: float | None = None
    working_distance_max_mm: float | None = None
    outer_diameter_mm: float | None = None
    overall_length_mm: float | None = None
    weight_g: float | None = None
    resolution_lp_per_mm: float | None = None
    source_url: str | None = None
    verified_on: str | None = None
    # The fields below deliberately retain the datum stated by the supplier.
    # In particular, a principal-plane coordinate is *not* an enclosure or
    # sensor coordinate: it is meaningful only together with its named
    # optical-surface reference.
    aperture_f_number: float | None = None
    front_housing_length_mm: float | None = None
    threaded_section_length_mm: float | None = None
    thread_major_diameter_mm: float | None = None
    thread_pitch_mm: float | None = None
    thread_tolerance_class: str | None = None
    first_object_surface_recess_from_front_housing_mm: float | None = None
    object_principal_plane_from_first_object_surface_mm: float | None = None
    image_principal_plane_from_last_image_surface_mm: float | None = None
    back_focal_length_min_mm: float | None = None
    back_focal_length_max_mm: float | None = None
    mechanical_drawing_id: str | None = None
    mechanical_source_url: str | None = None
    is_workbook_reference: bool = False
    provenance_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.provenance_notes, tuple):
            object.__setattr__(self, "provenance_notes", tuple(self.provenance_notes))
        if not self.id.strip() or not self.sku.strip():
            raise ValueError("Lens id and SKU are required.")
        if not isfinite(self.focal_length_mm) or self.focal_length_mm <= 0:
            raise ValueError("Lens focal length must be finite and positive.")
        for field_name in (
            "image_circle_mm",
            "wavelength_min_nm",
            "wavelength_max_nm",
            "working_distance_min_mm",
            "working_distance_max_mm",
            "outer_diameter_mm",
            "overall_length_mm",
            "weight_g",
            "resolution_lp_per_mm",
            "aperture_f_number",
            "front_housing_length_mm",
            "threaded_section_length_mm",
            "thread_major_diameter_mm",
            "thread_pitch_mm",
            "back_focal_length_min_mm",
            "back_focal_length_max_mm",
        ):
            value = getattr(self, field_name)
            if value is not None and (not isfinite(value) or value <= 0):
                raise ValueError(f"{field_name} must be finite and positive when specified.")
        recess = self.first_object_surface_recess_from_front_housing_mm
        if recess is not None and (not isfinite(recess) or recess < 0):
            raise ValueError(
                "first_object_surface_recess_from_front_housing_mm must be "
                "finite and non-negative when specified."
            )
        if (
            self.back_focal_length_min_mm is not None
            and self.back_focal_length_max_mm is not None
            and self.back_focal_length_min_mm > self.back_focal_length_max_mm
        ):
            raise ValueError("back focal length minimum must not exceed maximum.")


@dataclass(frozen=True, slots=True)
class ConstraintViolation:
    """One failed numerical or mechanical constraint."""

    code: str
    message: str
    amount: float | None = None
    limit: float | None = None


@dataclass(frozen=True, slots=True)
class DesignInput:
    """Canonical thin-lens Scheimpflug design request."""

    d_mm: float
    range_mm: float
    alpha_deg: float
    beta_deg: float
    lens_id: str = "edmund-33-879"
    sensor_id: str = "basler-aca1300-60gm-sensor"
    sensor_axis: str = "height"
    max_width_mm: float = 105.0
    max_rear_mm: float = 105.0
    laser_wavelength_nm: float | None = None
    max_sensor_tilt_deg: float | None = None
    focal_length_mm: float | None = None
    sensor_length_mm: float | None = None
    pixel_pitch_um: float | None = None


@dataclass(frozen=True, slots=True)
class WorkbookDesignInput:
    """Inputs used by the legacy workbook compatibility calculation."""

    v_mm: float
    d_mm: float
    sensor_length_mm: float | None
    alpha_deg: float | None = None
    sensor_id: str = "basler-aca1300-60gm-sensor"
    sensor_axis: str = "height"
    focal_length_literal_mm: float | None = None
    alpha_reference_deg: float | None = None
    rm_cmos_distance_mm: float | None = None
    fov_mm: float | None = None
    provenance_id: str | None = None


@dataclass(frozen=True, slots=True)
class SensorImagingMetrics:
    """Object-space coverage and sampling for one static sensor profile.

    ``horizontal`` and ``vertical`` refer to the camera sensor axes.  The
    selected ``sensor_axis`` is the triangulation/range axis; its field of view
    uses the exact nonlinear Scheimpflug image mapping.  The orthogonal axis
    uses the reference-plane thin-lens magnification ``fp / lo``.

    Range positions are signed offsets from the design reference target.
    Local range sensitivity is ``ds/dpixel`` in millimetres per pixel.  Metrics
    that cannot be defined because the active sensor crosses the mapping pole
    are ``None`` and ``valid`` is false; they are never represented by a
    plausible-looking infinity.
    """

    sensor: SensorProfile
    sensor_axis: Literal["width", "height"]
    valid: bool
    horizontal_fov_mm: float | None
    vertical_fov_mm: float | None
    horizontal_sampling_mm_per_px: float | None
    vertical_sampling_mm_per_px: float | None
    range_min_offset_mm: float | None
    range_max_offset_mm: float | None
    range_sensitivity_near_mm_per_px: float | None
    range_sensitivity_center_mm_per_px: float | None
    range_sensitivity_far_mm_per_px: float | None
    range_sensitivity_worst_mm_per_px: float | None
    invalid_reason: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def resolution_px(self) -> tuple[int, int]:
        """Return ``(horizontal, vertical)`` active pixel counts."""

        return self.sensor.width_px, self.sensor.height_px

    @property
    def dimensions_mm(self) -> tuple[float, float]:
        """Return ``(horizontal, vertical)`` active dimensions in millimetres."""

        return self.sensor.width_mm, self.sensor.height_mm

    @property
    def range_fov_mm(self) -> float | None:
        if self.range_min_offset_mm is None or self.range_max_offset_mm is None:
            return None
        return self.range_max_offset_mm - self.range_min_offset_mm


@dataclass(frozen=True, slots=True)
class DesignSolution:
    """Complete numerical result from either optical solver."""

    mode: DesignMode
    request: DesignInput | WorkbookDesignInput
    valid: bool
    focal_length_mm: float
    alpha_deg: float
    beta_deg: float
    lo_mm: float
    fp_mm: float
    total_optical_length_mm: float
    required_sensor_length_mm: float
    sensor_length_available_mm: float
    x_near_mm: float
    x_far_mm: float
    width_exact_mm: float
    rear_exact_mm: float
    width_proxy_mm: float
    rear_proxy_mm: float
    sensitivity_sensor_mm_per_object_mm: float
    distance_per_sensor_mm: float
    distance_per_pixel_mm: float | None
    ray_intercept_s_mm: float | None = None
    baseline_mm: float | None = None
    violations: tuple[ConstraintViolation, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: tuple[tuple[str, float], ...] = ()
    sensor_metrics: SensorImagingMetrics | None = None

    @property
    def l_required_mm(self) -> float:
        return self.required_sensor_length_mm

    @property
    def w_mm(self) -> float:
        """Conservative transverse envelope used for validation."""

        return self.width_exact_mm

    @property
    def r_mm(self) -> float:
        """Conservative rear envelope used for validation."""

        return self.rear_exact_mm

    @property
    def sensitivity(self) -> float:
        return self.sensitivity_sensor_mm_per_object_mm

    def diagnostic(self, key: str, default: float | None = None) -> float | None:
        return dict(self.diagnostics).get(key, default)


@dataclass(frozen=True, slots=True)
class SceneGeometry:
    """Named primitives for a real-time 2D optical section.

    ``object_principal_plane`` and ``image_principal_plane`` are the axial
    section coordinates of the object-space principal point H and image-space
    principal point H′.  Thin-lens solutions place both at ``lens_center``;
    no unverified principal-plane separation or lens-to-sensor ``h`` distance
    is implied.
    """

    emitter: Point2D
    target_near: Point2D
    target_center: Point2D
    target_far: Point2D
    lens_center: Point2D
    object_principal_plane: Point2D
    image_principal_plane: Point2D
    principal_planes_coincident: bool
    image_center: Point2D
    sensor_near: Point2D
    sensor_far: Point2D
    sensor_proxy_near: Point2D
    sensor_proxy_far: Point2D
    scheimpflug_intersection: Point2D | None
    laser_line: tuple[Point2D, Point2D]
    optical_axis: tuple[Point2D, Point2D]
    lens_plane: tuple[Point2D, Point2D]
    image_plane: tuple[Point2D, Point2D]
    object_range: tuple[Point2D, Point2D]
    front_plane_z_mm: float | None = None
    ray_intercept: Point2D | None = None

    def all_finite_points(self) -> tuple[Point2D, ...]:
        values = (
            self.emitter,
            self.target_near,
            self.target_center,
            self.target_far,
            self.lens_center,
            self.object_principal_plane,
            self.image_principal_plane,
            self.image_center,
            self.sensor_near,
            self.sensor_far,
            self.sensor_proxy_near,
            self.sensor_proxy_far,
        )
        optional = tuple(
            point
            for point in (self.scheimpflug_intersection, self.ray_intercept)
            if point is not None
        )
        return values + optional


@dataclass(frozen=True, slots=True)
class CompatibilityCheck:
    """One mount, optical, or mechanical compatibility result."""

    code: str
    label: str
    status: CompatibilityStatus
    message: str


@dataclass(frozen=True, slots=True)
class CompatibilityReport:
    """Compatibility results for one camera/lens pair."""

    camera_id: str
    lens_id: str
    checks: tuple[CompatibilityCheck, ...]

    @property
    def compatible(self) -> bool:
        return not any(item.status is CompatibilityStatus.FAIL for item in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(
            item.status in {CompatibilityStatus.WARNING, CompatibilityStatus.UNKNOWN}
            for item in self.checks
        )


@dataclass(frozen=True, slots=True)
class OptimizationRequest:
    """Discrete-lens and continuous-angle optimization request."""

    d_mm: float
    range_mm: float
    sensor_id: str = "basler-aca1300-60gm-sensor"
    sensor_axis: str = "height"
    lens_ids: tuple[str, ...] = ()
    algorithm: OptimizationAlgorithm | str = OptimizationAlgorithm.SCIPY
    alpha_bounds_deg: tuple[float, float] = (15.0, 45.0)
    beta_bounds_deg: tuple[float, float] = (20.0, 55.0)
    max_width_mm: float = 105.0
    max_rear_mm: float = 105.0
    seed: int = 2026
    scipy_population_multiplier: int = 15
    max_iterations: int = 300
    tolerance: float = 1e-8
    mpso_particles: int = 200
    mpso_stagnation_iterations: int = 30
    mpso_stagnation_delta: float = 0.1
    mpso_radius_threshold: float = 0.1
    mpso_mutation_probability: float = 0.2


@dataclass(frozen=True, slots=True)
class OptimizationCandidate:
    """One valid optimized lens/angle design."""

    lens_id: str
    solution: DesignSolution
    objective_mm_per_pixel: float
    evaluations: int


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Ranked optimization output."""

    algorithm: OptimizationAlgorithm
    candidates: tuple[OptimizationCandidate, ...]
    seed: int
    iterations: int
    evaluations: int
    cancelled: bool = False
    infeasible_reasons: tuple[ConstraintViolation, ...] = ()
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    @property
    def best(self) -> OptimizationCandidate | None:
        return self.candidates[0] if self.candidates else None
