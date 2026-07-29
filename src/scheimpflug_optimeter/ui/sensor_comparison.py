"""Read-only comparison table for static Basler sensor profiles.

The widget deliberately receives already-calculated metrics.  It does not know
how Scheimpflug geometry is solved and it never enumerates or connects to a
camera device.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheimpflug_optimeter.models import CameraProfile, SensorImagingMetrics


@dataclass(frozen=True, slots=True)
class _Column:
    key: str
    title: str
    tooltip: str


_COLUMNS = (
    _Column(
        "camera",
        "Basler 모델",
        "정적 카탈로그의 모델명입니다. 장치 검색이나 연결은 수행하지 않습니다.",
    ),
    _Column("resolution", "해상도\n(H × V px)", "활성 센서의 가로 × 세로 픽셀 수입니다."),
    _Column("pitch", "픽셀 피치\n(µm)", "정사각 픽셀 한 변의 물리적 크기입니다."),
    _Column(
        "active_area",
        "활성 크기\n(H × V mm)",
        "활성 센서의 가로 × 세로 물리 크기입니다.",
    ),
    _Column(
        "fov",
        "FOV\n(H × V mm)",
        "같은 광학 해를 센서 프로파일에 적용한 물체측 가로 × 세로 시야입니다.",
    ),
    _Column(
        "sampling",
        "물체 샘플링\n(H × V µm/px)",
        "물체 평면에서 센서 1픽셀이 대표하는 가로 × 세로 길이입니다.",
    ),
    _Column(
        "range_center",
        "거리 감도 · 중심\n(mm/px)",
        "기준 거리에서 센서 1픽셀 이동에 대응하는 레이저축 거리 변화입니다.",
    ),
    _Column(
        "range_worst",
        "거리 감도 · 최악\n(mm/px)",
        "센서가 포함하는 거리 구간에서 가장 큰 기하학적 거리 변화량입니다.",
    ),
    _Column("fps", "최대 fps", "제조사 정적 프로파일에 기록된 최대 프레임률입니다."),
    _Column(
        "status",
        "상태 / 계산 불가 사유",
        "유효성, 프로파일 경고 또는 계산할 수 없는 이유를 표시합니다.",
    ),
)

_INITIAL_COLUMN_WIDTHS = {
    "camera": 200,
    "resolution": 115,
    "pitch": 85,
    "active_area": 145,
    "fov": 145,
    "sampling": 175,
    "range_center": 130,
    "range_worst": 130,
    "fps": 85,
}


class SensorComparisonWidget(QWidget):
    """Compare precomputed imaging metrics for multiple camera profiles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sensorComparisonWidget")
        self.setAccessibleName("Basler 센서 성능 비교")
        self.setAccessibleDescription(
            "동일한 광학 해에서 정적 Basler 센서 프로파일의 해상도, FOV, "
            "샘플링 및 기하학적 거리 감도를 비교하는 표"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.title_label = QLabel("Basler 센서 성능 비교")
        self.title_label.setObjectName("sensorComparisonTitle")
        title_font = QFont(self.title_label.font())
        title_font.setPointSizeF(max(16.0, title_font.pointSizeF() + 5.0))
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setAccessibleName("Basler 센서 성능 비교 제목")
        layout.addWidget(self.title_label)

        self.description_label = QLabel(
            "동일한 광학 해에 각 정적 카탈로그 프로파일을 적용한 계산 결과입니다. "
            "이 화면은 장치를 검색하거나 연결하지 않습니다."
        )
        self.description_label.setObjectName("sensorComparisonDescription")
        self.description_label.setWordWrap(True)
        self.description_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        description_font = QFont(self.description_label.font())
        description_font.setPointSizeF(max(10.5, description_font.pointSizeF()))
        self.description_label.setFont(description_font)
        layout.addWidget(self.description_label)

        self.sensitivity_notice = QLabel(
            "ⓘ 감도는 레이저 삼각측량의 기하학적 거리 감도(mm/px)입니다. "
            "값이 작을수록 한 픽셀이 나타내는 거리 변화가 작습니다. "
            "QE·노이즈·노출에 따른 광학/광자 감도를 뜻하지 않습니다."
        )
        self.sensitivity_notice.setObjectName("sensorSensitivityNotice")
        self.sensitivity_notice.setProperty("role", "info")
        self.sensitivity_notice.setWordWrap(True)
        self.sensitivity_notice.setFrameShape(QFrame.Shape.StyledPanel)
        self.sensitivity_notice.setMargin(10)
        self.sensitivity_notice.setAccessibleName("거리 감도 정의 안내")
        self.sensitivity_notice.setAccessibleDescription(
            "표의 감도 값은 기하학적 밀리미터 퍼 픽셀이며 양자 효율이 아닙니다."
        )
        notice_font = QFont(self.sensitivity_notice.font())
        notice_font.setPointSizeF(max(10.5, notice_font.pointSizeF()))
        notice_font.setWeight(QFont.Weight.Medium)
        self.sensitivity_notice.setFont(notice_font)
        layout.addWidget(self.sensitivity_notice)

        self.selection_summary = QLabel("비교할 센서 계산 결과가 없습니다.")
        self.selection_summary.setObjectName("sensorComparisonSummary")
        self.selection_summary.setWordWrap(True)
        self.selection_summary.setAccessibleName("선택 센서 요약")
        summary_font = QFont(self.selection_summary.font())
        summary_font.setPointSizeF(max(10.5, summary_font.pointSizeF()))
        summary_font.setWeight(QFont.Weight.DemiBold)
        self.selection_summary.setFont(summary_font)
        layout.addWidget(self.selection_summary)

        self.table = QTableWidget(0, len(_COLUMNS), self)
        self.table.setObjectName("sensorComparisonTable")
        self.table.setAccessibleName("Basler 센서 계산 결과 비교표")
        self.table.setAccessibleDescription(
            "행은 카메라 프로파일이고 열은 센서 사양과 계산된 영상 지표입니다."
        )
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.horizontalHeader().setMinimumSectionSize(72)
        self.table.horizontalHeader().setDefaultAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.table.horizontalHeader().setMinimumHeight(52)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        table_font = QFont(self.table.font())
        table_font.setPointSizeF(max(10.5, table_font.pointSizeF()))
        self.table.setFont(table_font)
        header_font = QFont(table_font)
        header_font.setWeight(QFont.Weight.DemiBold)
        self.table.horizontalHeader().setFont(header_font)

        self.table.setHorizontalHeaderLabels([column.title for column in _COLUMNS])
        for index, column in enumerate(_COLUMNS):
            header_item = self.table.horizontalHeaderItem(index)
            header_item.setToolTip(column.tooltip)
            header_item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"{column.title}. {column.tooltip}",
            )

        header = self.table.horizontalHeader()
        for index in range(len(_COLUMNS)):
            mode = (
                QHeaderView.ResizeMode.Stretch
                if _COLUMNS[index].key == "status"
                else QHeaderView.ResizeMode.Interactive
            )
            header.setSectionResizeMode(index, mode)
            width = _INITIAL_COLUMN_WIDTHS.get(_COLUMNS[index].key)
            if width is not None:
                self.table.setColumnWidth(index, width)

        layout.addWidget(self.table, 1)
        self.setMinimumSize(860, 360)

    @staticmethod
    def column_index(key: str) -> int:
        """Return a stable table column index for tests and integrations."""

        for index, column in enumerate(_COLUMNS):
            if column.key == key:
                return index
        raise KeyError(f"Unknown sensor comparison column: {key!r}")

    def display_metrics(
        self,
        rows: Iterable[tuple[CameraProfile, SensorImagingMetrics]],
        selected_camera_id: str | None,
        *,
        context_warning: str | None = None,
    ) -> None:
        """Replace the table with externally calculated, read-only metric rows."""

        values = tuple(rows)
        self.table.setUpdatesEnabled(False)
        try:
            self.table.clearContents()
            self.table.setRowCount(len(values))
            selected_row: int | None = None
            valid_count = 0

            for row_index, (camera, metrics) in enumerate(values):
                profile_mismatch = camera.sensor.id != metrics.sensor.id
                if metrics.valid and not profile_mismatch:
                    valid_count += 1
                if camera.id == selected_camera_id:
                    selected_row = row_index
                self._populate_row(row_index, camera, metrics, profile_mismatch)

            self.table.clearSelection()
            if selected_row is not None:
                self.table.selectRow(selected_row)
                selected_camera = values[selected_row][0]
                selected_metrics = values[selected_row][1]
                selected_axis = "가로" if selected_metrics.sensor_axis == "width" else "세로"
                selected_fov = self._pair(
                    selected_metrics.horizontal_fov_mm,
                    selected_metrics.vertical_fov_mm,
                )
                selected_center = self._metric(selected_metrics.range_sensitivity_center_mm_per_px)
                selected_worst = self._metric(selected_metrics.range_sensitivity_worst_mm_per_px)
                self.selection_summary.setText(
                    f"선택: {selected_camera.manufacturer} {selected_camera.model}  ·  "
                    f"삼각측량 축 {selected_axis}  ·  FOV {selected_fov} mm  ·  "
                    f"거리 감도 중심/최악 {selected_center} / {selected_worst} mm/px  ·  "
                    f"비교 {len(values)}종 (계산 가능 {valid_count}종)"
                )
                self.table.scrollToItem(
                    self.table.item(selected_row, self.column_index("camera")),
                    QAbstractItemView.ScrollHint.EnsureVisible,
                )
            elif values:
                self.selection_summary.setText(
                    f"선택된 프로파일 없음  ·  비교 {len(values)}종  ·  계산 가능 {valid_count}종"
                )
            else:
                self.selection_summary.setText("비교할 센서 계산 결과가 없습니다.")
            if context_warning:
                details = self.selection_summary.text()
                self.selection_summary.setText(f"⚠ {context_warning}\n{details}")
                self.selection_summary.setProperty("state", "warning")
            else:
                self.selection_summary.setProperty("state", "ready")
            self.selection_summary.style().unpolish(self.selection_summary)
            self.selection_summary.style().polish(self.selection_summary)
        finally:
            self.table.setUpdatesEnabled(True)
            self.table.viewport().update()

    def _populate_row(
        self,
        row: int,
        camera: CameraProfile,
        metrics: SensorImagingMetrics,
        profile_mismatch: bool,
    ) -> None:
        sensor = camera.sensor
        status_text, status_tooltip, status_kind = self._status(camera, metrics, profile_mismatch)
        cells = {
            "camera": camera.model,
            "resolution": f"{sensor.width_px:,} × {sensor.height_px:,}",
            "pitch": f"{sensor.pixel_pitch_um:.3f}",
            "active_area": f"{sensor.width_mm:.4f} × {sensor.height_mm:.4f}",
            "fov": self._pair(metrics.horizontal_fov_mm, metrics.vertical_fov_mm),
            "sampling": self._sampling_pair(
                metrics.horizontal_sampling_mm_per_px,
                metrics.vertical_sampling_mm_per_px,
            ),
            "range_center": self._metric(metrics.range_sensitivity_center_mm_per_px),
            "range_worst": self._metric(metrics.range_sensitivity_worst_mm_per_px),
            "fps": f"{camera.max_fps:g} fps",
            "status": status_text,
        }
        tooltips = {
            "camera": self._camera_tooltip(camera),
            "resolution": f"활성 해상도: {sensor.width_px} × {sensor.height_px} px",
            "pitch": f"픽셀 피치: {sensor.pixel_pitch_um:.9g} µm",
            "active_area": (f"활성 센서: {sensor.width_mm:.9g} × {sensor.height_mm:.9g} mm"),
            "fov": self._exact_pair(metrics.horizontal_fov_mm, metrics.vertical_fov_mm, "mm"),
            "sampling": self._exact_pair(
                metrics.horizontal_sampling_mm_per_px,
                metrics.vertical_sampling_mm_per_px,
                "mm/px",
            ),
            "range_center": self._exact(metrics.range_sensitivity_center_mm_per_px),
            "range_worst": self._exact(metrics.range_sensitivity_worst_mm_per_px),
            "fps": f"정적 프로파일 최대 프레임률: {camera.max_fps:.9g} fps",
            "status": status_tooltip,
        }

        for column_index, column in enumerate(_COLUMNS):
            item = QTableWidgetItem(cells[column.key])
            item.setToolTip(tooltips[column.key])
            horizontal_alignment = (
                Qt.AlignmentFlag.AlignLeft
                if column.key in {"camera", "status"}
                else Qt.AlignmentFlag.AlignRight
            )
            item.setTextAlignment(horizontal_alignment | Qt.AlignmentFlag.AlignVCenter)
            if column.key == "camera":
                font = QFont(item.font())
                font.setWeight(QFont.Weight.DemiBold)
                item.setFont(font)
                item.setData(Qt.ItemDataRole.UserRole, camera.id)
            if column.key == "status":
                self._style_status(item, status_kind)
            self.table.setItem(row, column_index, item)

        self.table.setRowHeight(row, 44)

    @staticmethod
    def _pair(horizontal: float | None, vertical: float | None) -> str:
        if horizontal is None or vertical is None:
            return "—"
        return f"{horizontal:.3f} × {vertical:.3f}"

    @staticmethod
    def _sampling_pair(horizontal: float | None, vertical: float | None) -> str:
        if horizontal is None or vertical is None:
            return "—"
        return f"{horizontal * 1000.0:.2f} × {vertical * 1000.0:.2f}"

    @staticmethod
    def _metric(value: float | None) -> str:
        if value is None:
            return "—"
        return f"{value:.6f}"

    @staticmethod
    def _exact(value: float | None) -> str:
        if value is None:
            return "계산할 수 없음"
        return f"정확한 계산값: {value:.12g} mm/px"

    @staticmethod
    def _exact_pair(horizontal: float | None, vertical: float | None, unit: str) -> str:
        if horizontal is None or vertical is None:
            return "계산할 수 없음"
        return f"가로 {horizontal:.12g} {unit}\n세로 {vertical:.12g} {unit}"

    @staticmethod
    def _camera_tooltip(camera: CameraProfile) -> str:
        lines = [
            f"{camera.manufacturer} {camera.model}",
            f"인터페이스: {camera.interface}",
            f"마운트: {camera.mount}",
        ]
        if camera.verified_on:
            lines.append(f"사양 확인일: {camera.verified_on}")
        if camera.source_url:
            lines.append(f"공식 출처: {camera.source_url}")
        lines.extend(f"주의: {note}" for note in camera.notes)
        return "\n".join(lines)

    @staticmethod
    def _status(
        camera: CameraProfile,
        metrics: SensorImagingMetrics,
        profile_mismatch: bool,
    ) -> tuple[str, str, str]:
        if profile_mismatch:
            reason = (
                f"카메라 센서({camera.sensor.id})와 계산 센서"
                f"({metrics.sensor.id})가 일치하지 않습니다."
            )
            return "프로파일 불일치", reason, "invalid"
        if not metrics.valid:
            reason = metrics.invalid_reason or "계산 코어가 유효하지 않다고 판정했습니다."
            return f"계산 불가 · {reason}", reason, "invalid"
        if metrics.warnings:
            details = "\n".join(f"• {warning}" for warning in metrics.warnings)
            return "주의 · 세부 정보 확인", details, "warning"
        return "정상", "모든 비교 지표를 계산했습니다.", "valid"

    @staticmethod
    def _style_status(item: QTableWidgetItem, status_kind: str) -> None:
        if status_kind == "invalid":
            item.setForeground(QColor("#b42318"))
            item.setBackground(QColor("#fef3f2"))
        elif status_kind == "warning":
            item.setForeground(QColor("#8a4b08"))
            item.setBackground(QColor("#fffaeb"))
        else:
            item.setForeground(QColor("#067647"))
            item.setBackground(QColor("#ecfdf3"))
        font = QFont(item.font())
        font.setWeight(QFont.Weight.DemiBold)
        item.setFont(font)


__all__ = ["SensorComparisonWidget"]
