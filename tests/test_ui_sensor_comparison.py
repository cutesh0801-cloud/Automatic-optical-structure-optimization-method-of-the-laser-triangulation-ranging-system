from __future__ import annotations

from PySide6.QtWidgets import QHeaderView

from scheimpflug_optimeter.models import (
    CameraProfile,
    SensorImagingMetrics,
    SensorProfile,
)
from scheimpflug_optimeter.ui.sensor_comparison import SensorComparisonWidget


def _camera(*, camera_id: str, model: str, sensor_id: str) -> CameraProfile:
    return CameraProfile(
        id=camera_id,
        manufacturer="Basler",
        model=model,
        interface="GigE",
        mount="C",
        max_fps=60.0,
        sensor=SensorProfile(
            id=sensor_id,
            name=f"{model} sensor",
            width_px=1280,
            height_px=1024,
            pixel_pitch_um=5.3,
        ),
        verified_on="2026-07-29",
    )


def _metrics(
    sensor: SensorProfile,
    *,
    valid: bool = True,
    invalid_reason: str | None = None,
    warnings: tuple[str, ...] = (),
) -> SensorImagingMetrics:
    return SensorImagingMetrics(
        sensor=sensor,
        sensor_axis="height",
        valid=valid,
        horizontal_fov_mm=54.1234 if valid else None,
        vertical_fov_mm=43.2987 if valid else None,
        horizontal_sampling_mm_per_px=0.0422839 if valid else None,
        vertical_sampling_mm_per_px=0.0422839 if valid else None,
        range_min_offset_mm=-21.0 if valid else None,
        range_max_offset_mm=22.2987 if valid else None,
        range_sensitivity_near_mm_per_px=0.019 if valid else None,
        range_sensitivity_center_mm_per_px=0.020123456 if valid else None,
        range_sensitivity_far_mm_per_px=0.024 if valid else None,
        range_sensitivity_worst_mm_per_px=0.024 if valid else None,
        invalid_reason=invalid_reason,
        warnings=warnings,
    )


def test_displays_static_sensor_metrics_and_highlights_selected_row(qtbot):
    selected = _camera(
        camera_id="basler-aca1300-60gm",
        model="ace acA1300-60gm",
        sensor_id="sensor-ace",
    )
    other = _camera(
        camera_id="basler-dart",
        model="dart daA1280-54um",
        sensor_id="sensor-dart",
    )
    widget = SensorComparisonWidget()
    qtbot.addWidget(widget)

    widget.display_metrics(
        ((selected, _metrics(selected.sensor)), (other, _metrics(other.sensor))),
        selected_camera_id=selected.id,
    )

    assert widget.table.rowCount() == 2
    assert widget.table.columnCount() == 10
    assert "2종" in widget.selection_summary.text()
    assert selected.model in widget.selection_summary.text()
    assert "FOV 54.123 × 43.299 mm" in widget.selection_summary.text()
    assert "거리 감도 중심/최악" in widget.selection_summary.text()
    assert widget.table.selectionModel().selectedRows()[0].row() == 0
    assert widget.table.item(0, widget.column_index("resolution")).text() == "1,280 × 1,024"
    assert widget.table.item(0, widget.column_index("fov")).text() == "54.123 × 43.299"
    assert widget.table.item(0, widget.column_index("sampling")).text() == "42.28 × 42.28"
    assert widget.table.item(0, widget.column_index("range_center")).text() == "0.020123"
    assert widget.table.item(0, widget.column_index("status")).text() == "정상"


def test_invalid_reason_and_profile_warning_are_never_hidden(qtbot):
    invalid_camera = _camera(
        camera_id="invalid",
        model="invalid geometry",
        sensor_id="invalid-sensor",
    )
    warning_camera = _camera(
        camera_id="warning",
        model="warning geometry",
        sensor_id="warning-sensor",
    )
    widget = SensorComparisonWidget()
    qtbot.addWidget(widget)

    widget.display_metrics(
        (
            (
                invalid_camera,
                _metrics(
                    invalid_camera.sensor,
                    valid=False,
                    invalid_reason="센서 구간이 영상 매핑의 극점을 가로지릅니다.",
                ),
            ),
            (
                warning_camera,
                _metrics(
                    warning_camera.sensor,
                    warnings=("사용자 입력 센서 길이와 프로파일 크기가 다릅니다.",),
                ),
            ),
        ),
        selected_camera_id=invalid_camera.id,
    )

    invalid_status = widget.table.item(0, widget.column_index("status"))
    warning_status = widget.table.item(1, widget.column_index("status"))
    assert "계산 불가" in invalid_status.text()
    assert "극점" in invalid_status.text()
    assert "극점" in invalid_status.toolTip()
    assert widget.table.item(0, widget.column_index("fov")).text() == "—"
    assert "주의" in warning_status.text()
    assert "프로파일 크기" in warning_status.toolTip()
    assert "계산 가능 1종" in widget.selection_summary.text()


def test_mismatched_metric_profile_is_explicit_and_empty_state_resets(qtbot):
    camera = _camera(
        camera_id="camera",
        model="ace acA1300-60gm",
        sensor_id="camera-sensor",
    )
    other = _camera(
        camera_id="other",
        model="other",
        sensor_id="other-sensor",
    )
    widget = SensorComparisonWidget()
    qtbot.addWidget(widget)

    widget.display_metrics(
        ((camera, _metrics(other.sensor)),),
        selected_camera_id="missing-id",
    )

    status = widget.table.item(0, widget.column_index("status"))
    assert status.text() == "프로파일 불일치"
    assert camera.sensor.id in status.toolTip()
    assert other.sensor.id in status.toolTip()
    assert not widget.table.selectionModel().hasSelection()
    assert "선택된 프로파일 없음" in widget.selection_summary.text()

    widget.display_metrics(
        (),
        selected_camera_id=None,
        context_warning="입력 계산 오류",
    )
    assert widget.table.rowCount() == 0
    assert "입력 계산 오류" in widget.selection_summary.text()
    assert "비교할 센서 계산 결과가 없습니다." in widget.selection_summary.text()
    assert widget.selection_summary.property("state") == "warning"


def test_comparison_table_has_large_text_accessibility_and_resizable_columns(qtbot):
    widget = SensorComparisonWidget()
    qtbot.addWidget(widget)

    assert widget.accessibleName()
    assert "기하학적" in widget.sensitivity_notice.text()
    assert "작을수록" in widget.sensitivity_notice.text()
    assert "QE" in widget.sensitivity_notice.text()
    assert widget.table.font().pointSizeF() >= 10.5
    assert widget.title_label.font().pointSizeF() >= 16.0
    assert widget.table.accessibleName()
    assert widget.table.horizontalHeaderItem(0).toolTip()
    assert (
        widget.table.horizontalHeader().sectionResizeMode(widget.column_index("camera"))
        == QHeaderView.ResizeMode.Interactive
    )
    assert (
        widget.table.horizontalHeader().sectionResizeMode(widget.column_index("fov"))
        == QHeaderView.ResizeMode.Interactive
    )
    assert (
        widget.table.horizontalHeader().sectionResizeMode(widget.column_index("status"))
        == QHeaderView.ResizeMode.Stretch
    )
