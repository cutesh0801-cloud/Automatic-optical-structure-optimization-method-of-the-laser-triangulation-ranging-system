"""Design-tab controls and direct adapter to the pure optical core."""

from __future__ import annotations

import math
import threading
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from PySide6.QtCore import QObject, QRect, QSize, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .scene import OpticsGraphicsScene, OpticsGraphicsView, Point2D, SceneSnapshot


class CoreUnavailableError(RuntimeError):
    """Raised when the optical core is not importable yet."""


def _point(value: Any) -> Point2D:
    return Point2D(float(value.x_mm), float(value.z_mm))


class OpticalCoreFacade:
    """Thin adapter: the UI never repeats or substitutes an optical equation."""

    def __init__(self) -> None:
        self.import_error: Exception | None = None
        try:
            from scheimpflug_optimeter import hardware, models, optics

            self.hardware = hardware
            self.models = models
            self.optics = optics
        except (ImportError, AttributeError) as exc:
            self.import_error = exc
            self.hardware = None
            self.models = None
            self.optics = None

    @property
    def ready(self) -> bool:
        return self.import_error is None

    def cameras(self) -> tuple[Any, ...]:
        """Return static camera/sensor specifications used by the simulation."""

        if not self.ready:
            return ()
        catalog = getattr(self.hardware, "CAMERAS", ())
        return tuple(catalog.values()) if isinstance(catalog, Mapping) else tuple(catalog)

    def lenses(self) -> tuple[Any, ...]:
        if not self.ready:
            return ()
        catalog = getattr(self.hardware, "LENSES", ())
        return tuple(catalog.values()) if isinstance(catalog, Mapping) else tuple(catalog)

    def camera_sensor_length_mm(self, camera_id: str, sensor_axis: str) -> float:
        """Return a static catalog length only when the user explicitly requests it."""

        if not self.ready:
            raise CoreUnavailableError("하드웨어 카탈로그를 사용할 수 없습니다.")
        return float(self.hardware.get_camera(camera_id).sensor.length_mm(sensor_axis))

    def compare_sensor_profiles(self, solution: Any) -> tuple[tuple[Any, Any], ...]:
        """Evaluate every static sensor profile against one unchanged optical solution."""

        if not self.ready:
            raise CoreUnavailableError("하드웨어 카탈로그를 사용할 수 없습니다.")
        sensor_axis = solution.request.sensor_axis
        rows: list[tuple[Any, Any]] = []
        for camera in self.cameras():
            metrics = self.optics.calculate_sensor_imaging_metrics(
                camera.sensor,
                sensor_axis=sensor_axis,
                alpha_deg=solution.alpha_deg,
                beta_deg=solution.beta_deg,
                lo_mm=solution.lo_mm,
                fp_mm=solution.fp_mm,
            )
            rows.append((camera, metrics))
        return tuple(rows)

    def solve(self, values: Mapping[str, Any]) -> tuple[Any, Any, SceneSnapshot]:
        if not self.ready:
            raise CoreUnavailableError(f"광학 코어를 불러오지 못했습니다: {self.import_error}")
        camera = self.hardware.get_camera(values["camera_id"])
        sensor = camera.sensor
        mode = values["mode"]
        if mode == "workbook":
            request = self.models.WorkbookDesignInput(
                v_mm=float(values["v_mm"]),
                d_mm=float(values["d_mm"]),
                sensor_length_mm=float(values["sensor_length_mm"]),
                alpha_deg=float(values["alpha_deg"]),
                sensor_id=sensor.id,
                sensor_axis=values["sensor_axis"],
            )
            solution = self.optics.solve_workbook_design(request)
            lens = None
        else:
            lens = self.hardware.get_lens(values["lens_id"])
            request = self.models.DesignInput(
                d_mm=float(values["d_mm"]),
                range_mm=float(values["range_mm"]),
                alpha_deg=float(values["alpha_deg"]),
                beta_deg=float(values["beta_deg"]),
                lens_id=lens.id,
                sensor_id=sensor.id,
                sensor_axis=values["sensor_axis"],
                max_width_mm=float(values["max_width_mm"]),
                max_rear_mm=float(values["max_rear_mm"]),
                laser_wavelength_nm=float(values["wavelength_nm"]),
            )
            solution = self.optics.solve_canonical_design(
                request,
                lens=lens,
                sensor=sensor,
            )
        geometry = self.optics.build_scene_geometry(solution)
        return solution, lens, self.scene_snapshot(solution, geometry)

    @staticmethod
    def scene_snapshot(solution: Any, geometry: Any) -> SceneSnapshot:
        request = solution.request
        range_mm = getattr(request, "range_mm", None)
        if range_mm is None:
            range_mm = abs(solution.ray_intercept_s_mm or 0.0)
        working_distance_endpoints = (
            (
                _point(geometry.target_center),
                Point2D(
                    geometry.target_center.x_mm,
                    float(geometry.front_plane_z_mm),
                ),
            )
            if geometry.front_plane_z_mm is not None
            else (_point(geometry.emitter), _point(geometry.target_center))
        )
        range_endpoints = (
            (_point(geometry.target_center), _point(geometry.ray_intercept))
            if geometry.ray_intercept is not None
            else tuple(_point(value) for value in geometry.object_range)
        )
        warnings = tuple(solution.warnings) + tuple(
            violation.message for violation in solution.violations
        )
        return SceneSnapshot(
            emitter=_point(geometry.emitter),
            laser_endpoints=tuple(_point(value) for value in geometry.laser_line),
            target_near=_point(geometry.target_near),
            target_nominal=_point(geometry.target_center),
            target_far=_point(geometry.target_far),
            working_distance_endpoints=working_distance_endpoints,
            range_endpoints=range_endpoints,
            lens_center=_point(geometry.lens_center),
            lens_endpoints=tuple(_point(value) for value in geometry.lens_plane),
            image_center=_point(geometry.image_center),
            sensor_endpoints=(
                _point(geometry.sensor_near),
                _point(geometry.sensor_far),
            ),
            proxy_sensor_endpoints=(
                _point(geometry.sensor_proxy_near),
                _point(geometry.sensor_proxy_far),
            ),
            optical_axis_endpoints=tuple(_point(value) for value in geometry.optical_axis),
            chief_rays=(
                (
                    _point(geometry.target_near),
                    _point(geometry.lens_center),
                    _point(geometry.sensor_near),
                ),
                (
                    _point(geometry.target_far),
                    _point(geometry.lens_center),
                    _point(geometry.sensor_far),
                ),
            ),
            scheimpflug_point=(
                _point(geometry.scheimpflug_intersection)
                if geometry.scheimpflug_intersection is not None
                else None
            ),
            working_distance_mm=float(request.d_mm),
            measurement_range_mm=float(range_mm),
            w_mm=float(solution.width_exact_mm),
            r_mm=float(solution.rear_exact_mm),
            lo_mm=float(solution.lo_mm),
            fp_mm=float(solution.fp_mm),
            focal_length_mm=float(solution.focal_length_mm),
            valid=bool(solution.valid),
            warnings=warnings,
            workbook_mode=solution.mode.value == "workbook",
        )

    def compatibility(self, camera_id: str, lens_id: str, solution: Any | None):
        if not self.ready:
            return None
        design = getattr(solution, "request", solution)
        return self.hardware.evaluate_compatibility(
            self.hardware.get_camera(camera_id),
            self.hardware.get_lens(lens_id),
            design=design,
        )

    def optimization_request(self, values: Mapping[str, Any], algorithm: str):
        if not self.ready:
            raise CoreUnavailableError("광학 코어를 사용할 수 없습니다.")
        camera = self.hardware.get_camera(values["camera_id"])
        lens_ids = tuple(lens.id for lens in self.lenses())
        return self.models.OptimizationRequest(
            d_mm=float(values["d_mm"]),
            range_mm=float(values["range_mm"]),
            sensor_id=camera.sensor.id,
            sensor_axis=values["sensor_axis"],
            lens_ids=lens_ids,
            algorithm=algorithm,
            max_width_mm=float(values["max_width_mm"]),
            max_rear_mm=float(values["max_rear_mm"]),
        )


