"""Readable three-dimensional Scheimpflug geometry preview."""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import product
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .scene import Point2D, SceneSnapshot

np: Any | None = None
FigureCanvasQTAgg: Any | None = None
Figure: Any | None = None
NullFormatter: Any | None = None
Poly3DCollection: Any | None = None
_PLOT_IMPORT_ERROR: ImportError | None = None


_ELEVATION_DEG = 24.0
_AZIMUTH_DEG = -56.0
_X: Any = (1.0, 0.0, 0.0)
_Y: Any = (0.0, 1.0, 0.0)
_Z: Any = (0.0, 0.0, 1.0)
_COLORS = {
    "target": "#2fa86f",
    "lens_plane": "#2f83c5",
    "sensor": "#e3a008",
    "laser": "#d92d20",
    "camera": "#40566f",
    "lens": "#48a9dc",
    "ray": "#7254b3",
    "scheimpflug": "#b76e00",
    "axis": "#66788a",
}


def _load_plot_backend() -> bool:
    """Load the 3D numerical/rendering stack only when the tab is opened."""

    global Figure, FigureCanvasQTAgg, NullFormatter, Poly3DCollection
    global _X, _Y, _Z
    global _PLOT_IMPORT_ERROR, np
    if Figure is not None:
        return True
    if _PLOT_IMPORT_ERROR is not None:
        return False
    try:
        import numpy as numpy_module
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as canvas_class
        from matplotlib.figure import Figure as figure_class
        from matplotlib.ticker import NullFormatter as null_formatter_class
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection as poly_collection_class
    except ImportError as exc:  # pragma: no cover - required in packaged builds.
        _PLOT_IMPORT_ERROR = exc
        return False
    np = numpy_module
    FigureCanvasQTAgg = canvas_class
    Figure = figure_class
    NullFormatter = null_formatter_class
    Poly3DCollection = poly_collection_class
    _X = np.array((1.0, 0.0, 0.0))
    _Y = np.array((0.0, 1.0, 0.0))
    _Z = np.array((0.0, 0.0, 1.0))
    return True


def _point3(point: Point2D) -> np.ndarray:
    return np.array((point.x_mm, 0.0, point.z_mm), dtype=float)


def _unit(vector: Iterable[float], fallback: Iterable[float]) -> np.ndarray:
    value = np.asarray(tuple(vector), dtype=float)
    length = float(np.linalg.norm(value))
    if math.isfinite(length) and length > 1e-12:
        return value / length
    backup = np.asarray(tuple(fallback), dtype=float)
    return backup / float(np.linalg.norm(backup))


def _direction(first: Point2D, second: Point2D, fallback: Iterable[float]) -> np.ndarray:
    return _unit(
        (second.x_mm - first.x_mm, 0.0, second.z_mm - first.z_mm),
        fallback,
    )


def _clip(origin: np.ndarray, endpoint: np.ndarray, limit: float) -> tuple[np.ndarray, bool]:
    delta = endpoint - origin
    distance = float(np.linalg.norm(delta))
    if distance <= limit or distance <= 1e-12:
        return endpoint, False
    return origin + delta * (limit / distance), True


