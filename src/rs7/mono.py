"""Monochromatic steps: one channel (group) at a time, at a chosen photon flux, radiant power or drive level.

Typical use is a spectral-response or QE scan: step through the channels by wavelength with the same photon
flux at each step and take a measurement at every step::

    for step in mono_scan(rs7, 400, 1000, photons=1e13):
        capture_image(step.centroid_nm)          # your measurement
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from .device import RS7, Units
from .spectrum import centroid, fwhm, photon_flux

SCAN_RANGE = (360, 1100)  # nm, full range of the RS-7's spectra
WHITE_FWHM = 60.0  # nm: wider channels are white / broadband, not monochromatic


@dataclass
class MonoStep:
    channel: int  #: group leader that was set
    members: list[int]  #: all channels of that group
    nominal_nm: float  #: nominal wavelength from LIN
    centroid_nm: float | None  #: of the actual spectrum at this power
    peak_nm: float | None
    fwhm_nm: float | None
    power: float  #: drive level, % (internal units)
    radiometric: float  #: uW/cm2 (or uW/cm2/sr)
    photon_flux: float  #: photons/s/cm2 (or /sr)
    at_limit: bool  #: the requested flux or power needed more than the soft limit allows


def mono_channels(rs7: RS7, start: int = SCAN_RANGE[0], end: int = SCAN_RANGE[1], max_fwhm: float = WHITE_FWHM):
    """Group leaders with a narrow spectrum and nominal wavelength in ``start``-``end``, by wavelength.

    Returns ``[(leader, members, nominal_nm, nominal_fwhm), ...]``.
    """
    info = {c.channel: c for c in rs7.channel_info()}
    rows = []
    for lead, members in rs7.channel_groups().items():
        c = info.get(lead)
        if c and start <= c.nominal_wavelength <= end and 0 < c.nominal_fwhm <= max_fwhm:
            rows.append((lead, members, c.nominal_wavelength, c.nominal_fwhm))
    return sorted(rows, key=lambda r: r[2])


def _measure(rs7: RS7, lead: int, members: list[int], nominal: float, power: float, at_limit: bool) -> MonoStep:
    s = rs7.spectrum(lead, *SCAN_RANGE)
    peak = max(s, key=lambda p: p[1]) if s else None
    return MonoStep(
        channel=lead,
        members=members,
        nominal_nm=nominal,
        centroid_nm=centroid(s),
        peak_nm=peak[0] if peak and peak[1] > 0 else None,
        fwhm_nm=fwhm(s),
        power=power,
        radiometric=sum(v for _, v in s),
        photon_flux=photon_flux(s),
        at_limit=at_limit,
    )


def set_mono(
    rs7: RS7,
    channel: int,
    photons: float | None = None,
    radiometric: float | None = None,
    power: float | None = None,
) -> MonoStep:
    """Switch everything off except ``channel`` (and its group), set to exactly one of:

    - ``photons``: photon flux, photons/s/cm2 (or /sr), summed over the channel's spectrum;
    - ``radiometric``: uW/cm2 (or /sr);
    - ``power``: drive level in % (internal units).
    """
    if sum(x is not None for x in (photons, radiometric, power)) != 1:
        raise ValueError("give exactly one of photons, radiometric or power")
    groups = rs7.channel_groups()
    lead = next((g for g, m in groups.items() if channel in m), None)
    if lead is None:
        raise ValueError(f"channel {channel} is not fitted in this unit")
    nominal = next((c.nominal_wavelength for c in rs7.channel_info() if c.channel == lead), 0.0)
    limit = float(rs7.soft_limit())
    with rs7.using_units(Units.INTERNAL):
        rs7.all_off()
        if power is not None:
            p = min(power, limit)
            rs7.set_channel_power(lead, p)
            return _measure(rs7, lead, groups[lead], nominal, p, power > limit)
        goal = photons if photons is not None else radiometric
        assert goal is not None
        p, at_limit = 10.0, False
        for _ in range(4):  # LED output is close to, but not exactly, proportional to the drive level
            rs7.set_channel_power(lead, round(p, 4))
            step = _measure(rs7, lead, groups[lead], nominal, p, at_limit)
            got = step.photon_flux if photons is not None else step.radiometric
            if got <= 0:
                raise ValueError(f"channel {lead} gives no light")
            if abs(got / goal - 1) < 0.002 or at_limit:
                return step
            p = p * goal / got
            if p > limit:
                p, at_limit = limit, True
        return step


def mono_scan(
    rs7: RS7,
    start: int = SCAN_RANGE[0],
    end: int = SCAN_RANGE[1],
    photons: float | None = None,
    radiometric: float | None = None,
    power: float | None = None,
    max_fwhm: float = WHITE_FWHM,
) -> Iterator[MonoStep]:
    """Yield one :class:`MonoStep` per narrow channel from ``start`` to ``end`` nm, each set as in :func:`set_mono`.

    Do your measurement in the loop body. The unit's channel powers are restored afterwards (also on errors or
    when the loop is left early).
    """
    with rs7.using_units(Units.INTERNAL):
        before = rs7.channel_powers()
    try:
        for lead, *_ in mono_channels(rs7, start, end, max_fwhm):
            yield set_mono(rs7, lead, photons, radiometric, power)
    finally:
        with rs7.using_units(Units.INTERNAL):
            rs7.all_off()
            if before:
                rs7.set_channel_powers(before)