class DesignInputPanel(QWidget):
    """Korean-first authoritative design inputs."""

    changed = Signal()

    def __init__(self, facade: OpticalCoreFacade, parent=None) -> None:
        super().__init__(parent)
        self._facade = facade
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(11)
        self.title = QLabel("Scheimpflug 설계 입력")
        self.title.setObjectName("panelTitle")
        self.title.setWordWrap(True)
        self.title.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            self.title.sizePolicy().verticalPolicy(),
        )
        layout.addWidget(self.title)
        self.mode_help = QLabel()
        self.mode_help.setObjectName("modeHelp")
        self.mode_help.setWordWrap(True)
        self.input_labels: dict[str, QLabel] = {}

        self.mode = QComboBox()
        self.mode.addItem("워크북 호환 계산 (기본)", "workbook")
        self.mode.addItem("고급/연구 참고 · Canonical 설계", "canonical")
        self.camera = QComboBox()
        self.lens = QComboBox()
        for combo in (self.camera, self.lens):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(14)
        self.sensor_axis = QComboBox()
        self.sensor_axis.addItem("센서 높이 (vertical)", "height")
        self.sensor_axis.addItem("센서 폭 (horizontal)", "width")

        self.d_mm = self._spin(0.0, 100_000.0, 100.0, " mm")
        self.range_mm = self._spin(0.001, 100_000.0, 5.0, " mm")
        self.v_mm = self._spin(1.0, 100_000.0, 205.0, " mm")
        self.sensor_length_mm = self._spin(
            0.000001,
            100_000.0,
            5.4378,
            " mm",
            decimals=6,
        )
        self.load_sensor_length_button = QPushButton("L에 적용")
        self.camera.setToolTip(
            "광학 계산에 사용할 센서 치수 프리셋입니다. "
            "모델명은 규격 식별자이며 장치를 검색하거나 연결하지 않습니다."
        )
        self.load_sensor_length_button.setToolTip(
            "선택한 정적 센서 규격의 폭 또는 높이를 L 입력으로 복사합니다."
        )
        self.sensor_length_container = QWidget()
        sensor_length_layout = QHBoxLayout(self.sensor_length_container)
        sensor_length_layout.setContentsMargins(0, 0, 0, 0)
        sensor_length_layout.addWidget(self.sensor_length_mm, 1)
        sensor_length_layout.addWidget(self.load_sensor_length_button)
        self.alpha_deg = self._spin(0.01, 89.0, 14.27, "°", decimals=4)
        self.beta_deg = self._spin(0.01, 89.0, 30.0, "°", decimals=4)
        self.max_width_mm = self._spin(1.0, 10_000.0, 105.0, " mm")
        self.max_rear_mm = self._spin(1.0, 10_000.0, 105.0, " mm")
        self.wavelength_nm = self._spin(200.0, 2_000.0, 650.0, " nm", decimals=1)

        mode_group = QGroupBox("계산 방식")
        mode_form = QFormLayout(mode_group)
        self._configure_form(mode_form)
        self._add_input_row(
            mode_form,
            "mode",
            "계산 방식 · mode [선택]",
            self.mode,
            "Workbook은 V, d, L, α의 직접 입력 관계를 계산합니다. "
            "Canonical은 렌즈와 독립 α, β로 기울어진 결상을 비교합니다.",
        )
        layout.addWidget(mode_group)
        layout.addWidget(self.mode_help)

        self.profile_group = QGroupBox("정적 센서 규격")
        self.profile_group.setObjectName("staticSensorGroup")
        profile_form = QFormLayout(self.profile_group)
        self._configure_form(profile_form)
        self.profile_notice = QLabel("정적 프로파일만 사용 · 장치 연결 없음")
        self.profile_notice.setObjectName("staticSensorNotice")
        self.profile_notice.setWordWrap(True)
        self.profile_notice.setAccessibleName("정적 센서 규격은 실제 장치에 연결하지 않음")
        profile_form.addRow(self.profile_notice)
        self._add_input_row(
            profile_form,
            "camera",
            "정적 센서 · camera [px/µm]",
            self.camera,
            "해상도, 픽셀 피치와 활성 크기를 제공하는 정적 규격 프리셋입니다. "
            "모델명은 식별자일 뿐 실제 카메라를 검색하거나 연결하지 않습니다.",
        )
        self._add_input_row(
            profile_form,
            "sensor_axis",
            "삼각측량 축 · axis [width/height]",
            self.sensor_axis,
            "기울어진 센서에서 레이저 거리 변화가 투영되는 축입니다. "
            "선택 방향에 따라 FOV와 거리 감도 계산이 달라집니다.",
        )
        layout.addWidget(self.profile_group)

        self.parameter_group = QGroupBox("워크북 직접 입력")
        form = QFormLayout(self.parameter_group)
        self._configure_form(form)
        self.form = form
        self._add_input_row(
            form,
            "lens",
            "Edmund M12 렌즈 · f [mm]",
            self.lens,
            "Canonical 계산에 사용할 정적 렌즈 규격입니다. "
            "목록에는 SKU와 유효 초점거리 f가 표시됩니다.",
        )
        self._add_input_row(
            form,
            "v_mm",
            "워크북 기준 높이/거리 · V [mm]",
            self.v_mm,
            "워크북 기준 높이/거리 V입니다. 원본 관계식에서 b, lo와 R을 유도합니다.",
        )
        self._add_input_row(
            form,
            "d_mm",
            "워크북 WD 파라미터 · d [mm]",
            self.d_mm,
            "워크북 WD 파라미터 d입니다. R = V − d 계산에 사용하며, "
            "원본 식에는 d와 광학점 좌표를 잇는 추가 관계가 없습니다.",
        )
        self._add_input_row(
            form,
            "sensor_length_mm",
            "센서/이미지 길이 · L [mm]",
            self.sensor_length_container,
            "Workbook 계산에 직접 사용하는 유효 이미지 길이 L입니다. "
            "정적 센서 규격값은 오른쪽 버튼으로 명시적으로 복사할 수 있습니다.",
        )
        self.sensor_length_mm.setToolTip(
            "Workbook 계산에 직접 사용하는 유효 이미지 길이 L [mm]입니다."
        )
        self.sensor_length_mm.setAccessibleDescription(self.sensor_length_mm.toolTip())
        self.sensor_length_mm.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            self.sensor_length_mm.sizePolicy().verticalPolicy(),
        )
        self.sensor_length_container.setMinimumWidth(170)
        self._add_input_row(
            form,
            "alpha_deg",
            "수광각 · α [°]",
            self.alpha_deg,
            "레이저축과 카메라 수광 광축 사이의 각도 α입니다.",
        )
        self._add_input_row(
            form,
            "range_mm",
            "측정 범위 · S [mm]",
            self.range_mm,
            "Canonical 모드에서 기준 대상면을 중심으로 계산할 전체 깊이 범위 S입니다.",
        )
        self._add_input_row(
            form,
            "beta_deg",
            "센서 틸트각 · β [°]",
            self.beta_deg,
            "Canonical 모드에서 이미지/센서 평면에 적용하는 Scheimpflug 틸트각 β입니다.",
        )
        self._add_input_row(
            form,
            "max_width_mm",
            "기구 최대 폭 · W_max [mm]",
            self.max_width_mm,
            "Canonical 구조가 넘지 않아야 하는 수평 기구 외곽의 상한입니다.",
        )
        self._add_input_row(
            form,
            "max_rear_mm",
            "후방 허용 한계 · R_max [mm]",
            self.max_rear_mm,
            "Canonical 구조에서 기준 위치 뒤쪽으로 허용하는 기구 외곽의 상한입니다.",
        )
        self._add_input_row(
            form,
            "wavelength_nm",
            "레이저 파장 · λ [nm]",
            self.wavelength_nm,
            "선택 렌즈의 확인된 코팅 파장 범위와 호환성을 검사하는 설계 파장입니다.",
        )
        layout.addWidget(self.parameter_group)

        self.formula_card = QGroupBox("현재 모드 핵심 수식")
        self.formula_card.setObjectName("formulaCard")
        self._set_compact_font(self.formula_card, 8.8, bold=True)
        self.formula_card.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Maximum,
        )
        self.formula_card.setStyleSheet(
            """
            QGroupBox#formulaCard {
                background: #f8fbfe;
                border-color: #b9c9d8;
                padding: 6px 4px 4px 4px;
            }
            QLabel[formulaRole="modeSummary"] {
                background: #e7f1fc;
                border: 1px solid #a8c7e3;
                border-radius: 7px;
                color: #174a75;
                padding: 2px 6px;
            }
            QLabel[formulaRole="equationTag"] {
                background: #eaf0f5;
                border-radius: 4px;
                color: #3e5569;
                font-weight: 700;
                padding: 2px 4px;
            }
            QLabel[formulaRole="equation"] {
                color: #142f49;
            }
            QLabel[formulaRole="variableHint"] {
                color: #526577;
            }
            QFrame#formulaDivider {
                color: #cfdae4;
            }
            """
        )
        formula_layout = QVBoxLayout(self.formula_card)
        formula_layout.setContentsMargins(4, 5, 4, 4)
        formula_layout.setSpacing(3)
        formula_header = QHBoxLayout()
        formula_header.setContentsMargins(0, 0, 0, 0)
        formula_header.setSpacing(0)
        self.formula_mode_summary = QLabel()
        self.formula_mode_summary.setObjectName("formulaModeSummary")
        self.formula_mode_summary.setProperty("formulaRole", "modeSummary")
        self.formula_mode_summary.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self.formula_mode_summary.setWordWrap(False)
        self.formula_mode_summary.setSizePolicy(
            QSizePolicy.Policy.Maximum,
            QSizePolicy.Policy.Preferred,
        )
        self._set_compact_font(self.formula_mode_summary, 8.8)
        formula_header.addWidget(self.formula_mode_summary)
        formula_header.addStretch(1)
        formula_layout.addLayout(formula_header)

        equation_grid = QGridLayout()
        equation_grid.setContentsMargins(0, 0, 0, 0)
        equation_grid.setHorizontalSpacing(4)
        equation_grid.setVerticalSpacing(1)
        equation_grid.setColumnStretch(1, 1)
        self.formula_equation_rows: list[tuple[QLabel, QLabel]] = []
        for row in range(6):
            category = QLabel()
            category.setProperty("formulaRole", "equationTag")
            category.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
            category.setMinimumWidth(40)
            self._set_compact_font(category, 8.5, bold=True)
            equation = QLabel()
            equation.setProperty("formulaRole", "equation")
            equation.setWordWrap(True)
            equation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            equation.setToolTip("수식을 드래그해 복사할 수 있습니다.")
            equation.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            self._set_compact_font(equation, 9.5, monospace=True)
            equation_grid.addWidget(category, row, 0)
            equation_grid.addWidget(equation, row, 1)
            self.formula_equation_rows.append((category, equation))
        formula_layout.addLayout(equation_grid)

        divider = QFrame()
        divider.setObjectName("formulaDivider")
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFrameShadow(QFrame.Shadow.Plain)
        formula_layout.addWidget(divider)
        self.formula_variables = QLabel()
        self.formula_variables.setObjectName("formulaVariables")
        self.formula_variables.setProperty("formulaRole", "variableHint")
        self.formula_variables.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.formula_variables.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        self._set_compact_font(self.formula_variables, 8.5)
        formula_layout.addWidget(self.formula_variables)
        self.formula_mode_summary.setAccessibleName("현재 계산 모드 입력 요약")
        self.formula_variables.setAccessibleName("현재 모드 변수 설명, 마우스를 올려 상세 확인")
        self.formula_card.setAccessibleName("현재 계산 모드의 표시용 핵심 수식")
        layout.addWidget(self.formula_card)
        layout.addStretch(1)

        accessible_names = (
            (self.mode, "계산 모드"),
            (self.camera, "정적 센서 규격 프로파일"),
            (self.lens, "Edmund M12 렌즈 규격"),
            (self.sensor_axis, "센서 계산 축"),
            (self.v_mm, "워크북 기준 높이 또는 거리 V 밀리미터"),
            (self.d_mm, "워크북 WD 파라미터 d 밀리미터"),
            (self.sensor_length_mm, "센서 이미지 길이 L 밀리미터"),
            (self.alpha_deg, "수광각 알파 도"),
            (self.range_mm, "측정 범위 S 밀리미터"),
            (self.beta_deg, "센서 틸트 베타 도"),
            (self.max_width_mm, "최대 폭 W 밀리미터"),
            (self.max_rear_mm, "최대 후방 R 밀리미터"),
            (self.wavelength_nm, "레이저 파장 나노미터"),
        )
        for widget, name in accessible_names:
            widget.setAccessibleName(name)
        self.load_sensor_length_button.setAccessibleName("선택한 정적 센서 길이를 L 입력에 적용")
        self._load_catalogs()

        for widget in (
            self.mode,
            self.camera,
            self.lens,
            self.sensor_axis,
        ):
            widget.currentIndexChanged.connect(self.changed)
        for widget in (
            self.d_mm,
            self.range_mm,
            self.v_mm,
            self.sensor_length_mm,
            self.alpha_deg,
            self.beta_deg,
            self.max_width_mm,
            self.max_rear_mm,
            self.wavelength_nm,
        ):
            widget.valueChanged.connect(self.changed)
        self.mode.currentIndexChanged.connect(self._update_mode_visibility)
        self.load_sensor_length_button.clicked.connect(self.load_selected_camera_sensor_length)
        self._update_mode_visibility()

    @staticmethod
    def _configure_form(form: QFormLayout) -> None:
        form.setContentsMargins(8, 8, 8, 8)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

    def _add_input_row(
        self,
        form: QFormLayout,
        key: str,
        label_text: str,
        field: QWidget,
        help_text: str,
    ) -> None:
        """Add one compact, self-explanatory row without affecting calculations."""

        label = QLabel(label_text)
        label.setObjectName(f"{key}InputLabel")
        label.setWordWrap(True)
        label.setToolTip(help_text)
        label.setAccessibleName(label_text)
        label.setAccessibleDescription(help_text)
        field.setToolTip(help_text)
        field.setAccessibleDescription(help_text)
        # A modest explicit minimum makes QFormLayout wrap the field below a
        # long label instead of squeezing the editor into an unusable sliver.
        # Ignored keeps intrinsic combo/spin size hints from forcing a
        # horizontal scrollbar in the 315 px input pane.
        field.setMinimumWidth(132)
        field.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            field.sizePolicy().verticalPolicy(),
        )
        self.input_labels[key] = label
        if isinstance(field, QComboBox):
            # Model and mode identifiers are more important than saving one
            # row. Give them the full pane width instead of silently eliding
            # the selected Basler/lens name beside a long bilingual label.
            form.addRow(label)
            form.addRow(field)
        else:
            form.addRow(label, field)

    @staticmethod
    def _set_compact_font(
        widget: QWidget,
        point_size: float,
        *,
        bold: bool = False,
        monospace: bool = False,
    ) -> None:
        """Apply a restrained base size that still follows global font scaling."""

        font = widget.font()
        if monospace:
            font.setFamilies(["Cascadia Mono", "Consolas", "Malgun Gothic"])
        font.setPointSizeF(point_size)
        font.setBold(bold)
        widget.setFont(font)

    def _set_formula_content(
        self,
        *,
        mode_title: str,
        mode_summary: str,
        equations: tuple[tuple[str, str], ...],
        variables: tuple[tuple[str, str, str], ...],
    ) -> None:
        """Update reusable formula rows without rebuilding the card."""

        self.formula_card.setTitle(f"{mode_title} · 핵심 수식")
        self.formula_mode_summary.setText(mode_summary)
        for row, content in zip(self.formula_equation_rows, equations, strict=False):
            category, equation = row
            category_text, equation_text = content
            category.setText(category_text)
            equation.setText(equation_text)
            equation.setAccessibleName(f"{category_text} 관계식: {equation_text}")
            equation.setToolTip(f"{category_text} 관계식\n{equation_text}")
            category.show()
            equation.show()
        for category, equation in self.formula_equation_rows[len(equations) :]:
            category.hide()
            equation.hide()
        symbols = " · ".join(symbol for symbol, _name, _unit in variables)
        variable_details = "\n".join(
            f"{symbol} — {name} [{unit}]" for symbol, name, unit in variables
        )
        self.formula_variables.setText(f"변수 · {symbols}  ⓘ")
        self.formula_variables.setToolTip(variable_details)
        self.formula_variables.setAccessibleDescription(variable_details)

    @staticmethod
    def _spin(
        minimum: float,
        maximum: float,
        value: float,
        suffix: str,
        *,
        decimals: int = 3,
    ) -> QDoubleSpinBox:
        widget = QDoubleSpinBox()
        widget.setRange(minimum, maximum)
        widget.setDecimals(decimals)
        widget.setValue(value)
        widget.setSuffix(suffix)
        widget.setKeyboardTracking(False)
        return widget

    def _load_catalogs(self) -> None:
        self.camera.clear()
        for camera in self._facade.cameras():
            self.camera.addItem(
                f"{camera.manufacturer} {camera.model} "
                f"({camera.sensor.width_px}×{camera.sensor.height_px})",
                camera.id,
            )
        if not self.camera.count():
            self.camera.addItem("센서 규격 카탈로그 로드 실패", "")
            self.camera.setEnabled(False)

        self.lens.clear()
        for lens in self._facade.lenses():
            self.lens.addItem(
                f"#{lens.sku} · {lens.focal_length_mm:g} mm · {lens.name}",
                lens.id,
            )
        if not self.lens.count():
            self.lens.addItem("렌즈 카탈로그 로드 실패", "")
            self.lens.setEnabled(False)

    def _update_mode_visibility(self) -> None:
        workbook = self.mode.currentData() == "workbook"
        self.parameter_group.setTitle(
            "워크북 직접 입력" if workbook else "Canonical 비교 입력 및 제약"
        )
        # Combo boxes occupy a separate full-width row below their labels.
        # Toggle the lens label explicitly so workbook mode never leaves an
        # orphaned label behind when the lens selector itself is hidden.
        self.form.setRowVisible(self.input_labels["lens"], not workbook)
        for widget in (self.v_mm, self.sensor_length_container):
            self.form.setRowVisible(widget, workbook)
        for widget in (
            self.lens,
            self.range_mm,
            self.beta_deg,
            self.max_width_mm,
            self.max_rear_mm,
            self.wavelength_nm,
        ):
            self.form.setRowVisible(widget, not workbook)
        self.lens.setEnabled(not workbook and bool(self.lens.currentData()))
        if workbook:
            self.mode_help.setText(
                "V · d · L · α를 입력하세요. 결과와 2D 구조는 자동 갱신됩니다. "
                "센서 치수가 필요하면 ‘L에 적용’을 누르세요. "
                "센서 프로파일은 정적이며 실제 장치를 연결하지 않습니다."
            )
            self._set_formula_content(
                mode_title="워크북 호환",
                mode_summary="V · d · L · α 직접 입력",
                equations=(
                    ("각도", "β = 90° − α"),
                    ("베이스", "b = V tan α · x = L/2"),
                    ("외곽", "W = b + x · R = V − d"),
                    ("결상", "lo = V cos α · fp = b cos β"),
                    ("교차", "s = x lo sin β / [fp sin α − x sin(α + β)]"),
                    ("렌즈", "1/f = 1/lo + 1/fp"),
                ),
                variables=(
                    ("V", "워크북 기준 높이/거리", "mm"),
                    ("d", "워크북 WD 파라미터", "mm"),
                    ("L", "이미지 길이", "mm"),
                    ("α", "수광각", "°"),
                    ("β", "유도 결상각", "°"),
                    (
                        "s",
                        "센서 가장자리 광선의 레이저축 교차값; 화면에는 거리 |s| 표시",
                        "mm",
                    ),
                ),
            )
        else:
            self.mode_help.setText(
                "렌즈와 α · β · S를 선택하세요. 호환성과 기구 제약을 확인한 뒤 "
                "필요하면 최적화를 실행하세요."
            )
            self._set_formula_content(
                mode_title="Canonical 설계",
                mode_summary="f · α · β · S 입력",
                equations=(
                    ("비율", "r = tan β / tan α"),
                    ("거리", "lo = f(1 + r) · fp = f(1 + 1/r)"),
                    ("투영", "x(s) = s fp sin α / [lo sin β + s sin(α + β)]"),
                    ("센서", "L_required = |x(+S/2) − x(−S/2)|"),
                ),
                variables=(
                    ("d", "기준 WD", "mm"),
                    ("S", "측정 범위", "mm"),
                    ("f", "렌즈 초점거리", "mm"),
                    ("α", "수광각", "°"),
                    ("β", "센서 틸트각", "°"),
                    ("s", "기준면 대비 깊이", "mm"),
                ),
            )

    @Slot()
    def load_selected_camera_sensor_length(self) -> None:
        try:
            length = self._facade.camera_sensor_length_mm(
                self.camera.currentData(),
                self.sensor_axis.currentData(),
            )
        except Exception:
            return
        self.sensor_length_mm.setValue(length)

    def values(self) -> dict[str, Any]:
        return {
            "mode": self.mode.currentData(),
            "camera_id": self.camera.currentData(),
            "lens_id": self.lens.currentData(),
            "sensor_axis": self.sensor_axis.currentData(),
            "d_mm": self.d_mm.value(),
            "range_mm": self.range_mm.value(),
            "v_mm": self.v_mm.value(),
            "sensor_length_mm": self.sensor_length_mm.value(),
            "alpha_deg": self.alpha_deg.value(),
            "beta_deg": self.beta_deg.value(),
            "max_width_mm": self.max_width_mm.value(),
            "max_rear_mm": self.max_rear_mm.value(),
            "wavelength_nm": self.wavelength_nm.value(),
        }

    def apply_values(self, values: Mapping[str, Any]) -> None:
        blockers = [
            self.mode,
            self.camera,
            self.lens,
            self.sensor_axis,
            self.d_mm,
            self.range_mm,
            self.v_mm,
            self.sensor_length_mm,
            self.alpha_deg,
            self.beta_deg,
            self.max_width_mm,
            self.max_rear_mm,
            self.wavelength_nm,
        ]
        for widget in blockers:
            widget.blockSignals(True)
        try:
            for combo, key in (
                (self.mode, "mode"),
                (self.camera, "camera_id"),
                (self.lens, "lens_id"),
                (self.sensor_axis, "sensor_axis"),
            ):
                if key in values:
                    index = combo.findData(values[key])
                    if index >= 0:
                        combo.setCurrentIndex(index)
            for spin, key in (
                (self.d_mm, "d_mm"),
                (self.range_mm, "range_mm"),
                (self.v_mm, "v_mm"),
                (self.sensor_length_mm, "sensor_length_mm"),
                (self.alpha_deg, "alpha_deg"),
                (self.beta_deg, "beta_deg"),
                (self.max_width_mm, "max_width_mm"),
                (self.max_rear_mm, "max_rear_mm"),
                (self.wavelength_nm, "wavelength_nm"),
            ):
                if key in values:
                    spin.setValue(float(values[key]))
        finally:
            for widget in blockers:
                widget.blockSignals(False)
        self._update_mode_visibility()
        self.changed.emit()


