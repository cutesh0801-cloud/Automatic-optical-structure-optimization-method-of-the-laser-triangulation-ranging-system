from __future__ import annotations

import json
from dataclasses import replace

import pytest

from scheimpflug_optimeter.hardware.catalog import LENSES
from scheimpflug_optimeter.lens_presets import (
    UserLensPreset,
    lens_presets_from_dict,
    lens_presets_to_dict,
)
from scheimpflug_optimeter.project import (
    PROJECT_SUFFIX,
    ProjectDocument,
    ProjectError,
    load_project,
    normalize_project_path,
    save_project,
)


def test_project_round_trip_keeps_only_authoritative_values(tmp_path):
    document = ProjectDocument(
        project_name="검증 설계",
        design_input={
            "mode": "canonical",
            "d_mm": 200.0,
            "range_mm": 5.0,
            "alpha_deg": 30.0,
            "beta_deg": 25.0,
        },
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "edmund-33-879",
        },
        selected_optimization={"algorithm": "scipy", "seed": 2026},
        ui_state={"active_tab": 1, "design_splitter_sizes": [300, 800, 350]},
    )

    saved = save_project(tmp_path / "fixture", document)

    assert saved.name == f"fixture{PROJECT_SUFFIX}"
    assert load_project(saved) == document
    raw = json.loads(saved.read_text(encoding="utf-8"))
    assert list(raw)[0] == "schema_version"
    assert raw["schema_version"] == 1
    assert "derived" not in raw
    assert "design_solution" not in raw


def test_selected_user_lens_round_trip_is_detached_from_official_catalog(tmp_path):
    official = LENSES["edmund-58-206"]
    catalog_before = tuple(LENSES.items())
    preset = replace(
        UserLensPreset.from_lens_profile(
            official,
            user_id="line-a-175",
            name="Line A 17.5 mm",
        ),
        focal_length_mm=18.25,
        object_principal_plane_from_first_object_surface_mm=6.0,
    )
    document = ProjectDocument(
        project_name="User lens round trip",
        design_input={
            "mode": "workbook",
            "focal_length_literal_mm": preset.focal_length_mm,
            "user_lens_presets": lens_presets_to_dict((preset,)),
        },
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": preset.runtime_lens_id,
        },
    )

    loaded = load_project(save_project(tmp_path / "user-lens", document))
    loaded_presets = lens_presets_from_dict(loaded.design_input["user_lens_presets"])
    runtime = loaded_presets[0].to_lens_profile()

    assert loaded == document
    assert loaded.hardware["lens_id"] == "user-lens:line-a-175"
    assert loaded_presets == (preset,)
    assert runtime.id == loaded.hardware["lens_id"]
    assert runtime.focal_length_mm == pytest.approx(18.25)
    assert runtime is not official
    assert tuple(LENSES.items()) == catalog_before
    assert LENSES[official.id] is official
    assert runtime.id not in LENSES


def test_new_project_defaults_to_authoritative_workbook_inputs():
    document = ProjectDocument()

    assert document.design_input == {
        "mode": "workbook",
        "sensor_axis": "height",
        "v_mm": 150.0,
        "d_mm": 100.0,
        "sensor_length_mm": 5.4378,
        "sensor_length_linked": True,
        "focal_length_literal_mm": 17.5,
        "focal_length_linked": True,
        "alpha_manual": False,
        "alpha_deg": None,
        "user_lens_presets": {"schema_version": 1, "presets": []},
    }
    assert document.hardware["camera_id"] == "basler-aca1300-60gm"
    assert document.hardware["lens_id"] == "edmund-58-206"


def test_loading_ignores_stale_derived_values(tmp_path):
    path = tmp_path / f"stale{PROJECT_SUFFIX}"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": "old",
                "design_input": {"d_mm": 200.0},
                "hardware": {},
                "derived": {"w_mm": -999},
                "design_solution": {"valid": True},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_project(path)

    assert loaded.design_input == {"d_mm": 200.0}
    assert not hasattr(loaded, "derived")


@pytest.mark.parametrize("version", [0, 2, "1", True, None])
def test_unsupported_or_non_integer_schema_is_rejected(version):
    with pytest.raises(ProjectError, match="스키마|schema_version"):
        ProjectDocument.from_dict(
            {
                "schema_version": version,
                "project_name": "bad",
                "design_input": {},
                "hardware": {},
            }
        )


def test_project_rejects_nan():
    with pytest.raises(ProjectError, match="JSON"):
        ProjectDocument(project_name="nan", design_input={"d_mm": float("nan")})


def test_loading_ignores_legacy_calibration_reference(tmp_path):
    path = tmp_path / f"legacy{PROJECT_SUFFIX}"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_name": "legacy",
                "design_input": {"d_mm": 200.0},
                "hardware": {},
                "calibration_ref": {
                    "relative_path": "obsolete.json",
                    "sha256": "not-used",
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_project(path)

    assert not hasattr(loaded, "calibration_ref")
    assert "calibration_ref" not in loaded.to_dict()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("design", f"design{PROJECT_SUFFIX}"),
        ("design.json", f"design{PROJECT_SUFFIX}"),
        (f"design{PROJECT_SUFFIX}", f"design{PROJECT_SUFFIX}"),
    ],
)
def test_normalize_project_path_handles_compound_suffix(source, expected):
    assert normalize_project_path(source).name == expected
