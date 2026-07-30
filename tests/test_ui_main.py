from __future__ import annotations

import csv

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QToolBar

from scheimpflug_optimeter.app import create_application
from scheimpflug_optimeter.lens_presets import (
    LensPresetError,
    UserLensPreset,
    lens_presets_to_dict,
)
from scheimpflug_optimeter.project import ProjectDocument, ProjectError
from scheimpflug_optimeter.ui.main_window import MainWindow


def test_main_window_is_simulation_only(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)

    assert window.tabs.count() == 3
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "워크북 계산 · 실시간 2D",
        "3D Scheimpflug 시각화",
        "Basler 센서 비교",
    ]
    assert not hasattr(window, "camera")
    assert not hasattr(window, "calibration")


def test_desktop_layout_is_readable_responsive_and_explicitly_static(qtbot):
    application = create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    assert 9.5 <= application.font().pointSizeF() <= 15.0
    assert window.minimumWidth() == 1100
    assert window.minimumHeight() == 700
    assert window.tabs.documentMode()
    assert window.status_label.objectName() == "calculationStatus"
    assert window.status_label.property("state") in {"valid", "warning"}
    assert window.status_label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse

    inputs = window.design.input_panel
    assert inputs.title.text() == "Workbook 광학 설계 시트"
    assert inputs.camera.accessibleName() == "정적 Basler 센서 규격"
    assert "연노랑" in inputs.mode_help.text()
    assert inputs.worksheet_group.title() == "입력 및 계산 결과"
    assert inputs.formula_card.title() == "■ 설계 주요 공식"
    assert not hasattr(inputs, "mode")
    assert inputs.values()["mode"] == "workbook"

    assert not window.design.splitter.childrenCollapsible()
    assert window.design.splitter.handleWidth() >= 8
    assert window.design.splitter.count() == 2
    assert window.design.input_scroll.minimumWidth() >= 400
    assert not hasattr(window.design, "result_scroll")
    assert window.design.view.minimumWidth() >= 400
    assert (
        window.design.input_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    assert inputs.worksheet_table.accessibleName()
    assert (
        inputs.worksheet_table.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
    assert "유도 보각/결상 기하각" in inputs.formula_variables.text()
    assert "틸트" not in inputs.formula_variables.text()
    assert window.sensor_comparison.table.rowCount() == 4
    assert window.sensor_comparison.table.selectionModel().selectedRows()[0].row() == 0
    assert "4종" in window.sensor_comparison.selection_summary.text()
    assert "QE" in window.sensor_comparison.sensitivity_notice.text()

    toolbar = window.findChild(QToolBar, "mainToolbar")
    assert toolbar is not None
    toolbar_labels = {action.text() for action in toolbar.actions()}
    assert "워크북 입력 CSV 불러오기…" not in toolbar_labels
    assert {"새 프로젝트", "프로젝트 열기…", "저장", "전체 맞춤", "광학부 확대"} <= toolbar_labels


def test_workbook_sheet_and_formula_fit_without_horizontal_clipping_at_1280_by_720(
    qtbot,
):
    create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    panel = window.design.input_panel
    table = panel.worksheet_table
    assert window.design.splitter.count() == 2
    assert not hasattr(window.design, "result_scroll")
    assert table.horizontalScrollBar().maximum() == 0
    assert panel.width() <= window.design.input_scroll.viewport().width()
    assert panel.formula_card.visibleRegion().boundingRect().height() >= (
        panel.formula_card.height() - 1
    )
    assert all(
        table.item(row, 3) is None or not table.item(row, 3).flags() & Qt.ItemFlag.ItemIsEditable
        for row in range(table.rowCount())
    )


def test_main_window_live_design_and_project_recalculation(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.show()

    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)
    first_solution = window.design.solution
    first_fp = first_solution.fp_mm

    document = ProjectDocument(
        project_name="로드 후 재계산",
        design_input={
            "mode": "workbook",
            "sensor_axis": "height",
            "v_mm": 205.0,
            "d_mm": 110.0,
            "sensor_length_mm": 5.4378,
            "sensor_length_linked": True,
            "alpha_manual": False,
            "alpha_deg": None,
            "focal_length_literal_mm": 12.0,
        },
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "edmund-33-879",
        },
        # A project cannot smuggle a stale solution into the UI.
        selected_optimization=None,
    )
    window.apply_document(document)
    qtbot.waitUntil(
        lambda: window.design.solution is not None and window.design.solution.fp_mm != first_fp,
        timeout=5_000,
    )

    assert window.design.solution.request.d_mm == 110.0
    assert window.design.snapshot.working_distance_mm == 110.0
    assert window.windowTitle().endswith("로드 후 재계산")
    assert window.three_d._snapshot is window.design.snapshot


@pytest.mark.parametrize(
    "preset_payload",
    [
        None,
        {"schema_version": 1, "presets": []},
        lens_presets_to_dict(
            (
                UserLensPreset(
                    user_id="different-preset",
                    name="Different preset",
                    focal_length_mm=25.0,
                    mount="M12x0.5",
                ),
            )
        ),
    ],
    ids=("collection-missing", "collection-empty", "selected-preset-missing"),
)
def test_project_rejects_selected_user_lens_missing_from_local_collection(
    qtbot,
    preset_payload,
):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.shutdown()
    design_input = {
        "mode": "workbook",
        "sensor_axis": "height",
        "v_mm": 150.0,
        "d_mm": 100.0,
        "sensor_length_mm": 5.4378,
        "sensor_length_linked": True,
        "focal_length_literal_mm": 18.0,
        "alpha_manual": False,
        "alpha_deg": None,
    }
    if preset_payload is not None:
        design_input["user_lens_presets"] = preset_payload
    document = ProjectDocument(
        project_name="Missing selected user lens",
        design_input=design_input,
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "user-lens:not-in-project",
        },
    )

    with pytest.raises(ProjectError) as caught:
        window.apply_document(document)

    assert isinstance(caught.value.__cause__, LensPresetError)


