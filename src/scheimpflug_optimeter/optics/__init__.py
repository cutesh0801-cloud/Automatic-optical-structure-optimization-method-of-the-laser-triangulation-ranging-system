"""Public optical calculation API."""

from .geometry import build_scene_geometry
from .solvers import (
    OpticalInputError,
    calculate_sensor_imaging_metrics,
    image_coordinate_mm,
    image_sensitivity,
    solve_alpha,
    solve_canonical_design,
    solve_workbook_design,
)

__all__ = [
    "OpticalInputError",
    "build_scene_geometry",
    "calculate_sensor_imaging_metrics",
    "image_coordinate_mm",
    "image_sensitivity",
    "solve_alpha",
    "solve_canonical_design",
    "solve_workbook_design",
]
