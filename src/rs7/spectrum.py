"""Helpers for building target spectra and colors, no hardware needed."""

from __future__ import annotations

import math

# CIE 1931 spectral locus (nm -> x, y), enough points to draw the chart outline.
SPECTRAL_LOCUS = [
    (380, 0.1741, 0.0050),
    (460, 0.1440, 0.0297),
    (470, 0.1241, 0.0578),
    (480, 0.0913, 0.1327),
    (490, 0.0454, 0.2950),
    (500, 0.0082, 0.5384),
    (510, 0.0139, 0.7502),
    (520, 0.0743, 0.8338),
    (530, 0.1547, 0.8059),
    (540, 0.2296, 0.7543),
    (550, 0.3016, 0.6923),
    (560, 0.3731, 0.6245),
    (570, 0.4441, 0.5547),
    (580, 0.5125, 0.4866),
    (590, 0.5752, 0.4242),
    (600, 0.6270, 0.3725),
    (610, 0.6658, 0.3340),
    (620, 0.6915, 0.3083),
    (650, 0.7260, 0.2740),
    (700, 0.7347, 0.2653),
    (780, 0.7347, 0.2653),
]


def blackbody(cct: float, start: int, end: int) -> list[float]:
    """Planck spectrum at ``cct`` kelvin, 1 nm steps from ``start`` to ``end``, peak normalized to 1."""
    c2 = 1.4388e7  # nm * K

    def planck(nm):
        return nm**-5 / math.expm1(c2 / (nm * cct))

    values = [planck(nm) for nm in range(start, end + 1)]
    peak = max(values)
    return [v / peak for v in values]


def load_csv(path: str) -> list[tuple[float, float]]:
    """Read ``wavelength, amplitude`` lines (any step size); lines that are not numbers are skipped."""
    points = []
    with open(path) as f:
        for line in f:
            parts = line.replace(";", ",").split(",")
            try:
                points.append((float(parts[0]), float(parts[1])))
            except (ValueError, IndexError):
                continue
    return sorted(points)


def resample(points: list[tuple[float, float]], start: int, end: int) -> list[float]:
    """Linearly interpolate ``(nm, value)`` points to 1 nm steps; 0 outside the data."""
    out = []
    i = 0
    for nm in range(start, end + 1):
        while i + 1 < len(points) and points[i + 1][0] < nm:
            i += 1
        if not points or nm < points[0][0] or nm > points[-1][0]:
            out.append(0.0)
        elif i + 1 >= len(points):
            out.append(points[-1][1])
        else:
            (x0, y0), (x1, y1) = points[i], points[i + 1]
            out.append(y0 if x1 == x0 else y0 + (y1 - y0) * (nm - x0) / (x1 - x0))
    return out


def cct_to_xy(cct: float) -> tuple[float, float]:
    """CIE 1931 x, y of the Planckian locus at ``cct`` kelvin (1667-25000 K, Kim et al. approximation)."""
    t = min(max(cct, 1667.0), 25000.0)
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    return x, y


def wavelength_to_rgb(nm: float) -> tuple[int, int, int]:
    """Approximate display color of a wavelength; infrared shows as deep red, ultraviolet as violet."""
    if nm < 380:
        r, g, b = 0.45, 0.0, 0.6
    elif nm < 440:
        r, g, b = (440 - nm) / 60, 0.0, 1.0
    elif nm < 490:
        r, g, b = 0.0, (nm - 440) / 50, 1.0
    elif nm < 510:
        r, g, b = 0.0, 1.0, (510 - nm) / 20
    elif nm < 580:
        r, g, b = (nm - 510) / 70, 1.0, 0.0
    elif nm < 645:
        r, g, b = 1.0, (645 - nm) / 65, 0.0
    elif nm <= 700:
        r, g, b = 1.0, 0.0, 0.0
    else:
        r, g, b = max(0.35, 1 - (nm - 700) / 400), 0.0, 0.0
    return int(r * 255), int(g * 255), int(b * 255)
