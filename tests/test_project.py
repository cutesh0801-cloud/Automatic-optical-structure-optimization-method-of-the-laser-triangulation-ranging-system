from __future__ import annotations

import json

import pytest

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


def test_new_project_defaults_to_authoritative_workbook_inputs():
    document = ProjectDocument()

    assert document.design_input == {
        "mode": "workbook",
        "sensor_axis": "height",
        "v_mm": 205.0,
        "d_mm": 100.0,
        "sensor_length_mm": 5.4378,
        "alpha_deg": 14.27,
    }
    assert document.hardware["camera_id"] == "basler-aca1300-60gm"


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