class ResultPanel(QWidget):
    """Calculated values, constraints, compatibility, and optimization controls."""

    optimize_requested = Signal(str)
    cancel_requested = Signal()
    candidate_selected = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(7)
        title = QLabel("계산 결과")
        title.setObjectName("panelTitle")
        layout.addWidget(title)
        self.summary = QLabel("입력을 계산하는 중…")
        self.summary.setObjectName("solutionSummary")
        self.summary.setProperty("state", "warning")
        self.summary.setWordWrap(True)
        self.summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.summary.setAccessibleName("계산 유효성 요약")
        layout.addWidget(self.summary)

        values_group = QGroupBox("수치 결과")
        values_layout = QVBoxLayout(values_group)
        values_layout.setContentsMargins(5, 8, 5, 5)
        self.values = QTreeWidget()
        self.values.setHeaderLabels(["항목", "값"])
        self.values.setRootIsDecorated(False)
        self.values.setAlternatingRowColors(True)
        self.values.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.values.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.values.setAccessibleName("Scheimpflug 계산 수치 표")
        self.values.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.values.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.values.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.values.header().setStretchLastSection(False)
        self.values.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.values.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        values_layout.addWidget(self.values)
        layout.addWidget(values_group, 2)

        self.messages_group = QGroupBox("정적 규격 비교 및 제약")
        # The group chrome consumes roughly 60 px with the supported Fusion
        # style. Keep enough viewport height for one wrapped warning even
        # before the first deferred layout/typography pass.
        self.messages_group.setMinimumHeight(130)
        messages_layout = QVBoxLayout(self.messages_group)
        messages_layout.setContentsMargins(5, 8, 5, 5)
        self.messages = QListWidget()
        self.messages.setAlternatingRowColors(True)
        self.messages.setWordWrap(True)
        self.messages.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.messages.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        self.messages.setAccessibleName("설계 경고와 제약 조건")
        messages_layout.addWidget(self.messages)
        layout.addWidget(self.messages_group, 1)

        self.optimization_group = QGroupBox("고급/연구 참고 · 구조 최적화")
        optimization_layout = QVBoxLayout(self.optimization_group)
        optimization_layout.setContentsMargins(5, 8, 5, 5)
        row = QHBoxLayout()
        self.algorithm = QComboBox()
        self.algorithm.addItem("SciPy Differential Evolution", "scipy")
        self.algorithm.addItem("재현형 M-PSO", "mpso")
        self.optimize_button = QPushButton("최적화 실행")
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setEnabled(False)
        row.addWidget(self.algorithm)
        row.addWidget(self.optimize_button)
        row.addWidget(self.cancel_button)
        optimization_layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        optimization_layout.addWidget(self.progress)
        self.optimization_results = QListWidget()
        self.optimization_results.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Ignored,
        )
        optimization_layout.addWidget(self.optimization_results)
        layout.addWidget(self.optimization_group, 1)
        self.optimization_group.setVisible(False)

        self.optimize_button.clicked.connect(
            lambda: self.optimize_requested.emit(self.algorithm.currentData())
        )
        self.cancel_button.clicked.connect(self.cancel_requested)
        self.optimization_results.itemDoubleClicked.connect(self._select_candidate)

    def _set_summary(self, text: str, state: str) -> None:
        self.summary.setText(text)
        self.summary.setProperty("state", state)
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)

    def _resize_message_rows(self) -> None:
        """Wrap complete warning text to the current result-pane width."""

        scroll_extent = self.messages.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent,
            None,
            self.messages,
        )
        width = max(1, self.messages.viewport().width() - scroll_extent - 12)
        metrics = QFontMetrics(self.messages.font())
        flags = int(Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignLeft)
        tallest_row = 0
        for index in range(self.messages.count()):
            item = self.messages.item(index)
            raw_text = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(raw_text, str):
                raw_text = item.text()
                item.setData(Qt.ItemDataRole.UserRole, raw_text)
                item.setToolTip(raw_text)
            wrapped_text = self._wrap_message_text(raw_text, width, metrics)
            item.setText(wrapped_text)
            bounds = metrics.boundingRect(
                QRect(0, 0, width, 10_000),
                flags,
                wrapped_text,
            )
            row_height = max(28, bounds.height() + 10)
            item.setSizeHint(QSize(width, row_height))
            tallest_row = max(tallest_row, row_height)

        group_chrome = max(
            0,
            self.messages_group.height() - self.messages.viewport().height(),
        )
        required_group_height = max(130, tallest_row + group_chrome + 4)
        if self.messages_group.minimumHeight() != required_group_height:
            self.messages_group.setMinimumHeight(required_group_height)

    @staticmethod
    def _wrap_message_text(text: str, width: int, metrics: QFontMetrics) -> str:
        """Insert stable line breaks for delegates that otherwise elide list text."""

        lines: list[str] = []
        for paragraph in text.splitlines() or [""]:
            current = ""
            for character in paragraph:
                candidate = current + character
                if not current or metrics.horizontalAdvance(candidate) <= width:
                    current = candidate
                    continue
                space = current.rfind(" ")
                if space > 0:
                    lines.append(current[:space].rstrip())
                    current = current[space + 1 :] + character
                else:
                    lines.append(current.rstrip())
                    current = character.lstrip()
            lines.append(current.rstrip())
        return "\n".join(lines)

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._resize_message_rows()

    def display_solution(self, solution: Any, compatibility: Any | None) -> None:
        self.values.clear()
        status = "유효" if solution.valid else "사용 불가"
        workbook = solution.mode.value == "workbook"
        self.optimization_group.setVisible(not workbook)
        if workbook:
            summary_text = f"{status} · 워크북 호환 계산"
            rows = (
                ("워크북 기준 거리 V", solution.request.v_mm, "mm"),
                ("워크북 WD d", solution.request.d_mm, "mm"),
                ("센서/이미지 길이 L", solution.request.sensor_length_mm, "mm"),
                ("수광각 α", solution.alpha_deg, "°"),
                ("유도 결상각 β", solution.beta_deg, "°"),
                ("베이스라인 b", solution.baseline_mm, "mm"),
                ("반 센서 x=L/2", solution.x_far_mm, "mm"),
                ("워크북식 W=b+L/2", solution.width_exact_mm, "mm"),
                ("워크북식 R=V−d", solution.rear_exact_mm, "mm"),
                ("이미지 거리 fp", solution.fp_mm, "mm"),
                ("물체 거리 lo", solution.lo_mm, "mm"),
                (
                    "광선 교차 거리 |s|",
                    (
                        abs(solution.ray_intercept_s_mm)
                        if solution.ray_intercept_s_mm is not None
                        else None
                    ),
                    "mm",
                ),
                ("유도 초점거리 f", solution.focal_length_mm, "mm"),
                ("총 광로 lo+fp", solution.total_optical_length_mm, "mm"),
            )
        else:
            summary_text = f"{status} · Canonical 고급 계산"
            rows = (
                ("초점거리 f", solution.focal_length_mm, "mm"),
                ("수광각 α", solution.alpha_deg, "°"),
                ("센서 틸트 β", solution.beta_deg, "°"),
                ("물체 거리 lo", solution.lo_mm, "mm"),
                ("이미지 거리 fp", solution.fp_mm, "mm"),
                ("필요 센서 길이", solution.required_sensor_length_mm, "mm"),
                ("사용 가능 센서", solution.sensor_length_available_mm, "mm"),
                ("정확 외곽 W", solution.width_exact_mm, "mm"),
                ("정확 외곽 R", solution.rear_exact_mm, "mm"),
                ("근거리 결상 x", solution.x_near_mm, "mm"),
                ("원거리 결상 x", solution.x_far_mm, "mm"),
                ("거리/센서", solution.distance_per_sensor_mm, "mm/mm"),
                ("요청 범위 최악 민감도", solution.distance_per_pixel_mm, "mm/px"),
            )
        metrics = solution.sensor_metrics
        if metrics is not None:
            rows += (
                ("센서 가로 FOV", metrics.horizontal_fov_mm, "mm"),
                ("센서 세로 FOV", metrics.vertical_fov_mm, "mm"),
                (
                    "가로 샘플링",
                    (
                        metrics.horizontal_sampling_mm_per_px * 1000.0
                        if metrics.horizontal_sampling_mm_per_px is not None
                        else None
                    ),
                    "µm/px",
                ),
                (
                    "세로 샘플링",
                    (
                        metrics.vertical_sampling_mm_per_px * 1000.0
                        if metrics.vertical_sampling_mm_per_px is not None
                        else None
                    ),
                    "µm/px",
                ),
                (
                    "중앙 거리 민감도",
                    metrics.range_sensitivity_center_mm_per_px,
                    "mm/px",
                ),
                (
                    "최악 거리 민감도",
                    metrics.range_sensitivity_worst_mm_per_px,
                    "mm/px",
                ),
            )
        for name, value, unit in rows:
            if value is None or not math.isfinite(float(value)):
                text = "—"
            else:
                text = f"{float(value):.6g} {unit}"
            item = QTreeWidgetItem([name, text])
            item.setToolTip(0, name)
            item.setToolTip(1, text)
            if "FOV" in name:
                help_text = (
                    "센서 전체 유효 영역이 물체 공간에서 덮는 범위입니다. "
                    "선택한 삼각측량 축은 비선형 Scheimpflug 역투영을 사용합니다."
                )
                item.setToolTip(0, help_text)
                item.setToolTip(1, help_text)
            elif "샘플링" in name:
                help_text = "계산 FOV를 해당 축의 네이티브 픽셀 수로 나눈 평균 물체측 간격입니다."
                item.setToolTip(0, help_text)
                item.setToolTip(1, help_text)
            elif "거리 민감도" in name:
                help_text = (
                    "센서 1픽셀 이동에 대응하는 기하학적 거리 변화량입니다. "
                    "작을수록 더 미세하며, 양자효율이나 저조도 감도를 뜻하지 않습니다."
                )
                item.setToolTip(0, help_text)
                item.setToolTip(1, help_text)
            self.values.addTopLevelItem(item)

        self.messages.clear()
        for warning in solution.warnings:
            self.messages.addItem(f"⚠ {warning}")
        for violation in solution.violations:
            self.messages.addItem(f"✕ {violation.message}")
        if compatibility is not None:
            for check in compatibility.checks:
                marker = {
                    "pass": "✓",
                    "warning": "⚠",
                    "fail": "✕",
                    "unknown": "?",
                }.get(check.status.value, "•")
                self.messages.addItem(f"{marker} {check.label}: {check.message}")
        if not self.messages.count():
            self.messages.addItem("✓ 경고 및 제약 위반 없음")
        self._resize_message_rows()
        has_messages = bool(solution.warnings or solution.violations)
        if compatibility is not None:
            has_messages = has_messages or any(
                check.status.value != "pass" for check in compatibility.checks
            )
        self._set_summary(
            summary_text,
            "valid" if solution.valid and not has_messages else "warning",
        )

    def display_error(self, message: str) -> None:
        self._set_summary("계산 실패 · 입력값을 확인하세요", "error")
        self.values.clear()
        self.messages.clear()
        self.messages.addItem(f"✕ {message}")
        self._resize_message_rows()

    def set_optimizing(self, active: bool) -> None:
        self.optimize_button.setEnabled(not active)
        self.cancel_button.setEnabled(active)
        if active:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.optimization_results.clear()
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(100)

    @Slot(float, str)
    def update_optimization_progress(self, fraction: float, message: str) -> None:
        self.progress.setValue(round(max(0.0, min(1.0, fraction)) * 100.0))
        self._set_summary(message, "warning")

    def display_optimization(self, result: Any) -> None:
        self.set_optimizing(False)
        self.optimization_results.clear()
        if result.cancelled:
            self.optimization_results.addItem("사용자 취소")
            return
        if not result.candidates:
            self.optimization_results.addItem("유효 후보 없음")
            for violation in result.infeasible_reasons:
                self.optimization_results.addItem(f"· {violation.message}")
            return
        for rank, candidate in enumerate(result.candidates, start=1):
            from PySide6.QtWidgets import QListWidgetItem

            row = QListWidgetItem(
                f"{rank}. {candidate.lens_id} · "
                f"α {candidate.solution.alpha_deg:.3f}° · "
                f"β {candidate.solution.beta_deg:.3f}° · "
                f"{candidate.objective_mm_per_pixel:.6g} mm/px"
            )
            row.setData(Qt.ItemDataRole.UserRole, candidate)
            self.optimization_results.addItem(row)

    def _select_candidate(self, item) -> None:
        candidate = item.data(Qt.ItemDataRole.UserRole)
        if candidate is not None:
            self.candidate_selected.emit(candidate)


