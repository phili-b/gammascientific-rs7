"""Physics checks against published CIE values (no hardware)."""

import math

import pytest

from rs7 import Units
from rs7.colorimetry import analyze, compare, photometric_per_unit, spectral_rms
from rs7.illuminants import available, describe, target_spectrum
from rs7.match import scale_to_level


def spec(name, start=360, end=830, scale=1.0):
    return [(start + i, v * scale) for i, v in enumerate(target_spectrum(name, start, end))]


def test_library_has_the_usual_illuminants():
    names = available()
    for n in ("A", "D50", "D65", "E", "FL2", "LED-B3"):
        assert n in names


def test_d65_chromaticity_and_cct():
    r = analyze(spec("D65"))
    assert r.xy == pytest.approx((0.3127, 0.3290), abs=2e-4)
    assert r.cct == pytest.approx(6504, abs=5)
    assert r.cri_ra == pytest.approx(100, abs=0.5)


def test_illuminant_a_is_a_2856k_black_body():
    a = analyze(spec("A"))
    assert a.xy == pytest.approx((0.4476, 0.4074), abs=2e-4)
    assert a.cct == pytest.approx(2856, abs=3)
    assert a.duv is not None and abs(a.duv) < 1e-4
    assert a.cri_ra == pytest.approx(100, abs=0.5)


def test_fl2_color_rendering_matches_published_values():
    r = analyze(spec("FL2"))
    assert r.cri_ra == pytest.approx(64, abs=1)  # CIE 15 / CIE 13.3
    assert r.tm30_rf == pytest.approx(70, abs=1.5)
    assert r.cct == pytest.approx(4230, abs=30)


def test_daylight_at_any_temperature():
    r = analyze(spec("D5000"))
    assert r.cct == pytest.approx(5000, abs=15)
    assert r.duv is not None and r.duv > 0  # daylight sits above the Planckian locus
    with pytest.raises(ValueError):
        target_spectrum("D3000", 380, 780)


def test_black_body_names():
    assert analyze(spec("3000K")).cct == pytest.approx(3000, abs=3)
    assert analyze(spec("BB 2700")).cct == pytest.approx(2700, abs=3)
    assert describe("3000K") == "black body 3000 K"
    assert describe("d65") == "CIE illuminant D65"


def test_unknown_target_explains_the_options():
    with pytest.raises(ValueError, match="D<CCT>"):
        target_spectrum("sunshine", 380, 780)


def test_csv_target(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("nm,value\n500,0\n550,2\n600,0\n")
    values = target_spectrum(str(f), 500, 600)
    assert max(values) == 1.0 and values[50] == 1.0 and values[0] == 0.0


def test_photometric_units():
    # 1 uW/cm2/nm everywhere = 0.01 W/m2/nm; times 683 lm/W times the sum of V(lambda) (~106.86 nm)
    flat = [(nm, 1.0) for nm in range(360, 831)]
    r = analyze(flat, quality=False)
    assert r.photometric == pytest.approx(683.002 * 0.01 * 106.857, rel=2e-3)
    assert r.radiometric == pytest.approx(471)
    assert r.xy == pytest.approx((1 / 3, 1 / 3), abs=1e-3)  # equal energy


def test_scale_to_level():
    rel = target_spectrum("D65", 380, 780)
    k = scale_to_level(rel, 380, 500.0, Units.PHOTOMETRIC)
    assert photometric_per_unit([v * k for v in rel], 380) == pytest.approx(500)
    assert sum(v * scale_to_level(rel, 380, 20.0, Units.RADIOMETRIC) for v in rel) == pytest.approx(20)
    with pytest.raises(ValueError):
        scale_to_level(rel, 380, 1, Units.INTERNAL)


def test_compare_and_spectral_rms():
    d65, d50 = spec("D65", 380, 780), spec("D50", 380, 780)
    assert spectral_rms(d65, d65) == pytest.approx(0)
    assert spectral_rms([(nm, 3 * v) for nm, v in d65], d65) == pytest.approx(0)  # level does not matter
    c = compare(analyze(d50), analyze(d65), d50, d65)
    assert c.delta_uv_prime == pytest.approx(math.dist((0.2092, 0.4881), (0.1978, 0.4683)), abs=1e-3)
    assert c.spectral_rms is not None and c.spectral_rms > 5


def test_no_light():
    r = analyze([(nm, 0.0) for nm in range(360, 831)])
    assert r.photometric == 0 and r.xy is None and r.cct is None
