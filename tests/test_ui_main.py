from __future__ import annotations

import csv

import pytest

from scheimpflug_optimeter.project import ProjectDocument, ProjectError
from scheimpflug_optimeter.ui.main_window import MainWindow


def test_main_window_is_simulation_only(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)

    assert window.tabs.count() == 2
    assert [window.tabs.tabText(index) for index in range(window.tabs.count())] == [
        "워크북 계산 · 실시간 2D",
        "3D Scheimpflug 시각화",
    ]
    assert not hasattr(window, "camera")
    assert not hasattr(window, "calibration")


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
            "mode": "canonical",
            "sensor_axis": "height",
            "d_mm": 210.0,
            "range_mm": 4.0,
            "v_mm": 205.0,
            "alpha_deg": 27.0,
            "beta_deg": 25.0,
            "max_width_mm": 105.0,
            "max_rear_mm": 105.0,
            "wavelength_nm": 650.0,
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

    assert window.design.solution.request.d_mm == 210.0
    assert window.design.snapshot.working_distance_mm == 210.0
    assert window.windowTitle().endswith("로드 후 재계산")
    assert window.three_d._snapshot is window.design.snapshot


def test_input_changes_are_debounced_and_invalid_result_is_not_stale(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    previous = window.design.solution
    window.design.input_panel.alpha_deg.setValue(89.0)
    window.design.input_panel.beta_deg.setValue(89.0)
    assert window.design.solution is previous

    qtbot.wait(40)

    assert window.design.solution is not previous
    assert not window.design.solution.valid
    assert window.design.scene.invalid_overlay.isVisible()
    assert window.design.performance.text()


def test_workbook_is_default_and_direct_l_reproduces_both_regression_cases(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    first = window.design.solution
    assert window.design.input_panel.mode.currentData() == "workbook"
    assert first.request.sensor_length_mm == pytest.approx(5.4378)
    assert first.width_exact_mm == pytest.approx(54.858448275433375)
    assert first.ray_intercept_s_mm == pytest.approx(1165.9442466162743)
    assert window.design.result_panel.optimization_group.isHidden()
    assert not window.design.input_panel.sensor_length_container.isHidden()
    assert "고급/연구 참고" in window.design.input_panel.mode.itemText(1)
    assert window.tabs.tabText(0) == "워크북 계산 · 실시간 2D"
    assert window.tabs.tabText(1) == "3D Scheimpflug 시각화"
    assert window.design.scene.sceneRect().height() < 500.0
    assert "레이저 교차 거리 s" in window.design.scene.labels["range"].text()
    assert "화면 밖" in window.design.scene.labels["range"].text()
    assert not window.design.scene.target_near_line.isVisible()
    assert not window.design.scene.target_far_line.isVisible()

    rows = {
        window.design.result_panel.values.topLevelItem(index).text(0)
        for index in range(window.design.result_panel.values.topLevelItemCount())
    }
    assert {
        "베이스라인 b",
        "반 센서 길이 x=L/2",
        "외곽 W",
        "후방 R",
        "이미지 거리 fp",
        "물체 거리 lo",
        "레이저 교차 거리 s",
        "유도 초점거리 f",
        "총 광로 lo+fp",
    } <= rows

    window.design.apply_project_input(
        {
            "mode": "workbook",
            "v_mm": 200.0,
            "d_mm": 100.0,
            "sensor_length_mm": 3.0,
            "alpha_deg": 14.76,
        }
    )
    window.design.recalculate()
    second = window.design.solution
    assert second.request.sensor_length_mm == pytest.approx(3.0)
    assert second.width_exact_mm == pytest.approx(54.192933549234034)
    assert second.ray_intercept_s_mm == pytest.approx(146.09293389938426)

    window.design.input_panel.mode.setCurrentIndex(1)
    window.design.recalculate()
    assert window.design.input_panel.sensor_length_container.isHidden()
    assert not window.design.result_panel.optimization_group.isHidden()


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


def test_new_project_restores_workbook_defaults(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.design.apply_project_input(
        {
            "mode": "canonical",
            "v_mm": 500.0,
            "d_mm": 250.0,
            "sensor_length_mm": 3.0,
            "alpha_deg": 25.0,
        }
    )
    window.design.recalculate()

    window.new_project()

    values = window.design.project_input()
    assert values["mode"] == "workbook"
    assert values["v_mm"] == pytest.approx(205.0)
    assert values["d_mm"] == pytest.approx(100.0)
    assert values["sensor_length_mm"] == pytest.approx(5.4378)
    assert values["alpha_deg"] == pytest.approx(14.27)
    assert values["camera_id"] == "basler-aca1300-60gm"
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
