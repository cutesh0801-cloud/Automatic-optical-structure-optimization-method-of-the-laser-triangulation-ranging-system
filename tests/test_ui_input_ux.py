from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from scheimpflug_optimeter.hardware import get_lens
from scheimpflug_optimeter.lens_presets import UserLensPreset
from scheimpflug_optimeter.ui.design import (
    DesignInputPanel,
    DesignWidget,
    OpticalCoreFacade,
)
from scheimpflug_optimeter.ui.lens_preset_dialog import LensPresetDialog


def test_workbook_sheet_exposes_excel_columns_and_only_workbook_mode(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.resize(420, 700)
    panel.show()

    headers = tuple(
        panel.worksheet_table.horizontalHeaderItem(column).text()
        for column in range(panel.worksheet_table.columnCount())
    )
    assert headers == ("구분", "한글 항목", "변수", "값", "단위/출처")
    assert not hasattr(panel, "mode")
    assert panel.values()["mode"] == "workbook"
    assert panel.camera.currentData() == "basler-aca1300-60gm"
    assert panel.lens.currentData() == "edmund-58-206"
    assert panel.v_mm.value() == pytest.approx(150.0)
    assert panel.focal_length_mm.value() == pytest.approx(17.5)

    assert not panel.focal_length_mm.isEnabled()
    assert panel.v_mm.isEnabled()
    assert panel.d_mm.isEnabled()
    assert not panel.sensor_length_mm.isEnabled()
    assert not panel.alpha_deg.isEnabled()

    result = panel._result_items["baseline"]
    assert result.flags() & Qt.ItemFlag.ItemIsEnabled
    assert result.flags() & Qt.ItemFlag.ItemIsSelectable
    assert not result.flags() & Qt.ItemFlag.ItemIsEditable
    assert result.background().color() == panel.RESULT_BACKGROUND
    assert "연노랑" in panel.mode_help.text()
    assert "회색" in panel.mode_help.text()


def test_auto_and_manual_alpha_have_explicit_values_contract(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    automatic = panel.values()
    assert automatic["mode"] == "workbook"
    assert automatic["alpha_deg"] is None
    assert automatic["alpha_manual"] is False
    assert automatic["focal_length_literal_mm"] == pytest.approx(17.5)

    panel.manual_alpha_toggle.setChecked(True)
    panel.alpha_deg.setValue(14.27)

    manual = panel.values()
    assert manual["alpha_manual"] is True
    assert manual["alpha_deg"] == pytest.approx(14.27)
    assert panel.alpha_deg.isEnabled()
    assert "사용자 입력" in panel._source_items["alpha_input"].text()

    panel.manual_alpha_toggle.setChecked(False)

    assert panel.values()["alpha_deg"] is None
    assert not panel.alpha_deg.isEnabled()
    assert "f/V" in panel._source_items["alpha_input"].text()


def test_focal_length_defaults_to_selected_lens_and_override_is_explicit(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    assert panel.focal_length_link_toggle.isChecked()
    assert not panel.focal_length_mm.isEnabled()
    panel.lens.setCurrentIndex(panel.lens.findData("edmund-33-879"))
    assert panel.focal_length_mm.value() == pytest.approx(12.0)
    assert panel.values()["focal_length_linked"] is True

    panel.focal_length_link_toggle.setChecked(False)
    panel.focal_length_mm.setValue(12.4)
    assert panel.focal_length_mm.isEnabled()
    assert panel.values()["focal_length_linked"] is False
    assert panel.values()["focal_length_literal_mm"] == pytest.approx(12.4)
    assert "override" in panel._source_items["f"].text()


def test_linked_custom_focal_is_not_clamped_or_rounded_in_calculation(qtbot):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    preset = UserLensPreset(
        user_id="long-focal",
        name="Long focal prototype",
        focal_length_mm=2000.123456789,
        mount="M12x0.5",
    )
    widget.input_panel.v_mm.setValue(10_000.0)
    widget.input_panel.add_or_replace_user_lens_preset(preset)
    widget.recalculate()

    assert widget.input_panel.focal_length_mm.value() == pytest.approx(2000.123457)
    assert widget.input_panel.values()["focal_length_literal_mm"] == pytest.approx(
        2000.123456789,
        rel=0,
        abs=1e-12,
    )
    assert widget.solution is not None
    assert widget.solution.request.focal_length_literal_mm == pytest.approx(
        2000.123456789,
        rel=0,
        abs=1e-12,
    )


def test_formula_panel_is_large_typeset_and_tracks_live_solution(qtbot):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    widget.resize(1100, 650)
    widget.show()
    qtbot.waitUntil(lambda: widget.solution is not None, timeout=5_000)

    panel = widget.input_panel
    equations = {
        category.text(): equation.text() for category, equation in panel.formula_equation_rows
    }
    assert panel.formula_card.title() == "■ 설계 주요 공식"
    assert equations == {
        "렌즈식": "1/l₀ + 1/fₚ = 1/f",
        "결상 기하": "l₀ tan α = fₚ tan β",
        "자동 α": "sin² α cos α = f/V",
    }
    assert "f = 17.5 mm" in panel.formula_known.text()
    assert "V = 150 mm" in panel.formula_known.text()
    assert panel.formula_mode_summary.text() == "f / V 자동 α"
    assert all(equation.font().pointSizeF() >= 12.0 for _, equation in panel.formula_equation_rows)
    assert panel.formula_card.height() >= 218
    assert "유도 보각/결상 기하각" in panel.formula_variables.text()
    assert "틸트" not in panel.formula_variables.text()
    assert "thin-lens" in panel.formula_variables.text()
    assert all(item.text() != "—" for item in panel._formula_result_items.values())


def test_worksheet_narrow_mode_hides_suffixes_and_restores_full_excel_columns(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)
    panel.resize(420, 700)
    panel.show()
    qtbot.wait(1)

    assert panel.worksheet_table.isColumnHidden(0)
    assert panel.worksheet_table.isColumnHidden(4)
    assert panel.focal_length_mm.suffix() == ""
    assert panel.sensor_length_mm.suffix() == ""
    assert "mm" in panel._source_items["f"].toolTip()

    panel.resize(620, 700)
    qtbot.wait(1)
    assert not panel.worksheet_table.isColumnHidden(0)
    assert not panel.worksheet_table.isColumnHidden(4)
    assert panel.focal_length_mm.suffix() == " mm"
    assert panel.alpha_deg.suffix() == "°"


def test_sensor_catalog_rows_and_linked_l_update_together(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    assert panel._result_items["sensor_width_px"].text() == "1282"
    assert panel._result_items["sensor_height_px"].text() == "1026"
    assert float(panel._result_items["sensor_pitch"].text()) == pytest.approx(5.3)
    assert float(panel._result_items["sensor_width"].text()) == pytest.approx(6.7946)
    assert float(panel._result_items["sensor_height"].text()) == pytest.approx(5.4378)
    assert panel.sensor_length_mm.value() == pytest.approx(5.4378)

    dart_index = panel.camera.findData("basler-daa1280-54um")
    panel.camera.setCurrentIndex(dart_index)

    assert panel._result_items["sensor_width_px"].text() == "1280"
    assert panel._result_items["sensor_height_px"].text() == "960"
    assert panel.sensor_length_mm.value() == pytest.approx(3.6)

    panel.sensor_link_toggle.setChecked(False)
    panel.sensor_length_mm.setValue(7.0)
    panel.sensor_axis.setCurrentIndex(panel.sensor_axis.findData("width"))

    assert panel.sensor_length_mm.value() == pytest.approx(7.0)
    assert panel.sensor_length_mm.isEnabled()
    assert "사용자 입력" in panel._source_items["sensor_length"].text()


def test_solution_populates_optics_sensor_and_principal_plane_rows(qtbot):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    widget.show()
    qtbot.waitUntil(lambda: widget.solution is not None, timeout=5_000)

    panel = widget.input_panel
    for key in (
        "beta",
        "baseline",
        "half_sensor",
        "width",
        "rear",
        "lo",
        "fp",
        "total",
        "ray_intercept",
        "f_calc",
        "delta_f",
        "lens_x",
        "lens_z",
        "lens_front_x",
        "lens_front_z",
        "lens_rear_x",
        "lens_rear_z",
        "front_to_h",
        "catalog_h",
        "catalog_h_prime",
        "fov_x",
        "fov_y",
        "sampling_x",
        "sampling_y",
        "sensitivity_center",
        "sensitivity_worst",
    ):
        assert panel._result_items[key].text() != "—", key

    assert float(panel._result_items["lens_x"].text()) == pytest.approx(
        widget.snapshot.lens_center.x_mm,
        rel=1e-5,
    )
    assert float(panel._result_items["lens_z"].text()) == pytest.approx(
        widget.snapshot.lens_center.z_mm,
        rel=1e-5,
    )
    assert "H = H′ @" in panel._result_items["principal_planes"].text()
    assert "thin-lens" in panel._source_items["principal_planes"].text()
    assert widget.snapshot.lens_mechanics is not None
    assert widget.snapshot.lens_mechanics.sku == "58-206"
    assert float(panel._result_items["front_to_h"].text()) == pytest.approx(5.87)
    assert float(panel._result_items["catalog_h"].text()) == pytest.approx(5.57)
    assert float(panel._result_items["catalog_h_prime"].text()) == pytest.approx(-12.71)
    assert "외부 하우징이 아닙니다" in panel._result_items["catalog_h_prime"].toolTip()
    assert "기하" in panel._source_items["sensitivity_center"].text()


def test_apply_values_preserves_exact_workbook_mode_and_link_override(qtbot):
    panel = DesignInputPanel(OpticalCoreFacade())
    qtbot.addWidget(panel)

    panel.apply_values(
        {
            "mode": "workbook",
            "camera_id": "basler-aca1300-60gm",
            "lens_id": "edmund-33-879",
            "sensor_axis": "height",
            "focal_length_literal_mm": 12.0,
            "v_mm": 205.0,
            "d_mm": 100.0,
            "sensor_length_mm": 3.0,
            "sensor_length_linked": False,
            "alpha_manual": True,
            "alpha_deg": 14.27,
        }
    )
    values = panel.values()

    assert values["mode"] == "workbook"
    assert values["lens_id"] == "edmund-33-879"
    assert values["focal_length_literal_mm"] == pytest.approx(12.0)
    assert values["v_mm"] == pytest.approx(205.0)
    assert values["sensor_length_mm"] == pytest.approx(3.0)
    assert values["sensor_length_linked"] is False
    assert values["alpha_deg"] == pytest.approx(14.27)


def test_project_user_lens_preset_is_editable_round_trips_and_drives_geometry(
    qtbot,
):
    source = get_lens("edmund-58-206")
    preset = UserLensPreset.from_lens_profile(
        source,
        user_id="prototype-175",
        name="시제품 17.5",
    )
    preset = replace(
        preset,
        focal_length_mm=18.0,
        object_principal_plane_from_first_object_surface_mm=6.0,
    )
    first = DesignWidget()
    qtbot.addWidget(first)
    first.input_panel.add_or_replace_user_lens_preset(preset)
    first.recalculate()

    assert first.input_panel.lens.currentData() == "user-lens:prototype-175"
    assert first.solution is not None
    assert first.solution.request.focal_length_literal_mm == pytest.approx(18.0)
    assert first.snapshot.lens_mechanics is not None
    assert first.snapshot.lens_mechanics.object_principal_from_first_surface_mm == pytest.approx(
        6.0
    )

    saved_values = first.project_input()
    second = DesignWidget()
    qtbot.addWidget(second)
    second.apply_project_input(saved_values)
    second.recalculate()

    assert second.input_panel.lens.currentData() == "user-lens:prototype-175"
    assert second.input_panel.user_lens_presets() == (preset,)
    assert second.solution.focal_length_mm == pytest.approx(first.solution.focal_length_mm)


def test_lens_selector_clones_then_directly_edits_project_preset(
    qtbot,
    monkeypatch,
):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    panel = widget.input_panel
    panel.lens.setCurrentIndex(panel.lens.findData("edmund-58-206"))

    def accept_clone(dialog: LensPresetDialog) -> QDialog.DialogCode:
        dialog.user_id_edit.setText("my-shop-lens")
        dialog.name_edit.setText("조립 실측 17.8 mm")
        dialog.focal_length_spin.setValue(17.8)
        dialog.set_optional_value("image_circle_mm", 8.0)
        dialog.set_optional_value("working_distance_min_mm", 80.0)
        dialog.set_optional_value("working_distance_max_mm", 250.0)
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LensPresetDialog, "exec", accept_clone)
    panel.edit_lens_preset_action.trigger()

    assert panel.lens.currentData() == "user-lens:my-shop-lens"
    saved = panel.selected_user_lens_preset()
    assert saved is not None
    assert saved.focal_length_mm == pytest.approx(17.8)
    assert saved.image_circle_mm == pytest.approx(8.0)
    assert saved.working_distance_min_mm == pytest.approx(80.0)
    assert panel.delete_lens_preset_action.isEnabled()

    def accept_edit(dialog: LensPresetDialog) -> QDialog.DialogCode:
        assert dialog.user_id_edit.isReadOnly()
        dialog.focal_length_spin.setValue(18.1)
        dialog.set_optional_value(
            "object_principal_plane_from_first_object_surface_mm",
            6.2,
        )
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LensPresetDialog, "exec", accept_edit)
    panel.edit_lens_preset_action.trigger()

    edited = panel.selected_user_lens_preset()
    assert edited is not None
    assert edited.user_id == "my-shop-lens"
    assert edited.focal_length_mm == pytest.approx(18.1)
    assert edited.object_principal_plane_from_first_object_surface_mm == pytest.approx(6.2)


def test_preset_menu_creates_blank_lens_without_supplier_provenance(
    qtbot,
    monkeypatch,
):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    panel = widget.input_panel

    def accept_blank(dialog: LensPresetDialog) -> QDialog.DialogCode:
        assert dialog.is_new_preset
        dialog.user_id_edit.setText("in-house-m12")
        dialog.name_edit.setText("사내 M12 시제품")
        dialog.manufacturer_edit.setText("In-house")
        dialog.focal_length_spin.setValue(25.0)
        dialog.accept()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(LensPresetDialog, "exec", accept_blank)
    panel.new_lens_preset_action.trigger()

    preset = panel.selected_user_lens_preset()
    assert preset is not None
    assert preset.user_id == "in-house-m12"
    assert preset.source_profile_id is None
    assert preset.mechanical_drawing_id is None
    assert panel.lens.currentData() == "user-lens:in-house-m12"


def test_minimum_layout_keeps_formula_visible_and_scene_wide(qtbot):
    widget = DesignWidget()
    qtbot.addWidget(widget)
    widget.resize(1080, 580)
    widget.show()
    qtbot.waitUntil(lambda: widget.solution is not None, timeout=5_000)

    panel = widget.input_panel
    assert widget.splitter.count() == 2
    assert 390 <= widget.splitter.sizes()[0] <= 460
    assert widget.view.viewport().width() >= 600
    assert panel.width() <= widget.input_scroll.viewport().width()
    assert panel.worksheet_table.isColumnHidden(0)
    assert panel.worksheet_table.isColumnHidden(4)
    assert panel.focal_length_mm.width() >= 110
    assert panel.sensor_length_mm.width() >= 110
    assert panel.v_mm.width() >= 110
    assert panel.formula_card.visibleRegion().boundingRect().height() == (
        panel.formula_card.height()
    )
    assert widget.input_scroll.horizontalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    )
