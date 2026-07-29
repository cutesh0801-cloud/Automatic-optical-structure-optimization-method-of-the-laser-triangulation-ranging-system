"""Small exact helpers used by the 3D full-focus visualization."""

from __future__ import annotations

import math

from .solvers import OpticalInputError


def full_focus_angles(
    magnification: float, alpha_deg: float, beta_deg: float
) -> tuple[float, float]:
    """Return exact sensor tilt/pan angles ``gamma`` and ``delta`` in degrees.

    Implements ``tan(gamma)=m tan(alpha)`` and
    ``tan(delta)=m cos(gamma)/cos(alpha) tan(beta)``.
    """

    if not all(math.isfinite(value) for value in (magnification, alpha_deg, beta_deg)):
        raise OpticalInputError("Full-focus inputs must be finite.")
    if magnification <= 0:
        raise OpticalInputError("magnification must be positive.")
    alpha = math.radians(alpha_deg)
    beta = math.radians(beta_deg)
    if abs(math.cos(alpha)) <= 1e-12:
        raise OpticalInputError("alpha is singular at 90 degrees.")
    gamma = math.atan(magnification * math.tan(alpha))
    delta = math.atan(magnification * math.cos(gamma) / math.cos(alpha) * math.tan(beta))
    return math.degrees(gamma), math.degrees(delta)
