"""Convert optical solutions into named, renderer-independent primitives."""

from __future__ import annotations

import math

from scheimpflug_optimeter.models import (
    DesignInput,
    DesignMode,
    DesignSolution,
    Point2D,
    SceneGeometry,
    WorkbookDesignInput,
)

from .solvers import OpticalInputError


def _point(origin: Point2D, direction: tuple[float, float], distance: float) -> Point2D:
    return Point2D(
        origin.x_mm + direction[0] * distance,
        origin.z_mm + direction[1] * distance,
    )


def _line_intersection(
    first_origin: Point2D,
    first_direction: tuple[float, float],
    second_origin: Point2D,
    second_direction: tuple[float, float],
) -> Point2D | None:
    cross = first_direction[0] * second_direction[1] - first_direction[1] * second_direction[0]
    if abs(cross) <= 1e-12:
        return None
    delta = (
        second_origin.x_mm - first_origin.x_mm,
        second_origin.z_mm - first_origin.z_mm,
    )
    distance = (delta[0] * second_direction[1] - delta[1] * second_direction[0]) / cross
    result = _point(first_origin, first_direction, distance)
    if not math.isfinite(result.x_mm) or not math.isfinite(result.z_mm):
        return None
    return result


def _segment(
    center: Point2D, direction: tuple[float, float], half_length: float
) -> tuple[Point2D, Point2D]:
    return (
        _point(center, direction, -half_length),
        _point(center, direction, half_length),
    )


def _canonical_geometry(solution: DesignSolution, request: DesignInput) -> SceneGeometry:
    alpha = math.radians(solution.alpha_deg)
    beta = math.radians(solution.beta_deg)
    emitter = Point2D(0.0, 0.0)
    target_near = Point2D(0.0, request.d_mm - request.range_mm / 2.0)
    target_center = Point2D(0.0, request.d_mm)
    target_far = Point2D(0.0, request.d_mm + request.range_mm / 2.0)
    optical_direction = (-math.sin(alpha), math.cos(alpha))
    lens_center = _point(target_center, optical_direction, -solution.lo_mm)
    image_center = _point(lens_center, optical_direction, -solution.fp_mm)
    sensor_direction = (-math.sin(alpha + beta), math.cos(alpha + beta))
    sensor_near = _point(image_center, sensor_direction, solution.x_near_mm)
    sensor_far = _point(image_center, sensor_direction, solution.x_far_mm)
    sensor_proxy_near = _point(
        image_center, sensor_direction, -solution.required_sensor_length_mm / 2.0
    )
    sensor_proxy_far = _point(
        image_center, sensor_direction, solution.required_sensor_length_mm / 2.0
    )
    lens_direction = (math.cos(alpha), math.sin(alpha))
    scheimpflug = _line_intersection(lens_center, lens_direction, image_center, sensor_direction)
    symbol_half_length = max(2.5, min(20.0, solution.required_sensor_length_mm * 0.35))
    lens_plane = _segment(lens_center, lens_direction, symbol_half_length)
    return SceneGeometry(
        emitter=emitter,
        target_near=target_near,
        target_center=target_center,
        target_far=target_far,
        lens_center=lens_center,
        image_center=image_center,
        sensor_near=sensor_near,
        sensor_far=sensor_far,
        sensor_proxy_near=sensor_proxy_near,
        sensor_proxy_far=sensor_proxy_far,
        scheimpflug_intersection=scheimpflug,
        laser_line=(emitter, target_far),
        optical_axis=(target_center, image_center),
        lens_plane=lens_plane,
        image_plane=(sensor_near, sensor_far),
        object_range=(target_near, target_far),
    )


def _workbook_geometry(solution: DesignSolution, request: WorkbookDesignInput) -> SceneGeometry:
    alpha = math.radians(solution.alpha_deg)
    target_center = Point2D(0.0, 0.0)
    emitter = Point2D(0.0, request.v_mm)
    optical_direction = (math.sin(alpha), math.cos(alpha))
    lens_center = _point(target_center, optical_direction, solution.lo_mm)
    image_center = Point2D(solution.baseline_mm or 0.0, request.v_mm)
    half_sensor = solution.required_sensor_length_mm / 2.0
    # The workbook s formula uses the sensor edge on the laser-axis side
    # (b - L/2). That edge images the farther laser-axis intersection. Endpoint
    # names therefore follow object distance, not increasing sensor X.
    sensor_far = Point2D(image_center.x_mm - half_sensor, image_center.z_mm)
    sensor_near = Point2D(image_center.x_mm + half_sensor, image_center.z_mm)
    lens_direction = (math.cos(alpha), -math.sin(alpha))
    image_direction = (1.0, 0.0)
    scheimpflug = _line_intersection(lens_center, lens_direction, image_center, image_direction)
    lens_plane = _segment(lens_center, lens_direction, max(2.5, min(20.0, half_sensor)))
    target_far = (
        Point2D(0.0, -solution.ray_intercept_s_mm)
        if solution.ray_intercept_s_mm is not None
        else None
    )
    target_near = _line_intersection(
        lens_center,
        (
            sensor_near.x_mm - lens_center.x_mm,
            sensor_near.z_mm - lens_center.z_mm,
        ),
        target_center,
        (0.0, 1.0),
    )
    if target_near is None:
        target_near = target_center
    if target_far is None:
        target_far = target_center
    return SceneGeometry(
        emitter=emitter,
        target_near=target_near,
        target_center=target_center,
        target_far=target_far,
        lens_center=lens_center,
        image_center=image_center,
        sensor_near=sensor_near,
        sensor_far=sensor_far,
        sensor_proxy_near=sensor_near,
        sensor_proxy_far=sensor_far,
        scheimpflug_intersection=scheimpflug,
        laser_line=(emitter, target_far),
        optical_axis=(target_center, image_center),
        lens_plane=lens_plane,
        image_plane=(sensor_near, sensor_far),
        object_range=(target_near, target_far),
        front_plane_z_mm=request.d_mm,
        ray_intercept=target_far,
    )


def build_scene_geometry(solution: DesignSolution) -> SceneGeometry:
    """Build immutable drawing primitives from the exact calculation snapshot."""

    if not all(
        math.isfinite(value)
        for value in (
            solution.lo_mm,
            solution.fp_mm,
            solution.required_sensor_length_mm,
            solution.x_near_mm,
            solution.x_far_mm,
        )
    ):
        raise OpticalInputError("Cannot render non-finite optical geometry.")
    if solution.mode is DesignMode.CANONICAL:
        if not isinstance(solution.request, DesignInput):
            raise TypeError("Canonical solution does not carry a DesignInput.")
        return _canonical_geometry(solution, solution.request)
    if solution.mode is DesignMode.WORKBOOK:
        if not isinstance(solution.request, WorkbookDesignInput):
            raise TypeError("Workbook solution does not carry a WorkbookDesignInput.")
        return _workbook_geometry(solution, solution.request)
    raise OpticalInputError(f"Unsupported design mode: {solution.mode!r}")
