"""Robust sub-pixel laser stripe extraction."""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import NDArray

from .models import StripeResult


def extract_stripe(
    image: NDArray[np.generic],
    *,
    dark_frame: NDArray[np.generic] | None = None,
    orientation: str = "vertical",
    threshold_sigma: float = 5.0,
    minimum_contrast: float = 8.0,
    minimum_confidence: float = 0.2,
    continuity_scale_px: float = 6.0,
    maximum_jump_px: float = 20.0,
) -> StripeResult:
    """Extract a laser line using robust thresholding and a half-height centroid.

    ``vertical`` means that the laser coordinate is estimated along X for every
    image row.  ``horizontal`` estimates Y for every column.
    """

    raw = np.asarray(image)
    if raw.ndim != 2:
        raise ValueError("stripe extraction requires a 2-D monochrome image")
    if not np.issubdtype(raw.dtype, np.number) or not np.all(np.isfinite(raw)):
        raise ValueError("image must contain finite numeric pixels")
    if orientation not in {"vertical", "horizontal"}:
        raise ValueError("orientation must be 'vertical' or 'horizontal'")
    if threshold_sigma <= 0 or minimum_contrast <= 0:
        raise ValueError("threshold parameters must be positive")
    if not 0 <= minimum_confidence <= 1:
        raise ValueError("minimum_confidence must be between zero and one")
    if continuity_scale_px <= 0 or maximum_jump_px <= 0:
        raise ValueError("continuity parameters must be positive")

    working = raw.astype(np.float64)
    if dark_frame is not None:
        dark = np.asarray(dark_frame, dtype=np.float64)
        if dark.shape != working.shape or not np.all(np.isfinite(dark)):
            raise ValueError("dark_frame must be finite and match image shape")
        working = np.maximum(working - dark, 0.0)
    profiles = working if orientation == "vertical" else working.T
    raw_profiles = raw if orientation == "vertical" else raw.T
    count = profiles.shape[0]
    coordinates = np.full(count, np.nan, dtype=np.float64)
    confidence = np.zeros(count, dtype=np.float64)
    peak_intensity = np.zeros(count, dtype=np.float64)
    signal_to_noise = np.zeros(count, dtype=np.float64)
    previous_coordinate: float | None = None
    saturation_level = _saturation_level(raw)

    for profile_index, (profile, raw_profile) in enumerate(
        zip(profiles, raw_profiles, strict=True)
    ):
        baseline = float(np.median(profile))
        mad = float(np.median(np.abs(profile - baseline)))
        noise_sigma = max(1.4826 * mad, 0.25)
        threshold = baseline + max(minimum_contrast, threshold_sigma * noise_sigma)
        segments = _segments_above(profile, threshold)
        if not segments:
            continue

        candidates: list[tuple[float, int, int, int, float]] = []
        for start, stop in segments:
            values = np.maximum(profile[start:stop] - baseline, 0.0)
            signal = float(np.sum(values))
            if signal <= 0:
                continue
            peak = start + int(np.argmax(profile[start:stop]))
            rough_center = float(np.sum(np.arange(start, stop) * values) / signal)
            continuity_distance = (
                0.0 if previous_coordinate is None else abs(rough_center - previous_coordinate)
            )
            continuity_weight = math.exp(-continuity_distance / continuity_scale_px)
            score = signal * (0.3 + 0.7 * continuity_weight)
            candidates.append((score, start, stop, peak, signal))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, start, stop, peak, strongest_signal = candidates[0]

        local_peak = float(profile[peak])
        amplitude = local_peak - baseline
        if amplitude < minimum_contrast:
            continue
        half_height = baseline + 0.5 * amplitude
        half_start = peak
        while half_start > start and profile[half_start - 1] >= half_height:
            half_start -= 1
        half_stop = peak + 1
        while half_stop < stop and profile[half_stop] >= half_height:
            half_stop += 1
        coordinate = _piecewise_half_height_centroid(
            profile,
            baseline=baseline,
            half_height=half_height,
            first_index=half_start,
            stop_index=half_stop,
        )
        if coordinate is None:
            continue

        snr = amplitude / noise_sigma
        snr_factor = 1.0 - math.exp(-snr / 6.0)
        ambiguity_factor = 1.0
        if len(candidates) > 1:
            ambiguity_factor = max(
                0.15,
                1.0 - min(candidates[1][4] / max(strongest_signal, 1e-12), 1.0),
            )
        if previous_coordinate is None:
            continuity_factor = 1.0
        else:
            jump = abs(coordinate - previous_coordinate)
            continuity_factor = math.exp(-jump / continuity_scale_px)
            if jump > maximum_jump_px:
                continuity_factor *= 0.1
        saturated = float(raw_profile[peak]) >= saturation_level
        saturation_factor = 0.65 if saturated else 1.0
        row_confidence = float(
            np.clip(
                snr_factor * ambiguity_factor * continuity_factor * saturation_factor,
                0.0,
                1.0,
            )
        )

        coordinates[profile_index] = coordinate
        confidence[profile_index] = row_confidence
        peak_intensity[profile_index] = local_peak
        signal_to_noise[profile_index] = snr
        if row_confidence >= minimum_confidence:
            previous_coordinate = coordinate

    valid = np.isfinite(coordinates) & (confidence >= minimum_confidence)
    return StripeResult(
        coordinates_px=coordinates,
        profile_indices_px=np.arange(count, dtype=np.float64),
        confidence=confidence,
        valid_mask=valid,
        orientation=orientation,
        peak_intensity=peak_intensity,
        signal_to_noise=signal_to_noise,
    )


