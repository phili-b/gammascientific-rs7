"""Make the RS-7 reproduce a target spectrum (e.g. D65) at an absolute level, and report how well it did."""

from __future__ import annotations

from dataclasses import dataclass

from .colorimetry import ColorReport, Comparison, Spectrum, analyze, compare, photometric_per_unit
from .device import RS7, RS7Error, Units
from .illuminants import target_spectrum

ANALYSIS_RANGE = (360, 830)  # nm, range of the CIE observer functions


@dataclass
class MatchResult:
    target_name: str
    target: ColorReport
    output: ColorReport
    comparison: Comparison
    unit_rms_error: float  #: the RS-7's own spectral mismatch (RPE), %; NaN for the local fit
    target_spectrum: Spectrum  #: absolute, in the unit's radiometric units
    output_spectrum: Spectrum


def scale_to_level(relative: list[float], start: int, level: float, units: Units) -> float:
    """Factor that turns a relative spectrum into uW/cm2/nm (or /sr) with the given total ``level``."""
    if units == Units.PHOTOMETRIC:
        per_unit = photometric_per_unit(relative, start)
    elif units == Units.RADIOMETRIC:
        per_unit = sum(relative)  # 1 nm steps
    else:
        raise ValueError("give the level in photometric or radiometric units")
    if per_unit <= 0:
        raise ValueError("the target has no power in the chosen range")
    return level / per_unit


def match(
    rs7: RS7,
    target: str,
    level: float | None = None,
    units: Units = Units.PHOTOMETRIC,
    at_max: bool = False,
    start: int = 380,
    end: int = 780,
    include_white: bool = False,
    correct_chromaticity: bool = True,
    method: str = "local",
) -> MatchResult:
    """Fit the RS-7 to ``target`` (see :mod:`rs7.illuminants`) and report the result.

    - ``level``: total output to reach, in ``units`` (lux/nits or uW/cm2). ``None`` keeps the present output
      level, or uses the maximum if the unit is off.
    - ``at_max``: as bright as the soft limit allows (``level`` is ignored).
    - ``correct_chromaticity``: after the spectral fit, adjust the spectrum so the color matches the target
      exactly (slightly worse spectral match, perfect color).
    - ``method``: ``"local"`` solves the channel powers on the PC (:mod:`rs7.optimize`; the first time it
      measures every channel, about 10 s); ``"firmware"`` uses the RS-7's own fit (``FTS``).
      ``include_white`` only applies to the firmware fit (the local fit always uses every channel).
    """
    if method not in ("local", "firmware"):
        raise ValueError("method is 'local' or 'firmware'")
    relative = target_spectrum(target, start, end)
    if level is None and not at_max:
        level = rs7.output(units)
        at_max = level <= 0
    scale = scale_to_level(relative, start, level or 1.0, units) if not at_max else 1.0
    if method == "firmware":
        rs7.set_wavelength_range(start, end)
        rs7.set_target_spectrum([v * scale for v in relative])
        rs7.fit(include_white=include_white, at_max=at_max)
        if correct_chromaticity:
            _color_correct(rs7)
    else:
        from .optimize import fit as local_fit

        if at_max:  # solve at a moderate level; fit() then scales up to the soft limit
            scale = scale_to_level(relative, start, 100.0, Units.PHOTOMETRIC)
        local_fit(rs7, [v * scale for v in relative], start, at_max=at_max)
        # Level first, color last: OUTC would put the color back to what the channels gave before CCS.
        if level and not at_max:
            try:
                rs7.set_output(level, units)
            except RS7Error as e:  # a channel at its limit: keep the level the fit reached (it includes Y)
                if e.code != "06":
                    raise
        if correct_chromaticity:
            xy = analyze([(start + i, v) for i, v in enumerate(relative)], quality=False).xy
            if xy:
                _color_correct(rs7, (round(xy[0], 4), round(xy[1], 4)))
    if method == "firmware" and level and not at_max:
        rs7.set_output(level, units, keep_chromaticity=correct_chromaticity)
    rms = rs7.rms_error() if method == "firmware" else float("nan")

    output_spectrum = _read_output(rs7)
    output = analyze(output_spectrum)
    # Show the target at the level that was actually reached, so spectra and levels are comparable.
    target_abs = [v * scale_to_level(relative, start, output.photometric, Units.PHOTOMETRIC) for v in relative]
    target_spec = [(start + i, v) for i, v in enumerate(target_abs)]
    target_report = analyze(target_spec)
    return MatchResult(
        target_name=target,
        target=target_report,
        output=output,
        comparison=compare(output, target_report, output_spectrum, target_spec),
        unit_rms_error=rms,
        target_spectrum=target_spec,
        output_spectrum=output_spectrum,
    )


def _color_correct(rs7: RS7, xy: tuple[float, float] | None = None) -> None:
    """CCS. At full output it needs headroom: step the output down (to 97, 90, then 80 %) until it fits.

    If it still cannot, the color stays as the fit left it (the report shows the remaining error).
    """
    start_level = None
    for factor in (None, 0.97, 0.90, 0.80):
        try:
            if factor:
                start_level = start_level or rs7.output(Units.INTERNAL)
                rs7.set_output(start_level * factor, Units.INTERNAL)
            rs7.color_correct(xy)
            return
        except RS7Error as e:
            if e.code != "10":  # channel power soft limit
                raise


def measure(rs7: RS7) -> ColorReport:
    """Color report of the present output. Changes nothing on the unit."""
    return analyze(_read_output(rs7))


def measure_against(rs7: RS7, target: str, start: int = 380, end: int = 780) -> MatchResult:
    """Compare the present output with ``target``, scaled to the output's level. Changes nothing on the unit.

    ``unit_rms_error`` is NaN: no target is loaded into the RS-7.
    """
    output_spectrum = _read_output(rs7)
    output = analyze(output_spectrum)
    relative = target_spectrum(target, start, end)
    scale = scale_to_level(relative, start, output.photometric, Units.PHOTOMETRIC) if output.photometric > 0 else 1
    target_spec = [(start + i, v * scale) for i, v in enumerate(relative)]
    target_report = analyze(target_spec)
    return MatchResult(
        target_name=target,
        target=target_report,
        output=output,
        comparison=compare(output, target_report, output_spectrum, target_spec),
        unit_rms_error=float("nan"),
        target_spectrum=target_spec,
        output_spectrum=output_spectrum,
    )


def _read_output(rs7: RS7) -> list[tuple[int, float]]:
    """Output spectrum over the analysis range; the unit's wavelength range is put back afterwards."""
    previous_range = rs7.wavelength_range()
    try:
        return rs7.spectrum(0, *ANALYSIS_RANGE)
    finally:
        rs7.set_wavelength_range(*previous_range)
