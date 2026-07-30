from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace

import pytest

from scheimpflug_optimeter.hardware.catalog import LENSES
from scheimpflug_optimeter.lens_presets import (
    LENS_PRESET_COLLECTION_SCHEMA_VERSION,
    LENS_PRESET_SCHEMA_VERSION,
    LensPresetError,
    PrincipalPlaneDatum,
    UserLensPreset,
    dumps_lens_presets,
    lens_presets_from_dict,
    lens_presets_to_dict,
    loads_lens_presets,
)


def complete_preset(**changes: object) -> UserLensPreset:
    values: dict[str, object] = {
        "user_id": "shop-floor-175",
        "name": "Shop floor 17.5 mm",
        "focal_length_mm": 17.5,
        "aperture_f_number": 8.0,
        "mount": "M12x0.5",
        "outer_diameter_mm": 14.0,
        "overall_length_mm": 20.7,
        "front_housing_length_mm": 7.6,
        "threaded_section_length_mm": 13.1,
        "thread_major_diameter_mm": 12.0,
        "thread_pitch_mm": 0.5,
        "first_object_surface_recess_from_front_housing_mm": 0.12,
        "object_principal_plane_from_first_object_surface_mm": 5.57,
        "image_principal_plane_from_last_image_surface_mm": -12.71,
        "mechanical_datum": "front_housing_face",
    }
    values.update(changes)
    return UserLensPreset(**values)  # type: ignore[arg-type]


def test_copy_from_catalog_is_detached_and_catalog_stays_immutable() -> None:
    official = LENSES["edmund-83-954"]
    preset = UserLensPreset.from_lens_profile(
        official,
        user_id="prototype-a",
        name="Prototype A",
    )
    edited = replace(preset, focal_length_mm=18.25, name="Prototype A edited")
    runtime = edited.to_lens_profile()

    assert preset.source_profile_id == official.id
    assert runtime.id == "user-lens:prototype-a"
    assert runtime.focal_length_mm == 18.25
    assert runtime.name == "Prototype A edited"
    assert runtime.object_principal_plane_from_first_object_surface_mm == 5.57
    assert runtime.image_principal_plane_from_last_image_surface_mm == -12.71
    assert runtime.is_workbook_reference is False
    assert runtime.verified_on is None
    assert runtime.mechanical_drawing_id is None
    assert runtime.mechanical_source_url is None
    assert LENSES["edmund-83-954"] is official
    assert official.focal_length_mm == 17.5
    with pytest.raises(FrozenInstanceError):
        official.focal_length_mm = 20.0  # type: ignore[misc]


def test_complete_mechanics_and_principal_planes_are_renderable() -> None:
    preset = complete_preset()
    status = preset.mechanical_rendering_status

    assert status.enabled is True
    assert status.principal_planes_enabled is True
    assert status.missing_fields == ()
    assert status.issues == ()
    assert preset.object_principal_plane_datum is PrincipalPlaneDatum.FIRST_OBJECT_SURFACE
    assert preset.image_principal_plane_datum is PrincipalPlaneDatum.LAST_IMAGE_SURFACE


def test_flush_first_surface_zero_recess_remains_renderable_at_runtime() -> None:
    preset = complete_preset(
        first_object_surface_recess_from_front_housing_mm=0.0,
    )

    assert preset.mechanical_rendering_status.enabled is True
    runtime = preset.to_lens_profile()
    assert runtime.first_object_surface_recess_from_front_housing_mm == 0.0


def test_incomplete_mechanics_remain_valid_but_disable_body_rendering() -> None:
    preset = UserLensPreset(
        user_id="optical-only",
        name="Optical only",
        focal_length_mm=25.0,
        aperture_f_number=None,
        mount="M12x0.5",
    )

    status = preset.mechanical_rendering_status
    assert status.enabled is False
    assert status.principal_planes_enabled is False
    assert "overall_length_mm" in status.missing_fields
    assert preset.to_lens_profile().overall_length_mm is None


