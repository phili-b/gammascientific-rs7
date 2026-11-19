"""Read everything a front end shows (GUI window, web page) from the unit and analyze it. No Qt here."""

from __future__ import annotations

from typing import Any

from .colorimetry import analyze, compare
from .device import RS7, RS7Error, Units
from .illuminants import target_spectrum
from .match import ANALYSIS_RANGE, scale_to_level


def read_state(
    r: RS7,
    start: int,
    end: int,
    channels: list[int],
    plot_all: bool,
    sliders: bool,
    target: tuple[str, int, int] | None = None,
) -> dict:
    """Everything the window shows, read from the unit and analyzed (worker thread). Leaves the units on INTERNAL.

    ``target`` = (name, start, end): also build that target at the output's level and compare.
    """
    st: dict[str, Any] = {}
    if sliders:
        st["powers"] = r.channel_powers()
    r.set_units(Units.RADIOMETRIC)
    st["rad"] = r.output()
    r.set_units(Units.PHOTOMETRIC)
    st["lum"] = r.output()
    r.set_units(Units.INTERNAL)
    st["power"] = r.output()
    for key, read in (("xy", r.chromaticity), ("cct", r.cct)):
        try:
            st[key] = read()
        except RS7Error:  # no spectrum (all channels off)
            st[key] = None
    lo, hi = min(start, ANALYSIS_RANGE[0]), max(end, ANALYSIS_RANGE[1])
    full = r.spectrum(0, lo, hi)  # one read serves the plot and the analysis
    st["spec"] = [(nm, v) for nm, v in full if start <= nm <= end]
    analysis_spec = [(nm, v) for nm, v in full if ANALYSIS_RANGE[0] <= nm <= ANALYSIS_RANGE[1]]
    report = st["report"] = analyze(analysis_spec)
    st["chan_specs"] = {c: r.spectrum(c, start, end) for c in channels} if plot_all else {}
    r.set_wavelength_range(start, end)
    if target:
        name, t_start, t_end = target
        try:
            relative = target_spectrum(name, t_start, t_end)
            level = report.photometric if report.photometric > 0 else 1.0
            scale = scale_to_level(relative, t_start, level, Units.PHOTOMETRIC)
            t_spec = [(t_start + i, v * scale) for i, v in enumerate(relative)]
            t_report = analyze(t_spec)
            st["target"] = (t_spec, t_report, compare(report, t_report, analysis_spec, t_spec))
        except ValueError as e:
            st["target_error"] = str(e)
    return st