class ThreeDWidget(QWidget):
    """Explain equipment, optical planes, and their intersections in one 3D view."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._snapshot: SceneSnapshot | None = None
        self._fit_points: list[np.ndarray] = []
        self._head_points: list[np.ndarray] = []
        self._components: dict[str, list[object]] = {}
        self._beam_was_clipped = False
        self._view_mode = "head"
        self.figure: Any | None = None
        self.canvas: Any | None = None
        self.axes: Any | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)
        controls = QHBoxLayout()
        self.interaction_hint = QLabel(
            self._text("마우스 드래그: 회전 · 휠: 확대/축소", "Drag: rotate · Wheel: zoom")
        )
        self.interaction_hint.setObjectName("threeDInteractionHint")
        self.interaction_hint.setStyleSheet("color: #526577; padding: 2px 4px;")
        controls.addWidget(self.interaction_hint)
        controls.addStretch(1)
        self.head_button = self._view_button(
            "광학 헤드",
            "Optical head",
            "threeDHeadViewButton",
            "3D 광학 헤드 확대",
            checkable=True,
        )
        self.fit_button = self._view_button(
            "전체 구조",
            "Full assembly",
            "threeDFitButton",
            "3D 전체 구조 맞춤",
            checkable=True,
        )
        self.view_button = self._view_button(
            "기본 시점",
            "Default view",
            "threeDDefaultViewButton",
            "3D 기본 시점 복원",
        )
        self.view_group = QButtonGroup(self)
        self.view_group.setExclusive(True)
        self.view_group.addButton(self.head_button)
        self.view_group.addButton(self.fit_button)
        self.head_button.setChecked(True)
        for button in (self.head_button, self.fit_button, self.view_button):
            controls.addWidget(button)
        layout.addLayout(controls)

        info_bar = QFrame()
        info_bar.setObjectName("threeDInfoBar")
        info_bar.setStyleSheet(
            "QFrame#threeDInfoBar {"
            "  background: #f7f9fc;"
            "  border: 1px solid #d8e0e8;"
            "  border-radius: 7px;"
            "}"
            "QLabel {"
            "  color: #33475b;"
            "  padding: 5px 8px;"
            "}"
        )
        info_layout = QHBoxLayout(info_bar)
        info_layout.setContentsMargins(4, 2, 4, 2)
        info_layout.setSpacing(8)
        self.scene_key = QLabel(self._scene_key_markup())
        self.scene_key.setObjectName("threeDSceneKey")
        self.scene_key.setWordWrap(True)
        self.scene_key.setAccessibleName("3D 장면 색상과 선 범례")
        self.scene_key.setAccessibleDescription(
            "기준 대상, 렌즈, 센서, 레이저 중심 광선과 계산 교선을 색상 및 선 모양으로 구분합니다."
        )
        self.status_card = QLabel(
            self._text("계산 가능한 설계 입력을 기다리는 중", "Waiting for a valid design")
        )
        self.status_card.setObjectName("threeDStatusCard")
        self.status_card.setWordWrap(True)
        self.status_card.setMinimumWidth(260)
        self.status_card.setAccessibleName("3D 장면 상태")
        info_layout.addWidget(self.scene_key, 3)
        info_layout.addWidget(self.status_card, 2)
        layout.addWidget(info_bar)

        self.plot_host = QWidget()
        self.plot_layout = QVBoxLayout(self.plot_host)
        self.plot_layout.setContentsMargins(0, 0, 0, 0)
        self.plot_placeholder = QLabel("3D 탭을 열면 장면 렌더러를 준비합니다.")
        self.plot_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.plot_placeholder.setAccessibleName("3D 장면 준비 상태")
        self.plot_layout.addWidget(self.plot_placeholder, 1)
        layout.addWidget(self.plot_host, 1)
        self.head_button.clicked.connect(self.fit_head)
        self.fit_button.clicked.connect(self.fit_view)
        self.view_button.clicked.connect(self.reset_view)
        self._set_controls_enabled(False)

    def _text(self, korean: str, _english: str) -> str:
        """Return the Korean-first UI copy; the canvas itself contains no text."""

        return korean

    def _scene_key_markup(self) -> str:
        planes = (
            ("target", "■", "기준 대상", "Reference target"),
            ("lens_plane", "■", "렌즈면", "Lens"),
            ("sensor", "■", "센서면", "Sensor"),
        )
        lines = (
            ("laser", "━", "레이저 중심 광선", "Laser centre ray"),
            ("scheimpflug", "━", "Scheimpflug 교선", "Scheimpflug line"),
        )
        entries = [
            (f"<span style='color:{_COLORS[color]}'>{glyph}</span> {self._text(korean, english)}")
            for color, glyph, korean, english in (*planes, *lines)
        ]
        return " &nbsp;·&nbsp; ".join(entries)

    def _view_button(
        self,
        korean: str,
        english: str,
        object_name: str,
        accessible_name: str,
        *,
        checkable: bool = False,
    ) -> QPushButton:
        button = QPushButton(self._text(korean, english))
        button.setObjectName(object_name)
        button.setAccessibleName(accessible_name)
        button.setCheckable(checkable)
        return button

    def _set_controls_enabled(self, enabled: bool) -> None:
        for button in (self.head_button, self.fit_button, self.view_button):
            button.setEnabled(enabled)

    def _ensure_canvas(self) -> bool:
        """Create the Matplotlib canvas once, on first visible 3D render."""

        if self.canvas is not None:
            return True
        if not _load_plot_backend():
            self.plot_placeholder.setText(
                "3D 보기를 준비하지 못했습니다. Matplotlib 설치 상태를 확인하세요."
            )
            self.plot_placeholder.setAccessibleDescription(str(_PLOT_IMPORT_ERROR or ""))
            return False
        self.figure = Figure(figsize=(9.0, 6.4), constrained_layout=False)
        self.figure.set_facecolor("#ffffff")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setAccessibleName("3D Scheimpflug 광학 장면")
        self.axes = self.figure.add_subplot(111, projection="3d")
        self.axes.set_position((0.015, 0.025, 0.97, 0.95))
        self.plot_layout.replaceWidget(self.plot_placeholder, self.canvas)
        self.plot_placeholder.hide()
        self.plot_placeholder.deleteLater()
        return True

    def _register(self, name: str, *artists: object) -> None:
        self._components.setdefault(name, []).extend(artists)

    def _line(
        self,
        name: str,
        points: Iterable[np.ndarray],
        color: str,
        width: float,
        style: str = "-",
        alpha: float = 1.0,
    ) -> object:
        values = tuple(points)
        (artist,) = self.axes.plot(
            [point[0] for point in values],
            [point[1] for point in values],
            [point[2] for point in values],
            color=color,
            linewidth=width,
            linestyle=style,
            alpha=alpha,
        )
        self._register(name, artist)
        return artist

    def _refresh_status(self) -> None:
        snapshot = self._snapshot
        if snapshot is None:
            self.status_card.setText(
                self._text(
                    "계산 가능한 설계 입력을 기다리는 중",
                    "Waiting for a valid design",
                )
            )
            self.status_card.setStyleSheet("color: #5b6b7a; font-weight: 600;")
            return

        validity = (
            self._text("유효", "Valid") if snapshot.valid else self._text("제약 경고", "Warning")
        )
        view = (
            self._text("광학 헤드", "Optical head")
            if self._view_mode == "head"
            else self._text("전체 구조", "Full assembly")
        )
        parts = [
            validity,
            view,
            f"WD={snapshot.working_distance_mm:.1f} mm",
        ]
        if self._beam_was_clipped:
            parts.append(
                self._text(
                    f"빔 원거리 구간 생략 · 실제 Z={snapshot.laser_endpoints[1].z_mm:.1f} mm",
                    f"Remote beam clipped · actual Z={snapshot.laser_endpoints[1].z_mm:.1f} mm",
                )
            )
        self.status_card.setText(" · ".join(parts))
        color = "#9a3412" if not snapshot.valid else "#245c44"
        self.status_card.setStyleSheet(f"color: {color}; font-weight: 600;")

    def set_geometry(
        self,
        snapshot: SceneSnapshot | None,
        *,
        render: bool = True,
    ) -> None:
        """Store a calculation snapshot and render only while this tab is active."""

        self._snapshot = snapshot
        if not render or not self._ensure_canvas():
            return
        self._draw_empty() if snapshot is None else self._draw_snapshot(snapshot)

    def _style_axes(self) -> None:
        self.axes.set_facecolor("#fbfcfe")
        for axis in (self.axes.xaxis, self.axes.yaxis, self.axes.zaxis):
            axis.pane.set_facecolor((0.94, 0.96, 0.98, 0.72))
            axis.pane.set_edgecolor("#cbd5df")
            axis.set_major_formatter(NullFormatter())
            axis.set_minor_formatter(NullFormatter())
        self.axes.grid(True, color="#d7dfe7", linewidth=0.55, alpha=0.75)
        self.axes.tick_params(labelbottom=False, labelleft=False, labelright=False, labeltop=False)
        self.axes.set_xlabel("")
        self.axes.set_ylabel("")
        self.axes.set_zlabel("")
        self.axes.set_title("")
        self.axes.set_box_aspect((1.0, 1.0, 1.0), zoom=1.08)

    def _draw_empty(self) -> None:
        if self.canvas is None:
            return
        self.axes.clear()
        self._components.clear()
        self._fit_points.clear()
        self._head_points.clear()
        self._beam_was_clipped = False
        self._style_axes()
        for setter in (self.axes.set_xlim, self.axes.set_ylim, self.axes.set_zlim):
            setter(-10.0, 10.0)
        self.axes.view_init(elev=_ELEVATION_DEG, azim=_AZIMUTH_DEG)
        self._set_controls_enabled(False)
        self._refresh_status()
        self.canvas.draw_idle()

    def _plane(
        self,
        name: str,
        center: np.ndarray,
        first: np.ndarray,
        second: np.ndarray,
        half_first: float,
        half_second: float,
        color: str,
        opacity: float,
        normal_hint: np.ndarray,
        edge_style: str = "-",
    ) -> None:
        first = _unit(first, _X)
        second = _unit(second, _Y)
        normal = _unit(np.cross(first, second), _Z)
        if float(np.dot(normal, normal_hint)) < 0:
            normal = -normal
        corners = [
            center + first * half_first * sx + second * half_second * sy
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))
        ]
        face = Poly3DCollection(
            [corners],
            facecolors=color,
            edgecolors=color,
            linewidths=1.4,
            linestyles=edge_style,
            alpha=opacity,
        )
        self.axes.add_collection3d(face)
        normal_length = max(2.2, min(half_first, half_second) * 0.32)
        arrow = self.axes.quiver(
            *center,
            *normal,
            length=normal_length,
            normalize=True,
            arrow_length_ratio=0.22,
            color=color,
            linewidth=1.25,
        )
        self._register(name, face, arrow)
        self._fit_points.extend((*corners, center + normal * normal_length))

    def _box(
        self,
        name: str,
        center: np.ndarray,
        axes: tuple[np.ndarray, np.ndarray, np.ndarray],
        half_sizes: tuple[float, float, float],
        color: str,
        edge: str,
    ) -> None:
        axes = tuple(
            _unit(axis, fallback) for axis, fallback in zip(axes, (_X, _Y, _Z), strict=True)
        )
        vertices = [
            center
            + sum(
                (
                    axis * half_size * sign
                    for axis, half_size, sign in zip(axes, half_sizes, signs, strict=True)
                ),
                np.zeros(3),
            )
            for signs in product((-1.0, 1.0), repeat=3)
        ]
        faces = [
            [vertices[index] for index in indices]
            for indices in (
                (0, 1, 3, 2),
                (4, 5, 7, 6),
                (0, 1, 5, 4),
                (2, 3, 7, 6),
                (0, 2, 6, 4),
                (1, 3, 7, 5),
            )
        ]
        body = Poly3DCollection(
            faces,
            facecolors=color,
            edgecolors=edge,
            linewidths=0.8,
            alpha=0.86,
        )
        self.axes.add_collection3d(body)
        self._register(name, body)
        self._fit_points.extend(vertices)

    def _lens(
        self,
        center: np.ndarray,
        normal: np.ndarray,
        tangent: np.ndarray,
        radius: float,
        thickness: float,
    ) -> None:
        theta = np.linspace(0.0, 2.0 * math.pi, 28)
        axial, angle = np.meshgrid((-thickness / 2.0, thickness / 2.0), theta)
        normal, tangent = _unit(normal, _Z), _unit(tangent, _X)
        coordinates = (
            center[:, None, None]
            + normal[:, None, None] * axial
            + tangent[:, None, None] * (radius * np.cos(angle))
            + _Y[:, None, None] * (radius * np.sin(angle))
        )
        surface = self.axes.plot_surface(
            *coordinates,
            color=_COLORS["lens"],
            alpha=0.72,
            linewidth=0.35,
            edgecolor="#1f6389",
        )
        self._register("lens", surface)
        self._fit_points.extend(
            (
                center + tangent * radius,
                center - tangent * radius,
                center + _Y * radius,
                center - _Y * radius,
            )
        )

    def _draw_snapshot(self, snapshot: SceneSnapshot) -> None:
        self.axes.clear()
        self._components.clear()
        self._fit_points.clear()
        self._head_points.clear()
        self._beam_was_clipped = False

        emitter = _point3(snapshot.emitter)
        target = _point3(snapshot.target_nominal)
        lens = _point3(snapshot.lens_center)
        image = _point3(snapshot.image_center)
        lens_tangent = _direction(*snapshot.lens_endpoints, _X)
        sensor_tangent = _direction(*snapshot.sensor_endpoints, -_X)
        camera_axis = _unit(image - lens, _Z)
        sensor_normal = _unit(np.cross(sensor_tangent, _Y), camera_axis)
        if float(np.dot(sensor_normal, camera_axis)) < 0:
            sensor_normal = -sensor_normal

        main_points = (emitter, target, lens, image)
        span = max(
            20.0,
            snapshot.working_distance_mm,
            *(float(np.linalg.norm(a - b)) for a in main_points for b in main_points),
        )
        plane_half = max(7.0, min(42.0, span * 0.13))
        sensor_interval = max(
            2.0,
            float(
                np.linalg.norm(
                    _point3(snapshot.sensor_endpoints[1]) - _point3(snapshot.sensor_endpoints[0])
                )
            ),
        )
        sensor_half = max(sensor_interval * 0.65, plane_half * 0.26)

        beam_direction = _unit(target - emitter, _Z)
        plane_specs = (
            # A schematic target plate marks the nominal range only. It is not
            # presented as the Scheimpflug object plane because target pose is
            # not an input to the workbook model.
            (
                "target_plane",
                target,
                _X,
                _Y,
                plane_half * 1.05,
                plane_half * 0.8,
                "target",
                0.15,
                _Z,
                "-",
            ),
            (
                "lens_plane",
                lens,
                lens_tangent,
                _Y,
                plane_half * 0.82,
                plane_half * 0.66,
                "lens_plane",
                0.13,
                camera_axis,
                "-",
            ),
            (
                "sensor_plane",
                image,
                sensor_tangent,
                _Y,
                sensor_half,
                sensor_half * 0.76,
                "sensor",
                0.22,
                sensor_normal,
                "-",
            ),
        )
        for (
            name,
            center,
            first,
            second,
            half_first,
            half_second,
            color_key,
            opacity,
            normal_hint,
            style,
        ) in plane_specs:
            self._plane(
                name,
                center,
                first,
                second,
                half_first,
                half_second,
                _COLORS[color_key],
                opacity,
                normal_hint,
                style,
            )

        # Body dimensions are enlarged schematic cues; plane coordinates remain physical.
        lens_radius = max(4.5, min(12.0, plane_half * 0.3))
        self._lens(lens, camera_axis, lens_tangent, lens_radius, lens_radius * 0.28)
        body_depth = max(10.0, min(24.0, plane_half * 0.75))
        body_width = max(sensor_interval * 1.25, lens_radius * 1.9)
        body_height = max(sensor_interval, lens_radius * 1.55)
        camera_center = image + camera_axis * body_depth * 0.58
        self._box(
            "camera_body",
            camera_center,
            (camera_axis, lens_tangent, _Y),
            (body_depth / 2.0, body_width / 2.0, body_height / 2.0),
            _COLORS["camera"],
            "#27394c",
        )
        self._box(
            "sensor_body",
            image,
            (sensor_normal, sensor_tangent, _Y),
            (
                max(0.35, sensor_interval * 0.055),
                max(sensor_interval / 2.0, lens_radius * 0.62),
                max(2.5, sensor_interval * 0.5, lens_radius * 0.55),
            ),
            _COLORS["sensor"],
            "#946200",
        )
        emitter_size = max(4.0, min(9.0, plane_half * 0.25))
        emitter_center = emitter - beam_direction * emitter_size * 0.45
        emitter_side = _unit(np.cross(_Y, beam_direction), _X)
        self._box(
            "laser_emitter",
            emitter_center,
            (beam_direction, emitter_side, _Y),
            (emitter_size * 0.55, emitter_size * 0.55, emitter_size * 0.42),
            "#b42318",
            "#67140e",
        )

        actual_beam_end = _point3(snapshot.laser_endpoints[1])
        beam_end, self._beam_was_clipped = _clip(emitter, actual_beam_end, span * 1.35)
        self._line("laser_beam_glow", (emitter, beam_end), _COLORS["laser"], 6.0, alpha=0.12)
        self._line("laser_beam", (emitter, beam_end), _COLORS["laser"], 2.4)
        self._fit_points.extend((emitter, beam_end))

        axis_end = camera_center + camera_axis * body_depth * 0.55
        self._line("optical_axis", (target, axis_end), _COLORS["axis"], 1.35, "-.", 0.9)
        self._fit_points.extend((target, axis_end))
        for ray in snapshot.chief_rays:
            ray_target, ray_lens, ray_sensor = map(_point3, ray)
            ray_target, _ = _clip(ray_lens, ray_target, span * 1.15)
            self._line(
                "chief_rays",
                (ray_target, ray_lens, ray_sensor),
                _COLORS["ray"],
                1.0,
                alpha=0.74,
            )

        line_half = plane_half * 0.78
        scheimpflug = (
            _point3(snapshot.scheimpflug_point) if snapshot.scheimpflug_point is not None else None
        )
        if scheimpflug is not None:
            points = (scheimpflug - _Y * line_half, scheimpflug + _Y * line_half)
            self._line("scheimpflug_line", points, _COLORS["scheimpflug"], 3.2)
            marker = self.axes.scatter(
                [scheimpflug[0]],
                [scheimpflug[1]],
                [scheimpflug[2]],
                s=34,
                color=_COLORS["scheimpflug"],
                edgecolor="white",
                linewidth=0.8,
                depthshade=False,
            )
            self._register("scheimpflug_line", marker)
            self._fit_points.extend(points)
        head_centers = [emitter, lens, image, camera_center]
        if scheimpflug is not None and np.linalg.norm(scheimpflug - lens) <= plane_half * 2.5:
            head_centers.append(scheimpflug)
        values = np.asarray(head_centers)
        padding = max(8.0, plane_half * 0.36, body_height * 0.72, lens_radius * 1.25)
        self._head_points.extend(
            (
                values.min(axis=0) - padding,
                values.max(axis=0) + padding,
            )
        )

        self._style_axes()
        self.fit_head(draw=False)
        self.reset_view(draw=False)
        self._set_controls_enabled(True)
        self.canvas.draw_idle()

    def _fit_equal(self, points: Iterable[np.ndarray]) -> None:
        values = np.asarray(
            [point for point in points if np.all(np.isfinite(point))],
            dtype=float,
        )
        if not values.size:
            return
        minimum, maximum = values.min(axis=0), values.max(axis=0)
        center = (minimum + maximum) / 2.0
        half = max(1.0, float(np.max(maximum - minimum))) * 0.61
        self.axes.set_xlim(center[0] - half, center[0] + half)
        self.axes.set_ylim(center[1] - half, center[1] + half)
        self.axes.set_zlim(center[2] - half, center[2] + half)
        self.axes.set_box_aspect((1.0, 1.0, 1.0), zoom=1.08)

    def fit_head(self, _checked: bool = False, *, draw: bool = True) -> None:
        """Zoom to the equipment while retaining an off-screen laser/range cue."""

        if self.canvas is None or not self._head_points:
            return
        self._fit_equal(self._head_points)
        self._view_mode = "head"
        self.head_button.setChecked(True)
        self._refresh_status()
        if draw:
            self.canvas.draw_idle()

    def fit_view(self, _checked: bool = False, *, draw: bool = True) -> None:
        """Fit the complete working-distance relationship at equal axis scales."""

        if self.canvas is None or not self._fit_points:
            return
        self._fit_equal(self._fit_points)
        self._view_mode = "full"
        self.fit_button.setChecked(True)
        self._refresh_status()
        if draw:
            self.canvas.draw_idle()

    def reset_view(self, _checked: bool = False, *, draw: bool = True) -> None:
        """Restore the readable default camera angle without recalculating."""

        if self.canvas is None:
            return
        self.axes.view_init(elev=_ELEVATION_DEG, azim=_AZIMUTH_DEG)
        if draw:
            self.canvas.draw_idle()
