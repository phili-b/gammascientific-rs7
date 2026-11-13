"""Colorimetry and color quality of a measured or target spectrum (computed locally with colour-science).

Spectra are ``[(nm, value), ...]`` in the RS-7's radiometric units: uW/cm2/nm for an irradiant source,
uW/cm2/sr/nm for a radiant one. Photometric values then come out in lux or cd/m2 (nits) respectively.
"""

from __future__ import annotations

import math
import warnings
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from ._colour import colour

K_M = 683.002  #: lm/W, maximum luminous efficacy
UW_PER_CM2_TO_W_PER_M2 = 1e-2

Spectrum = Sequence[tuple[float, float]]  # (nm, value) at 1 nm steps


@dataclass
class ColorReport:
    """Colorimetry of one spectrum. Values that cannot be computed (e.g. no light) are ``None``."""

    radiometric: float  #: integrated power, uW/cm2 (or uW/cm2/sr)
    photometric: float  #: lux (or cd/m2)
    XYZ: tuple[float, float, float]  #: absolute tristimulus, same scale as ``photometric``
    xy: tuple[float, float] | None  #: CIE 1931 chromaticity
    uv_prime: tuple[float, float] | None  #: CIE 1976 u', v'
    cct: float | None  #: correlated color temperature, K (Ohno 2013)
    duv: float | None  #: distance from the Planckian locus in CIE 1960 uv (positive = above / greener)
    cri_ra: float | None  #: CIE 13.3 general color rendering index
    cri_r: dict[int, float] = field(default_factory=dict)  #: special indices R1-R14
    tm30_rf: float | None = None  #: ANSI/IES TM-30-18 fidelity index
    tm30_rg: float | None = None  #: ANSI/IES TM-30-18 gamut index
    peak_nm: float | None = None
    centroid_nm: float | None = None


@dataclass
class Comparison:
    """How well an output spectrum matches a target."""

    delta_uv_prime: float | None  #: chromaticity difference, CIE 1976 u'v' (0.001 is about a just noticeable step)
    delta_cct: float | None  #: K
    delta_duv: float | None
    level_ratio: float | None  #: output / target photometric level
    spectral_rms: float | None  #: % RMS of the difference of the area-normalized spectra, relative to their mean


def _to_sd(spectrum: Spectrum, start: int = 360, end: int = 830):
    """colour SpectralDistribution at 1 nm from start to end, zero outside the data."""
    c = colour()
    data = dict.fromkeys(range(start, end + 1), 0.0)
    for nm, v in spectrum:
        if start <= nm <= end and float(nm).is_integer():
            data[int(nm)] = max(float(v), 0.0)
    return c.SpectralDistribution(data)


def _cmfs(observer: int):
    c = colour()
    name = "CIE 1931 2 Degree Standard Observer" if observer == 2 else "CIE 1964 10 Degree Standard Observer"
    return c.MSDS_CMFS[name].copy().align(c.SpectralShape(360, 830, 1))


def analyze(spectrum: Spectrum, observer: int = 2, quality: bool = True) -> ColorReport:
    """Colorimetry of ``spectrum`` (1 nm steps). ``quality=False`` skips CRI and TM-30 (faster)."""
    c = colour()
    radiometric = sum(v for _, v in spectrum)  # 1 nm steps
    sd = _to_sd(spectrum)
    values = sd.values
    cmfs = _cmfs(observer)
    ybar_2 = _cmfs(2).values[:, 1]
    k = K_M * UW_PER_CM2_TO_W_PER_M2
    photometric = float(k * (values * ybar_2).sum())  # luminous quantities always use V(lambda) = ybar 2 deg
    X, Y, Z = (float(k * (values * cmfs.values[:, i]).sum()) for i in range(3))
    report = ColorReport(radiometric, photometric, (X, Y, Z), None, None, None, None, None)
    total = X + Y + Z
    if total <= 0 or photometric <= 0:
        return report
    report.xy = (X / total, Y / total)
    d = X + 15 * Y + 3 * Z
    report.uv_prime = (4 * X / d, 9 * Y / d)
    positive = [(nm, v) for nm, v in spectrum if v > 0]
    report.peak_nm = max(positive, key=lambda p: p[1])[0]
    report.centroid_nm = sum(nm * v for nm, v in positive) / sum(v for _, v in positive)

    # CCT / Duv are defined on the 2 degree observer, in CIE 1960 uv.
    X2, Y2, Z2 = (float((values * _cmfs(2).values[:, i]).sum()) for i in range(3))
    d2 = X2 + 15 * Y2 + 3 * Z2
    try:
        cct, duv = c.uv_to_CCT([4 * X2 / d2, 6 * Y2 / d2], method="Ohno 2013")
        report.cct, report.duv = float(cct), float(duv)
    except Exception:  # far from the Planckian locus
        pass
    if quality:
        _add_quality(report, sd)
    return report


