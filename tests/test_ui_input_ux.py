from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QSizePolicy

from scheimpflug_optimeter.ui.design import DesignInputPanel, OpticalCoreFacade


def test_input_labels_expose_name_variable_unit_and_context_help(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    expected_labels = {
        "mode": "계산 방식 · mode [선택]",
        "camera": "정적 센서 · camera [px/µm]",
        "sensor_axis": "삼각측량 축 · axis [width/height]",
        "lens": "Edmund M12 렌즈 · f [mm]",
        "v_mm": "워크북 기준 높이/거리 · V [mm]",
        "d_mm": "워크북 WD 파라미터 · d [mm]",
        "sensor_length_mm": "센서/이미지 길이 · L [mm]",
        "alpha_deg": "수광각 · α [°]",
        "range_mm": "측정 범위 · S [mm]",
        "beta_deg": "센서 틸트각 · β [°]",
        "max_width_mm": "기구 최대 폭 · W_max [mm]",
        "max_rear_mm": "후방 허용 한계 · R_max [mm]",
        "wavelength_nm": "레이저 파장 · λ [nm]",
    }

    assert {key: label.text() for key, label in panel.input_labels.items()} == expected_labels
    assert panel.input_labels["d_mm"].toolTip() == panel.d_mm.toolTip()
    assert "R = V − d" in panel.d_mm.toolTip()
    assert "광학점 좌표를 잇는 추가 관계가 없습니다" in panel.d_mm.toolTip()
    assert "레이저 발광 기준점" not in panel.d_mm.toolTip()
    assert "워크북 기준 높이/거리 V" in panel.v_mm.toolTip()
    assert "FOV" in panel.sensor_axis.toolTip()
    assert "실제 카메라" in panel.camera.toolTip()
    assert panel.d_mm.accessibleDescription() == panel.d_mm.toolTip()
    assert panel.input_labels["alpha_deg"].accessibleDescription()


def test_formula_card_tracks_workbook_and_canonical_modes(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.show()

    assert panel.formula_card.title() == "워크북 호환 · 핵심 수식"
    assert panel.formula_mode_summary.text() == "V · d · L · α 직접 입력"
    workbook_equations = {
        category.text(): equation.text()
        for category, equation in panel.formula_equation_rows
        if category.isVisible()
    }
    assert workbook_equations["각도"] == "β = 90° − α"
    assert workbook_equations["베이스"] == "b = V tan α · x = L/2"
    assert "W = b + x" in workbook_equations["외곽"]
    assert workbook_equations["렌즈"] == "1/f = 1/lo + 1/fp"
    assert panel.formula_variables.text() == "변수 · V · d · L · α · β · s  ⓘ"
    assert "V — 워크북 기준 높이/거리 [mm]" in panel.formula_variables.toolTip()
    assert "d — 워크북 WD 파라미터 [mm]" in panel.formula_variables.toolTip()
    assert "β — 유도 결상각 [°]" in panel.formula_variables.toolTip()
    assert (
        "s — 센서 가장자리 광선의 레이저축 교차값; 화면에는 거리 |s| 표시 [mm]"
        in panel.formula_variables.toolTip()
    )
    assert "입력하세요" in panel.mode_help.text()
    assert "자동 갱신" in panel.mode_help.text()
    assert "XLSX" not in panel.mode_help.text()
    assert "CSV" not in panel.mode_help.text()

    canonical_index = panel.mode.findData("canonical")
    panel.mode.setCurrentIndex(canonical_index)

    assert panel.formula_card.title() == "Canonical 설계 · 핵심 수식"
    assert panel.formula_mode_summary.text() == "f · α · β · S 입력"
    canonical_equations = {
        category.text(): equation.text()
        for category, equation in panel.formula_equation_rows
        if category.isVisible()
    }
    assert canonical_equations["비율"] == "r = tan β / tan α"
    assert "x(s)" in canonical_equations["투영"]
    assert "L_required" in canonical_equations["센서"]
    assert "S — 측정 범위 [mm]" in panel.formula_variables.toolTip()
    assert "β — 센서 틸트각 [°]" in panel.formula_variables.toolTip()
    assert "선택하세요" in panel.mode_help.text()
    assert "최적화를 실행하세요" in panel.mode_help.text()
    assert panel.v_mm.isHidden()
    assert panel.sensor_length_container.isHidden()
    assert not panel.range_mm.isHidden()
    assert not panel.beta_deg.isHidden()


def test_input_help_remains_readable_in_narrow_scroll_panel(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.resize(315, 1400)
    panel.show()

    assert panel.form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows
    assert all(equation.wordWrap() for _, equation in panel.formula_equation_rows)
    assert all(
        equation.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
        for _, equation in panel.formula_equation_rows
    )
    assert panel.formula_variables.accessibleName()
    assert panel.formula_variables.accessibleDescription()
    assert (
        panel.formula_variables.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )
    assert panel.formula_mode_summary.accessibleName()
    assert panel.formula_card.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Maximum
    assert not panel.formula_mode_summary.wordWrap()
    assert panel.formula_mode_summary.sizePolicy().horizontalPolicy() == (
        QSizePolicy.Policy.Maximum
    )
    assert panel.formula_card.height() <= 260
    assert panel.formula_card.font().pointSizeF() <= 8.8
    assert max(equation.font().pointSizeF() for _, equation in panel.formula_equation_rows) <= 9.5
    assert panel.minimumSizeHint().width() <= 315
    assert panel.mode.width() >= 240
    assert panel.camera.width() >= 240
    assert panel.sensor_axis.width() >= 240
    assert panel.d_mm.width() >= 132
    assert panel.sensor_length_container.width() >= 170
