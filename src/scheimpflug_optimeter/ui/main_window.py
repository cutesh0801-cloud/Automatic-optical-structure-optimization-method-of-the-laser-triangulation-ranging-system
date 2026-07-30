"""Main application window and file/export actions."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QToolBar,
)

from scheimpflug_optimeter import __version__
from scheimpflug_optimeter.lens_presets import LensPresetError
from scheimpflug_optimeter.project import (
    PROJECT_SUFFIX,
    ProjectDocument,
    ProjectError,
    load_project,
    save_project,
)

from .design import DesignWidget
from .sensor_comparison import SensorComparisonWidget
from .three_d import ThreeDWidget

_DEFAULT_DESIGN_INPUT = {
    "mode": "workbook",
    "sensor_axis": "height",
    "d_mm": 100.0,
    "v_mm": 150.0,
    "sensor_length_mm": 5.4378,
    "sensor_length_linked": True,
    "focal_length_literal_mm": 17.5,
    "focal_length_linked": True,
    "alpha_manual": False,
    "alpha_deg": None,
    "user_lens_presets": {"schema_version": 1, "presets": []},
}
_DEFAULT_HARDWARE = {
    "camera_id": "basler-aca1300-60gm",
    "lens_id": "edmund-58-206",
}


class MainWindow(QMainWindow):
    """Korean-first desktop shell for optical simulation and visualization."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle("Scheimpflug OptiMeter — 새 프로젝트")
        self.resize(1500, 920)
        self.setMinimumSize(1100, 700)
        self._project_path: Path | None = None
        self._project_name = "새 프로젝트"
        self._dirty = False
        self._loading = False
        self._latest_3d_snapshot: object | None = None
        self._settings = QSettings("Scheimpflug OptiMeter", "Scheimpflug OptiMeter")

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setAccessibleName("Scheimpflug 시뮬레이션 화면")
        self.design = DesignWidget()
        self.three_d = ThreeDWidget()
        self.sensor_comparison = SensorComparisonWidget()
        self.tabs.addTab(self.design, "워크북 계산 · 실시간 2D")
        self.tabs.addTab(self.three_d, "3D Scheimpflug 시각화")
        # Keep the historic 3D tab at index 1 so schema-v1 project view state
        # continues to open the same page after this comparison tab was added.
        self.tabs.addTab(self.sensor_comparison, "Basler 센서 비교")
        self.setCentralWidget(self.tabs)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self.statusBar().setSizeGripEnabled(False)
        self.status_label = QLabel()
        self.status_label.setObjectName("calculationStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status_label.setAccessibleName("현재 계산 상태")
        self.statusBar().addPermanentWidget(self.status_label)
        self._set_calculation_status(
            "계산 준비 · 입력값을 변경하면 자동으로 갱신됩니다.",
            "ready",
        )

        self.design.solution_changed.connect(self._on_solution_changed)
        self.design.input_panel.changed.connect(self._mark_dirty)
        self.design.export_png_button.clicked.connect(self.export_png)
        self.design.export_svg_button.clicked.connect(self.export_svg)
        self.tabs.currentChanged.connect(self._mark_dirty)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._restore_window_state()

    def _create_actions(self) -> None:
        self.new_action = QAction("새 프로젝트", self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.open_action = QAction("프로젝트 열기…", self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.save_action = QAction("저장", self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_as_action = QAction("다른 이름으로 저장…", self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.import_csv_action = QAction("워크북 입력 CSV 불러오기…", self)
        self.export_csv_action = QAction("워크북 계산 결과 CSV 내보내기…", self)
        self.export_png_action = QAction("광학 장면 PNG…", self)
        self.export_svg_action = QAction("광학 장면 SVG…", self)
        self.exit_action = QAction("끝내기", self)
        self.exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.fit_action = QAction("전체 맞춤", self)
        self.fit_action.setShortcut("F")
        self.head_zoom_action = QAction("광학부 확대", self)
        self.head_zoom_action.setShortcut("H")
        self.about_action = QAction("Scheimpflug OptiMeter 정보", self)

        self.new_action.setStatusTip("새 시뮬레이션 프로젝트를 만듭니다.")
        self.open_action.setStatusTip("저장된 Scheimpflug 프로젝트를 엽니다.")
        self.save_action.setStatusTip("현재 입력과 화면 상태를 저장합니다.")
        self.import_csv_action.setStatusTip("워크북 호환 입력 한 행을 CSV에서 불러옵니다.")
        self.export_csv_action.setStatusTip("현재 워크북 계산값을 CSV로 저장합니다.")
        self.fit_action.setStatusTip("2D 광학 구조 전체를 같은 축척으로 맞춥니다. (F)")
        self.head_zoom_action.setStatusTip("렌즈와 센서 주변 광학부를 확대합니다. (H)")

        self.new_action.triggered.connect(self.new_project)
        self.open_action.triggered.connect(self.open_project_dialog)
        self.save_action.triggered.connect(self.save_project)
        self.save_as_action.triggered.connect(self.save_project_as)
        self.import_csv_action.triggered.connect(self.import_workbook_csv_dialog)
        self.export_csv_action.triggered.connect(self.export_workbook_csv_dialog)
        self.export_png_action.triggered.connect(self.export_png)
        self.export_svg_action.triggered.connect(self.export_svg)
        self.exit_action.triggered.connect(self.close)
        self.fit_action.triggered.connect(self.design.view.fit_scene)
        self.head_zoom_action.triggered.connect(self.design.view.fit_optical_head)
        self.about_action.triggered.connect(self.show_about)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("파일")
        file_menu.addAction(self.new_action)
        file_menu.addAction(self.open_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.save_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self.import_csv_action)
        file_menu.addAction(self.export_csv_action)
        file_menu.addSeparator()
        file_menu.addAction(self.export_png_action)
        file_menu.addAction(self.export_svg_action)
        file_menu.addSeparator()
        file_menu.addAction(self.exit_action)

        view_menu = self.menuBar().addMenu("보기")
        view_menu.addAction(self.fit_action)
        view_menu.addAction(self.head_zoom_action)

        help_menu = self.menuBar().addMenu("도움말")
        help_menu.addAction(self.about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("기본 도구")
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        toolbar.setMinimumHeight(42)
        toolbar.addAction(self.new_action)
        toolbar.addAction(self.open_action)
        toolbar.addAction(self.save_action)
        toolbar.addSeparator()
        toolbar.addAction(self.fit_action)
        toolbar.addAction(self.head_zoom_action)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolbar)

    def _set_calculation_status(self, text: str, state: str) -> None:
        """Update the readable status text and its non-colour semantic state."""

        self.status_label.setText(text)
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _restore_window_state(self) -> None:
        geometry = self._settings.value("window/geometry")
        state = self._settings.value("window/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state)

    def _set_title(self) -> None:
        marker = " *" if self._dirty else ""
        self.setWindowTitle(f"Scheimpflug OptiMeter — {self._project_name}{marker}")

    def _mark_dirty(self, *_args) -> None:
        if self._loading:
            return
        self._dirty = True
        self._set_title()

    def _on_solution_changed(self, solution, snapshot) -> None:
        if solution is None or snapshot is None:
            self._latest_3d_snapshot = None
            self.sensor_comparison.display_metrics(
                (),
                selected_camera_id=None,
                context_warning="입력 계산 오류로 센서 비교를 중단했습니다.",
            )
            if self.tabs.currentWidget() is self.three_d:
                self.three_d.set_geometry(None)
            self._set_calculation_status(
                "계산 오류 · 입력 패널의 오류 메시지를 확인하세요.",
                "error",
            )
            return
        comparison_rows = self.design.facade.compare_sensor_profiles(solution)
        self.sensor_comparison.display_metrics(
            comparison_rows,
            selected_camera_id=self.design.input_panel.camera.currentData(),
            context_warning=(
                "현재 광학 해에 제약 위반이 있어 비교값은 설계에 사용할 수 없습니다."
                if not solution.valid
                else None
            ),
        )
        self._latest_3d_snapshot = snapshot
        self.three_d.set_geometry(
            snapshot,
            render=self.tabs.currentWidget() is self.three_d,
        )
        warning_count = len(solution.warnings)
        if not solution.valid:
            state = "제약 위반"
            status_state = "warning"
        elif warning_count:
            state = f"유효 · 경고 {warning_count}건"
            status_state = "warning"
        else:
            state = "유효"
            status_state = "valid"
        if solution.mode.value == "workbook":
            ray_intercept = (
                f"{abs(solution.ray_intercept_s_mm):.3f} mm"
                if solution.ray_intercept_s_mm is not None
                else "계산 불가"
            )
            self._set_calculation_status(
                f"워크북 {state} · W={solution.width_exact_mm:.3f} mm · "
                f"R={solution.rear_exact_mm:.3f} mm · "
                f"|s|={ray_intercept}",
                status_state,
            )
        else:
            self._set_calculation_status(
                f"Canonical {state} · f={solution.focal_length_mm:.3f} mm · "
                f"L={solution.required_sensor_length_mm:.3f} mm",
                status_state,
            )

    def _on_tab_changed(self, _index: int) -> None:
        if self.tabs.currentWidget() is not self.three_d:
            return
        if self._latest_3d_snapshot is None:
            self.three_d.set_geometry(None)
            return
        self.three_d.set_geometry(self._latest_3d_snapshot)

    def current_document(self) -> ProjectDocument:
        values = self.design.project_input()
        design_input = {
            key: value for key, value in values.items() if key not in {"camera_id", "lens_id"}
        }
        hardware = {
            "camera_id": values["camera_id"],
            "lens_id": values["lens_id"],
        }
        return ProjectDocument(
            project_name=self._project_name,
            design_input=design_input,
            hardware=hardware,
            # Schema-v1 retains this optional field, but the Workbook
            # simulator deliberately has no optimization execution path.
            selected_optimization=None,
            ui_state={
                "active_tab": self.tabs.currentIndex(),
                "design_splitter_sizes": self.design.splitter.sizes(),
            },
        )

    def apply_document(self, document: ProjectDocument, source: Path | None = None) -> None:
        self._loading = True
        try:
            try:
                raw_values = dict(document.design_input)
                if (
                    raw_values.get("focal_length_linked") is False
                    and "focal_length_literal_mm" not in raw_values
                    and "focal_length_mm" not in raw_values
                ):
                    raise LensPresetError(
                        "초점거리 연동을 해제한 프로젝트에는 초점거리 숫자값이 필요합니다."
                    )
                for state_key, required_key, label in (
                    ("alpha_manual", "alpha_deg", "α 직접 입력"),
                    ("sensor_length_linked", "sensor_length_mm", "센서 길이 연동 해제"),
                ):
                    required_state = state_key == "alpha_manual"
                    if (
                        raw_values.get(state_key) is required_state
                        and required_key not in raw_values
                    ):
                        raise LensPresetError(
                            f"{label} 상태에는 {required_key} 숫자값이 필요합니다."
                        )

                values = dict(_DEFAULT_DESIGN_INPUT)
                values.update(raw_values)
                # Schema-v1 files created before explicit link-state fields
                # existed are migrated deterministically from their numeric
                # input instead of inheriting whichever UI state is open.
                if "focal_length_mm" in raw_values and "focal_length_literal_mm" not in raw_values:
                    values.pop("focal_length_literal_mm", None)
                for state_key, numeric_key in (
                    ("focal_length_linked", "focal_length_mm"),
                    ("focal_length_linked", "focal_length_literal_mm"),
                    ("alpha_manual", "alpha_deg"),
                    ("sensor_length_linked", "sensor_length_mm"),
                ):
                    if state_key not in raw_values and numeric_key in raw_values:
                        values.pop(state_key, None)

                hardware = dict(_DEFAULT_HARDWARE)
                hardware.update(document.hardware)
                values.update(hardware)
                self.design.apply_project_input(values)
            except (LensPresetError, TypeError, ValueError) as exc:
                raise ProjectError(
                    f"프로젝트 입력 또는 사용자 렌즈 프리셋이 잘못되었습니다: {exc}"
                ) from exc
            # Read old project files without reviving their former optimizer
            # selection into this Workbook-only UI.
            self.design.selected_optimization = None
            sizes = document.ui_state.get("design_splitter_sizes")
            if isinstance(sizes, list) and all(
                isinstance(value, int) and value >= 0 for value in sizes
            ):
                if len(sizes) == 2:
                    self.design.splitter.setSizes(sizes)
                elif len(sizes) == 3:
                    # Schema-v1 projects created by the former three-pane UI
                    # keep the worksheet width and merge both visual panes.
                    self.design.splitter.setSizes([sizes[0], sizes[1] + sizes[2]])
            active_tab = document.ui_state.get("active_tab", 0)
            if isinstance(active_tab, int) and 0 <= active_tab < self.tabs.count():
                self.tabs.setCurrentIndex(active_tab)
            self._project_name = document.project_name
            self._project_path = source
            self._dirty = False
            self._set_title()
            self.design.recalculate()
        finally:
            self._loading = False

    def maybe_save_changes(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "변경 내용 저장",
            "현재 프로젝트의 변경 내용을 저장할까요?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self.save_project()
        return True

    def new_project(self) -> None:
        if not self.maybe_save_changes():
            return
        self.apply_document(
            ProjectDocument(
                design_input=_DEFAULT_DESIGN_INPUT,
                hardware=_DEFAULT_HARDWARE,
            )
        )

    def open_project_dialog(self) -> None:
        if not self.maybe_save_changes():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Scheimpflug 프로젝트 열기",
            str(self._project_path.parent if self._project_path else Path.home()),
            f"Scheimpflug 프로젝트 (*{PROJECT_SUFFIX});;JSON (*.json)",
        )
        if not filename:
            return
        self.open_project(filename)

    def open_project(self, path: str | Path) -> bool:
        source = Path(path).resolve()
        try:
            document = load_project(source)
            self.apply_document(document, source)
        except ProjectError as exc:
            QMessageBox.critical(self, "프로젝트 열기 실패", str(exc))
            return False
        self.statusBar().showMessage(f"열었습니다: {source}", 5_000)
        return True

    def save_project(self) -> bool:
        if self._project_path is None:
            return self.save_project_as()
        try:
            target = save_project(self._project_path, self.current_document())
        except ProjectError as exc:
            QMessageBox.critical(self, "프로젝트 저장 실패", str(exc))
            return False
        self._project_path = target
        self._project_name = target.name.removesuffix(PROJECT_SUFFIX)
        self._dirty = False
        self._set_title()
        self.statusBar().showMessage(f"저장했습니다: {target}", 5_000)
        return True

    def save_project_as(self) -> bool:
        initial = self._project_path or Path.home() / (self._project_name + PROJECT_SUFFIX)
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Scheimpflug 프로젝트 저장",
            str(initial),
            f"Scheimpflug 프로젝트 (*{PROJECT_SUFFIX})",
        )
        if not filename:
            return False
        self._project_path = Path(filename)
        self._project_name = self._project_path.name.removesuffix(PROJECT_SUFFIX)
        return self.save_project()

    def import_workbook_csv_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "워크북 입력 CSV 불러오기",
            str(self._project_path.parent if self._project_path else Path.home()),
            "CSV (*.csv)",
        )
        if not filename:
            return
        try:
            self.import_workbook_csv(filename)
        except ProjectError as exc:
            QMessageBox.critical(self, "CSV 불러오기 실패", str(exc))

    def import_workbook_csv(self, path: str | Path) -> None:
        """Load the first CSV scenario as authoritative V/d/L/alpha input."""

        source = Path(path)
        try:
            with source.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream), None)
        except OSError as exc:
            raise ProjectError(f"CSV 파일을 열지 못했습니다: {exc}") from exc
        if row is None:
            raise ProjectError("CSV에 계산 입력 행이 없습니다.")

        required = ("v_mm", "d_mm", "sensor_length_mm", "alpha_deg")
        missing = [key for key in required if not (row.get(key) or "").strip()]
        if missing:
            raise ProjectError(f"CSV 필수 열이 비어 있습니다: {', '.join(missing)}")
        try:
            numeric = {key: float(row[key]) for key in required}
        except ValueError as exc:
            raise ProjectError("CSV의 V, d, L, α는 숫자여야 합니다.") from exc
        if not all(math.isfinite(value) for value in numeric.values()):
            raise ProjectError("CSV 입력은 유한한 숫자여야 합니다.")
        if (
            numeric["v_mm"] <= 0.0
            or numeric["d_mm"] < 0.0
            or numeric["sensor_length_mm"] <= 0.0
            or not 0.0 < numeric["alpha_deg"] < 90.0
        ):
            raise ProjectError("CSV 입력 범위는 V>0, d≥0, L>0, 0<α<90°입니다.")

        values: dict[str, object] = {"mode": "workbook", **numeric}
        camera_id = (row.get("camera_id") or "").strip()
        sensor_axis = (row.get("sensor_axis") or "").strip()
        if camera_id:
            if self.design.input_panel.camera.findData(camera_id) < 0:
                raise ProjectError(f"CSV의 camera_id를 찾을 수 없습니다: {camera_id}")
            values["camera_id"] = camera_id
        if sensor_axis:
            if self.design.input_panel.sensor_axis.findData(sensor_axis) < 0:
                raise ProjectError("CSV의 sensor_axis는 height 또는 width여야 합니다.")
            values["sensor_axis"] = sensor_axis
        try:
            self.design.apply_project_input(values)
        except (LensPresetError, TypeError, ValueError) as exc:
            raise ProjectError(f"CSV 입력값을 적용할 수 없습니다: {exc}") from exc
        self.design.recalculate()
        self.tabs.setCurrentIndex(0)
        self._mark_dirty()
        self.statusBar().showMessage(f"워크북 입력 CSV를 불러왔습니다: {source}", 5_000)

    def export_workbook_csv_dialog(self) -> None:
        suggested = (self._project_path or Path.home() / self._project_name).with_suffix(".csv")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "워크북 계산 결과 CSV 내보내기",
            str(suggested),
            "CSV (*.csv)",
        )
        if not filename:
            return
        try:
            target = self.export_workbook_csv(filename)
        except ProjectError as exc:
            QMessageBox.critical(self, "CSV 내보내기 실패", str(exc))
            return
        self.statusBar().showMessage(f"계산 결과 CSV를 저장했습니다: {target}", 5_000)

    def export_workbook_csv(self, path: str | Path) -> Path:
        """Export one workbook-compatible input/result row with stable columns."""

        solution = self.design.solution
        if solution is None or solution.mode.value != "workbook":
            raise ProjectError("워크북 호환 계산 결과가 있어야 CSV로 내보낼 수 있습니다.")
        request = solution.request
        values = self.design.project_input()
        row = {
            "v_mm": request.v_mm,
            "d_mm": request.d_mm,
            "sensor_length_mm": request.sensor_length_mm,
            "alpha_deg": solution.alpha_deg,
            "beta_deg": solution.beta_deg,
            "baseline_mm": solution.baseline_mm,
            "half_sensor_x_mm": solution.x_far_mm,
            "width_w_mm": solution.width_exact_mm,
            "rear_r_mm": solution.rear_exact_mm,
            "fp_mm": solution.fp_mm,
            "lo_mm": solution.lo_mm,
            "ray_intercept_s_mm": solution.ray_intercept_s_mm,
            "f_derived_mm": solution.focal_length_mm,
            "total_lo_fp_mm": solution.total_optical_length_mm,
            "camera_id": values["camera_id"],
            "sensor_axis": values["sensor_axis"],
            "valid": solution.valid,
        }
        target = Path(path)
        if target.suffix.lower() != ".csv":
            target = target.with_suffix(".csv")
        try:
            with target.open("w", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
        except OSError as exc:
            raise ProjectError(f"CSV 파일을 저장하지 못했습니다: {exc}") from exc
        return target

    def export_png(self) -> None:
        self._export_scene("png")

    def export_svg(self) -> None:
        self._export_scene("svg")

    def _export_scene(self, kind: str) -> None:
        if self.design.solution is None:
            QMessageBox.warning(self, "내보내기", "먼저 유효한 계산을 완료하세요.")
            return
        suggested = (self._project_path or Path.home() / self._project_name).with_suffix(f".{kind}")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            f"{kind.upper()} 내보내기",
            str(suggested),
            f"{kind.upper()} (*.{kind})",
        )
        if not filename:
            return
        target = Path(filename).with_suffix(f".{kind}")
        try:
            if kind == "png":
                self.design.scene.export_png(target)
            else:
                self.design.scene.export_svg(target)
            snapshot = target.with_suffix(".snapshot.json")
            snapshot.write_text(
                json.dumps(
                    self.design.export_snapshot_dict(),
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "내보내기 실패", str(exc))
            return
        self.statusBar().showMessage(
            f"{target.name} 및 {snapshot.name} 저장 완료",
            5_000,
        )

    def show_about(self) -> None:
        QMessageBox.about(
            self,
            "Scheimpflug OptiMeter",
            f"<b>Scheimpflug OptiMeter {__version__}</b><br>"
            "워크북/CSV 기반 Scheimpflug 수치 계산·2D/3D 시각화 도구<br>"
            "정적 Basler 프로파일 FOV·샘플링·거리 민감도 비교<br>"
            "장치 연결이나 영상 측정 기능은 포함하지 않습니다.<br><br>"
            "Python 3.12 · PySide6 · Apache-2.0",
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt override
        if not self.maybe_save_changes():
            event.ignore()
            return
        self.design.shutdown()
        self._settings.setValue("window/geometry", self.saveGeometry())
        self._settings.setValue("window/state", self.saveState())
        event.accept()
