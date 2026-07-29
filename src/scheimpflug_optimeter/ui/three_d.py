"""Three-dimensional Scheimpflug geometry preview."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from scheimpflug_optimeter.optics import full_focus_angles as _core_full_focus_angles

from .scene import SceneSnapshot

try:
    from matplotlib import font_manager, rcParams
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
except ImportError:  # pragma: no cover - dependency is required in packaged builds.
    FigureCanvasQTAgg = None
    Figure = None


def full_focus_angles(
    magnification: float,
    alpha_deg: float,
    beta_deg: float,
) -> tuple[float, float]:
    """Expose the exact core helper at the view boundary without duplicating it."""

    return _core_full_focus_angles(magnification, alpha_deg, beta_deg)


def _configure_plot_font() -> bool:
    """Prefer Korean labels when a CJK font is actually installed."""

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


class ThreeDWidget(QWidget):
    """Matplotlib view of object, lens, sensor, focal, and laser planes."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._snapshot: SceneSnapshot | None = None
        self._alpha_deg = 0.0
        self._beta_deg = 0.0
        self._magnification = 1.0
        self._korean_labels = _configure_plot_font()

        if Figure is None or FigureCanvasQTAgg is None:
            self.canvas = None
            self._message = QLabel("3D 보기를 사용하려면 Matplotlib Qt backend가 필요합니다.")
            self._message.setWordWrap(True)
            layout.addWidget(self._message)
            return

        self.figure = Figure(figsize=(8.0, 6.0), constrained_layout=True)
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111, projection="3d")
        layout.addWidget(self.canvas)
        self._draw_empty()

    def set_geometry(
        self,
        snapshot: SceneSnapshot | None,
        *,
        alpha_deg: float,
        beta_deg: float,
        magnification: float | None = None,
        render: bool = True,
    ) -> None:
        self._snapshot = snapshot
        self._alpha_deg = alpha_deg
        self._beta_deg = beta_deg
        if magnification is not None and magnification > 0:
            self._magnification = magnification
        if not render:
            return
        if self.canvas is None:
            return
        if snapshot is None:
            self._draw_empty()
            return
        self._draw_snapshot(snapshot)

    def _draw_empty(self) -> None:
        if self.canvas is None:
            return
        self.axes.clear()
        self.axes.set_title(
            "계산 가능한 설계 입력이 필요합니다."
            if self._korean_labels
            else "Enter a calculable optical design."
        )
        self.axes.set_xlabel("X (mm)")
        self.axes.set_ylabel("Y (mm)")
        self.axes.set_zlabel("Z (mm)")
        self.canvas.draw_idle()

    def _plane(
        self,
        center: tuple[float, float, float],
        first_direction: tuple[float, float, float],
        second_direction: tuple[float, float, float],
        size: float,
        *,
        color: str,
        alpha: float,
        label: str,
    ) -> None:
        grid = np.linspace(-size, size, 2)
        first, second = np.meshgrid(grid, grid)
        center_array = np.asarray(center, dtype=float)
        vector_a = np.asarray(first_direction, dtype=float)
        vector_b = np.asarray(second_direction, dtype=float)
        coordinates = (
            center_array[:, None, None]
            + vector_a[:, None, None] * first
            + vector_b[:, None, None] * second
        )
        self.axes.plot_surface(
            coordinates[0],
            coordinates[1],
            coordinates[2],
            color=color,
            alpha=alpha,
            linewidth=0,
            label=label,
        )

    def _draw_snapshot(self, snapshot: SceneSnapshot) -> None:
        self.axes.clear()
        span = max(
            20.0,
            snapshot.working_distance_mm,
            snapshot.measurement_range_mm * 2.0,
        )
        plane_size = max(8.0, span * 0.14)

        alpha = math.radians(self._alpha_deg)
        beta = math.radians(self._beta_deg)
        try:
            gamma_deg, delta_deg = full_focus_angles(
                self._magnification,
                self._alpha_deg,
                self._beta_deg,
            )
        except ValueError:
            gamma_deg = delta_deg = float("nan")

        # Physical axes: X is receiver baseline, Y is out of section, Z follows laser.
        laser_z = np.array([snapshot.emitter.z_mm, snapshot.target_far.z_mm + plane_size])
        self.axes.plot(
            np.full(2, snapshot.emitter.x_mm),
            np.zeros(2),
            laser_z,
            color="#ff3b30",
            linewidth=2.2,
            label="레이저 조사선" if self._korean_labels else "Laser line",
        )

        self._plane(
            (
                snapshot.target_nominal.x_mm,
                0.0,
                snapshot.target_nominal.z_mm,
            ),
            (1.0, 0.0, 0.0),
            (0.0, 1.0, 0.0),
            plane_size,
            color="#43d17d",
            alpha=0.18,
            label="물체 평면" if self._korean_labels else "Object plane",
        )

        lens_tangent = (math.cos(alpha), 0.0, math.sin(alpha))
        self._plane(
            (snapshot.lens_center.x_mm, 0.0, snapshot.lens_center.z_mm),
            lens_tangent,
            (0.0, 1.0, 0.0),
            plane_size,
            color="#65b7ff",
            alpha=0.28,
            label="렌즈 평면" if self._korean_labels else "Lens plane",
        )

        # Actual image plane direction in the X/Z section.
        sensor_angle = alpha + beta
        sensor_tangent = (
            -math.sin(sensor_angle),
            0.0,
            math.cos(sensor_angle),
        )
        self._plane(
            (snapshot.image_center.x_mm, 0.0, snapshot.image_center.z_mm),
            sensor_tangent,
            (0.0, 1.0, 0.0),
            plane_size,
            color="#ffd166",
            alpha=0.34,
            label="실제 센서 평면" if self._korean_labels else "Actual sensor plane",
        )

        # Ideal focal plane: kept distinct to expose as-built sensor deviation.
        focus_center = (
            snapshot.image_center.x_mm,
            0.0,
            snapshot.image_center.z_mm,
        )
        self._plane(
            focus_center,
            sensor_tangent,
            (0.0, 1.0, 0.0),
            plane_size * 0.92,
            color="#ff9f43",
            alpha=0.12,
            label="이상 초점면" if self._korean_labels else "Ideal focal plane",
        )

        # A vertical laser sheet supplies the line-structured-light plane.
        self._plane(
            (snapshot.emitter.x_mm, 0.0, snapshot.working_distance_mm / 2.0),
            (0.0, 0.0, 1.0),
            (0.0, 1.0, 0.0),
            plane_size,
            color="#ff3b30",
            alpha=0.09,
            label="레이저 평면" if self._korean_labels else "Laser plane",
        )

        if snapshot.scheimpflug_point is not None:
            point = snapshot.scheimpflug_point
            y = np.array([-plane_size, plane_size])
            self.axes.plot(
                np.full(2, point.x_mm),
                y,
                np.full(2, point.z_mm),
                color="#ffb347",
                linewidth=3.0,
                label=("Scheimpflug 교선" if self._korean_labels else "Scheimpflug line"),
            )

        # Hinge line lies in the lens plane and is separately styled.  In this
        # section model it is drawn through the lens center and annotated, while
        # calibrated 3-D geometry can later provide an as-built offset.
        hinge_y = np.array([-plane_size, plane_size])
        self.axes.plot(
            np.full(2, snapshot.lens_center.x_mm),
            hinge_y,
            np.full(2, snapshot.lens_center.z_mm),
            color="#be95ff",
            linestyle="--",
            linewidth=2.0,
            label="hinge line",
        )

        for ray in snapshot.chief_rays:
            x = [point.x_mm for point in ray]
            z = [point.z_mm for point in ray]
            self.axes.plot(x, [0.0] * len(x), z, color="#be95ff", linewidth=1.0)

        title = "3D Scheimpflug 구조" if self._korean_labels else "3D Scheimpflug geometry"
        self.axes.set_title(f"{title}  γ={gamma_deg:.3f}°, δ={delta_deg:.3f}°")
        self.axes.set_xlabel("X (mm)")
        self.axes.set_ylabel("Y (mm)")
        self.axes.set_zlabel("Z (mm)")
        self.axes.set_box_aspect((1.0, 0.65, 1.0))
        self.axes.view_init(elev=23.0, azim=-58.0)
        self.axes.legend(loc="upper left", fontsize=8)
        self.canvas.draw_idle()
