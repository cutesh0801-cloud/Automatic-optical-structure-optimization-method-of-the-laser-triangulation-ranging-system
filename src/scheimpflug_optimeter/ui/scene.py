"""Reusable, equal-scale 2-D optical scene."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsPolygonItem,
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


@dataclass(frozen=True, slots=True)
class _CalloutSpec:
    """Device-space label placement request."""

    text: str
    anchor: Point2D
    preferred_quadrants: tuple[str, ...] = ("ne", "se", "nw", "sw")
    leader: bool = True


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

        self.laser_line = self._line("laser", 3.0)
        self.target_near_line = self._line("target", 1.5, Qt.PenStyle.DashLine)
        self.target_nominal_line = self._line("target", 2.6)
        self.target_far_line = self._line("target", 1.5, Qt.PenStyle.DashLine)
        self.lens_line = self._line("lens", 4.6)
        self.optical_axis_line = self._line("axis", 1.2, Qt.PenStyle.DashDotLine)
        self.sensor_line = self._line("sensor", 4.8)
        self.proxy_sensor_line = self._line("proxy", 1.6, Qt.PenStyle.DashLine)
        self.near_ray_before = self._line("ray", 1.2)
        self.near_ray_after = self._line("ray", 1.2)
        self.far_ray_before = self._line("ray", 1.2)
        self.far_ray_after = self._line("ray", 1.2)
        self.w_dimension = self._line("dimension", 1.2)
        self.r_dimension = self._line("dimension", 1.2)
        self.wd_dimension = self._line("dimension", 1.2)
        self.range_dimension = self._line("dimension", 1.2)
        self.dimension_arrowheads = {
            name: tuple(self._line("dimension", 1.2) for _ in range(4))
            for name in ("wd", "range", "w", "r")
        }

        self.emitter_marker = self._marker("laser", 5.0)
        self.lens_marker = self._marker("lens", 4.0)
        self.image_marker = self._marker("sensor", 3.5)
        self.scheimpflug_marker = self._marker("warning", 4.5)
        self.lens_plane_marker = self._screen_plane_marker("lens", 10.0, 5.2)
        self.sensor_plane_marker = self._screen_plane_marker("sensor", 12.0, 5.4)
        self.range_remote_arrow = self._remote_arrow("dimension")
        self.scheimpflug_remote_arrow = self._remote_arrow("warning")
        self.range_remote_arrow.setVisible(False)
        self.scheimpflug_remote_arrow.setVisible(False)

        self.invalid_overlay = QGraphicsRectItem()
        invalid_overlay_pen = QPen(self.COLORS["invalid"], 2.2, Qt.PenStyle.DashLine)
        invalid_overlay_pen.setCosmetic(True)
        self.invalid_overlay.setPen(invalid_overlay_pen)
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
                "legend",
                "invalid",
            )
        }
        self._callout_names = tuple(name for name in self.labels if name != "invalid")
        for name in self._callout_names:
            callout_font = QFont(self.labels[name].font())
            callout_font.setPointSizeF(10.5)
            self.labels[name].setFont(callout_font)
        self.label_backgrounds = {name: self._callout_background() for name in self._callout_names}
        self.label_leaders = {name: self._line("muted", 1.0) for name in self._callout_names}
        for leader in self.label_leaders.values():
            leader.setZValue(39.0)
        self._callout_specs: dict[str, _CalloutSpec] = {}
        self.labels["invalid"].setBrush(self.COLORS["invalid"])
        invalid_font = QFont()
        invalid_font.setBold(True)
        invalid_font.setPointSize(11)
        self.labels["invalid"].setFont(invalid_font)
        self.labels["invalid"].setZValue(51.0)
        self.invalid_overlay.setZValue(49.0)

        for item in (
            self.near_ray_before,
            self.near_ray_after,
            self.far_ray_before,
            self.far_ray_after,
        ):
            item.setZValue(5.0)
        for item in (
            self.w_dimension,
            self.r_dimension,
            self.wd_dimension,
            self.range_dimension,
            *(arrow for arrows in self.dimension_arrowheads.values() for arrow in arrows),
        ):
            item.setZValue(8.0)
        for item in (
            self.target_near_line,
            self.target_nominal_line,
            self.target_far_line,
        ):
            item.setZValue(12.0)
        self.proxy_sensor_line.setZValue(14.0)
        self.optical_axis_line.setZValue(15.0)
        self.laser_line.setZValue(20.0)
        self.lens_line.setZValue(24.0)
        self.sensor_line.setZValue(25.0)
        for item in (
            self.emitter_marker,
            self.lens_marker,
            self.image_marker,
            self.scheimpflug_marker,
        ):
            item.setZValue(30.0)
        self.lens_plane_marker.setZValue(31.0)
        self.sensor_plane_marker.setZValue(32.0)

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
                self.lens_plane_marker,
                self.sensor_plane_marker,
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
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item.setPen(pen)
        self.addItem(item)
        return item

    def _screen_plane_marker(
        self,
        color: str,
        half_length_px: float,
        width_px: float,
    ) -> QGraphicsLineItem:
        """Create a fixed-screen-size plane glyph anchored to physical geometry."""

        item = QGraphicsLineItem(-half_length_px, 0.0, half_length_px, 0.0)
        pen = QPen(self.COLORS[color], width_px)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        item.setPen(pen)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
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

    def _remote_arrow(self, color: str) -> QGraphicsPolygonItem:
        item = QGraphicsPolygonItem(
            QPolygonF((QPointF(0.0, 0.0), QPointF(-11.0, -5.0), QPointF(-11.0, 5.0)))
        )
        pen = QPen(self.COLORS[color], 1.2)
        pen.setCosmetic(True)
        item.setPen(pen)
        item.setBrush(self.COLORS[color])
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(35.0)
        self.addItem(item)
        return item

    def _callout_background(self) -> QGraphicsRectItem:
        item = QGraphicsRectItem()
        border = QColor(self.COLORS["muted"])
        border.setAlpha(190)
        pen = QPen(border, 1.0)
        pen.setCosmetic(True)
        item.setPen(pen)
        background = QColor(self.COLORS["background"])
        background.setAlpha(225)
        item.setBrush(background)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(40.0)
        self.addItem(item)
        return item

    def _text(self) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem()
        item.setBrush(self.COLORS["text"])
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations, True)
        item.setZValue(41.0)
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

    @staticmethod
    def _position_screen_plane(
        item: QGraphicsLineItem,
        endpoints: tuple[Point2D, Point2D],
    ) -> None:
        """Anchor a fixed-size glyph at a physical plane's centre and angle."""

        start = _scene_point(endpoints[0])
        end = _scene_point(endpoints[1])
        item.setPos((start + end) / 2.0)
        item.setRotation(
            math.degrees(
                math.atan2(
                    end.y() - start.y(),
                    end.x() - start.x(),
                )
            )
        )

    def _set_dimension(
        self,
        name: str,
        item: QGraphicsLineItem,
        first: Point2D,
        second: Point2D,
        arrow_size: float,
    ) -> None:
        self._set_line(item, first, second)
        start = _scene_point(first)
        end = _scene_point(second)
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = math.hypot(dx, dy)
        arrows = self.dimension_arrowheads[name]
        if length <= 1e-12:
            for arrow in arrows:
                arrow.setVisible(False)
            return
        ux = dx / length
        uy = dy / length
        cosine = math.cos(math.radians(28.0))
        sine = math.sin(math.radians(28.0))

        def rotated(vector_x: float, vector_y: float, sign: float) -> tuple[float, float]:
            return (
                vector_x * cosine - sign * vector_y * sine,
                sign * vector_x * sine + vector_y * cosine,
            )

        start_left = rotated(ux, uy, 1.0)
        start_right = rotated(ux, uy, -1.0)
        end_left = rotated(-ux, -uy, 1.0)
        end_right = rotated(-ux, -uy, -1.0)
        tails = (
            QPointF(
                start.x() + arrow_size * start_left[0],
                start.y() + arrow_size * start_left[1],
            ),
            QPointF(
                start.x() + arrow_size * start_right[0],
                start.y() + arrow_size * start_right[1],
            ),
            QPointF(
                end.x() + arrow_size * end_left[0],
                end.y() + arrow_size * end_left[1],
            ),
            QPointF(
                end.x() + arrow_size * end_right[0],
                end.y() + arrow_size * end_right[1],
            ),
        )
        for arrow, tip, tail in zip(
            arrows,
            (start, start, end, end),
            tails,
            strict=True,
        ):
            arrow.setLine(QLineF(tip, tail))
            arrow.setVisible(item.isVisible())

    @staticmethod
    def _clip_from_origin(origin: Point2D, target: Point2D, rect: QRectF) -> Point2D:
        """Clip an origin-to-target ray at the first rectangle boundary."""

        start = _scene_point(origin)
        end = _scene_point(target)
        if rect.contains(end):
            return target
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        candidates: list[tuple[float, QPointF]] = []
        if abs(dx) > 1e-12:
            for boundary_x in (rect.left(), rect.right()):
                ratio = (boundary_x - start.x()) / dx
                y = start.y() + ratio * dy
                if ratio >= 0.0 and rect.top() - 1e-9 <= y <= rect.bottom() + 1e-9:
                    candidates.append((ratio, QPointF(boundary_x, y)))
        if abs(dy) > 1e-12:
            for boundary_y in (rect.top(), rect.bottom()):
                ratio = (boundary_y - start.y()) / dy
                x = start.x() + ratio * dx
                if ratio >= 0.0 and rect.left() - 1e-9 <= x <= rect.right() + 1e-9:
                    candidates.append((ratio, QPointF(x, boundary_y)))
        forward = [value for value in candidates if value[0] <= 1.0 + 1e-9]
        if not forward:
            return OpticsGraphicsScene._clip_to_rect(target, rect)
        _, clipped = min(forward, key=lambda value: value[0])
        return Point2D(clipped.x(), -clipped.y())

    @staticmethod
    def _orient_remote_arrow(
        item: QGraphicsPolygonItem,
        clipped: Point2D,
        origin: Point2D,
        target: Point2D,
    ) -> None:
        item.setPos(_scene_point(clipped))
        direction_x = target.x_mm - origin.x_mm
        direction_y = -(target.z_mm - origin.z_mm)
        item.setRotation(math.degrees(math.atan2(direction_y, direction_x)))
        item.setVisible(True)

    def _queue_callout(
        self,
        name: str,
        text: str,
        anchor: Point2D,
        *,
        preferred: tuple[str, ...] = ("ne", "se", "nw", "sw"),
        leader: bool = True,
    ) -> None:
        label = self.labels[name]
        label.setText(text)
        self._callout_specs[name] = _CalloutSpec(text, anchor, preferred, leader)

    def _layout_transform(self) -> tuple[object, object, QRectF]:
        views = self.views()
        if views and views[0].viewport().width() > 40 and views[0].viewport().height() > 40:
            transform = views[0].viewportTransform()
            inverse, invertible = transform.inverted()
            if invertible:
                return (
                    transform,
                    inverse,
                    QRectF(views[0].viewport().rect()).adjusted(10.0, 10.0, -10.0, -10.0),
                )

        rect = self.sceneRect()
        device_rect = QRectF(10.0, 10.0, 940.0, 700.0)
        scale = min(
            device_rect.width() / max(rect.width(), 1.0),
            device_rect.height() / max(rect.height(), 1.0),
        )
        from PySide6.QtGui import QTransform

        transform = QTransform()
        transform.translate(device_rect.center().x(), device_rect.center().y())
        transform.scale(scale, scale)
        transform.translate(-rect.center().x(), -rect.center().y())
        inverse, _ = transform.inverted()
        return transform, inverse, device_rect

    @staticmethod
    def _line_intersects_rect(line: QLineF, rect: QRectF) -> bool:
        first = line.p1()
        second = line.p2()
        if rect.contains(first) or rect.contains(second):
            return True
        if (
            max(first.x(), second.x()) < rect.left()
            or min(first.x(), second.x()) > rect.right()
            or max(first.y(), second.y()) < rect.top()
            or min(first.y(), second.y()) > rect.bottom()
        ):
            return False
        edges = (
            QLineF(rect.topLeft(), rect.topRight()),
            QLineF(rect.topRight(), rect.bottomRight()),
            QLineF(rect.bottomRight(), rect.bottomLeft()),
            QLineF(rect.bottomLeft(), rect.topLeft()),
        )
        return any(
            line.intersects(edge)[0] is QLineF.IntersectionType.BoundedIntersection
            for edge in edges
        )

    @staticmethod
    def _candidate_rects(
        anchor: QPointF,
        width: float,
        height: float,
        preferred: tuple[str, ...],
    ) -> tuple[QRectF, ...]:
        directions = {
            "ne": (1.0, -1.0),
            "se": (1.0, 1.0),
            "nw": (-1.0, -1.0),
            "sw": (-1.0, 1.0),
            "e": (1.0, 0.0),
            "w": (-1.0, 0.0),
            "n": (0.0, -1.0),
            "s": (0.0, 1.0),
        }
        order = tuple(dict.fromkeys((*preferred, *directions)))
        candidates: list[QRectF] = []
        for ring in range(1, 9):
            gap = 10.0 + (ring - 1) * 14.0
            for direction in order:
                horizontal, vertical = directions[direction]
                if horizontal > 0:
                    x = anchor.x() + gap
                elif horizontal < 0:
                    x = anchor.x() - width - gap
                else:
                    x = anchor.x() - width / 2.0
                if vertical > 0:
                    y = anchor.y() + gap
                elif vertical < 0:
                    y = anchor.y() - height - gap
                else:
                    y = anchor.y() - height / 2.0
                candidates.append(QRectF(x, y, width, height))
        return tuple(candidates)

    def _geometry_obstacles(self, transform: object) -> tuple[QLineF, ...]:
        items = (
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
            self.wd_dimension,
            self.range_dimension,
            self.w_dimension,
            self.r_dimension,
        )
        result: list[QLineF] = []
        for item in items:
            if not item.isVisible() or item.line().length() <= 1e-12:
                continue
            line = item.line()
            result.append(QLineF(transform.map(line.p1()), transform.map(line.p2())))
        return tuple(result)

    def _callout_score(
        self,
        candidate: QRectF,
        *,
        anchor: QPointF,
        viewport_rect: QRectF,
        placed: list[QRectF],
        obstacles: tuple[QLineF, ...],
    ) -> float:
        outside = 0.0
        if not viewport_rect.contains(candidate):
            outside = (
                1_000_000.0
                + (
                    max(0.0, viewport_rect.left() - candidate.left())
                    + max(0.0, candidate.right() - viewport_rect.right())
                    + max(0.0, viewport_rect.top() - candidate.top())
                    + max(0.0, candidate.bottom() - viewport_rect.bottom())
                )
                * 10_000.0
            )
        collision = sum(
            10_000_000.0
            + candidate.intersected(other).width() * candidate.intersected(other).height()
            for other in placed
            if candidate.intersects(other)
        )
        line_crossings = sum(
            20_000.0
            for line in obstacles
            if self._line_intersects_rect(line, candidate.adjusted(-3, -3, 3, 3))
        )
        distance = math.hypot(
            candidate.center().x() - anchor.x(),
            candidate.center().y() - anchor.y(),
        )
        return outside + collision + line_crossings + distance

    def _select_callout_rect(
        self,
        candidates: tuple[QRectF, ...],
        *,
        anchor: QPointF,
        viewport_rect: QRectF,
        placed: list[QRectF],
        obstacles: tuple[QLineF, ...],
    ) -> QRectF:
        """Return the first clean preferred slot, scoring only fallback slots."""

        for candidate in candidates:
            collides = any(candidate.intersects(other) for other in placed)
            crosses = any(
                self._line_intersects_rect(line, candidate.adjusted(-3, -3, 3, 3))
                for line in obstacles
            )
            if viewport_rect.contains(candidate) and not collides and not crosses:
                return candidate

        fallback: tuple[float, QRectF] | None = None
        for candidate in candidates:
            score = self._callout_score(
                candidate,
                anchor=anchor,
                viewport_rect=viewport_rect,
                placed=placed,
                obstacles=obstacles,
            )
            if fallback is None or score < fallback[0]:
                fallback = (score, candidate)
        assert fallback is not None
        return fallback[1]

    def relayout_labels(self) -> None:
        """Place callouts in device coordinates after fit/zoom without moving geometry."""

        if self._snapshot is None:
            return
        transform, inverse, viewport_rect = self._layout_transform()
        obstacles = self._geometry_obstacles(transform)
        placed: list[QRectF] = []

        priority = (
            "legend",
            "distances",
            "wd",
            "range",
            "w",
            "r",
            "scheimpflug",
            "sensor",
            "lens",
            "axis",
            "proxy",
            "laser",
            "nominal",
            "near",
            "far",
        )
        for name in priority:
            label = self.labels[name]
            background = self.label_backgrounds[name]
            leader = self.label_leaders[name]
            spec = self._callout_specs.get(name)
            if spec is None or not label.isVisible():
                background.setVisible(False)
                leader.setVisible(False)
                continue
            anchor_scene = _scene_point(spec.anchor)
            anchor_device = transform.map(anchor_scene)
            text_rect = label.boundingRect()
            width = text_rect.width() + 14.0
            height = text_rect.height() + 8.0
            candidates = self._candidate_rects(
                anchor_device,
                width,
                height,
                spec.preferred_quadrants,
            )

            selected = self._select_callout_rect(
                candidates,
                anchor=anchor_device,
                viewport_rect=viewport_rect,
                placed=placed,
                obstacles=obstacles,
            )
            placed.append(selected.adjusted(-3.0, -3.0, 3.0, 3.0))
            label_device = QPointF(selected.left() + 7.0, selected.top() + 4.0)
            label_scene = inverse.map(label_device)
            label.setPos(label_scene)
            background.setRect(text_rect.adjusted(-7.0, -4.0, 7.0, 4.0))
            background.setPos(label_scene)
            background.setVisible(True)

            if not spec.leader or selected.contains(anchor_device):
                leader.setVisible(False)
                continue
            leader_end_device = QPointF(
                min(max(anchor_device.x(), selected.left()), selected.right()),
                min(max(anchor_device.y(), selected.top()), selected.bottom()),
            )
            leader.setLine(QLineF(anchor_scene, inverse.map(leader_end_device)))
            leader.setVisible(True)

    def visible_callout_rects(self) -> dict[str, QRectF]:
        """Return device-space callout bounds for diagnostics and UI tests."""

        transform, _, _ = self._layout_transform()
        result: dict[str, QRectF] = {}
        for name, background in self.label_backgrounds.items():
            if not background.isVisible():
                continue
            origin = transform.map(background.pos())
            rect = background.rect()
            result[name] = QRectF(
                origin.x() + rect.left(),
                origin.y() + rect.top(),
                rect.width(),
                rect.height(),
            )
        return result

    def _prepare_snapshot_callouts(
        self,
        snapshot: SceneSnapshot,
        scene_rect: QRectF,
        visible_laser_start: Point2D,
        visible_laser_end: Point2D,
        visible_targets: tuple[Point2D, Point2D, Point2D],
        visible_range_endpoints: tuple[Point2D, Point2D],
        *,
        targets_distinct: bool,
        range_is_remote: bool,
        intersection_is_remote: bool,
        dimension_x: float,
        range_x: float,
        bottom_z: float,
    ) -> None:
        """Create readable callout requests after all physical lines are in place."""

        label_colors = {
            "laser": "laser",
            "near": "target",
            "nominal": "target",
            "far": "target",
            "lens": "lens",
            "sensor": "sensor",
            "proxy": "proxy",
            "axis": "axis",
            "scheimpflug": "warning",
            "wd": "dimension",
            "range": "dimension",
            "w": "dimension",
            "r": "dimension",
            "distances": "text",
            "legend": "muted",
        }
        for name, color in label_colors.items():
            self.labels[name].setBrush(self.COLORS[color])

        laser_midpoint = Point2D(
            (visible_laser_start.x_mm + visible_laser_end.x_mm) / 2.0,
            (visible_laser_start.z_mm + visible_laser_end.z_mm) / 2.0,
        )
        self._queue_callout(
            "laser",
            "레이저 조사 직선",
            laser_midpoint,
            preferred=("nw", "sw", "ne", "se"),
        )
        if targets_distinct:
            self._queue_callout(
                "near",
                "근거리",
                visible_targets[0],
                preferred=("nw", "sw", "ne", "se"),
            )
            self._queue_callout(
                "far",
                "원거리",
                visible_targets[2],
                preferred=("sw", "nw", "se", "ne"),
            )
        self._queue_callout(
            "nominal",
            snapshot.target_nominal_label,
            visible_targets[1],
            preferred=("ne", "se", "nw", "sw"),
        )
        self._queue_callout(
            "lens",
            "렌즈 평면",
            snapshot.lens_center,
            preferred=("nw", "sw", "ne", "se"),
        )
        self._queue_callout(
            "sensor",
            "실제 이미지/센서 평면",
            snapshot.image_center,
            preferred=("ne", "se", "nw", "sw"),
        )
        optical_axis_midpoint = Point2D(
            (snapshot.optical_axis_endpoints[0].x_mm + snapshot.optical_axis_endpoints[1].x_mm)
            / 2.0,
            (snapshot.optical_axis_endpoints[0].z_mm + snapshot.optical_axis_endpoints[1].z_mm)
            / 2.0,
        )
        self._queue_callout(
            "axis",
            "수광 광축",
            optical_axis_midpoint,
            preferred=("se", "ne", "sw", "nw"),
        )
        if snapshot.proxy_sensor_endpoints is not None:
            proxy_midpoint = Point2D(
                (snapshot.proxy_sensor_endpoints[0].x_mm + snapshot.proxy_sensor_endpoints[1].x_mm)
                / 2.0,
                (snapshot.proxy_sensor_endpoints[0].z_mm + snapshot.proxy_sensor_endpoints[1].z_mm)
                / 2.0,
            )
            self._queue_callout(
                "proxy",
                "중심 대칭 패키지 근사",
                proxy_midpoint,
                preferred=("se", "sw", "ne", "nw"),
            )

        if snapshot.scheimpflug_point is not None:
            if intersection_is_remote:
                clipped = self._clip_from_origin(
                    snapshot.lens_center,
                    snapshot.scheimpflug_point,
                    scene_rect,
                )
                self.scheimpflug_marker.setVisible(False)
                self._orient_remote_arrow(
                    self.scheimpflug_remote_arrow,
                    clipped,
                    snapshot.lens_center,
                    snapshot.scheimpflug_point,
                )
                scheme_text = (
                    "Scheimpflug 교점 ↗ 화면 밖\n"
                    f"({snapshot.scheimpflug_point.x_mm:.2f}, "
                    f"{snapshot.scheimpflug_point.z_mm:.2f}) mm"
                )
                self._queue_callout(
                    "scheimpflug",
                    scheme_text,
                    clipped,
                    preferred=("sw", "nw", "se", "ne"),
                )
            else:
                self.scheimpflug_remote_arrow.setVisible(False)
                self._position(self.scheimpflug_marker, snapshot.scheimpflug_point)
                self._queue_callout(
                    "scheimpflug",
                    "Scheimpflug 교점",
                    snapshot.scheimpflug_point,
                    preferred=("ne", "se", "nw", "sw"),
                )

        self._queue_callout(
            "wd",
            f"WD d = {snapshot.working_distance_mm:.3f} mm",
            Point2D(
                dimension_x,
                (
                    snapshot.working_distance_endpoints[0].z_mm
                    + snapshot.working_distance_endpoints[1].z_mm
                )
                / 2.0,
            ),
            preferred=("w", "e", "nw", "sw"),
        )
        range_suffix = " · 화면 밖 →" if range_is_remote else ""
        self._queue_callout(
            "range",
            f"{snapshot.range_label} = {snapshot.measurement_range_mm:.3f} mm{range_suffix}",
            Point2D(
                range_x,
                (visible_range_endpoints[0].z_mm + visible_range_endpoints[1].z_mm) / 2.0,
            ),
            preferred=("w", "e", "sw", "nw"),
        )
        self._queue_callout(
            "w",
            f"W = {snapshot.w_mm:.3f} mm",
            Point2D(snapshot.w_mm / 2.0, bottom_z),
            preferred=("s", "n", "se", "sw"),
        )
        self._queue_callout(
            "r",
            f"R = {snapshot.r_mm:.3f} mm",
            Point2D(
                snapshot.lens_center.x_mm,
                snapshot.target_nominal.z_mm - snapshot.r_mm / 2.0,
            ),
            preferred=("e", "w", "ne", "se"),
        )
        self._queue_callout(
            "distances",
            (
                f"f = {snapshot.focal_length_mm:.3f} mm\n"
                f"lo = {snapshot.lo_mm:.3f} mm\n"
                f"fp = {snapshot.fp_mm:.3f} mm"
            ),
            snapshot.image_center,
            preferred=("se", "ne", "sw", "nw"),
        )
        self._queue_callout(
            "legend",
            (
                "범례  빨강: 레이저 · 노랑: 센서 · 보라: 결상광선\n"
                "청록 ↔: 치수 · 주황 점선: 패키지 근사"
            ),
            Point2D(scene_rect.right(), -scene_rect.top()),
            preferred=("sw", "w", "s"),
            leader=False,
        )

    def set_snapshot(self, snapshot: SceneSnapshot | None) -> None:
        """Update every scene item from one immutable calculation snapshot."""

        self._snapshot = snapshot
        self._callout_specs.clear()
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
        self.range_remote_arrow.setVisible(False)
        self.scheimpflug_remote_arrow.setVisible(False)
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
                self._clip_from_origin(
                    snapshot.range_endpoints[0],
                    snapshot.range_endpoints[1],
                    scene_rect,
                ),
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

        visible_laser_start = visible_point(snapshot.laser_endpoints[0])
        visible_laser_end = (
            self._clip_from_origin(
                snapshot.laser_endpoints[0],
                snapshot.laser_endpoints[1],
                scene_rect,
            )
            if not scene_rect.contains(_scene_point(snapshot.laser_endpoints[1]))
            else snapshot.laser_endpoints[1]
        )
        self._set_line(self.laser_line, visible_laser_start, visible_laser_end)

        target_half_width = max(8.0, scene_rect.width() * 0.06)
        visible_targets = (
            visible_point(snapshot.target_near),
            visible_point(snapshot.target_nominal),
            (
                self._clip_from_origin(
                    snapshot.target_nominal,
                    snapshot.target_far,
                    scene_rect,
                )
                if not scene_rect.contains(_scene_point(snapshot.target_far))
                else snapshot.target_far
            ),
        )
        for item, point in zip(
            (
                self.target_near_line,
                self.target_nominal_line,
                self.target_far_line,
            ),
            visible_targets,
            strict=True,
        ):
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
        arrow_size = max(2.0, min(7.0, characteristic * 0.018))
        self._set_dimension(
            "wd",
            self.wd_dimension,
            Point2D(dimension_x, snapshot.working_distance_endpoints[0].z_mm),
            Point2D(dimension_x, snapshot.working_distance_endpoints[1].z_mm),
            arrow_size,
        )
        range_x = dimension_x + max(4.0, scene_rect.width() * 0.04)
        self._set_dimension(
            "range",
            self.range_dimension,
            Point2D(range_x, visible_range_endpoints[0].z_mm),
            Point2D(range_x, visible_range_endpoints[1].z_mm),
            arrow_size,
        )
        bottom_z = envelope_bottom_z
        self._set_dimension(
            "w",
            self.w_dimension,
            Point2D(0.0, bottom_z),
            Point2D(snapshot.w_mm, bottom_z),
            arrow_size,
        )
        self._set_dimension(
            "r",
            self.r_dimension,
            Point2D(snapshot.lens_center.x_mm, snapshot.target_nominal.z_mm),
            Point2D(snapshot.lens_center.x_mm, snapshot.target_nominal.z_mm - snapshot.r_mm),
            arrow_size,
        )
        if range_is_remote:
            self._orient_remote_arrow(
                self.range_remote_arrow,
                visible_range_endpoints[1],
                snapshot.range_endpoints[0],
                snapshot.range_endpoints[1],
            )

        self._position(self.emitter_marker, snapshot.emitter)
        self._position(self.lens_marker, snapshot.lens_center)
        self._position(self.image_marker, snapshot.image_center)
        self._position_screen_plane(self.lens_plane_marker, snapshot.lens_endpoints)
        self._position_screen_plane(self.sensor_plane_marker, snapshot.sensor_endpoints)

        self.invalid_overlay.setRect(scene_rect)
        self.invalid_overlay.setVisible(not snapshot.valid)
        invalid_text = "\n".join(snapshot.warnings) or "유효하지 않은 광학 구조"
        if not snapshot.warnings:
            invalid_text = "유효하지 않은 광학 구조"
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
            self.lens_plane_marker,
            self.sensor_plane_marker,
            self.proxy_sensor_line,
            self.near_ray_before,
            self.near_ray_after,
            self.far_ray_before,
            self.far_ray_after,
        ):
            original = item.pen()
            if invalid_style:
                invalid_pen = QPen(
                    self.COLORS["invalid"],
                    original.widthF(),
                    Qt.PenStyle.DashLine,
                )
                invalid_pen.setCosmetic(True)
                invalid_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                item.setPen(invalid_pen)
            else:
                item.setPen(QPen(self._normal_pens[item]))
        self._prepare_snapshot_callouts(
            snapshot,
            scene_rect,
            visible_laser_start,
            visible_laser_end,
            visible_targets,
            visible_range_endpoints,
            targets_distinct=targets_distinct,
            range_is_remote=range_is_remote,
            intersection_is_remote=intersection_is_remote,
            dimension_x=dimension_x,
            range_x=range_x,
            bottom_z=bottom_z,
        )
        self.relayout_labels()

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
        self.setMinimumSize(400, 360)

    def fit_scene(self) -> None:
        scene = self.scene()
        if scene is not None and not scene.sceneRect().isEmpty():
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            if isinstance(scene, OpticsGraphicsScene):
                scene.relayout_labels()

    def fit_optical_head(self) -> None:
        scene = self.scene()
        if isinstance(scene, OpticsGraphicsScene):
            self.fitInView(
                scene.optical_head_rect(),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            scene.relayout_labels()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        self.scale(factor, factor)
        scene = self.scene()
        if isinstance(scene, OpticsGraphicsScene):
            scene.relayout_labels()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        scene = self.scene()
        if isinstance(scene, OpticsGraphicsScene):
            scene.relayout_labels()

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802 - Qt override
        super().scrollContentsBy(dx, dy)
        scene = self.scene()
        if isinstance(scene, OpticsGraphicsScene):
            scene.relayout_labels()
