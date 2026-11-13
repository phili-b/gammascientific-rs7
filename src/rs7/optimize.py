"""Local channel fit: solve the channel powers on the PC instead of with the RS-7's ``FTS``.

1. :func:`load_basis` measures each channel's spectrum once (about 10 s; each channel is switched to
   ``power`` % for a moment and put back) and caches it per LED board in ``~/.rs7``.
2. :func:`solve` finds channel powers (0 to the soft limit) whose summed spectra are closest to the target
   in the least-squares sense, with extra rows that pull the CIE XYZ (color and level) onto the target's.
3. :func:`fit` sets them, then re-reads the active channels' real spectra at their new powers (LEDs shift
   a little with current) and solves again.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from .colorimetry import K_M, UW_PER_CM2_TO_W_PER_M2
from .device import RS7, Units

BASIS_RANGE = (360, 1100)  # the full range of the RS-7, so IR leakage is seen too
CACHE_DIR = Path.home() / ".rs7"
COLOR_WEIGHT = 50.0  # how strongly XYZ is held to the target relative to the spectral shape
LEAK_WEIGHT = 0.5  # how strongly light outside the fit range is avoided
MIN_INSIDE = 0.05  # channels with less of their power inside the fit range are not used


@dataclass
class ChannelBasis:
    """Spectrum per 1 % of power for every channel group, 1 nm steps over ``start``-``end``."""

    board: str  #: LED board serial and calibration, the cache key
    start: int
    end: int
    power: float  #: % at which the spectra were measured
    groups: dict[int, list[int]]  #: group leader -> member channels
    spectra: dict[int, list[float]]  #: group leader -> spectrum per 1 %

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self)))

    @classmethod
    def load(cls, path: Path) -> ChannelBasis:
        d = json.loads(path.read_text())
        d["groups"] = {int(k): v for k, v in d["groups"].items()}
        d["spectra"] = {int(k): v for k, v in d["spectra"].items()}
        return cls(**d)


def _board_key(rs7: RS7) -> str:
    return f"{rs7.led_board_serial()} {rs7.calibration_info()}"


def measure_basis(rs7: RS7, power: float = 70.0, progress: Callable[[int, int], None] | None = None) -> ChannelBasis:
    """Measure every channel group's spectrum at ``power`` %. Each channel is put back to its own power."""
    groups = rs7.channel_groups()
    previous_range = rs7.wavelength_range()
    spectra: dict[int, list[float]] = {}
    with rs7.using_units(Units.INTERNAL):
        for i, lead in enumerate(groups):
            original = rs7.channel_power(lead)
            rs7.set_channel_power(lead, power)
            try:
                spectrum = rs7.spectrum(lead, *BASIS_RANGE)
            finally:
                rs7.set_channel_power(lead, original)
            spectra[lead] = [v / power for _, v in spectrum]
            if progress:
                progress(i + 1, len(groups))
    rs7.set_wavelength_range(*previous_range)
    return ChannelBasis(_board_key(rs7), *BASIS_RANGE, power, groups, spectra)


def load_basis(rs7: RS7, remeasure: bool = False, progress: Callable[[int, int], None] | None = None) -> ChannelBasis:
    """The cached basis for this unit, measured first if there is none (or ``remeasure``)."""
    key = _board_key(rs7)
    path = CACHE_DIR / f"basis-{key.split()[0]}.json"
    if not remeasure and path.is_file():
        basis = ChannelBasis.load(path)
        if basis.board == key and (basis.start, basis.end) == BASIS_RANGE:
            return basis
    basis = measure_basis(rs7, progress=progress)
    basis.save(path)
    return basis


