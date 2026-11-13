"""Target spectra for the RS-7: CIE illuminants, black bodies and CSV files.

A target is named by a string:

========================  =========================================================================
``"D65"``, ``"A"``, ...   any illuminant in colour-science's CIE library (see :func:`available`):
                          A, B, C, D50, D55, D60, D65, D75, E, FL1-FL12, FL3.1-FL3.15, HP1-HP5,
                          LED-B1...LED-V2, ID50, ID65, ISO 7589 ...
``"D5000"``               CIE daylight (D-series) at any correlated color temperature, 4000-25000 K
``"3000K"``, ``"BB3000"`` black body (Planck) at that temperature
``"path/to/file.csv"``    ``wavelength, value`` lines, any step size
========================  =========================================================================

Spectra are relative (peak 1); :func:`rs7.match.match` scales them to an absolute level.
"""

from __future__ import annotations

import re
from pathlib import Path

from ._colour import colour
from .spectrum import load_csv, resample

_D_SERIES = re.compile(r"^D\s*(\d{4,5})$", re.IGNORECASE)
_BLACKBODY = re.compile(r"^(?:BB\s*)?(\d{3,5}(?:\.\d+)?)\s*K?$", re.IGNORECASE)


def available() -> list[str]:
    """Names of the CIE library illuminants."""
    return sorted(colour().SDS_ILLUMINANTS, key=_natural)


def _natural(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def describe(name: str) -> str:
    """Human-readable description of a target name."""
    library = _library_name(name)
    if library:
        return f"CIE illuminant {library}"
    if m := _D_SERIES.match(name.strip()):
        return f"CIE daylight at {m.group(1)} K"
    if (m := _BLACKBODY.match(name.strip())) and not Path(name).is_file():
        return f"black body {float(m.group(1)):g} K"
    return Path(name).name


def _library_name(name: str) -> str | None:
    lookup = {k.lower(): k for k in colour().SDS_ILLUMINANTS}
    return lookup.get(name.strip().lower())


def target_spectrum(name: str, start: int, end: int) -> list[float]:
    """Relative spectrum of ``name`` at 1 nm steps from ``start`` to ``end`` nm, peak normalized to 1.

    Outside the illuminant's tabulated range the values are 0.
    """
    c = colour()
    if Path(name).is_file():
        values = resample(load_csv(name), start, end)
    else:
        library = _library_name(name)
        if library:
            sd = c.SDS_ILLUMINANTS[library]
        elif m := _D_SERIES.match(name.strip()):
            cct = float(m.group(1))
            if not 4000 <= cct <= 25000:
                raise ValueError("CIE daylight is defined from 4000 to 25000 K")
            sd = c.sd_CIE_illuminant_D_series(c.temperature.CCT_to_xy_CIE_D(cct))
        elif m := _BLACKBODY.match(name.strip()):
            sd = c.sd_blackbody(float(m.group(1)), c.SpectralShape(300, 1100, 1))
        else:
            raise ValueError(
                f"unknown target {name!r}: use a CIE illuminant name (e.g. D65, A, FL2, LED-B3), "
                "D<CCT> for daylight (e.g. D5000), <T>K for a black body (e.g. 3000K), or a CSV file"
            )
        points = [(float(nm), float(v)) for nm, v in zip(sd.wavelengths, sd.values, strict=True)]
        values = resample(points, start, end)
    peak = max(values, default=0.0)
    if peak <= 0:
        raise ValueError(f"target {name!r} has no power between {start} and {end} nm")
    return [v / peak for v in values]