def _segments_above(
    profile: NDArray[np.float64],
    threshold: float,
) -> list[tuple[int, int]]:
    indices = np.flatnonzero(profile >= threshold)
    if len(indices) == 0:
        return []
    breaks = np.flatnonzero(np.diff(indices) > 1)
    starts = np.concatenate(([indices[0]], indices[breaks + 1]))
    stops = np.concatenate((indices[breaks] + 1, [indices[-1] + 1]))
    return [(int(start), int(stop)) for start, stop in zip(starts, stops, strict=True)]


def _piecewise_half_height_centroid(
    profile: NDArray[np.float64],
    *,
    baseline: float,
    half_height: float,
    first_index: int,
    stop_index: int,
) -> float | None:
    """Centroid a linearly interpolated half-height region.

    Fractional crossing points remove the approximately quarter-pixel bias caused
    by centroiding only integer samples inside the FWHM.
    """

    last_index = stop_index - 1
    if first_index > 0 and profile[first_index - 1] < half_height:
        below = float(profile[first_index - 1])
        above = float(profile[first_index])
        fraction = (half_height - below) / max(above - below, np.finfo(float).eps)
        left = first_index - 1 + fraction
    else:
        left = float(first_index)
    if last_index + 1 < len(profile) and profile[last_index + 1] < half_height:
        above = float(profile[last_index])
        below = float(profile[last_index + 1])
        fraction = (above - half_height) / max(above - below, np.finfo(float).eps)
        right = last_index + fraction
    else:
        right = float(last_index)
    if right <= left:
        return float(first_index)

    integer_positions = np.arange(first_index, stop_index, dtype=np.float64)
    positions = np.concatenate(([left], integer_positions, [right]))
    values = np.concatenate(
        (
            [half_height - baseline],
            np.maximum(profile[first_index:stop_index] - baseline, 0.0),
            [half_height - baseline],
        )
    )
    # Remove duplicate boundary nodes when a crossing lands exactly on a sample.
    distinct = np.concatenate(([True], np.diff(positions) > np.finfo(float).eps))
    positions = positions[distinct]
    values = values[distinct]
    area = 0.0
    first_moment = 0.0
    for x0, x1, y0, y1 in zip(
        positions[:-1],
        positions[1:],
        values[:-1],
        values[1:],
        strict=True,
    ):
        width = float(x1 - x0)
        delta_y = float(y1 - y0)
        interval_area = width * float(y0 + y1) / 2.0
        interval_moment = width * (
            float(x0 * y0) + float(x0 * delta_y + width * y0) / 2.0 + width * delta_y / 3.0
        )
        area += interval_area
        first_moment += interval_moment
    if area <= np.finfo(float).eps:
        return None
    return first_moment / area


def _saturation_level(image: NDArray[np.generic]) -> float:
    if np.issubdtype(image.dtype, np.integer):
        return float(np.iinfo(image.dtype).max - 1)
    maximum = float(np.max(image))
    return 0.999 if maximum <= 1.0 else math.inf
