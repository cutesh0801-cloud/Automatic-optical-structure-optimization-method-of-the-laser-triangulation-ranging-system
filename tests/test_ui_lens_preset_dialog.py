from __future__ import annotations

from PySide6.QtWidgets import QDialog

from scheimpflug_optimeter.hardware.catalog import LENSES
from scheimpflug_optimeter.lens_presets import UserLensPreset
from scheimpflug_optimeter.ui.lens_preset_dialog import LensPresetDialog


def _optical_only_preset() -> UserLensPreset:
    return UserLensPreset(
        user_id="prototype-25",
        name="25 mm prototype",
        focal_length_mm=25.0,
        mount="M12x0.5",
    )


def test_dialog_clones_official_profile_and_exposes_clear_datum_labels(qtbot):
    official = LENSES["edmund-83-954"]
    dialog = LensPresetDialog(official)
    qtbot.addWidget(dialog)
    dialog.resize(1100, 700)
    dialog.show()

    preset = dialog.current_preset()
    assert preset is not None
    assert dialog.is_catalog_copy is True
    assert preset.source_profile_id == official.id
    assert preset.user_id != official.id
    assert preset.focal_length_mm == official.focal_length_mm
    assert dialog.user_id_edit.isReadOnly() is False
    assert "S1" in dialog.object_datum_label.text()
    assert "첫 번째 광학면" in dialog.object_datum_label.text()
    assert "하우징 전면" in dialog.object_datum_label.text()
    assert "SL" in dialog.image_datum_label.text()
    assert "마지막 광학면" in dialog.image_datum_label.text()
    assert dialog.save_button.accessibleName()
    assert dialog.cancel_button.accessibleName()
    assert dialog.height() <= 700


def test_direct_edits_return_detached_user_preset(qtbot):
    official = LENSES["edmund-83-954"]
    dialog = LensPresetDialog(official)
    qtbot.addWidget(dialog)

    dialog.user_id_edit.setText("custom-production-175")
    dialog.name_edit.setText("사용자 17.8 mm")
    dialog.mount_edit.setText("M12x0.5")
    dialog.focal_length_spin.setValue(17.8)
    dialog.set_optional_value("aperture_f_number", 5.6)
    dialog.set_optional_value("object_principal_plane_from_first_object_surface_mm", -1.25)
    dialog.set_optional_value("image_principal_plane_from_last_image_surface_mm", 2.5)

    edited = dialog.preset()
    assert edited.user_id == "custom-production-175"
    assert edited.name == "사용자 17.8 mm"
    assert edited.focal_length_mm == 17.8
    assert edited.aperture_f_number == 5.6
    assert edited.object_principal_plane_from_first_object_surface_mm == -1.25
    assert edited.image_principal_plane_from_last_image_surface_mm == 2.5
    assert edited.source_profile_id == official.id
    assert edited.mechanical_drawing_id is None
    assert edited.mechanical_source_url is None
    assert edited.source_verified_on is None
    assert official.focal_length_mm == 17.5


def test_blank_preset_has_editable_id_and_no_inherited_supplier_provenance(qtbot):
    blank = UserLensPreset(
        user_id="custom-lens",
        name="새 사용자 렌즈",
        focal_length_mm=17.5,
        mount="M12x0.5",
    )
    dialog = LensPresetDialog(blank, new_preset=True)
    qtbot.addWidget(dialog)

    assert dialog.user_id_edit.isReadOnly() is False
    dialog.user_id_edit.setText("in-house-25")
    dialog.manufacturer_edit.setText("In-house")
    dialog.sku_edit.setText("PROTO-25")
    dialog.focal_length_spin.setValue(25.0)
    dialog.set_optional_value("image_circle_mm", 9.0)
    dialog.set_optional_value("wavelength_min_nm", 635.0)
    dialog.set_optional_value("wavelength_max_nm", 660.0)
    dialog.set_optional_value("working_distance_min_mm", 100.0)
    dialog.set_optional_value("working_distance_max_mm", 400.0)
    dialog.set_optional_value("back_focal_length_min_mm", 5.0)
    dialog.set_optional_value("back_focal_length_max_mm", 6.0)

    preset = dialog.preset()
    assert preset.user_id == "in-house-25"
    assert preset.manufacturer == "In-house"
    assert preset.sku == "PROTO-25"
    assert preset.image_circle_mm == 9.0
    assert preset.wavelength_min_nm == 635.0
    assert preset.working_distance_max_mm == 400.0
    assert preset.back_focal_length_min_mm == 5.0
    assert preset.source_profile_id is None
    assert preset.source_url is None
    assert preset.mechanical_drawing_id is None


def test_existing_user_preset_keeps_id_while_values_remain_editable(qtbot):
    source = _optical_only_preset()
    dialog = LensPresetDialog(source)
    qtbot.addWidget(dialog)

    assert dialog.is_catalog_copy is False
    assert dialog.user_id_edit.isReadOnly() is True
    dialog.user_id_edit.setText("attempted-id-change")
    dialog.name_edit.setText("Edited prototype")
    dialog.focal_length_spin.setValue(26.0)

    edited = dialog.preset()
    assert edited.user_id == source.user_id
    assert edited.name == "Edited prototype"
    assert edited.focal_length_mm == 26.0


def test_invalid_required_value_disables_save_and_blocks_accept(qtbot):
    dialog = LensPresetDialog(_optical_only_preset())
    qtbot.addWidget(dialog)

    dialog.focal_length_spin.setValue(0.0)

    assert dialog.current_preset() is None
    assert dialog.save_button.isEnabled() is False
    assert dialog.validation_label.property("state") == "error"
    assert "저장할 수 없습니다" in dialog.validation_label.text()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected


def test_nullable_mechanics_save_as_optical_only_warning(qtbot):
    dialog = LensPresetDialog(LENSES["edmund-83-954"])
    qtbot.addWidget(dialog)

    for field_name in (
        "outer_diameter_mm",
        "overall_length_mm",
        "front_housing_length_mm",
        "threaded_section_length_mm",
        "thread_major_diameter_mm",
        "thread_pitch_mm",
        "first_object_surface_recess_from_front_housing_mm",
        "object_principal_plane_from_first_object_surface_mm",
        "image_principal_plane_from_last_image_surface_mm",
    ):
        dialog.set_optional_value(field_name, None)

    preset = dialog.preset()
    assert preset.outer_diameter_mm is None
    assert preset.overall_length_mm is None
    assert preset.object_principal_plane_from_first_object_surface_mm is None
    assert preset.mechanical_rendering_status.enabled is False
    assert dialog.save_button.isEnabled() is True
    assert dialog.validation_label.property("state") == "warning"
    assert "광학 계산 가능" in dialog.validation_label.text()


def test_segment_mismatch_warns_but_does_not_block_optical_save(qtbot):
    dialog = LensPresetDialog(LENSES["edmund-83-954"])
    qtbot.addWidget(dialog)

    dialog.set_optional_value("threaded_section_length_mm", 5.0)

    preset = dialog.preset()
    assert preset.mechanical_rendering_status.enabled is False
    assert dialog.save_button.isEnabled() is True
    assert dialog.validation_label.property("state") == "warning"
    assert "L_front + L_thread" in dialog.validation_label.text()
