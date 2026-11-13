"""Local fit, spectrum helpers and snapshots (no hardware)."""

import math

import pytest

from rs7.colorimetry import analyze
from rs7.optimize import ChannelBasis, solve
from rs7.snapshot import Snapshot
from rs7.spectrum import centroid, fwhm, photon_flux

START, END = 360, 1100


def gaussian(center, width, start=START, end=END):
    sigma = width / (2 * math.sqrt(2 * math.log(2)))
    return [math.exp(-0.5 * ((nm - center) / sigma) ** 2) for nm in range(start, end + 1)]


def test_fwhm_and_centroid_of_a_gaussian():
    s = list(zip(range(START, END + 1), gaussian(550, 20), strict=True))
    assert fwhm(s) == pytest.approx(20, abs=0.1)
    assert centroid(s) == pytest.approx(550, abs=0.01)


def test_photon_flux():
    # 1 uW/cm2 at 555 nm = 1e-6 W * 555e-9 m / (h c) = 2.794e12 photons/s/cm2
    assert photon_flux([(555, 1.0)]) == pytest.approx(2.794e12, rel=1e-3)


def basis_of(channels: dict[int, tuple[float, float]]) -> ChannelBasis:
    return ChannelBasis(
        board="test",
        start=START,
        end=END,
        power=70,
        groups={c: [c] for c in channels},
        spectra={c: [v * 0.01 for v in gaussian(*cw)] for c, cw in channels.items()},
    )


CHANNELS: dict[int, tuple[float, float]] = {1: (450, 25), 2: (520, 30), 3: (590, 15), 4: (630, 18), 5: (940, 40)}


def test_solve_recovers_a_mix_of_its_own_channels():
    b = basis_of(CHANNELS)
    truth = {1: 20.0, 2: 35.0, 3: 10.0, 4: 50.0}
    target = [sum(truth.get(c, 0) * b.spectra[c][i] for c in b.spectra) for i in range(END - START + 1)]
    got = solve(b, target[380 - START : 780 - START + 1], 380)
    for c, p in truth.items():
        assert got[c] == pytest.approx(p, rel=1e-3)
    assert got[5] == 0  # the IR channel has no power in the fit range and is not used


def test_solve_respects_the_power_limit_and_holds_the_color():
    b = basis_of(CHANNELS)
    flat = [3.0] * 401  # far more than the channels can give at 40 %
    got = solve(b, flat, 380, max_power=40)
    assert max(got.values()) <= 40 + 1e-9
    half = [0.2] * 401  # reachable: color (from the XYZ rows) must match closely
    got = solve(b, half, 380)
    mix = [(START + i, sum(got[c] * b.spectra[c][i] for c in b.spectra)) for i in range(END - START + 1)]
    out, tgt = analyze(mix, quality=False), analyze([(380 + i, 0.2) for i in range(401)], quality=False)
    assert out.uv_prime and tgt.uv_prime
    assert math.dist(out.uv_prime, tgt.uv_prime) < 0.002
    assert out.photometric == pytest.approx(tgt.photometric, rel=0.01)


def test_basis_cache_round_trip(tmp_path):
    b = basis_of(CHANNELS)
    b.save(tmp_path / "b.json")
    assert ChannelBasis.load(tmp_path / "b.json") == b


def test_snapshot_round_trip(tmp_path):
    snap = Snapshot(
        time="2026-11-13T19:00:00",
        board="LHX0416",
        units=2,
        wavelength_range=(380, 780),
        powers={3: 4.2, 6: 100.0},
        spectrum=[(360, 0.0), (361, 1.5)],
        photometric=1631.0,
        xy=(0.3549, 0.3894),
        cct=4806.0,
        note="test",
    )
    snap.save(tmp_path / "s.json")
    assert Snapshot.load(tmp_path / "s.json") == snap