def test_inconsistent_segment_sum_is_an_explicit_rendering_issue() -> None:
    preset = complete_preset(threaded_section_length_mm=9.0)
    status = preset.mechanical_rendering_status

    assert status.enabled is False
    assert [issue.code for issue in status.issues] == ["segment_length_mismatch"]
    assert "differs from overall_length_mm" in status.issues[0].message


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("focal_length_mm", 0.0),
        ("outer_diameter_mm", -1.0),
        ("thread_pitch_mm", float("inf")),
        ("aperture_f_number", float("nan")),
        ("first_object_surface_recess_from_front_housing_mm", -0.01),
    ],
)
def test_invalid_physical_numbers_are_rejected(field_name: str, value: float) -> None:
    with pytest.raises(LensPresetError):
        complete_preset(**{field_name: value})


def test_signed_principal_plane_values_accept_negative_but_require_optical_datums() -> None:
    preset = complete_preset(
        object_principal_plane_from_first_object_surface_mm=-1.25,
        image_principal_plane_from_last_image_surface_mm=-4.5,
    )
    assert preset.object_principal_plane_from_first_object_surface_mm == -1.25
    assert preset.image_principal_plane_from_last_image_surface_mm == -4.5

    with pytest.raises(LensPresetError, match="S1 -> H"):
        complete_preset(
            object_principal_plane_datum=PrincipalPlaneDatum.LAST_IMAGE_SURFACE,
        )
    with pytest.raises(LensPresetError, match="SL -> H'"):
        complete_preset(
            image_principal_plane_datum=PrincipalPlaneDatum.FIRST_OBJECT_SURFACE,
        )


def test_json_collection_round_trip_is_stable_and_schema_explicit() -> None:
    first = complete_preset()
    second = UserLensPreset.from_lens_profile(
        LENSES["edmund-58-206"],
        user_id="workbook-lens-copy",
    )

    encoded = dumps_lens_presets((first, second))
    decoded = loads_lens_presets(encoded)

    assert decoded == (first, second)
    payload = json.loads(encoded)
    assert payload["schema_version"] == LENS_PRESET_COLLECTION_SCHEMA_VERSION
    assert payload["presets"][0]["schema_version"] == LENS_PRESET_SCHEMA_VERSION
    assert payload["presets"][0]["object_principal_plane_datum"] == ("first_object_surface")
    assert payload["presets"][0]["image_principal_plane_datum"] == ("last_image_surface")
    assert lens_presets_to_dict(decoded) == payload


def test_duplicate_ids_are_rejected_during_write_and_parse() -> None:
    preset = complete_preset()
    with pytest.raises(LensPresetError, match="Duplicate"):
        lens_presets_to_dict((preset, preset))

    payload = lens_presets_to_dict((preset,))
    payload["presets"].append(preset.to_dict())
    with pytest.raises(LensPresetError, match="Duplicate"):
        lens_presets_from_dict(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 999, "presets": []},
        {"schema_version": True, "presets": []},
        {
            "schema_version": 1,
            "presets": [
                {
                    **complete_preset().to_dict(),
                    "schema_version": 999,
                }
            ],
        },
    ],
)
def test_unsupported_or_non_integer_schemas_are_rejected(
    payload: dict[str, object],
) -> None:
    with pytest.raises(LensPresetError, match="[Ss]chema"):
        lens_presets_from_dict(payload)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_json_extensions_are_rejected(constant: str) -> None:
    valid = complete_preset().to_dict()
    valid["focal_length_mm"] = constant
    text = json.dumps(
        {"schema_version": 1, "presets": [valid]},
        allow_nan=False,
    ).replace(f'"{constant}"', constant)

    with pytest.raises(LensPresetError, match="Non-finite"):
        loads_lens_presets(text)


def test_unknown_fields_are_rejected_instead_of_silently_ignored() -> None:
    raw = complete_preset().to_dict()
    raw["focal_lenght_mm"] = raw["focal_length_mm"]
    with pytest.raises(LensPresetError, match="Unknown"):
        UserLensPreset.from_dict(raw)
