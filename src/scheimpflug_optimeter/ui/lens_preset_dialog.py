"""Editor for project-local, user-defined lens presets.

The dialog never mutates the immutable hardware catalog.  Opening an official
``LensProfile`` creates a detached ``UserLensPreset`` copy, while opening an
existing user preset keeps its stable id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from scheimpflug_optimeter.lens_presets import LensPresetError, UserLensPreset
from scheimpflug_optimeter.models import LensProfile


@dataclass(frozen=True, slots=True)
class _NumberField:
    key: str
    korean_name: str
    variable: str
    unit: str
    signed: bool = False


_OPTIONAL_FIELDS = (
    _NumberField("aperture_f_number", "조리개값", "F/#", "—"),
    _NumberField("image_circle_mm", "이미지 서클", "IC", "mm"),
    _NumberField("wavelength_min_nm", "사용 파장 하한", "λ_min", "nm"),
    _NumberField("wavelength_max_nm", "사용 파장 상한", "λ_max", "nm"),
    _NumberField("working_distance_min_mm", "권장 WD 하한", "WD_min", "mm"),
    _NumberField("working_distance_max_mm", "권장 WD 상한", "WD_max", "mm"),
    _NumberField("resolution_lp_per_mm", "공간 해상력", "R_lens", "lp/mm"),
    _NumberField("outer_diameter_mm", "최대 외경", "D", "mm"),
    _NumberField("overall_length_mm", "전체 길이", "OAL", "mm"),
    _NumberField("weight_g", "중량", "m", "g"),
    _NumberField("front_housing_length_mm", "전면 하우징 길이", "L_front", "mm"),
    _NumberField("threaded_section_length_mm", "나사부 길이", "L_thread", "mm"),
    _NumberField("thread_major_diameter_mm", "나사 바깥지름", "D_thread", "mm"),
    _NumberField("thread_pitch_mm", "나사 피치", "P_thread", "mm"),
    _NumberField(
        "first_object_surface_recess_from_front_housing_mm",
        "전면에서 첫 광학면까지 깊이",
        "Front→S1",
        "mm",
    ),
    _NumberField(
        "object_principal_plane_from_first_object_surface_mm",
        "물체측 주평면 위치",
        "S1→H",
        "mm (부호 있음)",
        signed=True,
    ),
    _NumberField(
        "image_principal_plane_from_last_image_surface_mm",
        "상측 주평면 위치",
        "SL→H′",
        "mm (부호 있음)",
        signed=True,
    ),
    _NumberField("back_focal_length_min_mm", "후초점거리 하한", "BFL_min", "mm"),
    _NumberField("back_focal_length_max_mm", "후초점거리 상한", "BFL_max", "mm"),
)

_MECHANICAL_LABELS = {
    "outer_diameter_mm": "최대 외경 D",
    "overall_length_mm": "전체 길이 OAL",
    "front_housing_length_mm": "전면 하우징 길이 L_front",
    "threaded_section_length_mm": "나사부 길이 L_thread",
    "thread_major_diameter_mm": "나사 바깥지름 D_thread",
    "thread_pitch_mm": "나사 피치 P_thread",
    "first_object_surface_recess_from_front_housing_mm": "전면→첫 광학면 Front→S1",
    "object_principal_plane_from_first_object_surface_mm": "물체측 주평면 S1→H",
}


class LensPresetDialog(QDialog):
    """Edit a catalog lens copy or an existing :class:`UserLensPreset`."""

    def __init__(
        self,
        source: LensProfile | UserLensPreset,
        parent: QWidget | None = None,
        *,
        new_preset: bool = False,
    ) -> None:
        super().__init__(parent)
        if not isinstance(source, (LensProfile, UserLensPreset)):
            raise TypeError("source must be a LensProfile or UserLensPreset.")

        self.source = source
        self.is_catalog_copy = isinstance(source, LensProfile)
        self.is_new_preset = bool(new_preset)
        if self.is_catalog_copy and self.is_new_preset:
            raise ValueError("new_preset is only valid with a blank UserLensPreset.")
        self._id_is_editable = self.is_catalog_copy or self.is_new_preset
        self._base_preset = (
            UserLensPreset.from_lens_profile(
                source,
                user_id=_catalog_copy_id(source),
                name=f"{source.name} 사용자 프리셋",
            )
            if isinstance(source, LensProfile)
            else source
        )
        self._current_preset: UserLensPreset | None = None
        self._accepted_preset: UserLensPreset | None = None
        self.optional_checks: dict[str, QCheckBox] = {}
        self.numeric_inputs: dict[str, QDoubleSpinBox] = {}

        self.setObjectName("lensPresetDialog")
        self.setWindowTitle("사용자 렌즈 프리셋")
        self.setAccessibleName("사용자 렌즈 프리셋 편집")
        self.setAccessibleDescription(
            "광학값과 선택적인 기구 치수 및 H, H′ 주평면 좌표를 편집합니다."
        )
        self.resize(780, 680)
        self.setMinimumSize(600, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        if self.is_new_preset:
            intro_text = (
                "공식 출처를 상속하지 않는 새 프로젝트 프리셋입니다. "
                "체크를 끈 선택 치수는 ‘미입력’으로 저장됩니다."
            )
        elif self.is_catalog_copy:
            intro_text = (
                "공식 카탈로그는 변경하지 않습니다. 이 렌즈는 사용자 프리셋으로 "
                "복제되며, 저장한 값은 공급사 검증값으로 표시하지 않습니다."
            )
        else:
            intro_text = (
                "프로젝트 사용자 프리셋을 편집합니다. 체크를 끈 선택 치수는 "
                "‘미입력’으로 저장되며 공식 카탈로그에는 영향이 없습니다."
            )
        intro = QLabel(intro_text)
        intro.setObjectName("lensPresetIntroduction")
        intro.setWordWrap(True)
        intro.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(intro)

        scroll = QScrollArea()
        scroll.setObjectName("lensPresetScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setAccessibleName("렌즈 프리셋 입력 영역")
        root.addWidget(scroll, 1)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(4, 4, 4, 4)
        content_layout.setSpacing(10)
        scroll.setWidget(content)

        identity_group = QGroupBox("프리셋 식별 및 필수 광학값")
        identity_layout = QGridLayout(identity_group)
        identity_layout.setColumnStretch(0, 2)
        identity_layout.setColumnStretch(1, 1)
        identity_layout.setColumnStretch(2, 1)
        identity_layout.setColumnStretch(3, 1)
        self._add_headers(identity_layout, has_use_column=False)

        self.user_id_edit = self._line_edit("프리셋 ID user_id")
        self.name_edit = self._line_edit("프리셋 이름 name")
        self.manufacturer_edit = self._line_edit("제조사 manufacturer")
        self.sku_edit = self._line_edit("제품 번호 sku")
        self.mount_edit = self._line_edit("렌즈 마운트 mount")
        self.thread_tolerance_edit = self._line_edit("나사 공차 등급 thread_tolerance_class")
        self.focal_length_spin = self._number_input(
            "초점거리 focal_length_mm",
            signed=False,
        )
        self.numeric_inputs["focal_length_mm"] = self.focal_length_spin

        self._add_text_row(
            identity_layout,
            1,
            "프리셋 ID",
            "user_id",
            self.user_id_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            2,
            "프리셋 이름",
            "name",
            self.name_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            3,
            "제조사",
            "manufacturer",
            self.manufacturer_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            4,
            "제품 번호",
            "sku",
            self.sku_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            5,
            "렌즈 마운트",
            "mount",
            self.mount_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            6,
            "나사 공차 등급",
            "thread_tolerance_class",
            self.thread_tolerance_edit,
            "—",
        )
        self._add_text_row(
            identity_layout,
            7,
            "초점거리",
            "f",
            self.focal_length_spin,
            "mm",
        )
        content_layout.addWidget(identity_group)

        parameter_group = QGroupBox("선택 광학값 및 기구 형상")
        parameter_layout = QGridLayout(parameter_group)
        parameter_layout.setColumnStretch(0, 2)
        parameter_layout.setColumnStretch(1, 1)
        parameter_layout.setColumnStretch(3, 1)
        parameter_layout.setColumnStretch(4, 1)
        self._add_headers(parameter_layout, has_use_column=True)
        for row, field in enumerate(_OPTIONAL_FIELDS, start=1):
            self._add_optional_number_row(parameter_layout, row, field)
        content_layout.addWidget(parameter_group)

        datum_group = QGroupBox("주평면 좌표 기준면 (고정)")
        datum_layout = QVBoxLayout(datum_group)
        self.object_datum_label = self._datum_label(
            "S1→H: S1은 물체측 첫 번째 광학면입니다. 하우징 전면이나 나사 어깨가 "
            "아니며, 광축 방향의 부호 있는 거리입니다.",
            "S1에서 H까지의 고정 좌표 기준 설명",
        )
        self.image_datum_label = self._datum_label(
            "SL→H′: SL은 상측 마지막 광학면입니다. 센서면이나 하우징 후면이 아니며, "
            "광축 방향의 부호 있는 거리입니다.",
            "SL에서 H′까지의 고정 좌표 기준 설명",
        )
        datum_layout.addWidget(self.object_datum_label)
        datum_layout.addWidget(self.image_datum_label)
        content_layout.addWidget(datum_group)
        content_layout.addStretch(1)

        self.validation_label = QLabel()
        self.validation_label.setObjectName("lensPresetValidation")
        self.validation_label.setAccessibleName("렌즈 프리셋 실시간 검증 상태")
        self.validation_label.setWordWrap(True)
        self.validation_label.setFrameShape(QFrame.Shape.StyledPanel)
        self.validation_label.setMargin(10)
        self.validation_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.validation_label.setStyleSheet(
            """
            QLabel#lensPresetValidation[state="valid"] {
                color: #155f3c;
                background: #e8f7ee;
                border: 1px solid #8dcaaa;
                border-radius: 5px;
            }
            QLabel#lensPresetValidation[state="warning"] {
                color: #6b4b00;
                background: #fff6d8;
                border: 1px solid #d8b951;
                border-radius: 5px;
            }
            QLabel#lensPresetValidation[state="error"] {
                color: #8a1f28;
                background: #ffe8ea;
                border: 1px solid #df9ca2;
                border-radius: 5px;
            }
            """
        )
        root.addWidget(self.validation_label)

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        self.button_box.setObjectName("lensPresetButtons")
        self.save_button = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        self.cancel_button = self.button_box.button(QDialogButtonBox.StandardButton.Cancel)
        self.save_button.setText("저장")
        self.cancel_button.setText("취소")
        self.save_button.setAccessibleName("렌즈 프리셋 저장")
        self.cancel_button.setAccessibleName("렌즈 프리셋 편집 취소")
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

        self._populate(self._base_preset)
        self._connect_validation()
        self._validate()

    @staticmethod
    def _add_headers(layout: QGridLayout, *, has_use_column: bool) -> None:
        headers = (
            ("한글 항목", 0),
            ("수식/데이터 변수", 1),
            *((("사용", 2),) if has_use_column else ()),
            (("값", 3) if has_use_column else ("값", 2)),
            (("단위", 4) if has_use_column else ("단위", 3)),
        )
        for text, column in headers:
            label = QLabel(text)
            label.setProperty("role", "tableHeader")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(label, 0, column)

    @staticmethod
    def _line_edit(accessible_name: str) -> QLineEdit:
        editor = QLineEdit()
        editor.setAccessibleName(accessible_name)
        editor.setMinimumWidth(80)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return editor

    @staticmethod
    def _number_input(accessible_name: str, *, signed: bool) -> QDoubleSpinBox:
        editor = QDoubleSpinBox()
        editor.setAccessibleName(accessible_name)
        editor.setDecimals(6)
        editor.setSingleStep(0.1)
        editor.setRange(-1_000_000.0 if signed else 0.0, 1_000_000.0)
        editor.setKeyboardTracking(True)
        editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        editor.setMinimumWidth(80)
        editor.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        return editor

    @staticmethod
    def _add_text_row(
        layout: QGridLayout,
        row: int,
        korean_name: str,
        variable: str,
        editor: QWidget,
        unit: str,
    ) -> None:
        name_label = QLabel(korean_name)
        name_label.setWordWrap(True)
        name_label.setMinimumWidth(0)
        name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(name_label, row, 0)
        variable_label = QLabel(variable)
        variable_label.setWordWrap(True)
        variable_label.setMinimumWidth(0)
        variable_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        variable_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(variable_label, row, 1)
        layout.addWidget(editor, row, 2)
        unit_label = QLabel(unit)
        unit_label.setWordWrap(True)
        unit_label.setMinimumWidth(0)
        unit_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(unit_label, row, 3)

    def _add_optional_number_row(
        self,
        layout: QGridLayout,
        row: int,
        field: _NumberField,
    ) -> None:
        name_label = QLabel(field.korean_name)
        name_label.setWordWrap(True)
        name_label.setMinimumWidth(0)
        name_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        variable_label = QLabel(field.variable)
        variable_label.setWordWrap(True)
        variable_label.setMinimumWidth(0)
        variable_label.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        variable_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        enabled = QCheckBox()
        enabled.setAccessibleName(f"{field.korean_name} {field.variable} 값 사용")
        enabled.setToolTip("체크를 끄면 이 값은 미입력(None)으로 저장됩니다.")
        editor = self._number_input(
            f"{field.korean_name} {field.variable}",
            signed=field.signed,
        )
        editor.setToolTip(
            "부호 있는 광학면 기준 좌표입니다."
            if field.signed
            else "체크한 경우 유한한 유효값이어야 합니다."
        )
        self.optional_checks[field.key] = enabled
        self.numeric_inputs[field.key] = editor
        setattr(self, f"{field.key}_enabled", enabled)
        setattr(self, f"{field.key}_spin", editor)

        layout.addWidget(name_label, row, 0)
        layout.addWidget(variable_label, row, 1)
        layout.addWidget(enabled, row, 2, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(editor, row, 3)
        unit_label = QLabel(field.unit)
        unit_label.setWordWrap(True)
        unit_label.setMinimumWidth(0)
        unit_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(unit_label, row, 4)

    @staticmethod
    def _datum_label(text: str, accessible_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("lensDatumExplanation")
        label.setAccessibleName(accessible_name)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    def _populate(self, preset: UserLensPreset) -> None:
        self.user_id_edit.setText(preset.user_id)
        self.name_edit.setText(preset.name)
        self.manufacturer_edit.setText(preset.manufacturer)
        self.sku_edit.setText(preset.sku or "")
        self.mount_edit.setText(preset.mount)
        self.thread_tolerance_edit.setText(preset.thread_tolerance_class or "")
        for editor in (
            self.user_id_edit,
            self.name_edit,
            self.manufacturer_edit,
            self.sku_edit,
            self.mount_edit,
            self.thread_tolerance_edit,
        ):
            editor.setCursorPosition(0)
        self.focal_length_spin.setValue(preset.focal_length_mm)
        if not self._id_is_editable:
            self.user_id_edit.setReadOnly(True)
            self.user_id_edit.setToolTip(
                "기존 사용자 프리셋의 안정적인 참조를 위해 user_id는 유지됩니다."
            )

        for field in _OPTIONAL_FIELDS:
            value = getattr(preset, field.key)
            check = self.optional_checks[field.key]
            editor = self.numeric_inputs[field.key]
            check.setChecked(value is not None)
            editor.setEnabled(value is not None)
            if value is not None:
                editor.setValue(value)

    def _connect_validation(self) -> None:
        for editor in (
            self.user_id_edit,
            self.name_edit,
            self.manufacturer_edit,
            self.sku_edit,
            self.mount_edit,
            self.thread_tolerance_edit,
        ):
            editor.textChanged.connect(self._validate)
        self.focal_length_spin.valueChanged.connect(self._validate)
        for key, check in self.optional_checks.items():
            editor = self.numeric_inputs[key]
            check.toggled.connect(editor.setEnabled)
            check.toggled.connect(self._validate)
            editor.valueChanged.connect(self._validate)

    def set_optional_value(self, field_name: str, value: float | None) -> None:
        """Set one nullable numeric field using its ``UserLensPreset`` name."""

        try:
            check = self.optional_checks[field_name]
            editor = self.numeric_inputs[field_name]
        except KeyError as exc:
            raise KeyError(f"Unknown optional lens field: {field_name!r}") from exc
        check.setChecked(value is not None)
        if value is not None:
            editor.setValue(value)
        self._validate()

    def optional_value(self, field_name: str) -> float | None:
        """Return a nullable numeric field exactly as it would be saved."""

        try:
            check = self.optional_checks[field_name]
            editor = self.numeric_inputs[field_name]
        except KeyError as exc:
            raise KeyError(f"Unknown optional lens field: {field_name!r}") from exc
        return editor.value() if check.isChecked() else None

    def _build_preset(self) -> UserLensPreset:
        values = {field.key: self.optional_value(field.key) for field in _OPTIONAL_FIELDS}
        user_edit_note = "Project-local user-edited values; not supplier-verified after copying."
        provenance_notes = self._base_preset.provenance_notes
        if user_edit_note not in provenance_notes:
            provenance_notes = (*provenance_notes, user_edit_note)
        return replace(
            self._base_preset,
            user_id=(
                self.user_id_edit.text().strip()
                if self._id_is_editable
                else self._base_preset.user_id
            ),
            name=self.name_edit.text().strip(),
            manufacturer=self.manufacturer_edit.text().strip(),
            sku=self.sku_edit.text().strip() or None,
            mount=self.mount_edit.text().strip(),
            thread_tolerance_class=(self.thread_tolerance_edit.text().strip() or None),
            focal_length_mm=self.focal_length_spin.value(),
            # Keep source_profile_id/source_url only as an origin audit trail.
            # A project-edited value must not be presented as a supplier-
            # verified drawing or specification.
            mechanical_drawing_id=None,
            mechanical_source_url=None,
            source_verified_on=None,
            provenance_notes=provenance_notes,
            **values,
        )

    def _validate(self, *_args: object) -> UserLensPreset | None:
        try:
            preset = self._build_preset()
        except LensPresetError as exc:
            self._current_preset = None
            self.validation_label.setProperty("state", "error")
            self.validation_label.setText(f"오류 — 저장할 수 없습니다.\n{exc}")
            self.save_button.setEnabled(False)
            self._refresh_validation_style()
            return None

        self._current_preset = preset
        status = preset.mechanical_rendering_status
        messages: list[str] = []
        details: list[str] = []
        if status.missing_fields:
            missing = ", ".join(
                _MECHANICAL_LABELS.get(field, field) for field in status.missing_fields
            )
            messages.append(
                f"기구 필수값 {len(status.missing_fields)}개 미입력 · "
                "광학 계산 가능, 3D 실치수 외형 비활성"
            )
            details.append(f"미입력: {missing}")
        for issue in status.issues:
            if issue.code == "segment_length_mismatch":
                messages.append("L_front + L_thread ≠ OAL · 3D 실치수 외형 비활성")
                details.append(issue.message)
            elif issue.code == "first_surface_outside_front_housing":
                messages.append("Front→S1이 전면 하우징보다 큼 · 기준/부호 확인")
                details.append(issue.message)
            else:
                messages.append(issue.message)
                details.append(issue.message)
        if status.enabled and not status.principal_planes_enabled:
            messages.append("SL→H′ 미입력 · 실제 H′ 표시 비활성")

        if messages:
            self.validation_label.setProperty("state", "warning")
            self.validation_label.setText("경고 — 저장 가능 · " + " / ".join(messages))
            self.validation_label.setToolTip("\n".join((*messages, *details)))
        else:
            self.validation_label.setProperty("state", "valid")
            self.validation_label.setText(
                "검증 통과 — 광학값, 기구 구간 및 주평면 기준이 일관됩니다."
            )
            self.validation_label.setToolTip(self.validation_label.text())
        self.save_button.setEnabled(True)
        self._refresh_validation_style()
        return preset

    def _refresh_validation_style(self) -> None:
        style = self.validation_label.style()
        style.unpolish(self.validation_label)
        style.polish(self.validation_label)

    def current_preset(self) -> UserLensPreset | None:
        """Return the live validated value, or ``None`` while input is invalid."""

        return self._current_preset

    def preset(self) -> UserLensPreset:
        """Return the accepted preset, or the current valid preview value."""

        if self._accepted_preset is not None:
            return self._accepted_preset
        preset = self._validate()
        if preset is None:
            raise LensPresetError("The dialog currently contains invalid values.")
        return preset

    def result_preset(self) -> UserLensPreset:
        """Alias used by callers after ``exec()`` returns ``Accepted``."""

        return self.preset()

    def accept(self) -> None:
        """Accept only after constructing a fully valid optical preset."""

        preset = self._validate()
        if preset is None:
            return
        self._accepted_preset = preset
        super().accept()


def _catalog_copy_id(profile: LensProfile) -> str:
    raw = f"{profile.id}-copy"
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-._")
    if not sanitized or not sanitized[0].isalnum():
        sanitized = f"lens-{sanitized}" if sanitized else "lens-copy"
    return sanitized[:64]


__all__ = ["LensPresetDialog"]
