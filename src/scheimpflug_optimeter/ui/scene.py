"""Reusable, equal-scale 2-D optical scene."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)


@dataclass(frozen=True, slots=True)
class Point2D:
    """A point in the physical X/Z plane, expressed in millimetres."""

    x_mm: float
    z_mm: float


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    """All geometry needed by the 2-D view; the scene never solves optics."""

    emitter: Point2D
    laser_endpoints: tuple[Point2D, Point2D]
    target_near: Point2D
    target_nominal: Point2D
    target_far: Point2D
    working_distance_endpoints: tuple[Point2D, Point2D]
    range_endpoints: tuple[Point2D, Point2D]
    lens_center: Point2D
    lens_endpoints: tuple[Point2D, Point2D]
    image_center: Point2D
    sensor_endpoints: tuple[Point2D, Point2D]
    proxy_sensor_endpoints: tuple[Point2D, Point2D] | None
    optical_axis_endpoints: tuple[Point2D, Point2D]
    chief_rays: tuple[
        tuple[Point2D, Point2D, Point2D],
        tuple[Point2D, Point2D, Point2D],
    ]
    scheimpflug_point: Point2D | None
    working_distance_mm: float
    measurement_range_mm: float
    w_mm: float
    r_mm: float
    lo_mm: float
    fp_mm: float
    focal_length_mm: float
    valid: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)
    range_label: str = "측정 범위 S"
    target_nominal_label: str = "기준거리"
    workbook_mode: bool = False


def _scene_point(point: Point2D) -> QPointF:
    # Qt's screen Y axis points down; physical +Z points up in the diagram.
    return QPointF(point.x_mm, -point.z_mm)


def _bounds(points: Iterable[Point2D]) -> QRectF:
    finite = [point for point in points if math.isfinite(point.x_mm) and math.isfinite(point.z_mm)]
    if not finite:
        return QRectF(-10.0, -10.0, 20.0, 20.0)
    minimum_x = min(point.x_mm for point in finite)
    maximum_x = max(point.x_mm for point in finite)
    minimum_z = min(point.z_mm for point in finite)
    maximum_z = max(point.z_mm for point in finite)
    width = max(20.0, maximum_x - minimum_x)
    height = max(20.0, maximum_z - minimum_z)
    margin = max(10.0, 0.08 * max(width, height))
    return QRectF(
        minimum_x - margin,
        -(maximum_z + margin),
        width + 2.0 * margin,
        height + 2.0 * margin,
    )


class OpticsGraphicsScene(QGraphicsScene):
    """A graphics scene that updates existing items instead of rebuilding them."""

    COLORS = {
        "background": QColor("#10151d"),
        "grid": QColor("#263241"),
        "text": QColor("#e6edf3"),
        "muted": QColor("#9aa7b3"),
        "laser": QColor("#ff3b30"),
        "target": QColor("#43d17d"),
        "lens": QColor("#65b7ff"),
        "axis": QColor("#aab7c4"),
        "sensor": QColor("#ffd166"),
        "proxy": QColor("#ff9f43"),
        "ray": QColor("#be95ff"),
        "dimension": QColor("#64d8cb"),
        "invalid": QColor("#ff5d73"),
        "warning": QColor("#ffb347"),
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(self.COLORS["background"])
        self._snapshot: SceneSnapshot | None = None
        self._first_snapshot = True

        self.laser_line = self._line("laser", 2.4)
        self.target_near_line = self._line("target", 1.5, Qt.PenStyle.DashLine)
        self.target_nominal_line = self._line("target", 2.6)
        self.target_far_line = self._line("target", 1.5, Qt.PenStyle.DashLine)
        self.lens_line = self._line("lens", 4.0)
        self.optical_axis_line = self._line("axis", 1.2, Qt.PenStyle.DashDotLine)
        self.sensor_line = self._line("sensor", 4.2)
        self.proxy_sensor_line = self._line("proxy", 1.6, Qt.PenStyle.DashLine)
        self.near_ray_before = self._line("ray", 1.2)
        self.near_ray_after = self._line("ray", 1.2)
        self.far_ray_before = self._line("ray", 1.2)
        self.far_ray_after = self._line("ray", 1.2)
        self.w_dimension = self._line("dimension", 1.2)
        self.r_dimension = self._line("dimension", 1.2)
        self.wd_dimension = self._line("dimension", 1.2)
        self.range_dimension = self._line("dimension", 1.2)

        self.emitter_marker = self._marker("laser", 4.0)
        self.lens_marker = self._marker("lens", 4.0)
        self.image_marker = self._marker("sensor", 3.5)
        self.scheimpflug_marker = self._marker("warning", 4.5)

        self.invalid_overlay = QGraphicsRectItem()
        self.invalid_overlay.setPen(QPen(self.COLORS["invalid"], 2.2, Qt.PenStyle.DashLine))
        self.invalid_overlay.setBrush(Qt.BrushStyle.NoBrush)
        self.addItem(self.invalid_overlay)

        self.labels = {
            name: self._text()
            for name in (
                "laser",
                "near",
                "nominal",
                "far",
                "lens",
                "sensor",
                "proxy",
                "axis",
                "scheimpflug",
                "wd",
                "range",
                "w",
                "r",
                "distances",
                "invalid",
            )
        }
        self.labels["invalid"].setBrush(self.COLORS["invalid"])
        invalid_font = QFont()
        invalid_font.setBold(True)
        invalid_font.setPointSize(11)
        self.labels["invalid"].setFont(invalid_font)

        for item in self.items():
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._normal_pens = {
            item: QPen(item.pen())
            for item in (
                self.laser_line,
                self.target_near_line,
                self.target_nominal_line,
                self.target_far_line,
                self.lens_line,
                self.optical_axis_line,
                self.sensor_line,
                self.proxy_sensor_line,
                self.near_ray_before,
                self.near_ray_after,
                self.far_ray_before,
                self.far_ray_after,
            )
        }

    def _line(
        self,
        color: str,
        width: float,
        style: Qt.PenStyle = Qt.PenStyle.SolidLine,
    ) -> QGraphicsLineItem:
        item = QGraphicsLineItem()
        pen = QPen(self.COLORS[color], width, style)
        pen.setCosmetic(True)
        item.setPen(pen)
        self.addItem(item)
        return item

    def _marker(self, color: str, radius: float) -> QGraphicsEllipseItem:
        item = QGraphicsEllipseItem(-radius, -radius, radius * 2.0, radius * 2.0)
        pen = QPen(self.COLORS[color], 1.5)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(self.COLORS[color])
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.addItem(item)
        return item

    def _text(self) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem()
        item.setBrush(self.COLORS["text"])
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        self.addItem(item)
        return item

    @staticmethod
    def _set_line(
        item: QGraphicsLineItem,
        first: Point2D,
        second: Point2D,
    ) -> None:
        item.setLine(
            first.x_mm,
            -first.z_mm,
            second.x_mm,
            -second.z_mm,
        )

    @staticmethod
    def _position(item: QGraphicsItem, point: Point2D) -> None:
        item.setPos(_scene_point(point))

    def set_snapshot(self, snapshot: SceneSnapshot | None) -> None:
        """Update every scene item from one immutable calculation snapshot."""

        self._snapshot = snapshot
        self.set_invalid_message(None)
        if snapshot is None:
            for item in self.items():
                item.setVisible(False)
            self.labels["invalid"].setVisible(True)
            self.labels["invalid"].setText("계산 결과가 없습니다.")
            self.labels["invalid"].setPos(0.0, 0.0)
            self.setSceneRect(-100.0, -100.0, 200.0, 200.0)
            return

        for item in self.items():
            item.setVisible(True)
        self.proxy_sensor_line.setVisible(snapshot.proxy_sensor_endpoints is not None)
        self.labels["proxy"].setVisible(snapshot.proxy_sensor_endpoints is not None)
        self.scheimpflug_marker.setVisible(snapshot.scheimpflug_point is not None)
        self.labels["scheimpflug"].setVisible(snapshot.scheimpflug_point is not None)

        all_points = [
            snapshot.emitter,
            *snapshot.laser_endpoints,
            snapshot.target_near,
            snapshot.target_nominal,
            snapshot.target_far,
            *snapshot.working_distance_endpoints,
            snapshot.lens_center,
            *snapshot.lens_endpoints,
            snapshot.image_center,
            *snapshot.sensor_endpoints,
            *snapshot.optical_axis_endpoints,
        ]
        for ray in snapshot.chief_rays:
            all_points.extend(ray)
        if snapshot.proxy_sensor_endpoints:
            all_points.extend(snapshot.proxy_sensor_endpoints)
        if snapshot.workbook_mode:
            # Workbook ``s`` may be far below the useful head/WD geometry.
            all_points = [point for point in all_points if point != snapshot.target_far]
        envelope_bottom_z = (
            min(
                snapshot.emitter.z_mm,
                snapshot.lens_center.z_mm,
            )
            - 5.0
        )
        all_points.extend(
            (
                Point2D(snapshot.w_mm, envelope_bottom_z),
                Point2D(
                    snapshot.lens_center.x_mm,
                    snapshot.target_nominal.z_mm - snapshot.r_mm,
                ),
            )
        )

        # Remote range/Scheimpflug intersections should not destroy useful scale.
        nominal_bounds = _bounds(all_points)
        characteristic = max(nominal_bounds.width(), nominal_bounds.height())
        range_center = nominal_bounds.center()
        range_end = snapshot.range_endpoints[1]
        range_distance = math.hypot(
            range_end.x_mm - range_center.x(),
            -range_end.z_mm - range_center.y(),
        )
        range_is_remote = range_distance > 2.0 * characteristic
        if not range_is_remote:
            all_points.extend(snapshot.range_endpoints)

        visible_scheimpflug = snapshot.scheimpflug_point
        intersection_is_remote = False
        if visible_scheimpflug is not None:
            center = nominal_bounds.center()
            distance = math.hypot(
                visible_scheimpflug.x_mm - center.x(),
                -visible_scheimpflug.z_mm - center.y(),
            )
            intersection_is_remote = distance > 4.0 * characteristic
            if not intersection_is_remote:
                all_points.append(visible_scheimpflug)

        scene_rect = _bounds(all_points)
        self.setSceneRect(scene_rect)
        visible_range_endpoints = (
            (
                snapshot.range_endpoints[0],
                self._clip_to_rect(snapshot.range_endpoints[1], scene_rect),
            )
            if range_is_remote
            else snapshot.range_endpoints
        )

        def visible_point(point: Point2D) -> Point2D:
            return (
                point
                if scene_rect.contains(_scene_point(point))
                else self._clip_to_rect(point, scene_rect)
            )

        self._set_line(
            self.laser_line,
            *(visible_point(point) for point in snapshot.laser_endpoints),
        )

        target_half_width = max(8.0, scene_rect.width() * 0.06)
        for item, point in (
            (self.target_near_line, snapshot.target_near),
            (self.target_nominal_line, snapshot.target_nominal),
            (self.target_far_line, snapshot.target_far),
        ):
            point = visible_point(point)
            self._set_line(
                item,
                Point2D(point.x_mm - target_half_width, point.z_mm),
                Point2D(point.x_mm + target_half_width, point.z_mm),
            )
        targets_distinct = not snapshot.workbook_mode and (
            math.hypot(
                snapshot.target_near.x_mm - snapshot.target_far.x_mm,
                snapshot.target_near.z_mm - snapshot.target_far.z_mm,
            )
            > 1e-9
        )
        self.target_near_line.setVisible(targets_distinct)
        self.target_far_line.setVisible(targets_distinct)
        self.labels["near"].setVisible(targets_distinct)
        self.labels["far"].setVisible(targets_distinct)

        self._set_line(self.lens_line, *snapshot.lens_endpoints)
        self._set_line(self.sensor_line, *snapshot.sensor_endpoints)
        self._set_line(self.optical_axis_line, *snapshot.optical_axis_endpoints)
        if snapshot.proxy_sensor_endpoints is not None:
            self._set_line(self.proxy_sensor_line, *snapshot.proxy_sensor_endpoints)

        near_ray, far_ray = snapshot.chief_rays
        self._set_line(
            self.near_ray_before,
            visible_point(near_ray[0]),
            visible_point(near_ray[1]),
        )
        self._set_line(
            self.near_ray_after,
            visible_point(near_ray[1]),
            visible_point(near_ray[2]),
        )
        self._set_line(
            self.far_ray_before,
            visible_point(far_ray[0]),
            visible_point(far_ray[1]),
        )
        self._set_line(
            self.far_ray_after,
            visible_point(far_ray[1]),
            visible_point(far_ray[2]),
        )

        dimension_x = scene_rect.left() + scene_rect.width() * 0.08
        self._set_line(
            self.wd_dimension,
            Point2D(dimension_x, snapshot.working_distance_endpoints[0].z_mm),
            Point2D(dimension_x, snapshot.working_distance_endpoints[1].z_mm),
        )
        range_x = dimension_x + max(4.0, scene_rect.width() * 0.04)
        self._set_line(
            self.range_dimension,
            Point2D(range_x, visible_range_endpoints[0].z_mm),
            Point2D(range_x, visible_range_endpoints[1].z_mm),
        )
        bottom_z = envelope_bottom_z
        self._set_line(
            self.w_dimension,
            Point2D(0.0, bottom_z),
            Point2D(snapshot.w_mm, bottom_z),
        )
        self._set_line(
            self.r_dimension,
            Point2D(snapshot.lens_center.x_mm, snapshot.target_nominal.z_mm),
            Point2D(snapshot.lens_center.x_mm, snapshot.target_nominal.z_mm - snapshot.r_mm),
        )

        self._position(self.emitter_marker, snapshot.emitter)
        self._position(self.lens_marker, snapshot.lens_center)
        self._position(self.image_marker, snapshot.image_center)

        if snapshot.scheimpflug_point is not None:
            if intersection_is_remote:
                clipped = self._clip_to_rect(snapshot.scheimpflug_point, scene_rect)
                self._position(self.scheimpflug_marker, clipped)
                text = (
                    "Scheimpflug 교점 ↗ "
                    f"({snapshot.scheimpflug_point.x_mm:.2f}, "
                    f"{snapshot.scheimpflug_point.z_mm:.2f}) mm"
                )
                self.labels["scheimpflug"].setText(text)
                self._position(self.labels["scheimpflug"], clipped)
            else:
                self._position(self.scheimpflug_marker, snapshot.scheimpflug_point)
                self.labels["scheimpflug"].setText("Scheimpflug 교점")
                self._position(self.labels["scheimpflug"], snapshot.scheimpflug_point)

        label_offset_x = max(2.0, scene_rect.width() * 0.012)
        label_offset_z = max(2.0, scene_rect.height() * 0.012)

        def label(name: str, text: str, point: Point2D) -> None:
            self.labels[name].setText(text)
            self._position(
                self.labels[name],
                Point2D(point.x_mm + label_offset_x, point.z_mm + label_offset_z),
            )

        laser_midpoint = Point2D(
            (snapshot.laser_endpoints[0].x_mm + snapshot.laser_endpoints[1].x_mm) / 2.0,
            (snapshot.laser_endpoints[0].z_mm + snapshot.laser_endpoints[1].z_mm) / 2.0,
        )
        label("laser", "레이저 조사 직선", laser_midpoint)
        if targets_distinct:
            label(
                "near",
                "근거리",
                Point2D(
                    snapshot.target_near.x_mm - target_half_width,
                    snapshot.target_near.z_mm - label_offset_z,
                ),
            )
        label(
            "nominal",
            snapshot.target_nominal_label,
            Point2D(
                snapshot.target_nominal.x_mm + target_half_width,
                snapshot.target_nominal.z_mm,
            ),
        )
        if targets_distinct:
            label(
                "far",
                "원거리",
                Point2D(
                    snapshot.target_far.x_mm - target_half_width,
                    snapshot.target_far.z_mm + label_offset_z,
                ),
            )
        label("lens", "렌즈 평면", snapshot.lens_endpoints[0])
        label("sensor", "실제 이미지/센서 평면", snapshot.sensor_endpoints[0])
        optical_axis_midpoint = Point2D(
            (snapshot.optical_axis_endpoints[0].x_mm + snapshot.optical_axis_endpoints[1].x_mm)
            / 2.0,
            (snapshot.optical_axis_endpoints[0].z_mm + snapshot.optical_axis_endpoints[1].z_mm)
            / 2.0,
        )
        label("axis", "수광 광축", optical_axis_midpoint)
        if snapshot.proxy_sensor_endpoints is not None:
            label(
                "proxy",
                "중심 대칭 패키지 근사",
                snapshot.proxy_sensor_endpoints[0],
            )

        self.labels["wd"].setText(f"WD d = {snapshot.working_distance_mm:.3f} mm")
        self.labels["wd"].setPos(
            dimension_x + label_offset_x,
            -(
                snapshot.working_distance_endpoints[0].z_mm
                + snapshot.working_distance_endpoints[1].z_mm
            )
            / 2.0,
        )
        range_suffix = " ↓ (화면 밖)" if range_is_remote else ""
        self.labels["range"].setText(
            f"{snapshot.range_label} = {snapshot.measurement_range_mm:.3f} mm{range_suffix}"
        )
        self.labels["range"].setPos(
            range_x + label_offset_x,
            -(visible_range_endpoints[0].z_mm + visible_range_endpoints[1].z_mm) / 2.0,
        )
        self.labels["w"].setText(f"W = {snapshot.w_mm:.3f} mm")
        self.labels["w"].setPos(snapshot.w_mm / 2.0, -bottom_z)
        self.labels["r"].setText(f"R = {snapshot.r_mm:.3f} mm")
        self.labels["r"].setPos(
            snapshot.lens_center.x_mm + label_offset_x,
            -(snapshot.target_nominal.z_mm - snapshot.r_mm / 2.0),
        )
        self.labels["distances"].setText(
            f"f={snapshot.focal_length_mm:.3f}  lo={snapshot.lo_mm:.3f}  fp={snapshot.fp_mm:.3f} mm"
        )
        self._position(
            self.labels["distances"],
            Point2D(
                snapshot.image_center.x_mm + target_half_width,
                snapshot.image_center.z_mm - 2.0 * label_offset_z,
            ),
        )

        self.invalid_overlay.setRect(scene_rect)
        self.invalid_overlay.setVisible(not snapshot.valid)
        invalid_text = "\n".join(snapshot.warnings) or "유효하지 않은 광학 구조"
        self.labels["invalid"].setText(invalid_text if not snapshot.valid else "")
        self.labels["invalid"].setVisible(not snapshot.valid)
        self.labels["invalid"].setPos(
            scene_rect.left() + scene_rect.width() * 0.04,
            scene_rect.top() + scene_rect.height() * 0.04,
        )

        invalid_style = not snapshot.valid
        for item in (
            self.laser_line,
            self.target_near_line,
            self.target_nominal_line,
            self.target_far_line,
            self.lens_line,
            self.optical_axis_line,
            self.sensor_line,
            self.proxy_sensor_line,
            self.near_ray_before,
            self.near_ray_after,
            self.far_ray_before,
            self.far_ray_after,
        ):
            original = item.pen()
            if invalid_style:
                item.setPen(
                    QPen(
                        self.COLORS["invalid"],
                        original.widthF(),
                        Qt.PenStyle.DashLine,
                    )
                )
            else:
                item.setPen(QPen(self._normal_pens[item]))

    @staticmethod
    def _clip_to_rect(point: Point2D, rect: QRectF) -> Point2D:
        x = min(max(point.x_mm, rect.left()), rect.right())
        y = min(max(-point.z_mm, rect.top()), rect.bottom())
        return Point2D(x, -y)

    def set_invalid_message(self, message: str | None) -> None:
        """Show a calculation failure without retaining a stale valid diagram."""

        if message is None:
            return
        self._snapshot = None
        for item in self.items():
            item.setVisible(False)
        self.setSceneRect(-100.0, -100.0, 200.0, 200.0)
        self.invalid_overlay.setRect(self.sceneRect())
        self.invalid_overlay.setVisible(True)
        self.labels["invalid"].setVisible(True)
        self.labels["invalid"].setText(message)
        self.labels["invalid"].setPos(-90.0, -90.0)

    def export_png(self, path: str | Path, scale: float = 2.0) -> Path:
        """Render the current scene to a transparent-safe PNG image."""

        target = Path(path)
        rect = self.itemsBoundingRect().adjusted(-8.0, -8.0, 8.0, 8.0)
        width = max(1, math.ceil(rect.width() * scale))
        height = max(1, math.ceil(rect.height() * scale))
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(self.COLORS["background"])
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.render(painter, QRectF(0.0, 0.0, width, height), rect)
        painter.end()
        if not image.save(str(target), "PNG"):
            raise OSError(f"PNG 파일을 저장하지 못했습니다: {target}")
        return target

    def optical_head_rect(self) -> QRectF:
        """Return a readable target/lens/sensor detail region, excluding emitter WD."""

        snapshot = self._snapshot
        if snapshot is None:
            return self.sceneRect()
        points = [
            snapshot.target_near,
            snapshot.target_nominal,
            snapshot.target_far,
            snapshot.lens_center,
            *snapshot.lens_endpoints,
            snapshot.image_center,
            *snapshot.sensor_endpoints,
            *snapshot.optical_axis_endpoints,
        ]
        if snapshot.proxy_sensor_endpoints is not None:
            points.extend(snapshot.proxy_sensor_endpoints)
        if snapshot.scheimpflug_point is not None:
            head_bounds = _bounds(points)
            intersection = snapshot.scheimpflug_point
            center = head_bounds.center()
            if math.hypot(
                intersection.x_mm - center.x(),
                -intersection.z_mm - center.y(),
            ) <= 2.0 * max(head_bounds.width(), head_bounds.height()):
                points.append(intersection)
        return _bounds(points)

    def export_svg(self, path: str | Path) -> Path:
        """Render the current scene to SVG using Qt's vector generator."""

        from PySide6.QtSvg import QSvgGenerator

        target = Path(path)
        rect = self.itemsBoundingRect().adjusted(-8.0, -8.0, 8.0, 8.0)
        generator = QSvgGenerator()
        generator.setFileName(str(target))
        generator.setSize(rect.size().toSize())
        generator.setViewBox(rect)
        generator.setTitle("Scheimpflug OptiMeter optical layout")
        painter = QPainter(generator)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.render(painter, rect, rect)
        painter.end()
        return target


class OpticsGraphicsView(QGraphicsView):
    """Pan/zoom view that preserves the physical X/Z aspect ratio."""

    def __init__(self, scene: OpticsGraphicsScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setMinimumSize(520, 420)

    def fit_scene(self) -> None:
        scene = self.scene()
        if scene is not None and not scene.sceneRect().isEmpty():
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def fit_optical_head(self) -> None:
        scene = self.scene()
        if isinstance(scene, OpticsGraphicsScene):
            self.fitInView(
                scene.optical_head_rect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)
