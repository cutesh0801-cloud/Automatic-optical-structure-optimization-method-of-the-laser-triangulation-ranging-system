from __future__ import annotations

import numpy as np

from scheimpflug_optimeter.project import load_project
from scheimpflug_optimeter.ui import MainWindow


def test_mock_camera_calibration_measurement_and_project_reference(qtbot, tmp_path):
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    window.camera.connect_button.click()
    assert window.camera.trigger_button.isEnabled()
    window.camera.trigger_button.click()
    record = window.calibration.run_mock_calibration()
    qtbot.waitUntil(
        lambda: window.calibration.measure_button.isEnabled(),
        timeout=5_000,
    )

    section = window.calibration.run_measurement()
    assert record.intrinsic.accepted
    assert np.count_nonzero(section.valid_mask) > 1_000

    calibration_path = tmp_path / "mock-calibration.json"
    window.calibration.save_calibration(calibration_path)
    project_path = tmp_path / "mock-system.scheimpflug.json"
    window._project_path = project_path
    window._project_name = "mock-system"
    assert window.save_project()

    saved = load_project(project_path)
    assert saved.calibration_ref is not None
    assert saved.calibration_ref["relative_path"] == "mock-calibration.json"

    restored = MainWindow()
    qtbot.addWidget(restored)
    restored.apply_document(saved, project_path)
    assert restored.calibration.calibration_record is not None
    assert restored.calibration.calibration_record.identity == record.identity

    window._dirty = False
    restored._dirty = False
    window.close()
    restored.close()
