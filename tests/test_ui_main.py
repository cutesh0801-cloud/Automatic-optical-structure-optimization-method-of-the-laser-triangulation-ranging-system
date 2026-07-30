from __future__ import annotations

import csv

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QToolBar

from scheimpflug_optimeter.app import create_application
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
    assert inputs.profile_group.title() == "정적 센서 규격"
    assert "장치 연결 없음" in inputs.profile_notice.text()
    assert inputs.camera.accessibleName() == "정적 센서 규격 프로파일"
    assert "실제 장치를 연결하지 않습니다" in inputs.mode_help.text()
    assert inputs.parameter_group.title() == "워크북 직접 입력"

    assert not window.design.splitter.childrenCollapsible()
    assert window.design.splitter.handleWidth() >= 8
    assert window.design.input_scroll.minimumWidth() >= 315
    assert window.design.result_scroll.minimumWidth() >= 335
    assert window.design.view.minimumWidth() >= 400
    assert (
        window.design.input_scroll.horizontalScrollBarPolicy()
        == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )

    results = window.design.result_panel
    assert results.summary.objectName() == "solutionSummary"
    assert results.values.accessibleName() == "Scheimpflug 계산 수치 표"
    assert results.values.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert results.messages.accessibleName() == "설계 경고와 제약 조건"
    assert results.messages.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert window.sensor_comparison.table.rowCount() == 4
    assert window.sensor_comparison.table.selectionModel().selectedRows()[0].row() == 0
    assert "4종" in window.sensor_comparison.selection_summary.text()
    assert "QE" in window.sensor_comparison.sensitivity_notice.text()

    toolbar = window.findChild(QToolBar, "mainToolbar")
    assert toolbar is not None
    toolbar_labels = {action.text() for action in toolbar.actions()}
    assert "워크북 입력 CSV 불러오기…" not in toolbar_labels
    assert {"새 프로젝트", "프로젝트 열기…", "저장", "전체 맞춤", "광학부 확대"} <= toolbar_labels


def test_result_values_fit_without_nested_scrolling_at_1280_by_720(qtbot):
    create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    table = window.design.result_panel.values
    assert not window.design.result_scroll.verticalScrollBar().isVisible()
    assert not table.header().stretchLastSection()
    metrics = QFontMetrics(table.font())
    for column in range(2):
        widest_text = max(
            metrics.horizontalAdvance(table.topLevelItem(row).text(column))
            for row in range(table.topLevelItemCount())
        )
        assert widest_text <= table.columnWidth(column) - 4
    assert sum(table.columnWidth(column) for column in range(2)) <= table.viewport().width()


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


def test_signed_workbook_intercept_is_presented_as_distance_and_direction(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    window.design.input_panel.sensor_length_mm.setValue(7.0)
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
    rows = {
        window.design.result_panel.values.topLevelItem(index).text(
            0
        ): window.design.result_panel.values.topLevelItem(index).text(1)
        for index in range(window.design.result_panel.values.topLevelItemCount())
    }
    assert window.design.snapshot.measurement_range_mm == pytest.approx(distance)
    assert float(rows["광선 교차 거리 |s|"].split()[0]) == pytest.approx(
        distance,
        rel=1e-6,
    )
    assert f"|s|={distance:.3f} mm" in window.status_label.text()
    assert "|s|=-" not in window.status_label.text()
    assert "위 계속 ↑" in window.design.scene.labels["range"].text()


def test_constraint_messages_wrap_without_horizontal_scrolling(qtbot):
    create_application([])
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    window.resize(1280, 720)
    window.show()
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    mode = window.design.input_panel.mode
    mode.setCurrentIndex(mode.findData("canonical"))
    qtbot.waitUntil(
        lambda: (
            window.design.solution is not None
            and window.design.solution.mode.value == "canonical"
            and window.design.result_panel.messages.count() > 0
        ),
        timeout=1_000,
    )
    messages = window.design.result_panel.messages
    item = messages.item(0)
    qtbot.waitUntil(
        lambda: item.sizeHint().height() > QFontMetrics(messages.font()).height() + 8,
        timeout=1_000,
    )

    assert messages.horizontalScrollBar().maximum() == 0
    assert item.sizeHint().width() <= messages.viewport().width()
    assert item.sizeHint().height() <= messages.viewport().height()
    assert "\n" in item.text()


def test_input_changes_are_debounced_and_invalid_result_is_not_stale(qtbot):
    window = MainWindow()
    window.maybe_save_changes = lambda: True
    qtbot.addWidget(window)
    qtbot.waitUntil(lambda: window.design.solution is not None, timeout=5_000)

    previous = window.design.solution
    window.design.input_panel.alpha_deg.setValue(89.0)
    window.design.input_panel.beta_deg.setValue(89.0)
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
    assert window.status_label.property("state") == "warning"
    assert "경고" in window.status_label.text()


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
    assert window.tabs.tabText(2) == "Basler 센서 비교"
    assert window.design.scene.sceneRect().height() < 500.0
    assert "광선 교차 거리 |s|" in window.design.scene.labels["range"].text()
    assert "아래" in window.design.scene.labels["range"].text()
    assert not window.design.scene.target_near_line.isVisible()
    assert not window.design.scene.target_far_line.isVisible()

    rows = {
        window.design.result_panel.values.topLevelItem(index).text(0)
        for index in range(window.design.result_panel.values.topLevelItemCount())
    }
    assert {
        "베이스라인 b",
        "반 센서 x=L/2",
        "워크북식 W=b+L/2",
        "워크북식 R=V−d",
        "이미지 거리 fp",
        "물체 거리 lo",
        "광선 교차 거리 |s|",
        "유도 초점거리 f",
        "총 광로 lo+fp",
        "센서 가로 FOV",
        "센서 세로 FOV",
        "중앙 거리 민감도",
        "최악 거리 민감도",
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
