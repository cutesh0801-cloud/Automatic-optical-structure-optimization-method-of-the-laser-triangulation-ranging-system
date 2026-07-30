from __future__ import annotations

import json
from dataclasses import asdict
from types import MappingProxyType

import pytest

from scheimpflug_optimeter.hardware import (
    CAMERAS,
    LENSES,
    SENSORS,
    create_custom_camera_profile,
    evaluate_compatibility,
    get_camera,
    get_lens,
    get_sensor,
)
from scheimpflug_optimeter.models import (
    CompatibilityStatus,
    DesignInput,
    LensProfile,
)
from scheimpflug_optimeter.optics import solve_canonical_design


def test_catalog_contains_verified_basler_tiers_and_edmund_skus():
    assert isinstance(CAMERAS, MappingProxyType)
    assert isinstance(LENSES, MappingProxyType)
    assert len(CAMERAS) == 4
    assert set(LENSES) == {
        "edmund-33-879",
        "edmund-83-953",
        "edmund-36-376",
        "edmund-58-206",
        "edmund-83-954",
        "edmund-36-385",
        "edmund-70-646",
    }

    ace = get_camera("basler-aca1300-60gm")
    assert ace.model == "ace acA1300-60gm"
    assert ace.sensor.width_px == 1282
    assert ace.sensor.height_px == 1026
    assert ace.sensor.pixel_pitch_um == pytest.approx(5.3)
    assert ace.sensor.width_mm == pytest.approx(6.7946)
    assert ace.sensor.height_mm == pytest.approx(5.4378)
    assert ace.mount == "C"
    assert ace.max_fps == pytest.approx(60.0)
    assert ace.source_url == "https://docs.baslerweb.com/aca1300-60gm"

    dma = get_camera("basler-dma2048-37gm")
    assert (dma.sensor.width_px, dma.sensor.height_px) == (2064, 1552)
    assert dma.sensor.pixel_pitch_um == pytest.approx(2.25)
    assert dma.max_fps == pytest.approx(37.2)
    assert any("32.6 fps" in note and "packet size of 4000" in note for note in dma.notes)

    daa = get_camera("basler-daa2448-70um")
    assert (daa.sensor.width_px, daa.sensor.height_px) == (2448, 2048)
    assert any("2472 x 2064" in note for note in daa.notes)
    assert any("29.8 fps" in note and "72.8 fps" in note for note in daa.notes)


def test_workbook_reference_lens_and_f8_variant_remain_distinct_and_traceable():
    workbook_lens = get_lens("edmund-58-206")
    f8_lens = get_lens("edmund-83-954")

    assert workbook_lens.is_workbook_reference
    assert workbook_lens.sku == "58-206"
    assert workbook_lens.aperture_f_number == pytest.approx(2.5)
    assert f8_lens.sku == "83-954"
    assert not f8_lens.is_workbook_reference
    assert f8_lens.aperture_f_number == pytest.approx(8.0)
    assert workbook_lens.focal_length_mm == f8_lens.focal_length_mm == pytest.approx(17.5)

    for lens, expected_length, expected_thread, expected_recess in (
        (workbook_lens, 20.68, 13.08, 0.30),
        (f8_lens, 20.70, 13.10, 0.12),
    ):
        assert lens.outer_diameter_mm == pytest.approx(14.0)
        assert lens.overall_length_mm == pytest.approx(expected_length)
        assert lens.front_housing_length_mm == pytest.approx(7.60)
        assert lens.threaded_section_length_mm == pytest.approx(expected_thread)
        assert lens.thread_major_diameter_mm == pytest.approx(12.0)
        assert lens.thread_pitch_mm == pytest.approx(0.5)
        assert lens.first_object_surface_recess_from_front_housing_mm == pytest.approx(
            expected_recess
        )
        assert lens.object_principal_plane_from_first_object_surface_mm == pytest.approx(5.57)
        assert lens.image_principal_plane_from_last_image_surface_mm == pytest.approx(-12.71)
        assert lens.back_focal_length_min_mm == pytest.approx(4.9)
        assert lens.back_focal_length_max_mm == pytest.approx(5.8)
        assert lens.mechanical_drawing_id
        assert lens.mechanical_source_url
        assert "document/download/" in lens.mechanical_source_url
        assert lens.provenance_notes


