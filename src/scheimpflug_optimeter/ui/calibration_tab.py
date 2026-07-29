"""Calibration and single-frame measurement workbench.

The widget is intentionally self-contained so ``MainWindow`` only needs to add it
as a tab and forward camera frames through :meth:`set_camera_frame`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from scheimpflug_optimeter.calibration import (
    CalibrationGate,
    CalibrationRecord,
    HardwareIdentity,
    IntrinsicCalibration,
    LaserPlane,
    LaserPlaneFit,
    NewtonRangeCalibration,
    ThickLensParameters,
    assert_calibration_matches,
    calibrate_intrinsics,
    detect_checkerboard,
    fit_laser_plane,
    fit_newton_range,
)
from scheimpflug_optimeter.camera import CameraFrame, Roi
from scheimpflug_optimeter.measurement import (
    CrossSection,
    extract_stripe,
    triangulate_cross_section,
)


@dataclass(frozen=True, slots=True)
class FocusContrastResult:
    """Directional high-frequency contrast used for manual focus guidance."""

    horizontal_contrast: float
    vertical_contrast: float
    balance: float
    guidance: str


class CalibrationMeasurementWidget(QWidget):
    """Collect calibration inputs and run one-frame laser triangulation."""

    calibration_ready = Signal(object)
    measurement_ready = Signal(object)
    focus_assist_ready = Signal(object)
    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CalibrationMeasurementWidget")
        self._object_points: list[NDArray[np.float32]] = []
        self._image_points: list[NDArray[np.float32]] = []
        self._checkerboard_image_size: tuple[int, int] | None = None
        self._intrinsic: IntrinsicCalibration | None = None
        self._laser_plane_fit: LaserPlaneFit | None = None
        self._newton_range: NewtonRangeCalibration | None = None
        self._thick_lens: ThickLensParameters | None = None
        self._calibration_record: CalibrationRecord | None = None
        self._calibration_path: Path | None = None
        self._calibrated_identity: HardwareIdentity | None = None
        self._rotation = np.eye(3, dtype=np.float64)
        self._translation = np.zeros(3, dtype=np.float64)
        self._frame: CameraFrame | None = None
        self._image: NDArray[np.generic] | None = None
        self._frame_metadata: dict[str, Any] = {}
        self._cross_section: CrossSection | None = None

        self._build_ui()
        self._update_actions()

    @property
    def calibration_record(self) -> CalibrationRecord | None:
        return self._calibration_record

    @property
    def calibration_path(self) -> Path | None:
        return self._calibration_path

    @property
    def cross_section(self) -> CrossSection | None:
        return self._cross_section

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(self._build_identity_group())
        layout.addWidget(self._build_calibration_group())
        layout.addWidget(self._build_measurement_group())
        layout.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        self.status_label = QLabel("보정 자료를 준비하십시오.")
        self.status_label.setObjectName("calibrationStatus")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)

    def _build_identity_group(self) -> QGroupBox:
        group = QGroupBox("장비 식별 및 ROI")
        form = QGridLayout(group)

        self.camera_model_edit = QLineEdit("acA1300-60gm")
        self.camera_serial_edit = QLineEdit("MOCK-ACA1300-0001")
        self.lens_sku_edit = QLineEdit("#33-879")
        self.focal_length_spin = _double_spin(0.1, 200.0, 12.0, 4, " mm")
        self.resolution_width_spin = _integer_spin(1, 20_000, 1282)
        self.resolution_height_spin = _integer_spin(1, 20_000, 1026)
        self.roi_x_spin = _integer_spin(0, 20_000, 0)
        self.roi_y_spin = _integer_spin(0, 20_000, 0)
        self.roi_width_spin = _integer_spin(1, 20_000, 1282)
        self.roi_height_spin = _integer_spin(1, 20_000, 1026)
        self.orientation_combo = QComboBox()
        self.orientation_combo.addItem("Normal", "normal")
        self.orientation_combo.addItem("Flip X", "flip_x")
        self.orientation_combo.addItem("Flip Y", "flip_y")
        self.orientation_combo.addItem("Rotate 180°", "rotate_180")

        form.addWidget(QLabel("카메라 모델"), 0, 0)
        form.addWidget(self.camera_model_edit, 0, 1)
        form.addWidget(QLabel("Serial"), 0, 2)
        form.addWidget(self.camera_serial_edit, 0, 3)
        form.addWidget(QLabel("렌즈 SKU"), 1, 0)
        form.addWidget(self.lens_sku_edit, 1, 1)
        form.addWidget(QLabel("초점거리"), 1, 2)
        form.addWidget(self.focal_length_spin, 1, 3)
        form.addWidget(QLabel("전체 해상도 W×H"), 2, 0)
        resolution = QHBoxLayout()
        resolution.addWidget(self.resolution_width_spin)
        resolution.addWidget(QLabel("×"))
        resolution.addWidget(self.resolution_height_spin)
        form.addLayout(resolution, 2, 1)
        form.addWidget(QLabel("ROI X/Y"), 2, 2)
        offsets = QHBoxLayout()
        offsets.addWidget(self.roi_x_spin)
        offsets.addWidget(self.roi_y_spin)
        form.addLayout(offsets, 2, 3)
        form.addWidget(QLabel("ROI W×H"), 3, 0)
        roi_size = QHBoxLayout()
        roi_size.addWidget(self.roi_width_spin)
        roi_size.addWidget(QLabel("×"))
        roi_size.addWidget(self.roi_height_spin)
        form.addLayout(roi_size, 3, 1)
        form.addWidget(QLabel("센서 방향"), 3, 2)
        form.addWidget(self.orientation_combo, 3, 3)

        actions = QHBoxLayout()
        self.load_button = QPushButton("보정 JSON 불러오기")
        self.save_button = QPushButton("보정 JSON 저장")
        self.mock_button = QPushButton("결정론적 Mock 보정")
        self.mock_button.setObjectName("mockCalibrationButton")
        actions.addWidget(self.load_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.mock_button)
        actions.addStretch(1)
        form.addLayout(actions, 4, 0, 1, 4)

        self.load_button.clicked.connect(self._load_dialog)
        self.save_button.clicked.connect(self._save_dialog)
        self.mock_button.clicked.connect(self.run_mock_calibration)
        return group

    def _build_calibration_group(self) -> QGroupBox:
        group = QGroupBox("카메라·레이저 보정")
        layout = QGridLayout(group)

        self.board_columns_spin = _integer_spin(2, 30, 7)
        self.board_rows_spin = _integer_spin(2, 30, 6)
        self.square_size_spin = _double_spin(0.001, 500.0, 20.0, 3, " mm")
        layout.addWidget(QLabel("체커보드 내부 코너 열/행"), 0, 0)
        board_size = QHBoxLayout()
        board_size.addWidget(self.board_columns_spin)
        board_size.addWidget(QLabel("×"))
        board_size.addWidget(self.board_rows_spin)
        layout.addLayout(board_size, 0, 1)
        layout.addWidget(QLabel("정사각형 크기"), 0, 2)
        layout.addWidget(self.square_size_spin, 0, 3)

        self.checkerboard_import_button = QPushButton("체커보드 이미지 가져오기")
        self.checkerboard_run_button = QPushButton("내부 보정 실행")
        self.checkerboard_run_button.setEnabled(False)
        layout.addWidget(self.checkerboard_import_button, 1, 0)
        layout.addWidget(self.checkerboard_run_button, 1, 1)
        self.checkerboard_status_label = QLabel("유효 이미지 0/15")
        layout.addWidget(self.checkerboard_status_label, 1, 2, 1, 2)

        self.laser_plane_import_button = QPushButton("레이저 평면 Nx3 CSV")
        self.laser_plane_status_label = QLabel("레이저 평면 미보정")
        layout.addWidget(self.laser_plane_import_button, 2, 0)
        layout.addWidget(self.laser_plane_status_label, 2, 1, 1, 3)

        self.newton_import_button = QPushButton("Pixel/Range CSV")
        self.newton_status_label = QLabel("Newton 거리 보정 미적용")
        layout.addWidget(self.newton_import_button, 3, 0)
        layout.addWidget(self.newton_status_label, 3, 1, 1, 3)

        self.approval_label = QLabel("승인 상태: 보정 미완료")
        self.approval_label.setObjectName("calibrationApproval")
        layout.addWidget(self.approval_label, 4, 0, 1, 4)

        self.checkerboard_import_button.clicked.connect(self._checkerboard_dialog)
        self.checkerboard_run_button.clicked.connect(self._run_intrinsic_from_button)
        self.laser_plane_import_button.clicked.connect(self._laser_plane_dialog)
        self.newton_import_button.clicked.connect(self._newton_dialog)
        for control in (
            self.board_columns_spin,
            self.board_rows_spin,
            self.square_size_spin,
        ):
            control.valueChanged.connect(self.clear_checkerboard_observations)
        return group

    def _build_measurement_group(self) -> QGroupBox:
        group = QGroupBox("단일 프레임 측정")
        layout = QFormLayout(group)
        self.stripe_orientation_combo = QComboBox()
        self.stripe_orientation_combo.addItem("Vertical stripe: 행별 X 추출", "vertical")
        self.stripe_orientation_combo.addItem("Horizontal stripe: 열별 Y 추출", "horizontal")
        layout.addRow("레이저 선 방향", self.stripe_orientation_combo)

        actions = QHBoxLayout()
        self.measure_button = QPushButton("현재 프레임 측정")
        self.measure_button.setObjectName("runMeasurementButton")
        self.export_button = QPushButton("단면 CSV + 메타데이터 내보내기")
        actions.addWidget(self.measure_button)
        actions.addWidget(self.export_button)
        actions.addStretch(1)
        layout.addRow(actions)

        self.frame_status_label = QLabel("주입된 프레임 없음")
        self.measurement_status_label = QLabel("측정 결과 없음")
        self.measurement_status_label.setObjectName("measurementResult")
        layout.addRow("프레임", self.frame_status_label)
        layout.addRow("결과", self.measurement_status_label)

        focus_actions = QHBoxLayout()
        self.focus_button = QPushButton("FFT/Ronchi 포커스 분석")
        self.focus_button.setObjectName("focusAssistButton")
        self.focus_result_label = QLabel("포커스 분석 결과 없음")
        self.focus_result_label.setWordWrap(True)
        focus_actions.addWidget(self.focus_button)
        focus_actions.addWidget(self.focus_result_label, 1)
        layout.addRow("수동 Focus Assist", focus_actions)
        self.measure_button.clicked.connect(self._run_measurement_from_button)
        self.export_button.clicked.connect(self._export_dialog)
        self.focus_button.clicked.connect(self._run_focus_from_button)
        return group

    def hardware_identity(self) -> HardwareIdentity:
        """Read and validate the identity currently displayed by the widget."""

        resolution = (
            self.resolution_width_spin.value(),
            self.resolution_height_spin.value(),
        )
        roi = Roi(
            self.roi_x_spin.value(),
            self.roi_y_spin.value(),
            self.roi_width_spin.value(),
            self.roi_height_spin.value(),
        )
        if roi.x_px + roi.width_px > resolution[0]:
            raise ValueError("ROI exceeds the configured sensor width")
        if roi.y_px + roi.height_px > resolution[1]:
            raise ValueError("ROI exceeds the configured sensor height")
        return HardwareIdentity(
            camera_serial=self.camera_serial_edit.text().strip(),
            camera_model=self.camera_model_edit.text().strip(),
            lens_sku=self.lens_sku_edit.text().strip(),
            roi=roi,
            resolution_px=resolution,
            sensor_orientation=str(self.orientation_combo.currentData()),
        )

    def set_hardware_identity(self, identity: HardwareIdentity) -> None:
        self.camera_serial_edit.setText(identity.camera_serial)
        self.camera_model_edit.setText(identity.camera_model)
        self.lens_sku_edit.setText(identity.lens_sku)
        self.resolution_width_spin.setValue(identity.resolution_px[0])
        self.resolution_height_spin.setValue(identity.resolution_px[1])
        self.roi_x_spin.setValue(identity.roi.x_px)
        self.roi_y_spin.setValue(identity.roi.y_px)
        self.roi_width_spin.setValue(identity.roi.width_px)
        self.roi_height_spin.setValue(identity.roi.height_px)
        index = self.orientation_combo.findData(identity.sensor_orientation)
        self.orientation_combo.setCurrentIndex(max(index, 0))

    def clear_checkerboard_observations(self, _value: object = None) -> None:
        """Discard observations if board geometry changes."""

        self._object_points.clear()
        self._image_points.clear()
        self._checkerboard_image_size = None
        self.checkerboard_status_label.setText("유효 이미지 0/15")
        self.checkerboard_run_button.setEnabled(False)

    def import_checkerboard_images(
        self,
        paths: list[str | Path],
    ) -> IntrinsicCalibration | None:
        """Detect imported boards and auto-calibrate after 15 valid views."""

        columns = self.board_columns_spin.value()
        rows = self.board_rows_spin.value()
        square_size = self.square_size_spin.value()
        pattern_size = (columns, rows)
        object_template = np.zeros((columns * rows, 3), dtype=np.float32)
        object_template[:, :2] = np.mgrid[0:columns, 0:rows].T.reshape(-1, 2) * square_size
        expected_image_size = self._checkerboard_image_size
        imported = 0
        rejected = 0
        for path in paths:
            image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if image is None:
                rejected += 1
                continue
            image_size = (int(image.shape[1]), int(image.shape[0]))
            if expected_image_size is None:
                expected_image_size = image_size
            if image_size != expected_image_size:
                rejected += 1
                continue
            corners = detect_checkerboard(image, pattern_size)
            if corners is None or corners.shape != (columns * rows, 2):
                rejected += 1
                continue
            self._object_points.append(object_template.copy())
            self._image_points.append(np.asarray(corners, dtype=np.float32))
            imported += 1
        self._checkerboard_image_size = expected_image_size

        valid_count = len(self._image_points)
        self.checkerboard_status_label.setText(
            f"유효 이미지 {valid_count}/15 · 이번 가져오기 성공 {imported}, 제외 {rejected}"
        )
        self.checkerboard_run_button.setEnabled(valid_count >= 15)
        if valid_count >= 15:
            return self.run_intrinsic_calibration(image_size_px=expected_image_size)
        self._set_status("체커보드 유효 이미지가 15장 이상 필요합니다.")
        return None

    def run_intrinsic_calibration(
        self,
        *,
        image_size_px: tuple[int, int] | None = None,
    ) -> IntrinsicCalibration:
        """Run OpenCV Brown calibration over imported checkerboard observations."""

        if len(self._image_points) < 15:
            raise ValueError("at least 15 valid checkerboard images are required")
        if image_size_px is None:
            image_size_px = self._checkerboard_image_size
        if image_size_px is None:
            raise ValueError("checkerboard image size is unknown")
        identity = self.hardware_identity()
        calibrated_roi_size = (identity.roi.width_px, identity.roi.height_px)
        if image_size_px != calibrated_roi_size:
            raise ValueError(
                f"checkerboard size {image_size_px} does not match ROI {calibrated_roi_size}"
            )
        result = calibrate_intrinsics(
            self._object_points,
            self._image_points,
            image_size_px,
        )
        self._intrinsic = result
        self._thick_lens = None
        self._calibrated_identity = identity
        self.checkerboard_status_label.setText(
            f"RMS {result.rms_reprojection_error_px:.4f} px · "
            f"{result.gate.value.upper()} · {result.view_count} views"
        )
        self._refresh_calibration_record()
        self._set_status(
            f"내부 보정 완료: RMS {result.rms_reprojection_error_px:.4f} px, "
            f"gate={result.gate.value}"
        )
        return result

    def import_laser_plane_csv(self, path: str | Path) -> LaserPlaneFit:
        points = _load_numeric_csv(path, columns=3)
        result = fit_laser_plane(points[:, :3])
        self._laser_plane_fit = result
        inliers = int(np.count_nonzero(result.inlier_mask))
        self.laser_plane_status_label.setText(
            f"RMS {result.rms_residual_mm:.6f} mm · inliers {inliers}/{len(result.inlier_mask)}"
        )
        self._refresh_calibration_record()
        self._set_status("레이저 평면 보정을 완료했습니다.")
        return result

    def import_newton_csv(self, path: str | Path) -> NewtonRangeCalibration:
        samples = _load_numeric_csv(path, columns=2)
        result = fit_newton_range(samples[:, 0], samples[:, 1])
        self._newton_range = result
        self.newton_status_label.setText(
            f"a={result.a_per_mm_px:.8g}, b={result.b_per_mm:.8g}, "
            f"RMS={result.rms_inverse_range_per_mm:.3g} 1/mm"
        )
        self._refresh_calibration_record()
        self._set_status("Newton 거리 보정을 완료했습니다.")
        return result

    def run_mock_calibration(self) -> CalibrationRecord:
        """Create deterministic, approved calibration for CI and camera-less demos."""

        identity = self.hardware_identity()
        width = identity.roi.width_px
        height = identity.roi.height_px
        focal_px = max(width, height) * 1.8
        camera_matrix = np.asarray(
            [
                [focal_px, 0.0, (width - 1) / 2],
                [0.0, focal_px, (height - 1) / 2],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        self._intrinsic = IntrinsicCalibration(
            camera_matrix=camera_matrix,
            distortion_coefficients=np.zeros(5, dtype=np.float64),
            rms_reprojection_error_px=0.05,
            per_view_error_px=np.full(15, 0.05, dtype=np.float64),
            image_size_px=(width, height),
            view_count=15,
            coverage_quadrants=(True, True, True, True),
            gate=CalibrationGate.PASS,
        )
        plane = LaserPlane(np.asarray([0.0, 0.0, 1.0]), -200.0)
        self._laser_plane_fit = LaserPlaneFit(
            plane=plane,
            inlier_mask=np.ones(100, dtype=bool),
            rms_residual_mm=0.0,
            max_residual_mm=0.0,
            iterations=1,
        )
        self._newton_range = None
        pixel_pitch = self.focal_length_spin.value() / focal_px
        self._thick_lens = ThickLensParameters(
            focal_length_mm=self.focal_length_spin.value(),
            principal_x_px=(width - 1) / 2,
            principal_y_px=(height - 1) / 2,
            tilt_x_rad=0.0,
            tilt_y_rad=0.0,
            principal_plane_offset_mm=0.0,
            pixel_pitch_x_mm=pixel_pitch,
            pixel_pitch_y_mm=pixel_pitch,
        )
        self._calibrated_identity = identity
        self.checkerboard_status_label.setText("Mock RMS 0.0500 px · PASS · 15 views")
        self.laser_plane_status_label.setText("Mock plane Z=200 mm · RMS 0.000000 mm")
        self.newton_status_label.setText("Newton 거리 보정 미적용")
        record = self._refresh_calibration_record()
        assert record is not None
        self._set_status("결정론적 Mock 보정이 승인되었습니다.")
        return record

    def build_calibration_record(self) -> CalibrationRecord:
        """Build a serializable record, failing if required calibration is incomplete."""

        if self._intrinsic is None or not self._intrinsic.accepted:
            raise ValueError("an accepted intrinsic calibration is required")
        if self._laser_plane_fit is None:
            raise ValueError("laser plane calibration is required")
        identity = self._calibrated_identity or self.hardware_identity()
        focal_length = self.focal_length_spin.value()
        fx = float(self._intrinsic.camera_matrix[0, 0])
        fy = float(self._intrinsic.camera_matrix[1, 1])
        thick_lens = self._thick_lens or ThickLensParameters(
            focal_length_mm=focal_length,
            principal_x_px=float(self._intrinsic.camera_matrix[0, 2]),
            principal_y_px=float(self._intrinsic.camera_matrix[1, 2]),
            tilt_x_rad=0.0,
            tilt_y_rad=0.0,
            principal_plane_offset_mm=0.0,
            pixel_pitch_x_mm=focal_length / fx,
            pixel_pitch_y_mm=focal_length / fy,
        )
        quality = {
            "intrinsic_rms_px": self._intrinsic.rms_reprojection_error_px,
            "laser_plane_rms_mm": self._laser_plane_fit.rms_residual_mm,
            "laser_plane_max_mm": self._laser_plane_fit.max_residual_mm,
        }
        return CalibrationRecord(
            identity=identity,
            intrinsic=self._intrinsic,
            thick_lens=thick_lens,
            laser_plane=self._laser_plane_fit.plane,
            rotation_camera_to_measurement=self._rotation,
            translation_camera_origin_mm=self._translation,
            newton_range=self._newton_range,
            quality_metrics=quality,
        )

    def save_calibration(self, path: str | Path) -> Path:
        record = self.build_calibration_record()
        destination = Path(path).expanduser().resolve()
        destination.write_text(
            json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self._calibration_path = destination
        self._set_status(f"보정 저장: {destination}")
        return destination

    def load_calibration(self, path: str | Path) -> CalibrationRecord:
        source = Path(path).expanduser().resolve()
        payload = json.loads(source.read_text(encoding="utf-8"))
        record = _record_from_dict(payload)
        self._intrinsic = record.intrinsic
        rms_plane = float(record.quality_metrics.get("laser_plane_rms_mm", 0.0))
        max_plane = float(record.quality_metrics.get("laser_plane_max_mm", rms_plane))
        self._laser_plane_fit = LaserPlaneFit(
            plane=record.laser_plane,
            inlier_mask=np.empty(0, dtype=bool),
            rms_residual_mm=rms_plane,
            max_residual_mm=max_plane,
            iterations=0,
        )
        self._newton_range = record.newton_range
        self._thick_lens = record.thick_lens
        self._rotation = record.rotation_camera_to_measurement
        self._translation = record.translation_camera_origin_mm
        self._calibrated_identity = record.identity
        self._calibration_record = record
        self._calibration_path = source
        self.set_hardware_identity(record.identity)
        self.focal_length_spin.setValue(record.thick_lens.focal_length_mm)
        self.checkerboard_status_label.setText(
            f"RMS {record.intrinsic.rms_reprojection_error_px:.4f} px · "
            f"{record.intrinsic.gate.value.upper()} · {record.intrinsic.view_count} views"
        )
        self.laser_plane_status_label.setText(f"RMS {rms_plane:.6f} mm · loaded")
        if record.newton_range is not None:
            self.newton_status_label.setText(
                f"a={record.newton_range.a_per_mm_px:.8g}, "
                f"b={record.newton_range.b_per_mm:.8g} · loaded"
            )
        else:
            self.newton_status_label.setText("Newton 거리 보정 미적용")
        self.approval_label.setText(
            f"승인 상태: {record.intrinsic.gate.value.upper()} · "
            f"RMS {record.intrinsic.rms_reprojection_error_px:.4f} px"
        )
        self._update_actions()
        self.calibration_ready.emit(record)
        self._set_status(f"보정 불러오기: {source}")
        return record

    def reset_calibration(self) -> None:
        """Clear calibration state when starting an unrelated project."""

        self._object_points.clear()
        self._image_points.clear()
        self._checkerboard_image_size = None
        self._intrinsic = None
        self._laser_plane_fit = None
        self._newton_range = None
        self._thick_lens = None
        self._calibration_record = None
        self._calibration_path = None
        self._calibrated_identity = None
        self._cross_section = None
        self.checkerboard_status_label.setText("유효 이미지 0/15")
        self.laser_plane_status_label.setText("레이저 평면 미보정")
        self.newton_status_label.setText("Newton 거리 보정 미적용")
        self.approval_label.setText("승인 상태: 보정 미완료")
        self.measurement_status_label.setText("측정 결과 없음")
        self._update_actions()
        self._set_status("보정 상태를 초기화했습니다.")

    def set_camera_frame(
        self,
        frame_or_image: CameraFrame | NDArray[np.generic],
    ) -> None:
        """Inject a frame from ``CameraPreviewWidget`` or a plain test image."""

        if isinstance(frame_or_image, CameraFrame):
            image = frame_or_image.image
            self._frame = frame_or_image
            self._frame_metadata = {
                "frame_id": frame_or_image.frame_id,
                "timestamp_ns": frame_or_image.timestamp_ns,
                "camera_serial": frame_or_image.device.serial,
                "camera_model": frame_or_image.device.model,
            }
        else:
            image = np.asarray(frame_or_image)
            self._frame = None
            self._frame_metadata = {}
        if image.ndim != 2 or not np.issubdtype(image.dtype, np.number):
            raise ValueError("measurement frame must be a 2-D numeric image")
        self._image = np.asarray(image).copy()
        self.frame_status_label.setText(
            f"{image.shape[1]}×{image.shape[0]} px"
            + (
                f" · frame #{self._frame.frame_id}"
                if self._frame is not None
                else " · injected image"
            )
        )
        self._update_actions()

    def analyze_focus_contrast(
        self,
        image: NDArray[np.generic] | None = None,
        *,
        high_frequency_fraction: float = 0.25,
    ) -> FocusContrastResult:
        """Evaluate row/column FFT contrast and return manual adjustment guidance."""

        source = self._image if image is None else np.asarray(image)
        if source is None:
            raise ValueError("inject a frame before focus analysis")
        if source.ndim != 2 or min(source.shape) < 8:
            raise ValueError("focus analysis requires a grayscale image at least 8x8 pixels")
        if not 0.05 <= high_frequency_fraction <= 0.8:
            raise ValueError("high_frequency_fraction must be between 0.05 and 0.8")
        working = source.astype(np.float64)
        if not np.all(np.isfinite(working)):
            raise ValueError("focus image must contain finite pixels")

        horizontal = _directional_fft_contrast(
            working,
            axis=1,
            high_frequency_fraction=high_frequency_fraction,
        )
        vertical = _directional_fft_contrast(
            working,
            axis=0,
            high_frequency_fraction=high_frequency_fraction,
        )
        maximum = max(horizontal, vertical)
        balance = min(horizontal, vertical) / maximum if maximum > 0 else 0.0
        if maximum < 0.02:
            guidance = "고주파 대비가 낮습니다. 렌즈 초점을 먼저 천천히 조정하십시오."
        elif balance >= 0.8:
            guidance = "수평·수직 대비가 균형적입니다. 두 값이 최대가 되도록 미세 조정하십시오."
        elif horizontal < vertical:
            guidance = "수평 방향 대비가 낮습니다. 센서 pan/yaw를 소폭 조정하십시오."
        else:
            guidance = "수직 방향 대비가 낮습니다. 센서 tilt/pitch를 소폭 조정하십시오."
        result = FocusContrastResult(horizontal, vertical, balance, guidance)
        self.focus_result_label.setText(
            f"H={horizontal:.4f} · V={vertical:.4f} · balance={balance:.3f} · {guidance}"
        )
        self.focus_assist_ready.emit(result)
        self._set_status("수동 focus-assist 분석을 완료했습니다.")
        return result

    def run_measurement(self) -> CrossSection:
        """Extract a laser stripe and triangulate it against approved calibration."""

        if self._image is None:
            raise ValueError("inject a camera frame before measurement")
        record = self.build_calibration_record()
        current_identity = self.hardware_identity()
        assert_calibration_matches(record.identity, current_identity)
        if self._frame is not None:
            if self._frame.device.serial != record.identity.camera_serial:
                raise ValueError(
                    "injected frame serial does not match the calibrated camera serial"
                )
            frame_model = self._frame.device.model.removesuffix(" (simulated)")
            if frame_model != record.identity.camera_model:
                raise ValueError("injected frame model does not match the calibrated camera model")
        expected_shape = (
            record.identity.roi.height_px,
            record.identity.roi.width_px,
        )
        if self._image.shape != expected_shape:
            raise ValueError(
                f"frame shape {self._image.shape} does not match calibrated ROI {expected_shape}"
            )
        stripe = extract_stripe(
            self._image,
            orientation=str(self.stripe_orientation_combo.currentData()),
        )
        metadata: dict[str, Any] = {
            **self._frame_metadata,
            "hardware_identity": record.identity.to_dict(),
            "intrinsic_gate": record.intrinsic.gate.value,
            "intrinsic_rms_px": record.intrinsic.rms_reprojection_error_px,
            "laser_plane_rms_mm": record.quality_metrics["laser_plane_rms_mm"],
            "stripe_orientation": stripe.orientation,
            "newton_range": (
                None if record.newton_range is None else record.newton_range.to_dict()
            ),
        }
        cross_section = triangulate_cross_section(
            stripe,
            record.intrinsic.camera_matrix,
            record.laser_plane,
            distortion_coefficients=record.intrinsic.distortion_coefficients,
            rotation_camera_to_measurement=record.rotation_camera_to_measurement,
            translation_camera_origin_mm=record.translation_camera_origin_mm,
            metadata=metadata,
        )
        valid_count = int(np.count_nonzero(cross_section.valid_mask))
        mean_confidence = (
            float(np.mean(cross_section.confidence[cross_section.valid_mask]))
            if valid_count
            else 0.0
        )
        cross_section.metadata.update(
            {
                "valid_point_count": valid_count,
                "mean_confidence": mean_confidence,
            }
        )
        self._cross_section = cross_section
        self.measurement_status_label.setText(
            f"유효 점 {valid_count}/{len(cross_section.valid_mask)} · "
            f"평균 confidence {mean_confidence:.3f}"
        )
        self._update_actions()
        self.measurement_ready.emit(cross_section)
        self._set_status("단일 프레임 단면 측정을 완료했습니다.")
        return cross_section

    def export_measurement(
        self,
        csv_path: str | Path,
        metadata_path: str | Path | None = None,
    ) -> tuple[Path, Path]:
        if self._cross_section is None:
            raise ValueError("there is no cross-section to export")
        csv_destination = Path(csv_path)
        json_destination = (
            Path(metadata_path)
            if metadata_path is not None
            else csv_destination.with_suffix(".json")
        )
        self._cross_section.write_csv(csv_destination)
        self._cross_section.write_metadata(json_destination)
        self._set_status(f"측정 내보내기: {csv_destination}, {json_destination}")
        return csv_destination, json_destination

    def _refresh_calibration_record(self) -> CalibrationRecord | None:
        try:
            record = self.build_calibration_record()
        except (ValueError, ZeroDivisionError):
            self._calibration_record = None
            self.approval_label.setText("승인 상태: 보정 미완료")
            self._update_actions()
            return None
        self._calibration_record = record
        self.approval_label.setText(
            f"승인 상태: {record.intrinsic.gate.value.upper()} · "
            f"RMS {record.intrinsic.rms_reprojection_error_px:.4f} px"
        )
        self._update_actions()
        self.calibration_ready.emit(record)
        return record

    def _update_actions(self) -> None:
        calibration_complete = (
            self._intrinsic is not None
            and self._intrinsic.accepted
            and self._laser_plane_fit is not None
        )
        self.save_button.setEnabled(calibration_complete)
        self.measure_button.setEnabled(calibration_complete and self._image is not None)
        self.export_button.setEnabled(self._cross_section is not None)
        self.focus_button.setEnabled(self._image is not None)

    def _set_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.status_changed.emit(message)

    def _run_intrinsic_from_button(self) -> None:
        try:
            self.run_intrinsic_calibration()
        except Exception as exc:
            self._set_status(f"내부 보정 실패: {exc}")

    def _run_measurement_from_button(self) -> None:
        try:
            self.run_measurement()
        except Exception as exc:
            self._set_status(f"측정 차단: {exc}")

    def _run_focus_from_button(self) -> None:
        try:
            self.analyze_focus_contrast()
        except Exception as exc:
            self._set_status(f"Focus assist 실패: {exc}")

    def _checkerboard_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "체커보드 이미지 선택",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if paths:
            try:
                self.import_checkerboard_images(paths)
            except Exception as exc:
                self._set_status(f"체커보드 가져오기 실패: {exc}")

    def _laser_plane_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "레이저 평면 CSV", "", "CSV (*.csv)")
        if path:
            try:
                self.import_laser_plane_csv(path)
            except Exception as exc:
                self._set_status(f"레이저 평면 보정 실패: {exc}")

    def _newton_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Pixel/Range CSV", "", "CSV (*.csv)")
        if path:
            try:
                self.import_newton_csv(path)
            except Exception as exc:
                self._set_status(f"Newton 보정 실패: {exc}")

    def _load_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "보정 JSON 불러오기", "", "JSON (*.json)")
        if path:
            try:
                self.load_calibration(path)
            except Exception as exc:
                self._set_status(f"보정 불러오기 실패: {exc}")

    def _save_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "보정 JSON 저장", "", "JSON (*.json)")
        if path:
            try:
                self.save_calibration(path)
            except Exception as exc:
                self._set_status(f"보정 저장 실패: {exc}")

    def _export_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "단면 CSV 내보내기", "", "CSV (*.csv)")
        if path:
            try:
                self.export_measurement(path)
            except Exception as exc:
                self._set_status(f"측정 내보내기 실패: {exc}")


def _integer_spin(minimum: int, maximum: int, value: int) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _double_spin(
    minimum: float,
    maximum: float,
    value: float,
    decimals: int,
    suffix: str,
) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(minimum, maximum)
    spin.setDecimals(decimals)
    spin.setValue(value)
    spin.setSuffix(suffix)
    return spin


def _load_numeric_csv(path: str | Path, *, columns: int) -> NDArray[np.float64]:
    data = np.genfromtxt(path, delimiter=",", dtype=np.float64, ndmin=2)
    if data.ndim != 2 or data.shape[1] < columns:
        raise ValueError(f"CSV must contain at least {columns} numeric columns")
    data = data[:, :columns]
    data = data[np.all(np.isfinite(data), axis=1)]
    if len(data) < 3:
        raise ValueError("CSV must contain at least three finite data rows")
    return data


def _directional_fft_contrast(
    image: NDArray[np.float64],
    *,
    axis: int,
    high_frequency_fraction: float,
) -> float:
    length = image.shape[axis]
    centered = image - np.mean(image, axis=axis, keepdims=True)
    window_shape = [1, 1]
    window_shape[axis] = length
    window = np.hanning(length).reshape(window_shape)
    spectrum = np.fft.rfft(centered * window, axis=axis)
    power = np.abs(spectrum) ** 2
    power = np.moveaxis(power, axis, -1)
    if power.shape[-1] <= 1:
        return 0.0
    non_dc = power[..., 1:]
    start = max(1, int(np.ceil(non_dc.shape[-1] * high_frequency_fraction)))
    total = float(np.sum(non_dc))
    if total <= np.finfo(float).eps:
        return 0.0
    return float(np.clip(np.sum(non_dc[..., start:]) / total, 0.0, 1.0))


def _record_from_dict(payload: object) -> CalibrationRecord:
    if not isinstance(payload, dict) or int(payload.get("schema_version", -1)) != 1:
        raise ValueError("unsupported or missing calibration schema_version")
    identity_payload = payload.get("identity")
    intrinsic_payload = payload.get("intrinsic")
    thick_payload = payload.get("thick_lens")
    plane_payload = payload.get("laser_plane")
    if not all(
        isinstance(value, dict)
        for value in (identity_payload, intrinsic_payload, thick_payload, plane_payload)
    ):
        raise ValueError("calibration JSON is missing a required object")
    assert isinstance(identity_payload, dict)
    assert isinstance(intrinsic_payload, dict)
    assert isinstance(thick_payload, dict)
    assert isinstance(plane_payload, dict)
    image_size = intrinsic_payload["image_size_px"]
    coverage = intrinsic_payload["coverage_quadrants"]
    intrinsic = IntrinsicCalibration(
        camera_matrix=np.asarray(intrinsic_payload["camera_matrix"], dtype=np.float64),
        distortion_coefficients=np.asarray(
            intrinsic_payload["distortion_coefficients"], dtype=np.float64
        ),
        rms_reprojection_error_px=float(intrinsic_payload["rms_reprojection_error_px"]),
        per_view_error_px=np.asarray(intrinsic_payload["per_view_error_px"], dtype=np.float64),
        image_size_px=(int(image_size[0]), int(image_size[1])),
        view_count=int(intrinsic_payload["view_count"]),
        coverage_quadrants=tuple(bool(item) for item in coverage),
        gate=CalibrationGate(str(intrinsic_payload["gate"])),
    )
    thick_lens = ThickLensParameters(
        focal_length_mm=float(thick_payload["focal_length_mm"]),
        principal_x_px=float(thick_payload["principal_x_px"]),
        principal_y_px=float(thick_payload["principal_y_px"]),
        tilt_x_rad=float(thick_payload["tilt_x_rad"]),
        tilt_y_rad=float(thick_payload["tilt_y_rad"]),
        principal_plane_offset_mm=float(thick_payload["principal_plane_offset_mm"]),
        pixel_pitch_x_mm=float(thick_payload["pixel_pitch_x_mm"]),
        pixel_pitch_y_mm=float(thick_payload["pixel_pitch_y_mm"]),
    )
    plane = LaserPlane(
        np.asarray(plane_payload["normal"], dtype=np.float64),
        float(plane_payload["offset_mm"]),
    )
    newton_payload = payload.get("newton_range")
    newton = None
    if isinstance(newton_payload, dict):
        newton = NewtonRangeCalibration(
            a_per_mm_px=float(newton_payload["a_per_mm_px"]),
            b_per_mm=float(newton_payload["b_per_mm"]),
            rms_inverse_range_per_mm=float(newton_payload["rms_inverse_range_per_mm"]),
            sample_count=int(newton_payload["sample_count"]),
        )
    quality_payload = payload.get("quality_metrics", {})
    if not isinstance(quality_payload, dict):
        raise ValueError("quality_metrics must be an object")
    return CalibrationRecord(
        schema_version=1,
        created_at_utc=str(payload.get("created_at_utc", "")),
        identity=HardwareIdentity.from_dict(identity_payload),
        intrinsic=intrinsic,
        thick_lens=thick_lens,
        laser_plane=plane,
        rotation_camera_to_measurement=np.asarray(
            payload["rotation_camera_to_measurement"], dtype=np.float64
        ),
        translation_camera_origin_mm=np.asarray(
            payload["translation_camera_origin_mm"], dtype=np.float64
        ),
        newton_range=newton,
        quality_metrics={str(key): float(value) for key, value in quality_payload.items()},
    )
