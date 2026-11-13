import math

from rs7.spectrum import blackbody, cct_to_xy, load_csv, resample, wavelength_to_rgb


def test_blackbody_is_normalized_and_peaks_in_the_right_place():
    values = blackbody(5000, 380, 1100)
    assert max(values) == 1.0
    assert abs(380 + values.index(1.0) - 580) < 10  # Wien: 2.898e6 / 5000 = 580 nm


def test_cct_to_xy_known_points():
    x, y = cct_to_xy(6500)
    assert math.isclose(x, 0.3135, abs_tol=0.003) and math.isclose(y, 0.3237, abs_tol=0.003)
    x, y = cct_to_xy(2856)
    assert math.isclose(x, 0.4476, abs_tol=0.003) and math.isclose(y, 0.4074, abs_tol=0.003)


def test_resample_interpolates_and_zero_fills():
    assert resample([(400, 0.0), (410, 10.0)], 399, 411) == [0.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 0.0]


def test_load_csv_skips_header(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("wavelength,amplitude\n500,1\n400,0.5\n")
    assert load_csv(str(f)) == [(400.0, 0.5), (500.0, 1.0)]


def test_wavelength_to_rgb_ends():
    assert wavelength_to_rgb(650)[0] == 255
    assert wavelength_to_rgb(1000)[1] == 0