def test_project_rejects_invalid_user_lens_collection(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.shutdown()
    document = ProjectDocument(
        project_name="Invalid user lens collection",
        design_input={
            "mode": "workbook",
            "user_lens_presets": {"schema_version": 999, "presets": []},
        },
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "user-lens:invalid",
        },
    )

    with pytest.raises(ProjectError) as caught:
        window.apply_document(document)

    assert isinstance(caught.value.__cause__, LensPresetError)


def test_invalid_numeric_project_input_does_not_partially_commit_presets(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.shutdown()
    before = window.design.input_panel.values()
    incoming = UserLensPreset(
        user_id="incoming",
        name="Incoming lens",
        focal_length_mm=25.0,
        mount="M12x0.5",
    )
    design_input = dict(window.current_document().design_input)
    design_input.update(
        {
            "v_mm": "not-a-number",
            "user_lens_presets": lens_presets_to_dict((incoming,)),
        }
    )
    document = ProjectDocument(
        project_name="Invalid numeric value",
        design_input=design_input,
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": incoming.runtime_lens_id,
        },
    )

    with pytest.raises(ProjectError) as caught:
        window.apply_document(document)

    assert isinstance(caught.value.__cause__, LensPresetError)
    after = window.design.input_panel.values()
    assert after["lens_id"] == before["lens_id"]
    assert after["user_lens_presets"] == before["user_lens_presets"]
    assert after["v_mm"] == before["v_mm"]


