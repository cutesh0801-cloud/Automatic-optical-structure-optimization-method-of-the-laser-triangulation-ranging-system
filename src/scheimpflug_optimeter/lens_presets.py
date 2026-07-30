"""Project-local, user-editable lens presets.

The official hardware catalog remains process-global and immutable.  A user
who wants to alter one of those lenses first copies it into a
``UserLensPreset``.  Converting the preset back to ``LensProfile`` always
creates a new value with a ``user-lens:`` id; it never mutates or shadows the
official catalog entry.

Principal-plane offsets are signed optical-surface-relative coordinates:

* ``S1 -> H`` is measured from the first object-side optical surface.
* ``SL -> H'`` is measured from the last image-side optical surface.

Neither coordinate is a housing, thread shoulder, or sensor datum.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from scheimpflug_optimeter.models import LensProfile

LENS_PRESET_SCHEMA_VERSION = 1
LENS_PRESET_COLLECTION_SCHEMA_VERSION = 1
SEGMENT_SUM_ABSOLUTE_TOLERANCE_MM = 0.10
SEGMENT_SUM_RELATIVE_TOLERANCE = 0.01

_USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class LensPresetError(ValueError):
    """Raised when a user lens preset or preset collection is invalid."""


class PrincipalPlaneDatum(StrEnum):
    """Permitted optical datums for signed principal-plane coordinates."""

    FIRST_OBJECT_SURFACE = "first_object_surface"
    LAST_IMAGE_SURFACE = "last_image_surface"


@dataclass(frozen=True, slots=True)
class LensPresetIssue:
    """Stable, machine-readable validation issue."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class MechanicalRenderingStatus:
    """Whether a preset contains a trustworthy mechanical body description."""

    enabled: bool
    principal_planes_enabled: bool
    missing_fields: tuple[str, ...] = ()
    issues: tuple[LensPresetIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class UserLensPreset:
    """Immutable project-local lens parameters.

    Mechanical dimensions are optional so users can save an optical-only
    preset.  ``mechanical_rendering_status`` disables the physical lens model
    until every required body dimension is present and internally consistent.
    """

    user_id: str
    name: str
    focal_length_mm: float
    mount: str
    manufacturer: str = "User"
    sku: str | None = None
    aperture_f_number: float | None = None
    image_circle_mm: float | None = None
    wavelength_min_nm: float | None = None
    wavelength_max_nm: float | None = None
    working_distance_min_mm: float | None = None
    working_distance_max_mm: float | None = None
    outer_diameter_mm: float | None = None
    overall_length_mm: float | None = None
    weight_g: float | None = None
    resolution_lp_per_mm: float | None = None
    front_housing_length_mm: float | None = None
    threaded_section_length_mm: float | None = None
    thread_major_diameter_mm: float | None = None
    thread_pitch_mm: float | None = None
    thread_tolerance_class: str | None = None
    first_object_surface_recess_from_front_housing_mm: float | None = None
    object_principal_plane_from_first_object_surface_mm: float | None = None
    object_principal_plane_datum: PrincipalPlaneDatum = PrincipalPlaneDatum.FIRST_OBJECT_SURFACE
    image_principal_plane_from_last_image_surface_mm: float | None = None
    image_principal_plane_datum: PrincipalPlaneDatum = PrincipalPlaneDatum.LAST_IMAGE_SURFACE
    back_focal_length_min_mm: float | None = None
    back_focal_length_max_mm: float | None = None
    mechanical_datum: str = "front_housing_face"
    mechanical_drawing_id: str | None = None
    source_url: str | None = None
    mechanical_source_url: str | None = None
    source_profile_id: str | None = None
    source_verified_on: str | None = None
    provenance_notes: tuple[str, ...] = ()
    schema_version: int = LENS_PRESET_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or (
            self.schema_version != LENS_PRESET_SCHEMA_VERSION
        ):
            raise LensPresetError(
                f"Unsupported lens preset schema: {self.schema_version!r}; "
                f"expected {LENS_PRESET_SCHEMA_VERSION}."
            )

        for field_name in ("user_id", "name", "mount", "manufacturer", "mechanical_datum"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise LensPresetError(f"{field_name} must be a non-empty string.")
            object.__setattr__(self, field_name, value.strip())
        if not _USER_ID_PATTERN.fullmatch(self.user_id):
            raise LensPresetError(
                "user_id must start with an ASCII letter or digit and contain only "
                "letters, digits, '.', '_' or '-'; maximum length is 64."
            )

        for field_name in (
            "sku",
            "thread_tolerance_class",
            "mechanical_drawing_id",
            "source_url",
            "mechanical_source_url",
            "source_profile_id",
            "source_verified_on",
        ):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, str) or not value.strip():
                    raise LensPresetError(
                        f"{field_name} must be a non-empty string when specified."
                    )
                object.__setattr__(self, field_name, value.strip())

        positive_fields = (
            "focal_length_mm",
            "aperture_f_number",
            "image_circle_mm",
            "wavelength_min_nm",
            "wavelength_max_nm",
            "working_distance_min_mm",
            "working_distance_max_mm",
            "outer_diameter_mm",
            "overall_length_mm",
            "weight_g",
            "resolution_lp_per_mm",
            "front_housing_length_mm",
            "threaded_section_length_mm",
            "thread_major_diameter_mm",
            "thread_pitch_mm",
            "back_focal_length_min_mm",
            "back_focal_length_max_mm",
        )
        for field_name in positive_fields:
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _finite_number(value, field_name=field_name, positive=True),
                )

        recess_name = "first_object_surface_recess_from_front_housing_mm"
        recess = getattr(self, recess_name)
        if recess is not None:
            object.__setattr__(
                self,
                recess_name,
                _finite_number(recess, field_name=recess_name, nonnegative=True),
            )

        for field_name in (
            "object_principal_plane_from_first_object_surface_mm",
            "image_principal_plane_from_last_image_surface_mm",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(
                    self,
                    field_name,
                    _finite_number(value, field_name=field_name),
                )

        object_datum = _principal_plane_datum(
            self.object_principal_plane_datum,
            field_name="object_principal_plane_datum",
        )
        image_datum = _principal_plane_datum(
            self.image_principal_plane_datum,
            field_name="image_principal_plane_datum",
        )
        if object_datum is not PrincipalPlaneDatum.FIRST_OBJECT_SURFACE:
            raise LensPresetError(
                "S1 -> H must use datum 'first_object_surface'; a housing datum is invalid."
            )
        if image_datum is not PrincipalPlaneDatum.LAST_IMAGE_SURFACE:
            raise LensPresetError(
                "SL -> H' must use datum 'last_image_surface'; a housing datum is invalid."
            )
        object.__setattr__(self, "object_principal_plane_datum", object_datum)
        object.__setattr__(self, "image_principal_plane_datum", image_datum)

        if not isinstance(self.provenance_notes, tuple):
            object.__setattr__(self, "provenance_notes", tuple(self.provenance_notes))
        for note in self.provenance_notes:
            if not isinstance(note, str) or not note.strip():
                raise LensPresetError("provenance_notes must contain non-empty strings.")

        _validate_ordered_pair(
            self.wavelength_min_nm,
            self.wavelength_max_nm,
            label="wavelength",
        )
        _validate_ordered_pair(
            self.working_distance_min_mm,
            self.working_distance_max_mm,
            label="working distance",
        )
        _validate_ordered_pair(
            self.back_focal_length_min_mm,
            self.back_focal_length_max_mm,
            label="back focal length",
        )

    @property
    def runtime_lens_id(self) -> str:
        """Return an id that cannot collide with the official catalog namespace."""

        return f"user-lens:{self.user_id}"

    @property
    def validation_issues(self) -> tuple[LensPresetIssue, ...]:
        """Return non-fatal mechanical consistency findings."""

        issues: list[LensPresetIssue] = []
        if (
            self.front_housing_length_mm is not None
            and self.threaded_section_length_mm is not None
            and self.overall_length_mm is not None
        ):
            segment_sum = self.front_housing_length_mm + self.threaded_section_length_mm
            tolerance = max(
                SEGMENT_SUM_ABSOLUTE_TOLERANCE_MM,
                self.overall_length_mm * SEGMENT_SUM_RELATIVE_TOLERANCE,
            )
            difference = abs(segment_sum - self.overall_length_mm)
            if difference > tolerance:
                issues.append(
                    LensPresetIssue(
                        code="segment_length_mismatch",
                        message=(
                            "front_housing_length_mm + threaded_section_length_mm "
                            f"differs from overall_length_mm by {difference:.6g} mm "
                            f"(allowed {tolerance:.6g} mm)."
                        ),
                    )
                )
        if (
            self.first_object_surface_recess_from_front_housing_mm is not None
            and self.front_housing_length_mm is not None
            and self.first_object_surface_recess_from_front_housing_mm
            > self.front_housing_length_mm
        ):
            issues.append(
                LensPresetIssue(
                    code="first_surface_outside_front_housing",
                    message=(
                        "The first-surface recess exceeds the front housing length; "
                        "mechanical datum or sign is likely wrong."
                    ),
                )
            )
        return tuple(issues)

    @property
    def mechanical_rendering_status(self) -> MechanicalRenderingStatus:
        """Report whether the stepped mechanical lens body may be rendered."""

        required = (
            "outer_diameter_mm",
            "overall_length_mm",
            "front_housing_length_mm",
            "threaded_section_length_mm",
            "thread_major_diameter_mm",
            "thread_pitch_mm",
            "first_object_surface_recess_from_front_housing_mm",
            # The optical solution locates H.  S1 -> H is therefore required
            # to place the external housing from that solved coordinate.
            "object_principal_plane_from_first_object_surface_mm",
        )
        missing = tuple(name for name in required if getattr(self, name) is None)
        issues = self.validation_issues
        enabled = not missing and not issues
        principal_planes_enabled = (
            enabled and self.image_principal_plane_from_last_image_surface_mm is not None
        )
        return MechanicalRenderingStatus(
            enabled=enabled,
            principal_planes_enabled=principal_planes_enabled,
            missing_fields=missing,
            issues=issues,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the stable schema-v1 JSON object."""

        return {
            "schema_version": self.schema_version,
            "user_id": self.user_id,
            "name": self.name,
            "focal_length_mm": self.focal_length_mm,
            "mount": self.mount,
            "manufacturer": self.manufacturer,
            "sku": self.sku,
            "aperture_f_number": self.aperture_f_number,
            "image_circle_mm": self.image_circle_mm,
            "wavelength_min_nm": self.wavelength_min_nm,
            "wavelength_max_nm": self.wavelength_max_nm,
            "working_distance_min_mm": self.working_distance_min_mm,
            "working_distance_max_mm": self.working_distance_max_mm,
            "outer_diameter_mm": self.outer_diameter_mm,
            "overall_length_mm": self.overall_length_mm,
            "weight_g": self.weight_g,
            "resolution_lp_per_mm": self.resolution_lp_per_mm,
            "front_housing_length_mm": self.front_housing_length_mm,
            "threaded_section_length_mm": self.threaded_section_length_mm,
            "thread_major_diameter_mm": self.thread_major_diameter_mm,
            "thread_pitch_mm": self.thread_pitch_mm,
            "thread_tolerance_class": self.thread_tolerance_class,
            "first_object_surface_recess_from_front_housing_mm": (
                self.first_object_surface_recess_from_front_housing_mm
            ),
            "object_principal_plane_from_first_object_surface_mm": (
                self.object_principal_plane_from_first_object_surface_mm
            ),
            "object_principal_plane_datum": self.object_principal_plane_datum.value,
            "image_principal_plane_from_last_image_surface_mm": (
                self.image_principal_plane_from_last_image_surface_mm
            ),
            "image_principal_plane_datum": self.image_principal_plane_datum.value,
            "back_focal_length_min_mm": self.back_focal_length_min_mm,
            "back_focal_length_max_mm": self.back_focal_length_max_mm,
            "mechanical_datum": self.mechanical_datum,
            "mechanical_drawing_id": self.mechanical_drawing_id,
            "source_url": self.source_url,
            "mechanical_source_url": self.mechanical_source_url,
            "source_profile_id": self.source_profile_id,
            "source_verified_on": self.source_verified_on,
            "provenance_notes": list(self.provenance_notes),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> UserLensPreset:
        """Parse one schema-v1 preset and reject unknown or missing fields."""

        if not isinstance(raw, Mapping):
            raise LensPresetError("A lens preset must be a JSON object.")
        allowed = set(_SERIALIZED_FIELDS)
        unknown = sorted(set(raw) - allowed)
        if unknown:
            raise LensPresetError(f"Unknown lens preset fields: {', '.join(unknown)}.")
        missing = [name for name in _REQUIRED_SERIALIZED_FIELDS if name not in raw]
        if missing:
            raise LensPresetError(f"Missing lens preset fields: {', '.join(missing)}.")
        values = dict(raw)
        notes = values.get("provenance_notes", ())
        if not isinstance(notes, (list, tuple)):
            raise LensPresetError("provenance_notes must be a JSON array.")
        values["provenance_notes"] = tuple(notes)
        try:
            return cls(**values)
        except TypeError as exc:
            raise LensPresetError(f"Invalid lens preset fields: {exc}") from exc

    @classmethod
    def from_lens_profile(
        cls,
        profile: LensProfile,
        *,
        user_id: str,
        name: str | None = None,
    ) -> UserLensPreset:
        """Copy an official/static profile into a detached user preset."""

        return cls(
            user_id=user_id,
            name=name or f"{profile.name} (user preset)",
            focal_length_mm=profile.focal_length_mm,
            mount=profile.mount,
            manufacturer=profile.manufacturer,
            sku=profile.sku,
            aperture_f_number=profile.aperture_f_number,
            image_circle_mm=profile.image_circle_mm,
            wavelength_min_nm=profile.wavelength_min_nm,
            wavelength_max_nm=profile.wavelength_max_nm,
            working_distance_min_mm=profile.working_distance_min_mm,
            working_distance_max_mm=profile.working_distance_max_mm,
            outer_diameter_mm=profile.outer_diameter_mm,
            overall_length_mm=profile.overall_length_mm,
            weight_g=profile.weight_g,
            resolution_lp_per_mm=profile.resolution_lp_per_mm,
            front_housing_length_mm=profile.front_housing_length_mm,
            threaded_section_length_mm=profile.threaded_section_length_mm,
            thread_major_diameter_mm=profile.thread_major_diameter_mm,
            thread_pitch_mm=profile.thread_pitch_mm,
            thread_tolerance_class=profile.thread_tolerance_class,
            first_object_surface_recess_from_front_housing_mm=(
                profile.first_object_surface_recess_from_front_housing_mm
            ),
            object_principal_plane_from_first_object_surface_mm=(
                profile.object_principal_plane_from_first_object_surface_mm
            ),
            image_principal_plane_from_last_image_surface_mm=(
                profile.image_principal_plane_from_last_image_surface_mm
            ),
            back_focal_length_min_mm=profile.back_focal_length_min_mm,
            back_focal_length_max_mm=profile.back_focal_length_max_mm,
            mechanical_drawing_id=profile.mechanical_drawing_id,
            source_url=profile.source_url,
            mechanical_source_url=profile.mechanical_source_url,
            source_profile_id=profile.id,
            source_verified_on=profile.verified_on,
            provenance_notes=profile.provenance_notes,
        )

    def to_lens_profile(self) -> LensProfile:
        """Materialize a new runtime profile without touching the source catalog."""

        marker = (
            f"Project-local user preset {self.user_id!r}; mechanical datum={self.mechanical_datum}."
        )
        notes = self.provenance_notes
        if marker not in notes:
            notes = (*notes, marker)
        return LensProfile(
            id=self.runtime_lens_id,
            manufacturer=self.manufacturer,
            sku=self.sku or self.user_id,
            name=self.name,
            focal_length_mm=self.focal_length_mm,
            mount=self.mount,
            image_circle_mm=self.image_circle_mm,
            wavelength_min_nm=self.wavelength_min_nm,
            wavelength_max_nm=self.wavelength_max_nm,
            working_distance_min_mm=self.working_distance_min_mm,
            working_distance_max_mm=self.working_distance_max_mm,
            outer_diameter_mm=self.outer_diameter_mm,
            overall_length_mm=self.overall_length_mm,
            weight_g=self.weight_g,
            resolution_lp_per_mm=self.resolution_lp_per_mm,
            source_url=self.source_url,
            # A project-local editable value is never supplier-verified,
            # even when its audit trail names an official source profile.
            verified_on=None,
            aperture_f_number=self.aperture_f_number,
            front_housing_length_mm=self.front_housing_length_mm,
            threaded_section_length_mm=self.threaded_section_length_mm,
            thread_major_diameter_mm=self.thread_major_diameter_mm,
            thread_pitch_mm=self.thread_pitch_mm,
            thread_tolerance_class=self.thread_tolerance_class,
            first_object_surface_recess_from_front_housing_mm=(
                self.first_object_surface_recess_from_front_housing_mm
            ),
            object_principal_plane_from_first_object_surface_mm=(
                self.object_principal_plane_from_first_object_surface_mm
            ),
            image_principal_plane_from_last_image_surface_mm=(
                self.image_principal_plane_from_last_image_surface_mm
            ),
            back_focal_length_min_mm=self.back_focal_length_min_mm,
            back_focal_length_max_mm=self.back_focal_length_max_mm,
            mechanical_drawing_id=None,
            mechanical_source_url=None,
            is_workbook_reference=False,
            provenance_notes=notes,
        )


_SERIALIZED_FIELDS = tuple(UserLensPreset.__dataclass_fields__)
_REQUIRED_SERIALIZED_FIELDS = (
    "schema_version",
    "user_id",
    "name",
    "focal_length_mm",
    "mount",
)


def lens_presets_to_dict(presets: Iterable[UserLensPreset]) -> dict[str, Any]:
    """Return a validated, stable collection payload."""

    materialized = tuple(presets)
    _reject_duplicate_ids(materialized)
    return {
        "schema_version": LENS_PRESET_COLLECTION_SCHEMA_VERSION,
        "presets": [preset.to_dict() for preset in materialized],
    }


def lens_presets_from_dict(raw: Mapping[str, Any]) -> tuple[UserLensPreset, ...]:
    """Parse a collection payload and reject unsupported schemas/duplicates."""

    if not isinstance(raw, Mapping):
        raise LensPresetError("A lens preset collection must be a JSON object.")
    version = raw.get("schema_version")
    if type(version) is not int:
        raise LensPresetError("Lens preset collection schema_version must be an integer.")
    if version != LENS_PRESET_COLLECTION_SCHEMA_VERSION:
        raise LensPresetError(
            f"Unsupported lens preset collection schema: {version}; "
            f"expected {LENS_PRESET_COLLECTION_SCHEMA_VERSION}."
        )
    unknown = sorted(set(raw) - {"schema_version", "presets"})
    if unknown:
        raise LensPresetError(f"Unknown lens preset collection fields: {', '.join(unknown)}.")
    items = raw.get("presets")
    if not isinstance(items, list):
        raise LensPresetError("Lens preset collection 'presets' must be a JSON array.")
    presets = tuple(UserLensPreset.from_dict(item) for item in items)
    _reject_duplicate_ids(presets)
    return presets


def dumps_lens_presets(presets: Iterable[UserLensPreset], *, indent: int = 2) -> str:
    """Serialize presets as standards-compliant JSON (NaN is forbidden)."""

    return json.dumps(
        lens_presets_to_dict(presets),
        ensure_ascii=False,
        indent=indent,
        allow_nan=False,
    )


def loads_lens_presets(text: str) -> tuple[UserLensPreset, ...]:
    """Deserialize presets while rejecting JavaScript NaN/Infinity extensions."""

    try:
        raw = json.loads(text, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, LensPresetError) as exc:
        if isinstance(exc, LensPresetError):
            raise
        raise LensPresetError(
            f"Invalid lens preset JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}."
        ) from exc
    return lens_presets_from_dict(raw)


def _finite_number(
    value: object,
    *,
    field_name: str,
    positive: bool = False,
    nonnegative: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LensPresetError(f"{field_name} must be a finite number.")
    result = float(value)
    if not math.isfinite(result):
        raise LensPresetError(f"{field_name} must be a finite number.")
    if positive and result <= 0:
        raise LensPresetError(f"{field_name} must be positive when specified.")
    if nonnegative and result < 0:
        raise LensPresetError(f"{field_name} must be non-negative when specified.")
    return result


def _principal_plane_datum(
    value: object,
    *,
    field_name: str,
) -> PrincipalPlaneDatum:
    try:
        return PrincipalPlaneDatum(value)
    except (TypeError, ValueError) as exc:
        choices = ", ".join(item.value for item in PrincipalPlaneDatum)
        raise LensPresetError(f"{field_name} must be one of: {choices}.") from exc


def _validate_ordered_pair(
    minimum: float | None,
    maximum: float | None,
    *,
    label: str,
) -> None:
    if minimum is not None and maximum is not None and minimum > maximum:
        raise LensPresetError(f"{label} minimum must not exceed maximum.")


def _reject_duplicate_ids(presets: Iterable[UserLensPreset]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for preset in presets:
        if preset.user_id in seen:
            duplicates.add(preset.user_id)
        seen.add(preset.user_id)
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise LensPresetError(f"Duplicate user lens preset ids: {names}.")


def _reject_json_constant(value: str) -> Any:
    raise LensPresetError(f"Non-finite JSON number is not allowed: {value}.")
