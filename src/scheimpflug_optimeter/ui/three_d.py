"""Readable three-dimensional Scheimpflug geometry preview."""

from __future__ import annotations

import math
from collections.abc import Iterable
from itertools import product

import numpy as np
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from scheimpflug_optimeter.optics import full_focus_angles as _core_full_focus_angles

from .scene import Point2D, SceneSnapshot

try:
    from matplotlib import font_manager, rcParams
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
except ImportError:  # pragma: no cover - required in packaged builds.
    FigureCanvasQTAgg = None
    Figure = None


_ELEVATION_DEG = 24.0
_AZIMUTH_DEG = -56.0
_X = np.array((1.0, 0.0, 0.0))
_Y = np.array((0.0, 1.0, 0.0))
_Z = np.array((0.0, 0.0, 1.0))
_COLORS = {
    "object": "#2fa86f",
    "lens_plane": "#2f83c5",
    "sensor": "#e3a008",
    "focus": "#ed7d31",
    "laser": "#d92d20",
    "camera": "#40566f",
    "lens": "#48a9dc",
    "ray": "#7254b3",
    "scheimpflug": "#b76e00",
    "hinge": "#8b4bb3",
    "axis": "#66788a",
    "text": "#17212b",
    "muted": "#5b6b7a",
}


def full_focus_angles(
    magnification: float,
    alpha_deg: float,
    beta_deg: float,
) -> tuple[float, float]:
    """Expose the exact core helper without duplicating its calculation."""

    return _core_full_focus_angles(magnification, alpha_deg, beta_deg)