def test_project_rejects_invalid_unselected_user_lens_before_commit(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.shutdown()
    before = window.design.input_panel.values()
    invalid_unselected = UserLensPreset(
        user_id="too-long-focal",
        name="Out-of-range focal length",
        focal_length_mm=2_000_000.0,
        mount="M12x0.5",
    )
    current = window.current_document()
    design_input = dict(current.design_input)
    design_input["user_lens_presets"] = lens_presets_to_dict((invalid_unselected,))
    document = ProjectDocument(
        project_name="Invalid unselected user lens",
        design_input=design_input,
        hardware=dict(current.hardware),
    )

    with pytest.raises(ProjectError) as caught:
        window.apply_document(document)

    assert isinstance(caught.value.__cause__, LensPresetError)
    assert window.design.input_panel.values() == before


@pytest.mark.parametrize(
    ("state_key", "state_value", "required_key"),
    [
        ("focal_length_linked", False, "focal_length_literal_mm"),
        ("alpha_manual", True, "alpha_deg"),
        ("sensor_length_linked", False, "sensor_length_mm"),
    ],
    ids=("unlinked-focal", "manual-alpha", "unlinked-sensor-length"),
)
def test_project_rejects_explicit_manual_state_without_required_value(
    qtbot,
    state_key,
    state_value,
    required_key,
):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.shutdown()
    before = window.design.input_panel.values()
    current = window.current_document()
    design_input = dict(current.design_input)
    design_input[state_key] = state_value
    design_input.pop(required_key, None)
    document = ProjectDocument(
        project_name="Incomplete explicit input state",
        design_input=design_input,
        hardware=dict(current.hardware),
    )

    with pytest.raises(ProjectError) as caught:
        window.apply_document(document)

    assert isinstance(caught.value.__cause__, LensPresetError)
    assert window.design.input_panel.values() == before


def test_signed_workbook_intercept_is_presented_as_distance_and_direction(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    panel = window.design.input_panel
    panel.sensor_link_toggle.setChecked(False)
    panel.sensor_length_mm.setValue(20.0)
    qtbot.waitUntil(
        lambda: (
            window.design.solution is not None
            and window.design.solution.ray_intercept_s_mm is not None
            and window.design.solution.ray_intercept_s_mm < 0.0
        ),
        timeout=1_000,
    )

    solution = window.design.solution
    distance = abs(solution.ray_intercept_s_mm)
    assert window.design.snapshot.measurement_range_mm == pytest.approx(distance)
    assert float(panel._result_items["ray_intercept"].text()) == pytest.approx(
        distance,
        rel=1e-5,
    )
    assert f"|s|={distance:.3f} mm" in window.status_label.text()
    assert "|s|=-" not in window.status_label.text()
    assert f"|s| {distance:.3f} mm" in window.design.scene.labels["range"].text()


def test_invalid_workbook_status_is_visible_without_horizontal_scrolling(qtbot):
    create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    panel = window.design.input_panel
    panel.d_mm.setValue(panel.v_mm.value() + 50.0)
    qtbot.waitUntil(
        lambda: window.design.solution is not None and not window.design.solution.valid,
        timeout=1_000,
    )

    assert panel.worksheet_status.isVisible()
    assert "사용 불가" in panel.worksheet_status.text()
    assert "제약 위반" in panel.worksheet_status.text()
    assert panel.worksheet_table.horizontalScrollBar().maximum() == 0
    assert window.design.scene.invalid_overlay.isVisible()


def test_input_changes_are_debounced_and_invalid_result_is_not_stale(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    previous = window.design.solution
    window.design.input_panel.d_mm.setValue(window.design.input_panel.v_mm.value() + 50.0)
    assert window.design.solution is previous

    qtbot.waitUntil(lambda: window.design.solution is not previous, timeout=1_000)

    assert window.design.solution is not previous
    assert not window.design.solution.valid
    assert window.design.scene.invalid_overlay.isVisible()
    assert window.design.performance.text()
    assert window.sensor_comparison.selection_summary.property("state") == "warning"
    assert "제약 위반" in window.sensor_comparison.selection_summary.text()


def test_basler_comparison_recalculates_live_for_sensor_orientation(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.sensor_comparison.table.rowCount() == 4, timeout=5_000)

    table = window.sensor_comparison.table
    fov_column = window.sensor_comparison.column_index("fov")
    initial_fov = table.item(0, fov_column).text()
    assert "삼각측량 축 세로" in window.sensor_comparison.selection_summary.text()

    axis = window.design.input_panel.sensor_axis
    axis.setCurrentIndex(axis.findData("width"))
    qtbot.waitUntil(
        lambda: (
            window.design.solution is not None
            and window.design.solution.request.sensor_axis == "width"
        ),
        timeout=1_000,
    )

    assert "삼각측량 축 가로" in window.sensor_comparison.selection_summary.text()
    assert table.item(0, fov_column).text() != initial_fov
    assert window.status_label.property("state") in {"valid", "warning"}
    assert window.design.input_panel._result_items["fov_x"].text() != "—"
    assert window.design.input_panel._result_items["fov_y"].text() != "—"


def test_workbook_is_default_and_direct_l_reproduces_both_regression_cases(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    first = window.design.solution
    panel = window.design.input_panel
    assert window.design.input_panel.values()["mode"] == "workbook"
    assert first.request.sensor_length_mm == pytest.approx(5.4378)
    assert first.request.v_mm == pytest.approx(150.0)
    assert first.request.focal_length_literal_mm == pytest.approx(17.5)
    assert first.alpha_deg == pytest.approx(20.678860931176374)
    assert panel.lens.currentData() == "edmund-58-206"
    assert panel.manual_alpha_toggle.isChecked() is False
    assert panel.values()["alpha_deg"] is None
    assert not hasattr(window.design, "result_panel")
    assert "Workbook" in panel.worksheet_status.text()
    assert not window.design.input_panel.input_link_toolbar.isHidden()
    assert not window.design.input_panel.sensor_length_mm.isHidden()
    assert not hasattr(window.design.input_panel, "mode")
    assert window.tabs.tabText(0) == "워크북 계산 · 실시간 2D"
    assert window.tabs.tabText(1) == "3D Scheimpflug 시각화"
    assert window.tabs.tabText(2) == "Basler 센서 비교"
    assert window.design.scene.sceneRect().height() < 500.0
    assert "|s|" in window.design.scene.labels["range"].text()
    assert not window.design.scene.target_near_line.isVisible()
    assert not window.design.scene.target_far_line.isVisible()

    assert {
        "baseline",
        "half_sensor",
        "width",
        "rear",
        "fp",
        "lo",
        "ray_intercept",
        "f_calc",
        "total",
        "fov_x",
        "fov_y",
        "sensitivity_center",
        "sensitivity_worst",
    } <= panel._result_items.keys()
    assert all(
        panel._result_items[key].text() != "—"
        for key in (
            "baseline",
            "width",
            "fp",
            "lo",
            "fov_x",
            "fov_y",
            "sensitivity_center",
        )
    )

    window.design.apply_project_input(
        {
            "mode": "workbook",
            "v_mm": 205.0,
            "d_mm": 100.0,
            "sensor_length_mm": 5.4378,
            "sensor_length_linked": False,
            "alpha_deg": 14.27,
            "alpha_manual": True,
        }
    )
    window.design.recalculate()
    workbook_205 = window.design.solution
    assert workbook_205.width_exact_mm == pytest.approx(54.858448275433375)
    assert workbook_205.ray_intercept_s_mm == pytest.approx(1165.9442466162743)

    window.design.apply_project_input(
        {
            "mode": "workbook",
            "v_mm": 200.0,
            "d_mm": 100.0,
            "sensor_length_mm": 3.0,
            "sensor_length_linked": False,
            "alpha_deg": 14.76,
            "alpha_manual": True,
        }
    )
    window.design.recalculate()
    second = window.design.solution
    assert second.request.sensor_length_mm == pytest.approx(3.0)
    assert second.width_exact_mm == pytest.approx(54.192933549234034)
    assert second.ray_intercept_s_mm == pytest.approx(146.09293389938426)

    assert not hasattr(window.design.input_panel, "mode")
    assert not window.design.input_panel.input_link_toolbar.isHidden()
    assert not hasattr(window.design, "result_panel")


def test_workbook_csv_import_export_and_l_persistence(qtbot, tmp_path):
    source = tmp_path / "workbook-input.csv"
    source.write_text(
        "v_mm,d_mm,sensor_length_mm,alpha_deg,camera_id,sensor_axis\n"
        "200,100,3.0,14.76,basler-aca1300-60gm,height\n",
        encoding="utf-8",
    )
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)

    window.import_workbook_csv(source)

    assert window.design.project_input()["sensor_length_mm"] == pytest.approx(3.0)
    assert window.design.solution.request.sensor_length_mm == pytest.approx(3.0)
    document = window.current_document()
    assert document.design_input["sensor_length_mm"] == pytest.approx(3.0)

    target = window.export_workbook_csv(tmp_path / "result")
    with target.open("r", encoding="utf-8-sig", newline="") as stream:
        row = next(csv.DictReader(stream))
    assert float(row["sensor_length_mm"]) == pytest.approx(3.0)
    assert float(row["baseline_mm"]) == pytest.approx(52.692933549234034)
    assert float(row["ray_intercept_s_mm"]) == pytest.approx(146.09293389938426)


def test_csv_partial_import_preserves_existing_manual_focal_override(qtbot, tmp_path):
    source = tmp_path / "workbook-partial.csv"
    source.write_text(
        "v_mm,d_mm,sensor_length_mm,alpha_deg\n200,100,3.0,14.76\n",
        encoding="utf-8",
    )
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    panel = window.design.input_panel
    panel.focal_length_link_toggle.setChecked(False)
    panel.focal_length_mm.setValue(18.25)

    window.import_workbook_csv(source)

    assert not panel.focal_length_link_toggle.isChecked()
    assert panel.focal_length_mm.value() == pytest.approx(18.25)
    assert window.design.solution.request.focal_length_literal_mm == pytest.approx(18.25)


def test_legacy_project_without_link_state_uses_deterministic_defaults(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.apply_project_input(
        {
            "mode": "workbook",
            "focal_length_linked": False,
            "focal_length_literal_mm": 18.25,
            "sensor_length_linked": False,
            "sensor_length_mm": 3.0,
            "alpha_manual": True,
            "alpha_deg": 25.0,
        }
    )
    document = ProjectDocument(
        project_name="Legacy partial project",
        design_input={"mode": "workbook", "v_mm": 200.0, "d_mm": 100.0},
        hardware={},
    )

    window.apply_document(document)

    values = window.design.project_input()
    assert values["camera_id"] == "basler-aca1300-60gm"
    assert values["lens_id"] == "edmund-58-206"
    assert values["focal_length_linked"] is True
    assert values["sensor_length_linked"] is True
    assert values["alpha_manual"] is False
    assert values["focal_length_literal_mm"] == pytest.approx(17.5)
    assert values["sensor_length_mm"] == pytest.approx(5.4378)


def test_legacy_project_numeric_focal_without_link_state_is_inferred(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    document = ProjectDocument(
        project_name="Legacy focal override",
        design_input={
            "mode": "workbook",
            "focal_length_mm": 18.25,
            "v_mm": 150.0,
            "d_mm": 100.0,
        },
        hardware={
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "edmund-58-206",
        },
    )

    window.apply_document(document)

    values = window.design.project_input()
    assert values["focal_length_linked"] is False
    assert values["focal_length_literal_mm"] == pytest.approx(18.25)


def test_new_project_restores_workbook_defaults(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.apply_project_input(
        {
            "mode": "workbook",
            "v_mm": 500.0,
            "d_mm": 250.0,
            "sensor_length_mm": 3.0,
            "sensor_length_linked": False,
            "alpha_deg": 25.0,
            "alpha_manual": True,
        }
    )
    window.design.recalculate()

    window.new_project()

    values = window.design.project_input()
    assert values["mode"] == "workbook"
    assert values["camera_id"] == "basler-aca1300-60gm"
    assert values["v_mm"] != pytest.approx(500.0)
    assert values["d_mm"] != pytest.approx(250.0)
    assert values["sensor_length_mm"] != pytest.approx(3.0)
    assert window.design.solution is not None
    assert window.design.solution.mode.value == "workbook"


def test_workbook_csv_rejects_unknown_hardware_instead_of_reusing_stale_selection(
    qtbot,
    tmp_path,
):
    source = tmp_path / "unknown-camera.csv"
    source.write_text(
        "v_mm,d_mm,sensor_length_mm,alpha_deg,camera_id,sensor_axis\n"
        "205,100,5.4378,14.27,unknown-camera,diagonal\n",
        encoding="utf-8",
    )
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)

    with pytest.raises(ProjectError, match="camera_id"):
        window.import_workbook_csv(source)


def test_inactive_advanced_3d_defers_matplotlib_draw(qtbot, monkeypatch):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)
    draws = []
    monkeypatch.setattr(
        window.three_d,
        "_draw_snapshot",
        lambda snapshot: draws.append(snapshot),
    )

    window.design.input_panel.manual_alpha_toggle.setChecked(True)
    window.design.input_panel.alpha_deg.setValue(14.5)
    qtbot.waitUntil(
        lambda: (
            window.design.solution is not None
            and window.design.solution.alpha_deg == pytest.approx(14.5)
        ),
        timeout=1_000,
    )

    assert draws == []
    assert window.three_d._snapshot is window.design.snapshot
    window.tabs.setCurrentWidget(window.three_d)
    assert draws == [window.design.snapshot]