def solve(
    basis: ChannelBasis,
    target: list[float],
    start: int,
    max_power: float = 100.0,
    color_weight: float = COLOR_WEIGHT,
    fit_range: tuple[int, int] | None = None,
) -> dict[int, float]:
    """Channel powers (%) per group leader that best reproduce ``target``.

    ``target`` is absolute (uW/cm2/nm or /sr) at 1 nm from ``start``. The spectral rows cover ``fit_range``
    (default: the target's range); three extra rows hold X, Y and Z to the target's over the whole basis
    range, so color and level are matched as well.
    """
    import numpy as np
    from scipy.optimize import lsq_linear

    from .colorimetry import _cmfs

    leads = list(basis.spectra)
    nm = np.arange(basis.start, basis.end + 1)
    B = np.array([basis.spectra[c] for c in leads]).T  # (wavelengths, channels), per 1 %
    t = np.zeros(len(nm))
    for i, v in enumerate(target):
        j = start + i - basis.start
        if 0 <= j < len(nm):
            t[j] = v
    lo, hi = fit_range or (start, start + len(target) - 1)
    inside = (nm >= lo) & (nm <= hi)
    scale = abs(t[inside]).mean()
    if scale <= 0:
        raise ValueError("the target has no power in the fit range")
    cmfs = _cmfs(2)
    cmf = np.zeros((3, len(nm)))
    for k, w in enumerate(cmfs.wavelengths):
        j = int(w) - basis.start
        if 0 <= j < len(nm):
            cmf[:, j] = cmfs.values[k]
    M = K_M * UW_PER_CM2_TO_W_PER_M2 * cmf
    xyz_t = M @ t
    w = color_weight * math.sqrt(inside.sum()) / xyz_t[1]
    # Like the firmware, only use channels with real power inside the fit range; the others
    # (e.g. IR LEDs) would otherwise be unconstrained. Light that leaks outside the range is penalized.
    totals = B.sum(axis=0)
    use = (totals > 0) & (B[inside].sum(axis=0) >= MIN_INSIDE * totals)
    outside = ~inside
    A = np.vstack([B[inside] / scale, B[outside] / scale * LEAK_WEIGHT, (M @ B) * w])[:, use]
    b = np.concatenate([t[inside] / scale, t[outside] / scale * LEAK_WEIGHT, xyz_t * w])
    result = lsq_linear(A, b, bounds=(0.0, max_power))
    powers = dict.fromkeys(leads, 0.0)
    powers.update({c: float(p) for c, p in zip(np.array(leads)[use].tolist(), result.x, strict=True)})
    return powers


def apply(rs7: RS7, basis: ChannelBasis, powers: dict[int, float]) -> None:
    """Set every group to its power (internal %); groups not in ``powers`` are switched off."""
    with rs7.using_units(Units.INTERNAL):
        rs7.set_channel_powers(
            {c: round(powers.get(c, 0.0), 4) if powers.get(c, 0.0) >= 1e-3 else 0 for c in basis.spectra}
        )


def fit(
    rs7: RS7,
    target: list[float],
    start: int,
    at_max: bool = False,
    iterations: int = 2,
    basis: ChannelBasis | None = None,
) -> dict[int, float]:
    """Fit the RS-7 to the absolute ``target`` (1 nm from ``start``) and set it. Returns the powers that were set.

    The basis is only a model (LEDs shift with drive current, and it was measured at one power), so after
    each step the real output spectrum is read and the remaining error is added back to the target before
    solving again (``iterations`` times). ``at_max`` first scales the target up until a channel reaches the
    soft limit.
    """
    import numpy as np

    basis = basis or load_basis(rs7)
    max_power = 0.95 * float(rs7.soft_limit())  # headroom for trimming the level afterwards
    fit_range = (start, start + len(target) - 1)
    nm = np.arange(basis.start, basis.end + 1)
    goal = np.zeros(len(nm))
    for i, v in enumerate(target):
        if 0 <= start + i - basis.start < len(nm):
            goal[start + i - basis.start] = v
    if at_max:
        first = solve(basis, list(goal), basis.start, max_power, fit_range=fit_range)
        goal *= min((max_power / p for p in first.values() if p > 1e-6), default=1.0)
    aim = goal.copy()
    powers: dict[int, float] = {}
    for i in range(iterations + 1):
        powers = solve(basis, list(aim), basis.start, max_power, fit_range=fit_range)
        apply(rs7, basis, powers)
        if i == iterations:
            break
        measured = np.array([v for _, v in rs7.spectrum(0, basis.start, basis.end)])
        aim = aim + (goal - measured)  # aim past the model's error
    return powers
