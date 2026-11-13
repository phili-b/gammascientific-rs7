"""Characterize the unit itself: how it dims, and how stable it is over time."""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

from .colorimetry import analyze
from .device import RS7, RS7Error, Units
from .spectrum import centroid, fwhm, photon_flux

DEFAULT_LEVELS: list[float] = [1, 2, 5, 10, 20, 50, 100]


def dimming(rs7: RS7, levels: list[float] | None = None, channel: int | None = None) -> Iterator[dict[str, Any]]:
    """Step the output through ``levels`` (%, internal units) and yield one row per level.

    - ``channel=None``: scales the present spectrum (``OUT``); rows hold the measured output (``OUTA``),
      luminance, x, y, CCT and centroid, which show the color shift with dimming.
    - ``channel=N``: only that channel (others off); rows hold its radiant power, photon flux, centroid,
      peak and FWHM, which show the LED's wavelength shift with drive current.

    The unit's channel powers are restored afterwards.
    """
    steps = levels or DEFAULT_LEVELS
    with rs7.using_units(Units.INTERNAL):
        before = rs7.channel_powers()
        try:
            if channel is not None:
                rs7.all_off()
            for level in steps:
                row: dict[str, Any] = {"level": level}
                if channel is not None:
                    rs7.set_channel_power(channel, level)
                    s = rs7.spectrum(channel, 360, 1100)
                    peak = max(s, key=lambda p: p[1])
                    row |= {
                        "radiometric": sum(v for _, v in s),
                        "photon_flux": photon_flux(s),
                        "centroid_nm": centroid(s),
                        "peak_nm": peak[0] if peak[1] > 0 else None,
                        "fwhm_nm": fwhm(s),
                    }
                else:
                    rs7.set_output(level, Units.INTERNAL)
                    a = analyze(rs7.spectrum(0, 360, 830), quality=False)
                    row |= {
                        "actual": rs7.actual_output(),
                        "photometric": a.photometric,
                        "x": a.xy[0] if a.xy else None,
                        "y": a.xy[1] if a.xy else None,
                        "cct": a.cct,
                        "centroid_nm": a.centroid_nm,
                    }
                yield row
        finally:
            rs7.all_off()
            if before:
                rs7.set_channel_powers(before)


def monitor(
    rs7: RS7, interval: float = 10.0, duration: float = 600.0, units: Units = Units.PHOTOMETRIC
) -> Iterator[dict[str, Any]]:
    """Log the unit every ``interval`` s for ``duration`` s (0 = until stopped); changes nothing.

    Rows: time, set output (``OUT``), measured output (``OUTA``, monitor photodiode), x, y, CCT, and the
    TEC temperatures. Useful for warm-up and drift.
    """
    t0 = time.monotonic()
    while True:
        with rs7.using_units(units):
            nominal, actual = rs7.output(), rs7.actual_output()
        try:
            (x, y), cct = rs7.chromaticity(), rs7.cct()
        except RS7Error:
            x = y = cct = None
        led, mon = rs7.temperatures()
        elapsed = time.monotonic() - t0
        yield {
            "time_s": round(elapsed, 2),
            "output": nominal,
            "actual": actual,
            "x": x,
            "y": y,
            "cct": cct,
            "led_temp_c": led,
            "monitor_temp_c": mon,
        }
        if duration and elapsed + interval > duration:
            return
        time.sleep(max(0.0, t0 + elapsed + interval - time.monotonic()))
