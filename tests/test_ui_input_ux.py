from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout

from scheimpflug_optimeter.ui.design import DesignInputPanel, OpticalCoreFacade


def test_input_labels_expose_name_variable_unit_and_context_help(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    expected_labels = {
        "mode": "계산 방식 · mode [선택]",
        "camera": "정적 센서 · camera [px/µm]",
        "sensor_axis": "삼각측량 축 · axis [width/height]",
        "lens": "Edmund M12 렌즈 · f [mm]",
        "v_mm": "워크북 기준 거리 · V [mm]",
        "d_mm": "워킹 디스턴스 · d [mm]",
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
    assert "레이저 발광 기준점" in panel.d_mm.toolTip()
    assert "FOV" in panel.sensor_axis.toolTip()
    assert "실제 카메라" in panel.camera.toolTip()
    assert panel.d_mm.accessibleDescription() == panel.d_mm.toolTip()
    assert panel.input_labels["alpha_deg"].accessibleDescription()


def test_formula_card_tracks_workbook_and_canonical_modes(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.show()

    assert panel.formula_card.title() == "현재 모드 핵심 수식"
    assert "Workbook Compatibility" in panel.formula_mode_title.text()
    assert "β=90°−α" in panel.formula_equations.text()
    assert "W=b+x" in panel.formula_equations.text()
    assert "1/f=1/lo+1/fp" in panel.formula_equations.text()
    assert "V 기준 거리" in panel.formula_variables.text()
    assert "L 이미지 길이" in panel.formula_variables.text()

    canonical_index = panel.mode.findData("canonical")
    panel.mode.setCurrentIndex(canonical_index)

    assert "Canonical Design" in panel.formula_mode_title.text()
    assert "r=tanβ/tanα" in panel.formula_equations.text()
    assert "x(s)" in panel.formula_equations.text()
    assert "L_required" in panel.formula_equations.text()
    assert "S 측정 범위" in panel.formula_variables.text()
    assert "β 센서 틸트각" in panel.formula_variables.text()
    assert panel.v_mm.isHidden()
    assert panel.sensor_length_container.isHidden()
    assert not panel.range_mm.isHidden()
    assert not panel.beta_deg.isHidden()


def test_input_help_remains_readable_in_narrow_scroll_panel(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.resize(315, 720)
    panel.show()

    assert panel.form.rowWrapPolicy() == QFormLayout.RowWrapPolicy.WrapLongRows
    assert panel.formula_equations.wordWrap()
    assert panel.formula_variables.wordWrap()
    assert (
        panel.formula_equations.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )
    assert (
        panel.formula_variables.textInteractionFlags()
        & Qt.TextInteractionFlag.TextSelectableByMouse
    )
    assert panel.formula_equations.accessibleName()
    assert panel.formula_variables.accessibleName()
    assert panel.minimumSizeHint().width() <= 315
    assert panel.camera.width() >= 132
    assert panel.d_mm.width() >= 132
    assert panel.sensor_length_container.width() >= 170
