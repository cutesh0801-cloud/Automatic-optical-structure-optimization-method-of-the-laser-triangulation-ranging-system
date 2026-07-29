"""Measurement result models suitable for UI overlays and data export."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class StripeResult:
    """One sub-pixel laser coordinate and confidence per sampled image profile."""

    coordinates_px: NDArray[np.float64]
    profile_indices_px: NDArray[np.float64]
    confidence: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    orientation: str
    peak_intensity: NDArray[np.float64]
    signal_to_noise: NDArray[np.float64]

    def __post_init__(self) -> None:
        length = len(self.coordinates_px)
        arrays = (
            self.profile_indices_px,
            self.confidence,
            self.valid_mask,
            self.peak_intensity,
            self.signal_to_noise,
        )
        if any(np.asarray(value).shape != (length,) for value in arrays):
            raise ValueError("all stripe arrays must be one-dimensional and equally sized")
        if self.orientation not in {"vertical", "horizontal"}:
            raise ValueError("orientation must be 'vertical' or 'horizontal'")

    @property
    def pixels_xy(self) -> NDArray[np.float64]:
        if self.orientation == "vertical":
            return np.column_stack((self.coordinates_px, self.profile_indices_px))
        return np.column_stack((self.profile_indices_px, self.coordinates_px))

    @property
    def valid_pixels_xy(self) -> NDArray[np.float64]:
        return self.pixels_xy[self.valid_mask]


@dataclass(frozen=True, slots=True)
class CrossSection:
    """Calibrated points produced from one laser-stripe frame."""

    pixels_xy: NDArray[np.float64]
    points_mm: NDArray[np.float64]
    confidence: NDArray[np.float64]
    valid_mask: NDArray[np.bool_]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        count = len(self.pixels_xy)
        if np.asarray(self.pixels_xy).shape != (count, 2):
            raise ValueError("pixels_xy must have shape (N, 2)")
        if np.asarray(self.points_mm).shape != (count, 3):
            raise ValueError("points_mm must have shape (N, 3)")
        if np.asarray(self.confidence).shape != (count,):
            raise ValueError("confidence must have shape (N,)")
        if np.asarray(self.valid_mask).shape != (count,):
            raise ValueError("valid_mask must have shape (N,)")

    @property
    def valid_points_mm(self) -> NDArray[np.float64]:
        return self.points_mm[self.valid_mask]

    def csv_rows(self) -> list[dict[str, float | bool]]:
        return [
            {
                "pixel_x_px": float(pixel[0]),
                "pixel_y_px": float(pixel[1]),
                "x_mm": float(point[0]),
                "y_mm": float(point[1]),
                "z_mm": float(point[2]),
                "confidence": float(confidence),
                "valid": bool(valid),
            }
            for pixel, point, confidence, valid in zip(
                self.pixels_xy,
                self.points_mm,
                self.confidence,
                self.valid_mask,
                strict=True,
            )
        ]

    def write_csv(self, path: str | Path) -> None:
        destination = Path(path)
        rows = self.csv_rows()
        fieldnames = [
            "pixel_x_px",
            "pixel_y_px",
            "x_mm",
            "y_mm",
            "z_mm",
            "confidence",
            "valid",
        ]
        with destination.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def write_metadata(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.metadata, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