def _add_quality(report: ColorReport, sd: Any) -> None:
    c = colour()
    from colour.quality import colour_fidelity_index_ANSIIESTM3018

    with warnings.catch_warnings():  # colour notes every internal resampling; not useful here
        warnings.simplefilter("ignore", c.utilities.ColourRuntimeWarning)
        _cri_and_tm30(report, sd, c, colour_fidelity_index_ANSIIESTM3018)


def _cri_and_tm30(report: ColorReport, sd: Any, c: Any, tm30: Any) -> None:
    try:
        cri = c.colour_rendering_index(sd, additional_data=True)
        report.cri_ra = float(cri.Q_a)
        report.cri_r = {int(i): float(s.Q_a) for i, s in cri.Q_as.items()}
    except Exception:
        pass
    try:
        tm = tm30(sd.copy().trim(c.SpectralShape(380, 780, 1)), additional_data=True)
        report.tm30_rf, report.tm30_rg = float(tm.R_f), float(tm.R_g)
    except Exception:
        pass


def compare(
    output: ColorReport, target: ColorReport, output_spectrum: Spectrum, target_spectrum: Spectrum
) -> Comparison:
    """Compare an output with its target. The spectral RMS uses the target's wavelength range."""

    def diff(a, b):
        return None if a is None or b is None else a - b

    duv_prime = None
    if output.uv_prime and target.uv_prime:
        duv_prime = math.dist(output.uv_prime, target.uv_prime)
    return Comparison(
        delta_uv_prime=duv_prime,
        delta_cct=diff(output.cct, target.cct),
        delta_duv=diff(output.duv, target.duv),
        level_ratio=output.photometric / target.photometric if target.photometric > 0 else None,
        spectral_rms=spectral_rms(output_spectrum, target_spectrum),
    )


def spectral_rms(output: Spectrum, target: Spectrum) -> float | None:
    """RMS difference of the two spectra after scaling both to the same area over the target's range,
    in % of the target's mean value. 0 is a perfect spectral match."""
    t = {int(nm): v for nm, v in target}
    o = {int(nm): v for nm, v in output}
    nms = [nm for nm in t if nm in o]
    t_sum, o_sum = sum(t[nm] for nm in nms), sum(o[nm] for nm in nms)
    if not nms or t_sum <= 0 or o_sum <= 0:
        return None
    tn = [t[nm] / t_sum for nm in nms]
    on = [o[nm] / o_sum for nm in nms]
    mean = sum(tn) / len(tn)
    return 100 * math.sqrt(sum((a - b) ** 2 for a, b in zip(on, tn, strict=True)) / len(tn)) / mean


def photometric_per_unit(relative: list[float], start: int) -> float:
    """Photometric value (lux or nits) of a relative spectrum taken as uW/cm2/nm (or /sr)."""
    ybar = {int(nm): y for nm, y in zip(_cmfs(2).wavelengths, _cmfs(2).values[:, 1], strict=True)}
    return K_M * UW_PER_CM2_TO_W_PER_M2 * sum(v * ybar.get(start + i, 0.0) for i, v in enumerate(relative))
