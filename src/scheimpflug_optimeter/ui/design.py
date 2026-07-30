"""Design-tab controls and direct adapter to the pure optical core."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scheimpflug_optimeter.lens_presets import (
    LensPresetError,
    UserLensPreset,
    lens_presets_from_dict,
    lens_presets_to_dict,
)

from .scene import (
    LensMechanicalSnapshot,
    OpticsGraphicsScene,
    OpticsGraphicsView,
    Point2D,
    SceneSnapshot,
    build_lens_body_section,
)


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

    def lens_from_values(
        self,
        values: Mapping[str, Any],
    ) -> tuple[Any, bool]:
        """Resolve an immutable official or project-local lens profile."""

        lens_id = str(values["lens_id"])
        if not lens_id.startswith("user-lens:"):
            return self.hardware.get_lens(lens_id), True
        try:
            presets = lens_presets_from_dict(values["user_lens_presets"])
        except (KeyError, LensPresetError) as exc:
            raise CoreUnavailableError(f"사용자 렌즈 프리셋을 읽을 수 없습니다: {exc}") from exc
        preset = next(
            (item for item in presets if item.runtime_lens_id == lens_id),
            None,
        )
        if preset is None:
            raise CoreUnavailableError(
                f"프로젝트에서 사용자 렌즈 프리셋을 찾을 수 없습니다: {lens_id}"
            )
        return preset.to_lens_profile(), preset.mechanical_rendering_status.enabled

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
        lens, mechanics_enabled = self.lens_from_values(values)
        mode = values["mode"]
        if mode != "workbook":
            raise CoreUnavailableError("이 화면은 구조설계_rev.1.xlsx Workbook 계산만 지원합니다.")
        alpha_value = values.get("alpha_deg")
        focal_literal = values.get("focal_length_literal_mm")
        request = self.models.WorkbookDesignInput(
            v_mm=float(values["v_mm"]),
            d_mm=float(values["d_mm"]),
            sensor_length_mm=float(values["sensor_length_mm"]),
            alpha_deg=(None if alpha_value is None else float(alpha_value)),
            sensor_id=sensor.id,
            sensor_axis=values["sensor_axis"],
            focal_length_literal_mm=(None if focal_literal is None else float(focal_literal)),
        )
        solution = self.optics.solve_workbook_design(request)
        geometry = self.optics.build_scene_geometry(solution)
        return (
            solution,
            lens,
            self.scene_snapshot(
                solution,
                geometry,
                lens,
                mechanics_enabled=mechanics_enabled,
            ),
        )

    @staticmethod
    def scene_snapshot(
        solution: Any,
        geometry: Any,
        lens: Any | None = None,
        *,
        mechanics_enabled: bool = True,
    ) -> SceneSnapshot:
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
        lens_mechanics = None
        required_mechanical_fields = (
            "overall_length_mm",
            "outer_diameter_mm",
            "front_housing_length_mm",
            "threaded_section_length_mm",
            "thread_major_diameter_mm",
            "first_object_surface_recess_from_front_housing_mm",
            "object_principal_plane_from_first_object_surface_mm",
        )
        if (
            mechanics_enabled
            and lens is not None
            and all(
                getattr(lens, field_name, None) is not None
                for field_name in required_mechanical_fields
            )
        ):
            raw_h_prime = getattr(
                lens,
                "image_principal_plane_from_last_image_surface_mm",
                None,
            )
            lens_mechanics = LensMechanicalSnapshot(
                lens_id=str(lens.id),
                sku=str(lens.sku),
                drawing_id=getattr(lens, "mechanical_drawing_id", None),
                overall_length_mm=float(lens.overall_length_mm),
                outer_diameter_mm=float(lens.outer_diameter_mm),
                front_housing_length_mm=float(lens.front_housing_length_mm),
                threaded_section_length_mm=float(lens.threaded_section_length_mm),
                thread_major_diameter_mm=float(lens.thread_major_diameter_mm),
                first_surface_recess_mm=float(
                    lens.first_object_surface_recess_from_front_housing_mm
                ),
                object_principal_from_first_surface_mm=float(
                    lens.object_principal_plane_from_first_object_surface_mm
                ),
                image_principal_from_last_surface_mm=(
                    float(raw_h_prime) if raw_h_prime is not None else None
                ),
                source_url=getattr(lens, "mechanical_source_url", None),
                supplier_verified=not str(lens.id).startswith("user-lens:"),
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
            alpha_deg=float(solution.alpha_deg),
            beta_deg=float(solution.beta_deg),
            baseline_mm=(float(solution.baseline_mm) if solution.baseline_mm is not None else None),
            v_mm=(float(request.v_mm) if solution.mode.value == "workbook" else None),
            object_principal_plane=_point(geometry.object_principal_plane),
            image_principal_plane=_point(geometry.image_principal_plane),
            principal_planes_coincident=bool(geometry.principal_planes_coincident),
            lens_mechanics=lens_mechanics,
        )


class DesignInputPanel(QWidget):
    """Workbook-first worksheet with explicit input and calculated cell roles."""

    changed = Signal()

    TABLE_HEADERS = ("구분", "한글 항목", "변수", "값", "단위/출처")
    INPUT_BACKGROUND = QColor("#fff3bf")
    CATALOG_BACKGROUND = QColor("#e7f2ff")
    RESULT_BACKGROUND = QColor("#eef1f4")
    ERROR_BACKGROUND = QColor("#ffe5e8")
    SECTION_BACKGROUND = QColor("#dde6ee")

    def __init__(self, facade: OpticalCoreFacade, parent=None) -> None:
        super().__init__(parent)
        self._facade = facade
        self._rows: dict[str, int] = {}
        self._result_items: dict[str, QTableWidgetItem] = {}
        self._source_items: dict[str, QTableWidgetItem] = {}
        self._formula_result_items: dict[str, QTableWidgetItem] = {}
        self._user_lens_presets: dict[str, UserLensPreset] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        # Keep the title, short guidance and complete formula card in the
        # initial 720 px-high viewport even when Windows font metrics are a
        # few pixels taller.  Four pixels still separates each worksheet
        # section without spending eight pixels twice above the formula card.
        layout.setSpacing(4)

        self.title = QLabel("Workbook 광학 설계 시트")
        self.title.setObjectName("panelTitle")
        self.title.setAccessibleName("Workbook 전용 Scheimpflug 계산 시트")
        layout.addWidget(self.title)

        self.mode_help = QLabel(
            "연노랑은 직접 입력, 연파랑은 카탈로그·센서 연동, 회색은 잠긴 계산 결과입니다."
        )
        self.mode_help.setObjectName("modeHelp")
        self.mode_help.setWordWrap(True)
        layout.addWidget(self.mode_help)

        self.camera = QComboBox()
        self.sensor_axis = QComboBox()
        self.sensor_axis.addItem("센서 높이 · vertical", "height")
        self.sensor_axis.addItem("센서 폭 · horizontal", "width")
        self.lens = QComboBox()
        for combo in (self.camera, self.sensor_axis, self.lens):
            combo.setSizeAdjustPolicy(
                QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
            )
            combo.setMinimumContentsLength(10)

        self.lens_preset_menu_button = QPushButton("프리셋 관리…")
        self.lens_preset_menu_button.setToolTip(
            "빈 렌즈 프리셋을 만들거나 선택 렌즈를 복제·편집·삭제합니다."
        )
        self.lens_preset_menu = QMenu(self.lens_preset_menu_button)
        self.new_lens_preset_action = self.lens_preset_menu.addAction("새 프리셋…")
        self.edit_lens_preset_action = self.lens_preset_menu.addAction("복제하여 편집…")
        self.lens_preset_menu.addSeparator()
        self.delete_lens_preset_action = self.lens_preset_menu.addAction("선택 프리셋 삭제")
        self.new_lens_preset_action.setToolTip(
            "공식 출처를 상속하지 않는 빈 프로젝트 렌즈 프리셋을 만듭니다."
        )
        self.edit_lens_preset_action.setToolTip(
            "공식 렌즈는 프로젝트 프리셋으로 복제하고, 사용자 렌즈는 직접 편집합니다."
        )
        self.delete_lens_preset_action.setToolTip("선택한 프로젝트 사용자 프리셋을 삭제합니다.")
        self.lens_preset_menu_button.setMenu(self.lens_preset_menu)
        self.lens_action_container = QWidget()
        self.lens_action_container.setObjectName("lensPresetToolbar")
        lens_action_layout = QHBoxLayout(self.lens_action_container)
        lens_action_layout.setContentsMargins(7, 5, 7, 5)
        lens_action_layout.setSpacing(7)
        lens_action_label = QLabel("프리셋")
        lens_action_label.setObjectName("lensPresetToolbarLabel")
        lens_action_layout.addWidget(lens_action_label)
        lens_action_layout.addStretch(1)
        self.lens_preset_menu_button.setMinimumWidth(132)
        lens_action_layout.addWidget(self.lens_preset_menu_button)
        self.lens_action_container.setStyleSheet(
            """
            QWidget#lensPresetToolbar {
                background: #e7f2ff;
                border: 1px solid #b6c9d9;
                border-radius: 5px;
            }
            QLabel#lensPresetToolbarLabel {
                color: #17344e;
                font-weight: 700;
            }
            """
        )

        self.focal_length_mm = self._spin(
            0.000001,
            1_000_000.0,
            17.5,
            " mm",
            decimals=6,
        )
        self.focal_length_literal_mm = self.focal_length_mm
        self.focal_length_link_toggle = QCheckBox("렌즈 연동")
        self.focal_length_link_toggle.setChecked(True)
        self.focal_length_link_toggle.setToolTip(
            "켜면 선택한 공식/사용자 렌즈 프리셋의 f를 사용합니다. "
            "끄면 Workbook 회귀용 f를 직접 덮어씁니다."
        )
        self.v_mm = self._spin(1.0, 100_000.0, 150.0, " mm")
        self.d_mm = self._spin(0.0, 100_000.0, 100.0, " mm")
        self.sensor_length_mm = self._spin(
            0.000001,
            100_000.0,
            5.4378,
            " mm",
            decimals=6,
        )
        self.alpha_deg = self._spin(0.01, 54.735610317, 20.68, "°", decimals=6)
        self.manual_alpha_toggle = QCheckBox("α 직접 입력")
        self.manual_alpha_toggle.setToolTip(
            "켜면 원본 Workbook 회귀용 α를 직접 입력합니다. 끄면 f/V의 저각 해를 자동 계산합니다."
        )
        self.sensor_link_toggle = QCheckBox("센서 연동")
        self.sensor_link_toggle.setChecked(True)
        self.sensor_link_toggle.setToolTip("선택한 카메라와 축의 활성 길이를 L에 자동 적용합니다.")
        self.load_sensor_length_button = QPushButton("센서값 적용", self)
        self.load_sensor_length_button.hide()

        self.input_link_toolbar = QWidget()
        self.input_link_toolbar.setObjectName("inputLinkToolbar")
        input_link_layout = QHBoxLayout(self.input_link_toolbar)
        input_link_layout.setContentsMargins(7, 4, 7, 4)
        input_link_layout.setSpacing(12)
        input_link_label = QLabel("입력 연동")
        input_link_label.setObjectName("inputLinkToolbarLabel")
        input_link_layout.addWidget(input_link_label)
        input_link_layout.addStretch(1)
        input_link_layout.addWidget(self.focal_length_link_toggle)
        input_link_layout.addWidget(self.sensor_link_toggle)
        self.input_link_toolbar.setStyleSheet(
            """
            QWidget#inputLinkToolbar {
                background: #f7fafc;
                border: 1px solid #c7d2dc;
                border-radius: 5px;
            }
            QLabel#inputLinkToolbarLabel {
                color: #334e65;
                font-weight: 700;
            }
            """
        )

        self.alpha_mode_container = QWidget()
        alpha_mode_layout = QHBoxLayout(self.alpha_mode_container)
        alpha_mode_layout.setContentsMargins(0, 0, 0, 0)
        alpha_mode_layout.addWidget(self.manual_alpha_toggle)
        alpha_mode_layout.addStretch(1)

        self._build_formula_card()
        layout.addWidget(self.formula_card)

        self.worksheet_group = QGroupBox("입력 및 계산 결과")
        worksheet_layout = QVBoxLayout(self.worksheet_group)
        worksheet_layout.setContentsMargins(5, 8, 5, 5)
        worksheet_layout.addWidget(self.lens_action_container)
        worksheet_layout.addWidget(self.input_link_toolbar)
        self.worksheet_table = QTableWidget(0, len(self.TABLE_HEADERS))
        self.worksheet_table.setObjectName("workbookWorksheet")
        self.worksheet_table.setHorizontalHeaderLabels(self.TABLE_HEADERS)
        self.worksheet_table.verticalHeader().setVisible(False)
        self.worksheet_table.setShowGrid(True)
        self.worksheet_table.setAlternatingRowColors(False)
        self.worksheet_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.worksheet_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.worksheet_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.worksheet_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.worksheet_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.worksheet_table.setMinimumHeight(205)
        self.worksheet_table.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Expanding,
        )
        self.worksheet_table.setAccessibleName(
            "Workbook 입력과 잠긴 계산 결과를 함께 표시하는 시트"
        )
        header = self.worksheet_table.horizontalHeader()
        for column, width in ((0, 44), (1, 80), (2, 42), (4, 82)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.worksheet_table.setColumnWidth(column, width)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setStretchLastSection(False)
        self.worksheet_table.setStyleSheet(
            """
            QTableWidget#workbookWorksheet {
                background: #ffffff;
                alternate-background-color: #ffffff;
                border: 1px solid #b8c4cf;
                gridline-color: #c8d1da;
                font-size: 10.5pt;
            }
            QTableWidget#workbookWorksheet::item {
                padding: 3px 5px;
            }
            QTableWidget#workbookWorksheet::item:selected {
                color: #102f4c;
                background: #cfe6fb;
            }
            QHeaderView::section {
                background: #dce6ef;
                color: #17344e;
                border: 0;
                border-right: 1px solid #aebdca;
                border-bottom: 1px solid #9eafbd;
                padding: 5px 3px;
                font-weight: 700;
            }
            """
        )
        worksheet_layout.addWidget(self.worksheet_table)
        layout.addWidget(self.worksheet_group, 1)

        self.worksheet_status = QLabel("계산 준비")
        self.worksheet_status.setObjectName("worksheetStatus")
        self.worksheet_status.setWordWrap(True)
        self.worksheet_status.setAccessibleName("Workbook 계산 상태")
        layout.addWidget(self.worksheet_status)

        self._build_worksheet_rows()
        self._configure_accessibility()

        self._load_catalogs()
        default_lens = self.lens.findData("edmund-58-206")
        if default_lens >= 0:
            self.lens.setCurrentIndex(default_lens)
        default_camera = self.camera.findData("basler-aca1300-60gm")
        if default_camera >= 0:
            self.camera.setCurrentIndex(default_camera)
        self._sync_lens_focal()
        self._update_lens_source()
        self._refresh_sensor_profile()
        self._set_alpha_mode_visuals()
        self._update_formula_known()

        self.camera.currentIndexChanged.connect(self._on_camera_or_axis_changed)
        self.sensor_axis.currentIndexChanged.connect(self._on_camera_or_axis_changed)
        self.lens.currentIndexChanged.connect(self._on_lens_changed)
        self.new_lens_preset_action.triggered.connect(self._create_lens_preset)
        self.edit_lens_preset_action.triggered.connect(self._edit_lens_preset)
        self.delete_lens_preset_action.triggered.connect(self._delete_selected_lens_preset)
        self.sensor_link_toggle.toggled.connect(self._on_sensor_link_toggled)
        self.focal_length_link_toggle.toggled.connect(self._on_focal_length_link_toggled)
        self.manual_alpha_toggle.toggled.connect(self._on_manual_alpha_toggled)
        self.load_sensor_length_button.clicked.connect(self.load_selected_camera_sensor_length)
        for widget in (
            self.focal_length_mm,
            self.v_mm,
            self.d_mm,
            self.sensor_length_mm,
            self.alpha_deg,
        ):
            widget.valueChanged.connect(self._on_numeric_input_changed)
        self._update_lens_action_state()
        self._update_focal_length_visuals()
        self._update_worksheet_columns()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "worksheet_table"):
            self._update_worksheet_columns()

    def _update_worksheet_columns(self) -> None:
        """Keep numeric cells readable while preserving the full Excel view."""

        compact = self.width() < 500
        header = self.worksheet_table.horizontalHeader()
        self.worksheet_table.setColumnHidden(0, compact)
        self.worksheet_table.setColumnHidden(4, compact)
        for spin in (
            self.focal_length_mm,
            self.v_mm,
            self.d_mm,
            self.sensor_length_mm,
            self.alpha_deg,
        ):
            spin.setSuffix("" if compact else str(spin.property("worksheetWideSuffix") or ""))
        if compact:
            header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
            self.worksheet_table.setColumnWidth(1, 128)
            self.worksheet_table.setColumnWidth(2, 52)
        else:
            for column, width in ((0, 44), (1, 80), (2, 42), (4, 82)):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
                self.worksheet_table.setColumnWidth(column, width)
            header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

    def _build_formula_card(self) -> None:
        self.formula_card = QGroupBox("■ 설계 주요 공식")
        self.formula_card.setObjectName("formulaCard")
        self.formula_card.setMinimumHeight(370)
        self.formula_card.setMaximumHeight(400)
        self.formula_card.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.formula_card.setStyleSheet(
            """
            QGroupBox#formulaCard {
                background: #f8fbfe;
                border: 1px solid #9fb4c6;
                border-radius: 7px;
                margin-top: 10px;
                padding: 8px 6px 5px 6px;
                color: #15344f;
                font-size: 11pt;
                font-weight: 700;
            }
            QLabel[formulaRole="modeSummary"] {
                background: #e5f1fc;
                border: 1px solid #a7c7e3;
                border-radius: 5px;
                color: #174a75;
                padding: 3px 7px;
            }
            QLabel[formulaRole="equationTag"] {
                color: #50687c;
                font-weight: 700;
            }
            QLabel[formulaRole="equation"] {
                color: #102f4c;
                font-size: 13pt;
                font-family: "Cambria Math", "Segoe UI Symbol", "Malgun Gothic";
            }
            QLabel[formulaRole="known"] {
                color: #17344e;
                font-size: 11pt;
                font-weight: 700;
            }
            """
        )
        formula_layout = QVBoxLayout(self.formula_card)
        formula_layout.setContentsMargins(7, 9, 7, 6)
        formula_layout.setSpacing(4)

        header_row = QHBoxLayout()
        self.formula_mode_summary = QLabel("f / V 자동 α")
        self.formula_mode_summary.setProperty("formulaRole", "modeSummary")
        self.formula_mode_summary.setAccessibleName("현재 α 계산 방식")
        header_row.addWidget(self.formula_mode_summary)
        header_row.addStretch(1)
        formula_layout.addLayout(header_row)
        self.formula_known = QLabel()
        self.formula_known.setProperty("formulaRole", "known")
        self.formula_known.setAccessibleName("현재 Known f와 V")
        self.formula_known.setWordWrap(True)
        self.formula_known.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        formula_layout.addWidget(self.formula_known)

        equation_grid = QGridLayout()
        equation_grid.setContentsMargins(0, 0, 0, 0)
        equation_grid.setHorizontalSpacing(7)
        equation_grid.setVerticalSpacing(1)
        equation_grid.setColumnStretch(1, 1)
        equations = (
            ("렌즈식", "1/l₀ + 1/fₚ = 1/f"),
            ("결상 기하", "l₀ tan α = fₚ tan β"),
            ("자동 α", "sin² α cos α = f/V"),
        )
        self.formula_equation_rows: list[tuple[QLabel, QLabel]] = []
        for row, (category_text, equation_text) in enumerate(equations):
            category = QLabel(category_text)
            category.setProperty("formulaRole", "equationTag")
            equation = QLabel(equation_text)
            equation.setProperty("formulaRole", "equation")
            equation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            equation.setSizePolicy(
                QSizePolicy.Policy.Ignored,
                QSizePolicy.Policy.Preferred,
            )
            equation.setAccessibleName(f"{category_text}: {equation_text}")
            equation_grid.addWidget(category, row, 0)
            equation_grid.addWidget(equation, row, 1)
            self.formula_equation_rows.append((category, equation))
        formula_layout.addLayout(equation_grid)

        self.formula_results = QTableWidget(4, 4)
        self.formula_results.setObjectName("formulaResults")
        self.formula_results.setHorizontalHeaderLabels(("항목", "값", "항목", "값"))
        self.formula_results.verticalHeader().setVisible(False)
        self.formula_results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.formula_results.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.formula_results.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.formula_results.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Four data rows plus the responsive header must remain fully visible
        # at the largest supported typography scale.
        self.formula_results.setFixedHeight(136)
        self.formula_results.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Fixed,
        )
        self.formula_results.setStyleSheet(
            """
            QTableWidget#formulaResults {
                background: #ffffff;
                border: 1px solid #c2ced8;
                gridline-color: #d5dde4;
                font-size: 10pt;
            }
            QHeaderView::section {
                background: #e5ebf0;
                padding: 2px;
                font-weight: 700;
            }
            """
        )
        formula_pairs = (
            (("v", "V"), ("baseline", "b")),
            (("fp", "fₚ"), ("lo", "l₀")),
            (("total", "fₚ+l₀"), ("alpha", "α")),
            (("beta", "β"), ("f_calc", "f 계산")),
        )
        for row, pair in enumerate(formula_pairs):
            for pair_index, (key, label) in enumerate(pair):
                label_column = pair_index * 2
                value_column = label_column + 1
                label_item = self._readonly_item(label, self.RESULT_BACKGROUND)
                value_item = self._readonly_item("—", self.RESULT_BACKGROUND)
                value_item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                self.formula_results.setItem(row, label_column, label_item)
                self.formula_results.setItem(row, value_column, value_item)
                self._formula_result_items[key] = value_item
        formula_header = self.formula_results.horizontalHeader()
        formula_header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row in range(self.formula_results.rowCount()):
            self.formula_results.setRowHeight(row, 20)
        formula_layout.addWidget(self.formula_results)

        self.formula_variables = QLabel(
            "β = 유도 보각/결상 기하각 · 계산 H = H′ (thin-lens). "
            "실제 렌즈 catalog H/H′는 별도 데이터입니다."
        )
        self.formula_variables.setToolTip(
            "현재 Workbook 계산은 얇은 렌즈 모델이므로 H와 H′를 렌즈 중심의 "
            "같은 점에 둡니다. 실제 렌즈의 주평면 오프셋을 이 좌표로 해석하지 않습니다."
        )
        self.formula_variables.setWordWrap(True)
        self.formula_variables.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.formula_variables.setAccessibleName("각도 및 주평면 해석")
        formula_layout.addWidget(self.formula_variables)

    def _build_worksheet_rows(self) -> None:
        self._add_widget_row(
            "선택",
            "Basler 카메라",
            "camera",
            self.camera,
            "정적 카탈로그",
            role="catalog",
        )
        self._add_widget_row(
            "선택",
            "삼각측량 축",
            "axis",
            self.sensor_axis,
            "FOV 계산 축",
            role="catalog",
        )
        self._add_widget_row(
            "선택",
            "Edmund M12 렌즈",
            "lens",
            self.lens,
            "정적 카탈로그",
            role="catalog",
        )
        self._add_result_row("센서", "가로 해상도", "Wₚₓ", "sensor_width_px", "px · catalog")
        self._add_result_row("센서", "세로 해상도", "Hₚₓ", "sensor_height_px", "px · catalog")
        self._add_result_row("센서", "픽셀 피치", "p", "sensor_pitch", "µm · catalog")
        self._add_result_row("센서", "활성 폭", "Lₓ", "sensor_width", "mm · catalog")
        self._add_result_row("센서", "활성 높이", "Lᵧ", "sensor_height", "mm · catalog")

        self._add_widget_row(
            "입력",
            "초점거리",
            "f",
            self.focal_length_mm,
            "mm · 렌즈 연동",
            role="catalog",
        )
        self._add_widget_row(
            "입력",
            "기준 높이/거리",
            "V",
            self.v_mm,
            "mm · 사용자",
            role="input",
        )
        self._add_widget_row(
            "입력",
            "Working distance",
            "d",
            self.d_mm,
            "mm · 사용자",
            role="input",
        )
        self._add_widget_row(
            "입력",
            "센서/이미지 길이",
            "L",
            self.sensor_length_mm,
            "선택 축 연동",
            role="catalog",
            key="sensor_length",
        )
        self._add_widget_row(
            "입력",
            "α 계산 방식",
            "mode",
            self.alpha_mode_container,
            "기본: f/V 자동",
            role="catalog",
            key="alpha_mode",
        )
        self._add_widget_row(
            "입력/계산",
            "수광각",
            "α",
            self.alpha_deg,
            "° · 자동 계산",
            role="result",
            key="alpha_input",
        )

        result_rows = (
            ("기하", "유도 보각/결상 기하각", "β", "beta", "° · β=90°−α"),
            ("기하", "베이스라인", "b", "baseline", "mm · V tan α"),
            ("기하", "반 이미지 길이", "x", "half_sensor", "mm · L/2"),
            ("기하", "횡방향 외곽", "W", "width", "mm · b+x"),
            ("기하", "축방향 외곽", "R", "rear", "mm · V−d"),
            ("결상", "물체 거리", "l₀", "lo", "mm · 계산"),
            ("결상", "이미지 거리", "fₚ", "fp", "mm · 계산"),
            ("결상", "총 광로", "fₚ+l₀", "total", "mm · 계산"),
            ("결상", "광선 교차 거리", "|s|", "ray_intercept", "mm · 계산"),
            ("결상", "계산 초점거리", "f_calc", "f_calc", "mm · 계산"),
            ("결상", "초점거리 편차", "Δf", "delta_f", "mm · f_calc−f"),
            ("좌표", "렌즈 위치 X", "Lens X", "lens_x", "mm · zero=(0,0)"),
            ("좌표", "렌즈 위치 Z", "Lens Z", "lens_z", "mm · zero=(0,0)"),
            (
                "렌즈 기구",
                "전면 하우징 위치 X",
                "F0 X",
                "lens_front_x",
                "mm · H에서 역산",
            ),
            (
                "렌즈 기구",
                "전면 하우징 위치 Z",
                "F0 Z",
                "lens_front_z",
                "mm · H에서 역산",
            ),
            (
                "렌즈 기구",
                "후면 하우징 위치 X",
                "B X",
                "lens_rear_x",
                "mm · 공식 외형",
            ),
            (
                "렌즈 기구",
                "후면 하우징 위치 Z",
                "B Z",
                "lens_rear_z",
                "mm · 공식 외형",
            ),
            (
                "렌즈 기구",
                "전면 하우징→H",
                "F0→H",
                "front_to_h",
                "mm · S1 recess + S1→H",
            ),
            (
                "렌즈 기구",
                "공급사 물체측 주평면",
                "S1→H",
                "catalog_h",
                "mm · 첫 물체측 광학면 기준",
            ),
            (
                "렌즈 기구",
                "공급사 상측 주평면",
                "SL→H′",
                "catalog_h_prime",
                "mm · 마지막 상측 광학면 기준",
            ),
            (
                "주평면",
                "물체/상측 주평면",
                "H/H′",
                "principal_planes",
                "thin-lens · 수치 분리 없음",
            ),
            ("센서 결과", "가로 FOV", "FOVₓ", "fov_x", "mm · 계산"),
            ("센서 결과", "세로 FOV", "FOVᵧ", "fov_y", "mm · 계산"),
            ("센서 결과", "가로 샘플링", "Δx/px", "sampling_x", "µm/px · 계산"),
            ("센서 결과", "세로 샘플링", "Δy/px", "sampling_y", "µm/px · 계산"),
            (
                "센서 결과",
                "중앙 거리 민감도",
                "ds/px",
                "sensitivity_center",
                "mm/px · 기하",
            ),
            (
                "센서 결과",
                "최악 거리 민감도",
                "max ds/px",
                "sensitivity_worst",
                "mm/px · 기하",
            ),
        )
        for group, name, symbol, key, source in result_rows:
            self._add_result_row(group, name, symbol, key, source)

    def _configure_accessibility(self) -> None:
        accessible_names = (
            (self.camera, "정적 Basler 센서 규격"),
            (self.sensor_axis, "삼각측량 센서 축"),
            (self.lens, "Edmund M12 렌즈 규격"),
            (self.focal_length_link_toggle, "선택 렌즈 초점거리 연동"),
            (self.focal_length_mm, "Known 초점거리 f 밀리미터"),
            (self.v_mm, "Known 기준 높이 또는 거리 V 밀리미터"),
            (self.d_mm, "Working distance d 밀리미터"),
            (self.sensor_length_mm, "센서 이미지 길이 L 밀리미터"),
            (self.alpha_deg, "수광각 알파 도"),
        )
        for widget, name in accessible_names:
            widget.setAccessibleName(name)

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
        widget.setProperty("worksheetWideSuffix", suffix)
        widget.setKeyboardTracking(False)
        return widget

    @classmethod
    def _readonly_item(
        cls,
        text: str,
        background: QColor | None = None,
    ) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        item.setBackground(background or cls.RESULT_BACKGROUND)
        return item

    def _base_row(
        self,
        group: str,
        name: str,
        symbol: str,
        source: str,
        *,
        key: str,
    ) -> int:
        row = self.worksheet_table.rowCount()
        self.worksheet_table.insertRow(row)
        self.worksheet_table.setRowHeight(
            row,
            max(28, self.worksheet_table.fontMetrics().height() + 12),
        )
        group_item = self._readonly_item(group, self.SECTION_BACKGROUND)
        name_item = self._readonly_item(name, self.RESULT_BACKGROUND)
        symbol_item = self._readonly_item(symbol, self.RESULT_BACKGROUND)
        source_item = self._readonly_item(source, self.RESULT_BACKGROUND)
        compact_tooltip = f"{group} · {name}\n{symbol} · {source}"
        name_item.setToolTip(compact_tooltip)
        symbol_item.setToolTip(compact_tooltip)
        symbol_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        source_item.setToolTip(source)
        self.worksheet_table.setItem(row, 0, group_item)
        self.worksheet_table.setItem(row, 1, name_item)
        self.worksheet_table.setItem(row, 2, symbol_item)
        self.worksheet_table.setItem(row, 4, source_item)
        self._rows[key] = row
        self._source_items[key] = source_item
        return row

    def _add_widget_row(
        self,
        group: str,
        name: str,
        symbol: str,
        widget: QWidget,
        source: str,
        *,
        role: str,
        key: str | None = None,
    ) -> None:
        row_key = key or symbol
        row = self._base_row(group, name, symbol, source, key=row_key)
        backing = self._readonly_item(
            "",
            self.INPUT_BACKGROUND if role == "input" else self.CATALOG_BACKGROUND,
        )
        self.worksheet_table.setItem(row, 3, backing)
        self.worksheet_table.setCellWidget(row, 3, widget)
        self._style_cell_widget(widget, role)

    def _add_result_row(
        self,
        group: str,
        name: str,
        symbol: str,
        key: str,
        source: str,
    ) -> None:
        row = self._base_row(group, name, symbol, source, key=key)
        value_item = self._readonly_item("—", self.RESULT_BACKGROUND)
        value_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.worksheet_table.setItem(row, 3, value_item)
        self._result_items[key] = value_item

    def _style_cell_widget(self, widget: QWidget, role: str) -> None:
        background = {
            "input": "#fff3bf",
            "catalog": "#e7f2ff",
            "result": "#eef1f4",
        }[role]
        widget.setProperty("worksheetRole", role)
        widget.setStyleSheet(
            f"""
            QComboBox, QDoubleSpinBox, QWidget {{
                background: {background};
            }}
            QComboBox, QDoubleSpinBox {{
                border: 1px solid #9eacb8;
                border-radius: 3px;
                padding: 2px 4px;
                min-height: 20px;
            }}
            QDoubleSpinBox:disabled {{
                color: #31485c;
                background: {background};
            }}
            """
        )

    def _load_catalogs(self) -> None:
        self.camera.clear()
        for camera in self._facade.cameras():
            self.camera.addItem(
                f"{camera.model} · {camera.sensor.width_px}×{camera.sensor.height_px}",
                camera.id,
            )
            self.camera.setItemData(
                self.camera.count() - 1,
                (
                    f"{camera.manufacturer} {camera.model}\n"
                    f"{camera.sensor.width_px}×{camera.sensor.height_px} px · "
                    f"{camera.sensor.pixel_pitch_um:g} µm"
                ),
                Qt.ItemDataRole.ToolTipRole,
            )
        if not self.camera.count():
            self.camera.addItem("센서 카탈로그 로드 실패", "")
            self.camera.setEnabled(False)

        self._reload_lens_choices()

    def _reload_lens_choices(self, selected_id: str | None = None) -> None:
        """Rebuild official and project-local choices without mutating either."""

        if selected_id is None:
            selected_id = self.lens.currentData()
        self.lens.blockSignals(True)
        self.lens.clear()
        for lens in self._facade.lenses():
            reference = " · Workbook 58206 기준" if lens.is_workbook_reference else ""
            self.lens.addItem(
                f"#{lens.sku} · {lens.focal_length_mm:g} mm{reference}",
                lens.id,
            )
            principal_details = ""
            if lens.object_principal_plane_from_first_object_surface_mm is not None:
                principal_details += (
                    f"\nS1→H={lens.object_principal_plane_from_first_object_surface_mm:g} mm"
                )
            if lens.image_principal_plane_from_last_image_surface_mm is not None:
                principal_details += (
                    "\nSL→H′="
                    f"{lens.image_principal_plane_from_last_image_surface_mm:g} mm"
                    " · 마지막 광학면 기준"
                )
            self.lens.setItemData(
                self.lens.count() - 1,
                (
                    f"{lens.name}\n{lens.mount}"
                    f"{principal_details}\n"
                    "H′의 외부 하우징 절대 위치는 공개자료로 확정하지 않습니다."
                ),
                Qt.ItemDataRole.ToolTipRole,
            )
        if self._user_lens_presets and self.lens.count():
            self.lens.insertSeparator(self.lens.count())
        for preset in self._user_lens_presets.values():
            status = preset.mechanical_rendering_status
            mechanics = "3D 외형 사용" if status.enabled else "광학값만 사용"
            self.lens.addItem(
                (f"사용자 · {preset.name} [{preset.user_id}] · {preset.focal_length_mm:g} mm"),
                preset.runtime_lens_id,
            )
            self.lens.setItemData(
                self.lens.count() - 1,
                (
                    f"프로젝트 사용자 프리셋\n"
                    f"id={preset.user_id} · {mechanics}\n"
                    "S1→H와 SL→H′는 각각 지정된 광학면 기준값입니다."
                ),
                Qt.ItemDataRole.ToolTipRole,
            )
        if not self.lens.count():
            self.lens.addItem("렌즈 카탈로그 로드 실패", "")
            self.lens.setEnabled(False)
        if selected_id:
            selected_index = self.lens.findData(selected_id)
            if selected_index >= 0:
                self.lens.setCurrentIndex(selected_index)
        self.lens.blockSignals(False)
        self._update_lens_action_state()

    def _camera_profile(self):
        camera_id = self.camera.currentData()
        return next(
            (camera for camera in self._facade.cameras() if camera.id == camera_id),
            None,
        )

    def _lens_profile(self):
        lens_id = self.lens.currentData()
        if isinstance(lens_id, str) and lens_id.startswith("user-lens:"):
            preset = next(
                (
                    item
                    for item in self._user_lens_presets.values()
                    if item.runtime_lens_id == lens_id
                ),
                None,
            )
            return preset.to_lens_profile() if preset is not None else None
        return next(
            (lens for lens in self._facade.lenses() if lens.id == lens_id),
            None,
        )

    def selected_user_lens_preset(self) -> UserLensPreset | None:
        lens_id = self.lens.currentData()
        return next(
            (
                preset
                for preset in self._user_lens_presets.values()
                if preset.runtime_lens_id == lens_id
            ),
            None,
        )

    def user_lens_presets(self) -> tuple[UserLensPreset, ...]:
        return tuple(self._user_lens_presets.values())

    def add_or_replace_user_lens_preset(
        self,
        preset: UserLensPreset,
        *,
        select: bool = True,
    ) -> None:
        """Add one validated project-local preset and optionally select it."""

        # Materialize and range-check before changing the collection so a
        # programmatic caller cannot leave a half-applied preset behind.
        runtime_lens = preset.to_lens_profile()
        focal = float(runtime_lens.focal_length_mm)
        if (
            not math.isfinite(focal)
            or focal < self.focal_length_mm.minimum()
            or focal > self.focal_length_mm.maximum()
        ):
            raise LensPresetError(
                f"사용자 렌즈 초점거리가 UI/계산 허용 범위를 벗어납니다: {focal:.12g} mm"
            )
        self._user_lens_presets[preset.user_id] = preset
        selected_id = preset.runtime_lens_id if select else self.lens.currentData()
        self._reload_lens_choices(str(selected_id) if selected_id else None)
        if select:
            index = self.lens.findData(preset.runtime_lens_id)
            if index >= 0:
                self.lens.setCurrentIndex(index)
        self._sync_lens_focal()
        self._update_lens_source()
        self._update_formula_known()
        self.changed.emit()

    def remove_user_lens_preset(self, user_id: str) -> None:
        """Remove a project preset; official catalog entries are never changed."""

        preset = self._user_lens_presets.pop(user_id, None)
        if preset is None:
            return
        fallback = (
            preset.source_profile_id
            if preset.source_profile_id
            and any(lens.id == preset.source_profile_id for lens in self._facade.lenses())
            else "edmund-58-206"
        )
        self._reload_lens_choices(fallback)
        index = self.lens.findData(fallback)
        if index >= 0:
            self.lens.setCurrentIndex(index)
        self._sync_lens_focal()
        self._update_lens_source()
        self._update_formula_known()
        self.changed.emit()

    def _set_result(
        self,
        key: str,
        value: float | int | str | None,
        *,
        decimals: int = 6,
    ) -> None:
        item = self._result_items[key]
        if isinstance(value, str):
            text = value
        elif value is None or not math.isfinite(float(value)):
            text = "—"
        elif isinstance(value, int):
            text = f"{value:d}"
        else:
            text = f"{float(value):.{decimals}g}"
        item.setText(text)
        item.setToolTip(text)
        item.setBackground(self.RESULT_BACKGROUND)

    def _set_formula_result(
        self,
        key: str,
        value: float | None,
        unit: str,
    ) -> None:
        item = self._formula_result_items[key]
        if value is None or not math.isfinite(float(value)):
            item.setText("—")
        else:
            item.setText(f"{float(value):.4g} {unit}")

    def _refresh_sensor_profile(self) -> None:
        camera = self._camera_profile()
        if camera is None:
            for key in (
                "sensor_width_px",
                "sensor_height_px",
                "sensor_pitch",
                "sensor_width",
                "sensor_height",
            ):
                self._set_result(key, None)
            return
        sensor = camera.sensor
        self._set_result("sensor_width_px", sensor.width_px)
        self._set_result("sensor_height_px", sensor.height_px)
        self._set_result("sensor_pitch", sensor.pixel_pitch_um)
        self._set_result("sensor_width", sensor.width_mm)
        self._set_result("sensor_height", sensor.height_mm)
        if self.sensor_link_toggle.isChecked():
            self.sensor_length_mm.blockSignals(True)
            self.sensor_length_mm.setValue(sensor.length_mm(str(self.sensor_axis.currentData())))
            self.sensor_length_mm.blockSignals(False)
        self._update_sensor_length_visuals()

    def _sync_lens_focal(self) -> None:
        if not self.focal_length_link_toggle.isChecked():
            return
        lens = self._lens_profile()
        if lens is None:
            return
        focal = float(lens.focal_length_mm)
        if (
            not math.isfinite(focal)
            or focal < self.focal_length_mm.minimum()
            or focal > self.focal_length_mm.maximum()
        ):
            raise LensPresetError(
                "선택 렌즈 초점거리가 입력 범위를 벗어납니다: "
                f"{focal:.12g} mm "
                f"({self.focal_length_mm.minimum():g}–"
                f"{self.focal_length_mm.maximum():g} mm)"
            )
        self.focal_length_mm.blockSignals(True)
        self.focal_length_mm.setValue(focal)
        self.focal_length_mm.blockSignals(False)
        self.focal_length_mm.setToolTip(f"선택 렌즈 프리셋의 정확한 f = {focal:.12g} mm")

    def _update_focal_length_visuals(self) -> None:
        linked = self.focal_length_link_toggle.isChecked()
        self.focal_length_mm.setEnabled(not linked)
        self._style_cell_widget(
            self.focal_length_mm,
            "catalog" if linked else "input",
        )
        source = "mm · 선택 렌즈 f 연동" if linked else "mm · Workbook 사용자 override"
        self._source_items["f"].setText(source)
        self._source_items["f"].setToolTip(
            source
            + (
                "\n프리셋의 초점거리와 항상 일치합니다."
                if linked
                else "\n선택 렌즈 외형과 계산 f가 다를 수 있으므로 의도적으로만 사용하세요."
            )
        )

    def _update_lens_source(self) -> None:
        source_item = self._source_items["lens"]
        preset = self.selected_user_lens_preset()
        if preset is not None:
            status = preset.mechanical_rendering_status
            source_item.setText("프로젝트 사용자 프리셋")
            source_item.setToolTip(
                f"{preset.name}\n"
                f"원본={preset.source_profile_id or '사용자 신규'}\n"
                + (
                    "기구 외형 렌더링 가능"
                    if status.enabled
                    else "기구 외형 비활성 · "
                    + ", ".join(
                        (
                            *status.missing_fields,
                            *(issue.code for issue in status.issues),
                        )
                    )
                )
            )
            return
        is_workbook_reference = self.lens.currentData() == "edmund-58-206"
        source_item.setText(
            "Workbook ref · #58-206" if is_workbook_reference else "catalog · WB #58-206 별도"
        )
        source_item.setToolTip(
            "Workbook의 58206_002는 Edmund Optics #58-206 17.5 mm f/2.5를 "
            "가리킵니다. #83-954 17.5 mm f/8과는 다른 SKU입니다."
        )

    def _update_sensor_length_visuals(self) -> None:
        linked = self.sensor_link_toggle.isChecked()
        self.sensor_length_mm.setEnabled(not linked)
        self._style_cell_widget(
            self.sensor_length_mm,
            "catalog" if linked else "input",
        )
        axis_name = "높이" if self.sensor_axis.currentData() == "height" else "폭"
        source = f"센서 {axis_name} 연동" if linked else "mm · 사용자 입력"
        self._source_items["sensor_length"].setText(source)
        self._source_items["sensor_length"].setToolTip(source)

    def _set_alpha_mode_visuals(self) -> None:
        manual = self.manual_alpha_toggle.isChecked()
        self.alpha_deg.setEnabled(manual)
        self._style_cell_widget(self.alpha_deg, "input" if manual else "result")
        source = "° · 사용자 입력" if manual else "° · f/V 저각 해"
        self._source_items["alpha_input"].setText(source)
        self._source_items["alpha_input"].setToolTip(source)
        mode_source = "워크북 회귀 α 직접 입력" if manual else "기본 · f/V 자동 α"
        self._source_items["alpha_mode"].setText(mode_source)
        self.formula_mode_summary.setText(
            "α 직접 입력 · Workbook 회귀" if manual else "f / V 자동 α"
        )

    def _update_formula_known(self) -> None:
        focal = self.focal_length_mm.value()
        if self.focal_length_link_toggle.isChecked():
            lens = self._lens_profile()
            if lens is not None:
                focal = float(lens.focal_length_mm)
        self.formula_known.setText(f"Known · f = {focal:.6g} mm · V = {self.v_mm.value():.4g} mm")

    def _on_camera_or_axis_changed(self, _index: int) -> None:
        self._refresh_sensor_profile()
        self.changed.emit()

    def _on_lens_changed(self, _index: int) -> None:
        self._sync_lens_focal()
        self._update_lens_source()
        self._update_lens_action_state()
        self._update_focal_length_visuals()
        self._update_formula_known()
        self.changed.emit()

    def _update_lens_action_state(self) -> None:
        preset = self.selected_user_lens_preset()
        self.edit_lens_preset_action.setText(
            "프리셋 편집…" if preset is not None else "복제하여 편집…"
        )
        self.delete_lens_preset_action.setEnabled(preset is not None)

    @Slot()
    def _create_lens_preset(self) -> None:
        """Create a blank project preset without inherited supplier claims."""

        from .lens_preset_dialog import LensPresetDialog

        blank = UserLensPreset(
            user_id=self._unique_user_lens_id("custom-lens"),
            name="새 사용자 렌즈",
            focal_length_mm=self.focal_length_mm.value(),
            mount="M12x0.5",
        )
        dialog = LensPresetDialog(blank, self, new_preset=True)
        self._run_lens_preset_dialog(dialog, selected_preset=None)

    @Slot()
    def _edit_lens_preset(self) -> None:
        """Clone an official lens or edit the selected project preset."""

        from .lens_preset_dialog import LensPresetDialog

        selected_preset = self.selected_user_lens_preset()
        source = selected_preset or self._lens_profile()
        if source is None:
            QMessageBox.warning(
                self,
                "렌즈 프리셋",
                "편집할 렌즈를 찾을 수 없습니다.",
            )
            return

        dialog = LensPresetDialog(source, self)
        if selected_preset is None:
            base_id = dialog.user_id_edit.text().strip() or "lens-copy"
            dialog.user_id_edit.setText(self._unique_user_lens_id(base_id))
        self._run_lens_preset_dialog(
            dialog,
            selected_preset=selected_preset,
        )

    def _run_lens_preset_dialog(
        self,
        dialog: QDialog,
        *,
        selected_preset: UserLensPreset | None,
    ) -> None:
        """Save a valid dialog result without overwriting another preset."""

        while dialog.exec() == QDialog.DialogCode.Accepted:
            preset = dialog.result_preset()
            existing = self._user_lens_presets.get(preset.user_id)
            if existing is None or (
                selected_preset is not None and existing.user_id == selected_preset.user_id
            ):
                self.add_or_replace_user_lens_preset(preset)
                return

            unique_id = self._unique_user_lens_id(preset.user_id)
            QMessageBox.warning(
                self,
                "프리셋 ID 중복",
                (
                    f"‘{preset.user_id}’ ID가 이미 프로젝트에 있습니다.\n"
                    f"기존 프리셋을 덮어쓰지 않도록 ‘{unique_id}’를 입력했습니다."
                ),
            )
            dialog.user_id_edit.setText(unique_id)
            dialog.user_id_edit.setFocus()
            dialog.user_id_edit.selectAll()

    def _unique_user_lens_id(self, base_id: str) -> str:
        """Return a stable project-local id without overwriting another preset."""

        normalized = base_id[:64]
        if normalized not in self._user_lens_presets:
            return normalized
        suffix = 2
        while True:
            suffix_text = f"-{suffix}"
            candidate = f"{normalized[: 64 - len(suffix_text)]}{suffix_text}"
            if candidate not in self._user_lens_presets:
                return candidate
            suffix += 1

    @Slot()
    def _delete_selected_lens_preset(self) -> None:
        preset = self.selected_user_lens_preset()
        if preset is None:
            return
        answer = QMessageBox.question(
            self,
            "사용자 렌즈 프리셋 삭제",
            f"프로젝트 프리셋 ‘{preset.name}’을 삭제할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.remove_user_lens_preset(preset.user_id)

    def _on_sensor_link_toggled(self, _checked: bool) -> None:
        self._refresh_sensor_profile()
        self.changed.emit()

    def _on_focal_length_link_toggled(self, checked: bool) -> None:
        if checked:
            self._sync_lens_focal()
        self._update_focal_length_visuals()
        self._update_formula_known()
        self.changed.emit()

    def _on_manual_alpha_toggled(self, _checked: bool) -> None:
        self._set_alpha_mode_visuals()
        self.changed.emit()

    def _on_numeric_input_changed(self, _value: float) -> None:
        self._update_formula_known()
        self.changed.emit()

    @Slot()
    def load_selected_camera_sensor_length(self) -> None:
        self.sensor_link_toggle.setChecked(True)
        self._refresh_sensor_profile()

    def values(self) -> dict[str, Any]:
        manual_alpha = self.manual_alpha_toggle.isChecked()
        focal_linked = self.focal_length_link_toggle.isChecked()
        focal_literal = self.focal_length_mm.value()
        if focal_linked:
            lens = self._lens_profile()
            if lens is None:
                raise LensPresetError("선택한 렌즈의 초점거리를 읽을 수 없습니다.")
            focal_literal = float(lens.focal_length_mm)
        return {
            "mode": "workbook",
            "camera_id": self.camera.currentData(),
            "lens_id": self.lens.currentData(),
            "user_lens_presets": lens_presets_to_dict(self._user_lens_presets.values()),
            "sensor_axis": self.sensor_axis.currentData(),
            "focal_length_literal_mm": focal_literal,
            "focal_length_linked": focal_linked,
            "v_mm": self.v_mm.value(),
            "d_mm": self.d_mm.value(),
            "sensor_length_mm": self.sensor_length_mm.value(),
            "sensor_length_linked": self.sensor_link_toggle.isChecked(),
            "alpha_manual": manual_alpha,
            "alpha_deg": self.alpha_deg.value() if manual_alpha else None,
        }

    def apply_values(self, values: Mapping[str, Any]) -> None:
        missing = object()
        requested_mode = values.get("mode", "workbook")
        if requested_mode != "workbook":
            raise LensPresetError(
                f"이 화면은 Workbook 입력만 열 수 있습니다: mode={requested_mode!r}"
            )

        def requested_text(key: str, current: Any, label: str) -> str:
            raw = values.get(key, current)
            if not isinstance(raw, str) or not raw.strip():
                raise LensPresetError(f"{label} ID는 비어 있을 수 없습니다.")
            return raw.strip()

        def requested_bool(key: str, default: bool) -> bool:
            if key not in values:
                return default
            raw = values[key]
            if type(raw) is not bool:
                raise LensPresetError(f"{key} 값은 true/false여야 합니다.")
            return raw

        def requested_number(
            raw: Any,
            spin: QDoubleSpinBox,
            label: str,
        ) -> float:
            if raw is None or isinstance(raw, bool):
                raise LensPresetError(f"{label} 값은 유한한 숫자여야 합니다.")
            try:
                number = float(raw)
            except (TypeError, ValueError) as exc:
                raise LensPresetError(f"{label} 값을 숫자로 읽을 수 없습니다: {raw!r}") from exc
            if not math.isfinite(number) or number < spin.minimum() or number > spin.maximum():
                raise LensPresetError(
                    f"{label} 값 {number!r}이 허용 범위 "
                    f"{spin.minimum():g}–{spin.maximum():g}를 벗어납니다."
                )
            return number

        preset_payload = values.get("user_lens_presets", missing)
        parsed_presets = dict(self._user_lens_presets)
        if preset_payload is not missing:
            presets = lens_presets_from_dict(preset_payload)
            parsed_presets = {preset.user_id: preset for preset in presets}

        runtime_user_lenses = {}
        for preset in parsed_presets.values():
            try:
                runtime_lens = preset.to_lens_profile()
            except (TypeError, ValueError) as exc:
                raise LensPresetError(
                    f"사용자 렌즈 프리셋 {preset.user_id!r}을 적용할 수 없습니다: {exc}"
                ) from exc
            requested_number(
                runtime_lens.focal_length_mm,
                self.focal_length_mm,
                f"사용자 렌즈 {preset.user_id!r} 초점거리 f",
            )
            runtime_user_lenses[runtime_lens.id] = runtime_lens

        requested_camera_id = requested_text(
            "camera_id",
            self.camera.currentData(),
            "카메라",
        )
        requested_axis = requested_text(
            "sensor_axis",
            self.sensor_axis.currentData(),
            "센서 축",
        )
        requested_lens_id = requested_text(
            "lens_id",
            self.lens.currentData(),
            "렌즈",
        )
        camera = next(
            (item for item in self._facade.cameras() if item.id == requested_camera_id),
            None,
        )
        if camera is None:
            raise LensPresetError(
                f"프로젝트가 참조하는 카메라를 찾을 수 없습니다: {requested_camera_id}"
            )
        if requested_axis not in {"height", "width"}:
            raise LensPresetError(
                f"프로젝트가 참조하는 센서 축을 찾을 수 없습니다: {requested_axis}"
            )
        if requested_lens_id.startswith("user-lens:"):
            selected_lens = runtime_user_lenses.get(requested_lens_id)
            if selected_lens is None:
                raise LensPresetError(
                    f"선택한 사용자 렌즈 프리셋이 프로젝트 데이터에 없습니다: {requested_lens_id}"
                )
        else:
            selected_lens = next(
                (lens for lens in self._facade.lenses() if lens.id == requested_lens_id),
                None,
            )
            if selected_lens is None:
                raise LensPresetError(
                    f"프로젝트가 참조하는 렌즈를 찾을 수 없습니다: {requested_lens_id}"
                )

        explicit_focal_raw = values.get(
            "focal_length_literal_mm",
            values.get("focal_length_mm", missing),
        )
        explicit_focal = (
            None
            if explicit_focal_raw is missing or explicit_focal_raw is None
            else requested_number(
                explicit_focal_raw,
                self.focal_length_mm,
                "초점거리 f",
            )
        )
        if "focal_length_linked" in values:
            focal_linked = requested_bool(
                "focal_length_linked",
                self.focal_length_link_toggle.isChecked(),
            )
        elif explicit_focal_raw is missing:
            focal_linked = self.focal_length_link_toggle.isChecked()
        else:
            focal_linked = explicit_focal is None or math.isclose(
                explicit_focal,
                float(selected_lens.focal_length_mm),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        if (
            "focal_length_linked" in values
            and not focal_linked
            and (explicit_focal_raw is missing or explicit_focal is None)
        ):
            raise LensPresetError(
                "초점거리 연동을 해제한 프로젝트에는 focal_length_literal_mm 숫자값이 필요합니다."
            )
        focal_value = (
            requested_number(
                selected_lens.focal_length_mm,
                self.focal_length_mm,
                "선택 렌즈 초점거리 f",
            )
            if focal_linked
            else (explicit_focal if explicit_focal is not None else self.focal_length_mm.value())
        )

        numeric_candidates: dict[str, float] = {}
        for key, spin, label in (
            ("v_mm", self.v_mm, "기준 높이/거리 V"),
            ("d_mm", self.d_mm, "Working distance d"),
            ("sensor_length_mm", self.sensor_length_mm, "센서/이미지 길이 L"),
        ):
            numeric_candidates[key] = (
                requested_number(values[key], spin, label) if key in values else spin.value()
            )

        alpha_raw = values.get("alpha_deg", missing)
        alpha_value = (
            None
            if alpha_raw is None
            else (
                requested_number(alpha_raw, self.alpha_deg, "수광각 α")
                if alpha_raw is not missing
                else self.alpha_deg.value()
            )
        )
        if "alpha_manual" in values:
            manual_alpha = requested_bool(
                "alpha_manual",
                self.manual_alpha_toggle.isChecked(),
            )
        elif alpha_raw is not missing:
            manual_alpha = alpha_value is not None
        else:
            manual_alpha = self.manual_alpha_toggle.isChecked()
        if (
            "alpha_manual" in values
            and manual_alpha
            and (alpha_raw is missing or alpha_value is None)
        ):
            raise LensPresetError("α 직접 입력 모드에는 alpha_deg 값이 필요합니다.")

        if "sensor_length_linked" in values:
            sensor_linked = requested_bool(
                "sensor_length_linked",
                self.sensor_link_toggle.isChecked(),
            )
        elif "sensor_length_mm" in values:
            sensor_linked = math.isclose(
                numeric_candidates["sensor_length_mm"],
                camera.sensor.length_mm(requested_axis),
                rel_tol=1e-9,
                abs_tol=1e-9,
            )
        else:
            sensor_linked = self.sensor_link_toggle.isChecked()
        if (
            "sensor_length_linked" in values
            and not sensor_linked
            and "sensor_length_mm" not in values
        ):
            raise LensPresetError(
                "센서 길이 연동을 해제한 프로젝트에는 sensor_length_mm 숫자값이 필요합니다."
            )

        # Commit only after references, conversions, ranges and linked values
        # all pass.  A failed project load leaves the current project intact.
        if preset_payload is not missing:
            self._user_lens_presets = parsed_presets
            self._reload_lens_choices(requested_lens_id)

        blockers = (
            self.camera,
            self.sensor_axis,
            self.lens,
            self.focal_length_mm,
            self.v_mm,
            self.d_mm,
            self.sensor_length_mm,
            self.alpha_deg,
            self.sensor_link_toggle,
            self.focal_length_link_toggle,
            self.manual_alpha_toggle,
        )
        for widget in blockers:
            widget.blockSignals(True)
        try:
            for combo, selected_id in (
                (self.camera, requested_camera_id),
                (self.sensor_axis, requested_axis),
                (self.lens, requested_lens_id),
            ):
                combo.setCurrentIndex(combo.findData(selected_id))

            self.focal_length_link_toggle.setChecked(focal_linked)
            self.focal_length_mm.setValue(focal_value)
            for spin, key in (
                (self.v_mm, "v_mm"),
                (self.d_mm, "d_mm"),
                (self.sensor_length_mm, "sensor_length_mm"),
            ):
                spin.setValue(numeric_candidates[key])
            if alpha_value is not None:
                self.alpha_deg.setValue(alpha_value)
            self.manual_alpha_toggle.setChecked(manual_alpha)
            self.sensor_link_toggle.setChecked(sensor_linked)
        finally:
            for widget in blockers:
                widget.blockSignals(False)

        self._refresh_sensor_profile()
        self._update_lens_source()
        self._update_lens_action_state()
        self._update_focal_length_visuals()
        self._set_alpha_mode_visuals()
        self._update_formula_known()
        self.changed.emit()

    def display_solution(self, solution: Any, snapshot: SceneSnapshot | None) -> None:
        self.alpha_deg.blockSignals(True)
        self.alpha_deg.setValue(float(solution.alpha_deg))
        self.alpha_deg.blockSignals(False)

        focal_input = float(
            solution.request.focal_length_literal_mm
            if solution.request.focal_length_literal_mm is not None
            else self.focal_length_mm.value()
        )
        lens_body = build_lens_body_section(snapshot) if snapshot is not None else None
        mechanics = snapshot.lens_mechanics if snapshot is not None else None
        results: dict[str, float | None] = {
            "beta": solution.beta_deg,
            "baseline": solution.baseline_mm,
            "half_sensor": solution.x_far_mm,
            "width": solution.width_exact_mm,
            "rear": solution.rear_exact_mm,
            "lo": solution.lo_mm,
            "fp": solution.fp_mm,
            "total": solution.total_optical_length_mm,
            "ray_intercept": (
                abs(solution.ray_intercept_s_mm)
                if solution.ray_intercept_s_mm is not None
                else None
            ),
            "f_calc": solution.focal_length_mm,
            "delta_f": solution.focal_length_mm - focal_input,
            "lens_x": snapshot.lens_center.x_mm if snapshot is not None else None,
            "lens_z": snapshot.lens_center.z_mm if snapshot is not None else None,
            "lens_front_x": (lens_body.front_housing.x_mm if lens_body is not None else None),
            "lens_front_z": (lens_body.front_housing.z_mm if lens_body is not None else None),
            "lens_rear_x": (lens_body.rear_housing.x_mm if lens_body is not None else None),
            "lens_rear_z": (lens_body.rear_housing.z_mm if lens_body is not None else None),
            "front_to_h": (
                mechanics.front_housing_to_object_principal_mm if mechanics is not None else None
            ),
            "catalog_h": (
                mechanics.object_principal_from_first_surface_mm if mechanics is not None else None
            ),
            "catalog_h_prime": (
                mechanics.image_principal_from_last_surface_mm if mechanics is not None else None
            ),
        }
        for key, value in results.items():
            self._set_result(key, value)

        if mechanics is not None:
            drawing = (
                mechanics.drawing_id or "공식 공급사 자료"
                if mechanics.supplier_verified
                else "사용자 입력 · 공급사 검증 아님"
            )
            for key in (
                "lens_front_x",
                "lens_front_z",
                "lens_rear_x",
                "lens_rear_z",
                "front_to_h",
            ):
                self._result_items[key].setToolTip(
                    f"#{mechanics.sku} · {drawing}\n"
                    "계산 H 좌표와 전면 하우징→H datum으로 외형 위치를 역산했습니다."
                )
            self._result_items["catalog_h"].setToolTip(
                f"#{mechanics.sku} · S1(첫 물체측 광학면)→H\n양(+) 방향은 CMOS/이미지 방향입니다."
            )
            self._result_items["catalog_h_prime"].setToolTip(
                f"#{mechanics.sku} · SL(마지막 상측 광학면)→H′\n"
                "이 값의 기준은 외부 하우징이 아닙니다. 공개 도면에 SL의 "
                "하우징 절대 위치가 없어 실제 H′ 공간 좌표는 표시하지 않습니다."
            )

        if snapshot is None:
            principal_text = "H = H′ (thin-lens 기준)"
        else:
            object_plane = snapshot.object_principal_plane or snapshot.lens_center
            image_plane = snapshot.image_principal_plane or snapshot.lens_center
            if snapshot.principal_planes_coincident:
                principal_text = f"H = H′ @ ({object_plane.x_mm:.4g}, {object_plane.z_mm:.4g})"
            else:
                principal_text = (
                    f"H ({object_plane.x_mm:.4g}, {object_plane.z_mm:.4g}) · "
                    f"H′ ({image_plane.x_mm:.4g}, {image_plane.z_mm:.4g})"
                )
        self._set_result("principal_planes", principal_text)
        self._result_items["principal_planes"].setToolTip(
            f"{principal_text}\n"
            "현재 좌표는 thin-lens 계산 모델입니다. 실제 렌즈 catalog의 H/H′ "
            "오프셋 또는 하우징 기준 절대 위치와 혼동하지 마세요."
        )

        metrics = solution.sensor_metrics
        sensor_results = {
            "fov_x": metrics.horizontal_fov_mm if metrics is not None else None,
            "fov_y": metrics.vertical_fov_mm if metrics is not None else None,
            "sampling_x": (
                metrics.horizontal_sampling_mm_per_px * 1000.0
                if metrics is not None and metrics.horizontal_sampling_mm_per_px is not None
                else None
            ),
            "sampling_y": (
                metrics.vertical_sampling_mm_per_px * 1000.0
                if metrics is not None and metrics.vertical_sampling_mm_per_px is not None
                else None
            ),
            "sensitivity_center": (
                metrics.range_sensitivity_center_mm_per_px if metrics is not None else None
            ),
            "sensitivity_worst": (
                metrics.range_sensitivity_worst_mm_per_px if metrics is not None else None
            ),
        }
        for key, value in sensor_results.items():
            self._set_result(key, value)

        formula_values = {
            "v": (solution.request.v_mm, "mm"),
            "baseline": (solution.baseline_mm, "mm"),
            "fp": (solution.fp_mm, "mm"),
            "lo": (solution.lo_mm, "mm"),
            "total": (solution.total_optical_length_mm, "mm"),
            "alpha": (solution.alpha_deg, "°"),
            "beta": (solution.beta_deg, "°"),
            "f_calc": (solution.focal_length_mm, "mm"),
        }
        for key, (value, unit) in formula_values.items():
            self._set_formula_result(key, value, unit)

        warning_count = len(solution.warnings) + len(solution.violations)
        if solution.valid and warning_count == 0:
            status = "계산 완료 · 유효한 Workbook 구조"
            color = "#1c6b43"
            background = "#e7f6ee"
        elif solution.valid:
            status = f"계산 완료 · 경고 {warning_count}건"
            color = "#805200"
            background = "#fff3d6"
        else:
            status = f"사용 불가 · 제약 위반 {warning_count}건"
            color = "#9d2436"
            background = "#ffe5e8"
        self.worksheet_status.setText(status)
        self.worksheet_status.setStyleSheet(
            f"color:{color}; background:{background}; "
            "border-radius:4px; padding:4px 7px; font-weight:700;"
        )
        self._set_alpha_mode_visuals()

    def display_error(self, message: str) -> None:
        sensor_keys = {
            "sensor_width_px",
            "sensor_height_px",
            "sensor_pitch",
            "sensor_width",
            "sensor_height",
        }
        for key, item in self._result_items.items():
            if key in sensor_keys:
                continue
            item.setText("—")
            item.setToolTip(message)
            item.setBackground(self.ERROR_BACKGROUND)
        for item in self._formula_result_items.values():
            item.setText("—")
        self.worksheet_status.setText(f"계산 실패 · {message}")
        self.worksheet_status.setStyleSheet(
            "color:#9d2436; background:#ffe5e8; "
            "border-radius:4px; padding:4px 7px; font-weight:700;"
        )


class DesignWidget(QWidget):
    """Two-pane Workbook worksheet and live optical visualization."""

    solution_changed = Signal(object, object)

    def __init__(self, facade: OpticalCoreFacade | None = None, parent=None) -> None:
        super().__init__(parent)
        self.facade = facade or OpticalCoreFacade()
        self.solution: Any | None = None
        self.snapshot: SceneSnapshot | None = None
        self._has_completed_initial_render = False
        # Schema-v1 compatibility only. Workbook UI does not create or apply
        # optimization candidates.
        self.selected_optimization: dict[str, Any] | None = None

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
        self.input_scroll = self._scroll(self.input_panel, minimum_width=400)
        self.splitter.addWidget(self.input_scroll)
        self.splitter.addWidget(self.view)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([420, 1_000])
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
        except Exception as exc:
            self.solution = None
            self.snapshot = None
            message = str(exc)
            self.scene.set_invalid_message(message)
            self.input_panel.display_error(message)
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
        self.input_panel.display_solution(solution, snapshot)
        elapsed_ms = (perf_counter() - started) * 1000.0
        initial_render = not self._has_completed_initial_render
        if not initial_render:
            badge_text = f"갱신 {elapsed_ms:.1f} ms"
            badge_state = "valid" if elapsed_ms <= 100.0 else "warning"
        else:
            badge_text = f"초기 표시 {elapsed_ms:.1f} ms"
            badge_state = "valid"
            self._has_completed_initial_render = True
        self._set_performance(badge_text, badge_state)
        self.performance.setToolTip(
            f"입력 변경부터 계산·장면 갱신까지 {elapsed_ms:.1f} ms "
            f"({'목표 100 ms 이내' if elapsed_ms <= 100.0 else '목표 100 ms 초과'})"
            if not initial_render
            else f"첫 화면 구성 {elapsed_ms:.1f} ms · 실시간 갱신 목표와 별도"
        )
        self.solution_changed.emit(solution, snapshot)

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