def test_lens_catalog_extended_fields_are_json_serializable_and_tuple_backed():
    lens = get_lens("edmund-58-206")

    assert isinstance(lens.provenance_notes, tuple)
    serialized = json.loads(json.dumps(asdict(lens)))
    assert serialized["is_workbook_reference"] is True
    assert serialized["image_principal_plane_from_last_image_surface_mm"] == pytest.approx(-12.71)
    assert serialized["provenance_notes"]

    direct = LensProfile(
        id="provenance-test",
        manufacturer="Test",
        sku="PROV",
        name="Provenance test",
        focal_length_mm=10.0,
        provenance_notes=["input list is frozen as a tuple"],  # type: ignore[arg-type]
    )
    assert direct.provenance_notes == ("input list is frozen as a tuple",)


def test_sensor_can_be_resolved_by_sensor_or_camera_id_and_catalog_is_immutable():
    sensor = get_sensor("basler-aca1300-60gm-sensor")
    assert get_sensor("basler-aca1300-60gm") is sensor
    assert SENSORS[sensor.id] is sensor
    with pytest.raises(TypeError):
        CAMERAS["new"] = get_camera("basler-aca1300-60gm")  # type: ignore[index]
    with pytest.raises(KeyError, match="Unknown lens"):
        get_lens("does-not-exist")


def test_custom_camera_profile_is_validated_without_mutating_static_catalog():
    before = tuple(CAMERAS)
    custom = create_custom_camera_profile(
        profile_id="custom-line-camera",
        model="Line camera prototype",
        width_px=1920,
        height_px=1200,
        pixel_pitch_um=3.45,
        interface="USB 3.0",
        mount="S",
        max_fps=50.0,
    )

    assert custom.sensor.width_mm == pytest.approx(6.624)
    assert custom.sensor.id == "custom-line-camera-sensor"
    assert tuple(CAMERAS) == before
    assert custom.id not in CAMERAS


def test_unverified_lens_fields_remain_none_instead_of_guessed_values():
    lens = get_lens("edmund-33-879")

    assert lens.focal_length_mm == pytest.approx(12.0)
    assert lens.mount == "M12x0.5"
    assert lens.image_circle_mm is None
    assert lens.working_distance_min_mm is None
    assert lens.wavelength_min_nm is None
    assert lens.overall_length_mm is None
    assert lens.weight_g is None


def test_aca_m12_report_requires_adapter_tilt_and_reports_unknown_specs():
    camera = get_camera("basler-aca1300-60gm")
    lens = get_lens("edmund-33-879")
    design = DesignInput(200.0, 2.0, 25.0, 25.0, laser_wavelength_nm=650.0)
    report = evaluate_compatibility(camera, lens, design)
    checks = {check.code: check for check in report.checks}

    assert report.compatible
    assert report.has_warnings
    assert checks["mount"].status is CompatibilityStatus.WARNING
    assert "#53-675" in checks["mount"].message
    assert "does not provide Scheimpflug tilt" in checks["mount"].message
    assert checks["image_circle"].status is CompatibilityStatus.UNKNOWN
    assert checks["working_distance"].status is CompatibilityStatus.UNKNOWN
    assert checks["tilt_mechanism"].status is CompatibilityStatus.WARNING
    assert checks["m12_flange"].status is CompatibilityStatus.WARNING


def test_report_accepts_ui_design_solution_and_enforces_verified_limits():
    camera = get_camera("basler-aca1300-60gm")
    lens = LensProfile(
        id="verified-lens",
        manufacturer="Test",
        sku="TEST",
        name="Verified test lens",
        focal_length_mm=12.0,
        image_circle_mm=5.0,
        wavelength_min_nm=600.0,
        wavelength_max_nm=700.0,
        working_distance_min_mm=100.0,
        working_distance_max_mm=300.0,
        overall_length_mm=20.0,
        weight_g=5.0,
        resolution_lp_per_mm=120.0,
    )
    request = DesignInput(
        200.0,
        2.0,
        25.0,
        25.0,
        focal_length_mm=12.0,
        sensor_length_mm=camera.sensor.height_mm,
        pixel_pitch_um=camera.sensor.pixel_pitch_um,
        laser_wavelength_nm=650.0,
        max_sensor_tilt_deg=20.0,
        max_width_mm=500.0,
        max_rear_mm=500.0,
    )
    solution = solve_canonical_design(request)
    checks = {check.code: check for check in evaluate_compatibility(camera, lens, solution).checks}

    assert checks["image_circle"].status is CompatibilityStatus.FAIL
    assert checks["working_distance"].status is CompatibilityStatus.PASS
    assert checks["wavelength"].status is CompatibilityStatus.PASS
    assert checks["tilt_mechanism"].status is CompatibilityStatus.FAIL