class _OptimizationWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(float, str)

    def __init__(self, request: Any, cancelled: threading.Event) -> None:
        super().__init__()
        self.request = request
        self.cancelled = cancelled

    @Slot()
    def run(self) -> None:
        try:
            from scheimpflug_optimeter.optimization import optimize_design

            result = optimize_design(
                self.request,
                progress=lambda fraction, message: self.progress.emit(
                    fraction,
                    message,
                ),
                cancelled=self.cancelled.is_set,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class DesignWidget(QWidget):
    """Three-part live design workspace."""

    solution_changed = Signal(object, object)

    def __init__(self, facade: OpticalCoreFacade | None = None, parent=None) -> None:
        super().__init__(parent)
        self.facade = facade or OpticalCoreFacade()
        self.solution: Any | None = None
        self.snapshot: SceneSnapshot | None = None
        self.selected_optimization: dict[str, Any] | None = None
        self._optimization_thread: QThread | None = None
        self._optimization_worker: _OptimizationWorker | None = None
        self._optimization_cancel = threading.Event()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        scene_toolbar = QFrame()
        scene_toolbar.setObjectName("sceneToolbar")
        toolbar = QHBoxLayout(scene_toolbar)
        toolbar.setContentsMargins(10, 6, 10, 6)
        toolbar.setSpacing(7)
        workspace_title = QLabel("2D 광학 장면")
        workspace_title.setObjectName("workspaceTitle")
        toolbar.addWidget(workspace_title)
        toolbar.addSpacing(6)
        self.scene_key = QLabel(
            "<span style='color:#ff3b30'>●</span> 레이저&nbsp;&nbsp;"
            "<span style='color:#65b7ff'>━</span> 렌즈&nbsp;&nbsp;"
            "<span style='color:#ffd166'>━</span> 센서&nbsp;&nbsp;"
            "<span style='color:#be95ff'>━</span> 결상광선&nbsp;&nbsp;"
            "<span style='color:#48d7c8'>↔</span> 치수"
        )
        self.scene_key.setObjectName("sceneKey")
        self.scene_key.setTextFormat(Qt.TextFormat.RichText)
        self.scene_key.setAccessibleName("2D 장면 색상 키")
        self.scene_key.setAccessibleDescription(
            "레이저, 렌즈, 센서, 결상광선과 계산 치수를 색상으로 구분합니다."
        )
        self.scene_key.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        scene_key_font = self.scene_key.font()
        scene_key_font.setPointSizeF(9.2)
        self.scene_key.setFont(scene_key_font)
        toolbar.addWidget(self.scene_key, 1)
        self.fit_button = QPushButton("작업영역 맞춤")
        self.fit_button.setProperty("role", "primary")
        self.head_zoom_button = QPushButton("광학부 확대")
        self.export_png_button = QPushButton("PNG 저장")
        self.export_svg_button = QPushButton("SVG 저장")
        self.performance = QLabel("대기")
        self.performance.setObjectName("performanceBadge")
        self.performance.setProperty("state", "idle")
        self.performance.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.performance.setToolTip("입력 변경부터 계산·2D 장면 갱신까지 걸린 시간입니다.")
        self.performance.setAccessibleName("실시간 갱신 성능")
        self.fit_button.setToolTip("레이저·워킹 디스턴스·광학부를 동일 축척으로 화면에 맞춥니다.")
        self.head_zoom_button.setToolTip("렌즈와 센서 주변 광학부를 확대합니다.")
        self.export_png_button.setToolTip("현재 계산 스냅샷과 2D 장면을 PNG로 저장합니다.")
        self.export_svg_button.setToolTip("현재 계산 스냅샷과 2D 장면을 SVG로 저장합니다.")
        toolbar.addWidget(self.fit_button)
        toolbar.addWidget(self.head_zoom_button)
        toolbar.addWidget(self.export_png_button)
        toolbar.addWidget(self.export_svg_button)
        toolbar.addWidget(self.performance)
        layout.addWidget(scene_toolbar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setObjectName("designSplitter")
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(8)
        self.splitter.setOpaqueResize(True)
        self.input_panel = DesignInputPanel(self.facade)
        self.scene = OpticsGraphicsScene(self)
        self.view = OpticsGraphicsView(self.scene)
        self.view.setMinimumWidth(400)
        self.view.setAccessibleName("실시간 Scheimpflug 2D 광학 장면")
        self.result_panel = ResultPanel()
        self.input_scroll = self._scroll(self.input_panel, minimum_width=315)
        self.result_scroll = self._scroll(self.result_panel, minimum_width=335)
        self.splitter.addWidget(self.input_scroll)
        self.splitter.addWidget(self.view)
        self.splitter.addWidget(self.result_scroll)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)
        # At 1280 px the result pane needs this width to show both the longest
        # workbook label and the six-significant-digit sensitivity value
        # without hiding a column behind the disabled horizontal scrollbar.
        self.splitter.setSizes([315, 820, 500])
        layout.addWidget(self.splitter, 1)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(16)
        self._debounce.timeout.connect(self.recalculate)
        self._initial_calculation = QTimer(self)
        self._initial_calculation.setSingleShot(True)
        self._initial_calculation.timeout.connect(self.recalculate)
        self.input_panel.changed.connect(self.schedule_recalculation)
        self.fit_button.clicked.connect(self.view.fit_scene)
        self.head_zoom_button.clicked.connect(self.view.fit_optical_head)
        self.result_panel.optimize_requested.connect(self.start_optimization)
        self.result_panel.cancel_requested.connect(self.cancel_optimization)
        self.result_panel.candidate_selected.connect(self.apply_candidate)
        self._initial_calculation.start(0)

    @staticmethod
    def _scroll(widget: QWidget, *, minimum_width: int) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(widget)
        area.setMinimumWidth(minimum_width)
        return area

    def _set_performance(self, text: str, state: str) -> None:
        self.performance.setText(text)
        self.performance.setProperty("state", state)
        self.performance.style().unpolish(self.performance)
        self.performance.style().polish(self.performance)

    def schedule_recalculation(self) -> None:
        self._debounce.start()

    @Slot()
    def recalculate(self) -> None:
        from time import perf_counter

        started = perf_counter()
        try:
            solution, _lens, snapshot = self.facade.solve(self.input_panel.values())
            compatibility = None
            if self.input_panel.values()["mode"] == "canonical":
                compatibility = self.facade.compatibility(
                    self.input_panel.values()["camera_id"],
                    self.input_panel.values()["lens_id"],
                    solution,
                )
        except Exception as exc:
            self.solution = None
            self.snapshot = None
            message = str(exc)
            self.scene.set_invalid_message(message)
            self.result_panel.display_error(message)
            self._set_performance(
                f"계산 오류 · {(perf_counter() - started) * 1000.0:.1f} ms",
                "error",
            )
            self.solution_changed.emit(None, None)
            return

        self.solution = solution
        self.snapshot = snapshot
        self.scene.set_snapshot(snapshot)
        if self.view.transform().isIdentity():
            self.view.fit_scene()
        self.result_panel.display_solution(solution, compatibility)
        elapsed_ms = (perf_counter() - started) * 1000.0
        self._set_performance(
            f"갱신 {elapsed_ms:.1f} ms",
            "valid" if elapsed_ms <= 100.0 else "warning",
        )
        self.performance.setToolTip(
            f"입력 변경부터 계산·장면 갱신까지 {elapsed_ms:.1f} ms "
            f"({'목표 100 ms 이내' if elapsed_ms <= 100.0 else '목표 100 ms 초과'})"
        )
        self.solution_changed.emit(solution, snapshot)

    @Slot(str)
    def start_optimization(self, algorithm: str) -> None:
        if self._optimization_thread is not None:
            return
        try:
            request = self.facade.optimization_request(
                self.input_panel.values(),
                algorithm,
            )
        except Exception as exc:
            self.result_panel.display_error(str(exc))
            return
        self._optimization_cancel.clear()
        thread = QThread(self)
        worker = _OptimizationWorker(request, self._optimization_cancel)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._optimization_finished)
        worker.failed.connect(self._optimization_failed)
        worker.progress.connect(self.result_panel.update_optimization_progress)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._optimization_thread_finished)
        self._optimization_thread = thread
        self._optimization_worker = worker
        self.result_panel.set_optimizing(True)
        thread.start()

    @Slot()
    def cancel_optimization(self) -> None:
        self._optimization_cancel.set()
        self.result_panel.summary.setText("현재 세대가 끝난 뒤 최적화를 취소합니다…")

    @Slot(object)
    def _optimization_finished(self, result: Any) -> None:
        self.result_panel.display_optimization(result)

    @Slot(str)
    def _optimization_failed(self, message: str) -> None:
        self.result_panel.set_optimizing(False)
        self.result_panel.optimization_results.addItem(f"최적화 실패: {message}")

    @Slot()
    def _optimization_thread_finished(self) -> None:
        self._optimization_thread = None
        self._optimization_worker = None

    @Slot(object)
    def apply_candidate(self, candidate: Any) -> None:
        values = {
            "lens_id": candidate.lens_id,
            "alpha_deg": candidate.solution.alpha_deg,
            "beta_deg": candidate.solution.beta_deg,
        }
        self.selected_optimization = {
            "lens_id": candidate.lens_id,
            "alpha_deg": candidate.solution.alpha_deg,
            "beta_deg": candidate.solution.beta_deg,
            "objective_mm_per_pixel": candidate.objective_mm_per_pixel,
        }
        self.input_panel.apply_values(values)

    def project_input(self) -> dict[str, Any]:
        return self.input_panel.values()

    def apply_project_input(self, values: Mapping[str, Any]) -> None:
        self.input_panel.apply_values(values)

    def export_snapshot_dict(self) -> dict[str, Any]:
        if self.solution is None:
            return {}
        raw = asdict(self.solution) if is_dataclass(self.solution) else dict(vars(self.solution))

        def make_json_safe(value: Any):
            if hasattr(value, "value"):
                return value.value
            if isinstance(value, Mapping):
                return {key: make_json_safe(item) for key, item in value.items()}
            if isinstance(value, (tuple, list)):
                return [make_json_safe(item) for item in value]
            return value

        return make_json_safe(raw)

    def shutdown(self) -> None:
        self._initial_calculation.stop()
        self._debounce.stop()
        self.cancel_optimization()
        thread = self._optimization_thread
        if thread is not None:
            thread.quit()
            thread.wait(2_000)