def _configure_plot_font() -> bool:
    if Figure is None:
        return False
    for family in ("Malgun Gothic", "Noto Sans CJK KR", "AppleGothic"):
        try:
            font_manager.findfont(family, fallback_to_default=False)
        except ValueError:
            continue
        rcParams["font.family"] = family
        rcParams["axes.unicode_minus"] = False
        return True
    return False


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
        self._alpha_deg = self._beta_deg = 0.0
        self._magnification = 1.0
        self._korean_labels = _configure_plot_font()
        self._fit_points: list[np.ndarray] = []
        self._head_points: list[np.ndarray] = []
        self._components: dict[str, list[object]] = {}
        self._beam_was_clipped = False
        self._view_mode = "head"

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

        if Figure is None or FigureCanvasQTAgg is None:
            self.canvas = None
            message = QLabel("3D 보기를 사용하려면 Matplotlib Qt backend가 필요합니다.")
            message.setWordWrap(True)
            layout.addWidget(message)
            self._set_controls_enabled(False)
            return

        self.figure = Figure(figsize=(9.0, 6.4), constrained_layout=False)
        self.figure.set_facecolor("#ffffff")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setAccessibleName("3D Scheimpflug 광학 장면")
        self.axes = self.figure.add_subplot(111, projection="3d")
        self.axes.set_position((0.025, 0.125, 0.95, 0.755))
        layout.addWidget(self.canvas, 1)
        self.head_button.clicked.connect(self.fit_head)
        self.fit_button.clicked.connect(self.fit_view)
        self.view_button.clicked.connect(self.reset_view)
        self._draw_empty()

    def _text(self, korean: str, english: str) -> str:
        return korean if self._korean_labels else english

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

    def _callout(
        self,
        name: str,
        anchor: np.ndarray,
        position: np.ndarray,
        text: str,
        color: str,
    ) -> None:
        self._line(name, (anchor, position), color, 0.9, alpha=0.82)
        label = self.axes.text(
            *position,
            text,
            color=_COLORS["text"],
            fontsize=8.2,
            ha="center",
            va="center",
            bbox={
                "boxstyle": "round,pad=0.24",
                "facecolor": "white",
                "edgecolor": color,
                "alpha": 0.94,
                "linewidth": 0.9,
            },
            zorder=30,
            clip_on=True,
        )
        self._register(name, label)
        self._fit_points.append(position)

    def set_geometry(
        self,
        snapshot: SceneSnapshot | None,
        *,
        alpha_deg: float,
        beta_deg: float,
        magnification: float | None = None,
        render: bool = True,
    ) -> None:
        """Store a calculation snapshot and render only while this tab is active."""

        self._snapshot = snapshot
        self._alpha_deg = alpha_deg
        self._beta_deg = beta_deg
        if magnification is not None and magnification > 0:
            self._magnification = magnification
        if not render or self.canvas is None:
            return
        self._draw_empty() if snapshot is None else self._draw_snapshot(snapshot)

    def _style_axes(self) -> None:
        self.axes.set_facecolor("#fbfcfe")
        for axis in (self.axes.xaxis, self.axes.yaxis, self.axes.zaxis):
            axis.pane.set_facecolor((0.94, 0.96, 0.98, 0.72))
            axis.pane.set_edgecolor("#cbd5df")
        self.axes.grid(True, color="#d7dfe7", linewidth=0.55, alpha=0.75)
        self.axes.tick_params(labelsize=8, colors=_COLORS["muted"], pad=1)
        self.axes.set_xlabel(
            self._text("X — 카메라 기준선 (mm)", "X — camera baseline (mm)"),
            labelpad=9,
        )
        self.axes.set_ylabel(
            self._text("Y — 화면 밖 방향 (mm)", "Y — out of section (mm)"),
            labelpad=9,
        )
        self.axes.set_zlabel(
            self._text("Z — 레이저 방향 (mm)", "Z — laser direction (mm)"),
            labelpad=9,
        )
        self.axes.set_box_aspect((1.0, 1.0, 1.0), zoom=1.08)

    def _draw_empty(self) -> None:
        if self.canvas is None:
            return
        self.axes.clear()
        self._components.clear()
        self._fit_points.clear()
        self._head_points.clear()
        self.axes.set_title(
            self._text(
                "계산 가능한 설계 입력이 필요합니다.",
                "Enter a calculable optical design.",
            )
        )
        self._style_axes()
        for setter in (self.axes.set_xlim, self.axes.set_ylim, self.axes.set_zlim):
            setter(-10.0, 10.0)
        self.axes.view_init(elev=_ELEVATION_DEG, azim=_AZIMUTH_DEG)
        self._set_controls_enabled(False)
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
        label: str,
        normal_hint: np.ndarray,
        label_shift: np.ndarray,
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
        self._callout(name, center, center + label_shift, label, color)
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
        self._callout(
            "lens",
            center,
            center - _Y * radius * 1.9 - tangent * radius * 0.55,
            self._text("렌즈", "Lens"),
            _COLORS["lens"],
        )
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
        try:
            gamma, delta = full_focus_angles(
                self._magnification,
                self._alpha_deg,
                self._beta_deg,
            )
        except ValueError:
            gamma = delta = math.nan

        beam_direction = _unit(target - emitter, _Z)
        laser_plane_center = (emitter + target) / 2.0
        laser_half = max(
            plane_half,
            min(float(np.linalg.norm(target - emitter)) / 2.0, plane_half * 2.0),
        )
        plane_specs = (
            (
                "object_plane",
                target,
                _X,
                _Y,
                plane_half * 1.05,
                plane_half * 0.8,
                "object",
                0.15,
                self._text("물체 평면", "Object plane"),
                _Z,
                _Z * plane_half * 0.08,
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
                self._text("렌즈 평면", "Lens plane"),
                camera_axis,
                lens_tangent * plane_half * 0.68 + _Y * plane_half * 0.48,
                "-",
            ),
            (
                "ideal_focus_plane",
                image,
                sensor_tangent,
                _Y,
                sensor_half * 1.24,
                sensor_half,
                "focus",
                0.07,
                self._text(
                    "이상 초점면\n(센서와 일치)",
                    "Ideal focal plane\n(coincident with sensor)",
                ),
                sensor_normal,
                (
                    sensor_tangent * sensor_half * 1.45
                    + sensor_normal * sensor_half * 0.15
                    + _Y * sensor_half * 1.2
                ),
                "--",
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
                self._text("실제 센서 평면", "Actual sensor plane"),
                sensor_normal,
                (
                    -sensor_tangent * sensor_half * 1.05
                    + sensor_normal * sensor_half * 0.12
                    - _Y * sensor_half * 1.12
                ),
                "-",
            ),
            (
                "laser_plane",
                laser_plane_center,
                beam_direction,
                _Y,
                laser_half,
                plane_half * 0.55,
                "laser",
                0.055,
                self._text("레이저 평면", "Laser plane"),
                _X,
                _X * plane_half * 0.15,
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
            label,
            normal_hint,
            shift,
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
                label,
                normal_hint,
                shift,
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
        self._callout(
            "camera_body",
            camera_center,
            (
                camera_center
                + camera_axis * body_depth * 0.42
                + _Y * body_height * 1.05
                - lens_tangent * body_width * 0.45
            ),
            self._text("카메라 바디", "Camera body"),
            _COLORS["camera"],
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
        self._callout(
            "laser_emitter",
            emitter_center,
            emitter_center - _Y * emitter_size * 1.7 + emitter_side * emitter_size,
            self._text("레이저 발광기", "Laser emitter"),
            _COLORS["laser"],
        )

        actual_beam_end = _point3(snapshot.laser_endpoints[1])
        beam_end, self._beam_was_clipped = _clip(emitter, actual_beam_end, span * 1.35)
        self._line("laser_beam_glow", (emitter, beam_end), _COLORS["laser"], 6.0, alpha=0.12)
        self._line("laser_beam", (emitter, beam_end), _COLORS["laser"], 2.4)
        self._fit_points.extend((emitter, beam_end))
        if self._beam_was_clipped:
            self._callout(
                "laser_beam",
                beam_end,
                beam_end + _X * plane_half * 0.12,
                self._text(
                    f"빔 계속 → 실제 Z={actual_beam_end[2]:.1f} mm",
                    f"Beam continues → actual Z={actual_beam_end[2]:.1f} mm",
                ),
                _COLORS["laser"],
            )

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
        # This remains a clearly named reference: principal-plane data is not in the snapshot.
        hinge = (lens - _Y * line_half, lens + _Y * line_half)
        self._line("hinge_line", hinge, _COLORS["hinge"], 2.4, "--")
        self._fit_points.extend(hinge)

        head_centers = [emitter, lens, image, camera_center]
        if scheimpflug is not None and np.linalg.norm(scheimpflug - lens) <= plane_half * 2.5:
            head_centers.append(scheimpflug)
        values = np.asarray(head_centers)
        padding = max(8.0, plane_half * 0.36, body_height * 0.72, lens_radius * 1.25)
        self._head_points.extend(
            (
                values.min(axis=0) - padding,
                values.max(axis=0) + padding,
                *hinge,
            )
        )

        title = self._text("3D Scheimpflug 장비·평면 관계", "3D Scheimpflug assembly")
        angles = self._text(
            f"정확식 센서 자세  γ={gamma:.3f}° · δ={delta:.3f}°",
            f"Exact full-focus pose  γ={gamma:.3f}° · δ={delta:.3f}°",
        )
        self.axes.set_title(f"{title}\n{angles}", fontsize=12.0, pad=14, color=_COLORS["text"])
        self._view_notes(snapshot)
        self._style_axes()
        self._add_legend()
        self.fit_head(draw=False)
        self.reset_view(draw=False)
        self._set_controls_enabled(True)
        self.canvas.draw_idle()

    def _view_notes(self, snapshot: SceneSnapshot) -> None:
        style = {
            "boxstyle": "round,pad=0.2",
            "facecolor": "white",
            "alpha": 0.92,
        }
        schematic = self.axes.text2D(
            0.012,
            0.09,
            self._text(
                "개념 형상 · 장비 외형 크기는 실제 축척이 아님",
                "Schematic equipment shapes · body sizes are not to scale",
            ),
            transform=self.axes.transAxes,
            fontsize=7.8,
            color=_COLORS["muted"],
            bbox={**style, "edgecolor": "#c4ced8"},
        )
        self._head_note = self.axes.text2D(
            0.64,
            0.09,
            self._text(
                f"레이저 진행 → 화면 밖 물체/범위 · WD={snapshot.working_distance_mm:.1f} mm",
                f"Laser continues → off-screen range · WD={snapshot.working_distance_mm:.1f} mm",
            ),
            transform=self.axes.transAxes,
            fontsize=7.8,
            color=_COLORS["laser"],
            bbox={**style, "edgecolor": _COLORS["laser"]},
        )
        self._register("view_notes", schematic, self._head_note)

    def _add_legend(self) -> None:
        handles = [
            Patch(
                facecolor=_COLORS[key],
                edgecolor=_COLORS[key],
                alpha=0.24,
                label=self._text(korean, english),
            )
            for key, korean, english in (
                ("object", "물체 평면", "Object plane"),
                ("lens_plane", "렌즈 평면", "Lens plane"),
                ("sensor", "센서 평면", "Sensor plane"),
                ("laser", "레이저 평면", "Laser plane"),
            )
        ]
        handles.extend(
            Line2D(
                (0,),
                (0,),
                color=_COLORS[key],
                linewidth=width,
                linestyle=style,
                label=self._text(korean, english),
            )
            for key, width, style, korean, english in (
                ("laser", 2.4, "-", "레이저 빔", "Laser beam"),
                ("scheimpflug", 3.2, "-", "Scheimpflug 교선", "Scheimpflug line"),
                ("hinge", 2.4, "--", "Hinge 기준선", "Hinge reference"),
            )
        )
        legend = self.axes.legend(
            handles=handles,
            loc="upper left",
            bbox_to_anchor=(0.012, 0.985),
            fontsize=7.8,
            framealpha=0.94,
            edgecolor="#b7c3cf",
            ncols=2,
            title=self._text("표시 요소", "Scene key"),
            title_fontsize=8.2,
        )
        self._register("legend", legend)

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
        self._head_note.set_visible(True)
        if draw:
            self.canvas.draw_idle()

    def fit_view(self, _checked: bool = False, *, draw: bool = True) -> None:
        """Fit the complete working-distance relationship at equal axis scales."""

        if self.canvas is None or not self._fit_points:
            return
        self._fit_equal(self._fit_points)
        self._view_mode = "full"
        self.fit_button.setChecked(True)
        self._head_note.set_visible(False)
        if draw:
            self.canvas.draw_idle()

    def reset_view(self, _checked: bool = False, *, draw: bool = True) -> None:
        """Restore the readable default camera angle without recalculating."""

        if self.canvas is None:
            return
        self.axes.view_init(elev=_ELEVATION_DEG, azim=_AZIMUTH_DEG)
        if draw:
            self.canvas.draw_idle()
