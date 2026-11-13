"""Camera client, chart geometry and color accuracy math (no hardware)."""

import io
import json
import struct
import zlib

import numpy as np
import pytest

from rs7.camera import CameraError, PicamWeb, RawCapture, bayer_means, parse_npz
from rs7.chart import ChartGeometry, parse_corners, preview_png, write_png
from rs7.colorcheck import (
    PATCH_NAMES,
    WHITE,
    PatchData,
    auto_exposure,
    cross_accuracy,
    delta_e2000,
    fit_ccm,
    fit_illuminant,
    reference_xyz,
)
from rs7.illuminants import target_spectrum

SQUARE = ((100.0, 100.0), (600.0, 100.0), (600.0, 400.0), (100.0, 400.0))


def spectrum(name):
    return [(360 + i, v) for i, v in enumerate(target_spectrum(name, 360, 830))]


# ---- chart geometry --------------------------------------------------------------------------------------


def test_homography_maps_the_corners_exactly():
    g = ChartGeometry(((503.0, 603.0), (1310.0, 552.0), (1327.0, 1043.0), (535.0, 1063.0)))  # tilted
    centers = g.patch_centers()
    assert centers.shape == (24, 2)
    for index, corner in zip((0, 5, 23, 18), g.corners, strict=True):  # TL, TR, BR, BL
        assert centers[index] == pytest.approx(corner, abs=1e-6)


def test_axis_aligned_chart_is_a_regular_grid():
    centers = ChartGeometry(SQUARE).patch_centers().reshape(4, 6, 2)
    assert centers[:, :, 0] == pytest.approx(np.tile(100 + 100 * np.arange(6), (4, 1)))
    assert centers[:, :, 1] == pytest.approx(np.tile((100 + 100 * np.arange(4))[:, None], (1, 6)))


def test_rois_are_even_aligned_and_inside_their_patch():
    for g in (ChartGeometry(SQUARE), ChartGeometry()):
        for (x, y, w, h), (cx, cy) in zip(g.patch_rois(), g.patch_centers(), strict=True):
            assert x % 2 == y % 2 == w % 2 == h % 2 == 0
            assert abs(x + w / 2 - cx) <= 2 and abs(y + h / 2 - cy) <= 2
    assert ChartGeometry(SQUARE).patch_rois()[0] == (82, 82, 36, 36)  # 0.35 * 100 pitch, rounded to even


def test_geometry_file_round_trip(tmp_path):
    path = tmp_path / "chart.json"
    assert ChartGeometry.load(path) == ChartGeometry()  # nothing saved: the default
    g = ChartGeometry(SQUARE, roi_fraction=0.3)
    g.save(path)
    assert ChartGeometry.load(path) == g


def test_parse_corners():
    assert parse_corners("1,2 3,4 5,6 7.5,8") == ((1, 2), (3, 4), (5, 6), (7.5, 8))
    with pytest.raises(ValueError):
        parse_corners("1,2 3,4")


# ---- raw frames ------------------------------------------------------------------------------------------


def test_bayer_means_of_a_grbg_frame():
    frame = np.zeros((16, 16))
    frame[0::2, 0::2] = frame[1::2, 1::2] = 50  # G
    frame[0::2, 1::2] = 100  # R
    frame[1::2, 0::2] = 200  # B
    frame += 10  # black level
    rgb, peak = bayer_means(frame, (4, 6, 8, 8), "GRBG", black=10)
    assert rgb == pytest.approx([100, 50, 200])
    assert peak == 210
    odd, _ = bayer_means(frame, (3, 5, 8, 8), "GRBG", black=10)  # an odd start still finds the colors by parity
    assert odd == pytest.approx([100, 50, 200])


def synthetic_npz(count=2, bit_depth=12, exposure=20000):
    frames = np.full((count, 4, 6), 1000, dtype=np.uint16)
    meta = {"ExposureTime": exposure, "AnalogueGain": 1.0005, "SensorBlackLevels": [3600, 3600, 3600, 3600]}
    buffer = io.BytesIO()
    np.savez(
        buffer,
        frames=frames,
        metadata=np.str_(json.dumps([meta] * count)),
        raw=np.str_(json.dumps({"format": "SGRBG16", "size": [6, 4], "bit_depth": bit_depth})),
    )
    return buffer.getvalue()


def test_parse_npz_like_the_service():
    capture = parse_npz(synthetic_npz())
    assert capture.frames.shape == (2, 4, 6) and capture.frames.dtype == np.float64
    assert capture.black_level == pytest.approx(225)  # 3600 in 16-bit units is 225 in 12 bit
    assert capture.bit_depth == 12 and capture.full_scale == 4095
    assert capture.exposure_us == 20000 and capture.analogue_gain == pytest.approx(1.0005)
    assert capture.pattern == "GRBG"


# ---- camera controls (a fake service) --------------------------------------------------------------------


class FakeCamera(PicamWeb):
    def __init__(self, controls):
        super().__init__("http://fake")
        self.state = dict(controls)
        self.posts = []

    def _json(self, path, body=None):
        if body is not None:
            self.posts.append(body)
            self.state.update(body)
            return {}
        if path == "/api/metadata":
            return {"ExposureTime": self.state["ExposureTime"], "AnalogueGain": 1.0, "FrameDuration": 100}
        return {k: {"value": v} for k, v in self.state.items()}


def test_manual_exposure_restores_the_previous_settings_also_on_errors():
    cam = FakeCamera({"AeEnable": False, "ExposureTime": 67402, "AnalogueGain": 1.0})
    with pytest.raises(RuntimeError), cam.manual_exposure(20000):
        assert cam.state["ExposureTime"] == 20000 and cam.state["AeEnable"] is False
        raise RuntimeError
    assert cam.state == {"AeEnable": False, "ExposureTime": 67402, "AnalogueGain": 1.0}


def test_manual_exposure_gives_auto_exposure_back():
    cam = FakeCamera({"AeEnable": True, "ExposureTime": 30000, "AnalogueGain": 1.0})
    with cam.manual_exposure(5000):
        assert cam.state["AeEnable"] is False
    assert cam.posts[-1] == {"AeEnable": True}


def test_manual_exposure_with_nothing_set_gives_the_default_auto_exposure_back():
    cam = FakeCamera({})  # a freshly started service: no control has a value yet
    with cam.manual_exposure(5000):
        assert cam.state["AeEnable"] is False
    assert cam.posts[-1] == {"AeEnable": True}


def test_unreachable_camera_is_a_camera_error():
    with pytest.raises(CameraError):
        PicamWeb("http://127.0.0.1:1", timeout=1).info()


# ---- PNG -------------------------------------------------------------------------------------------------


def read_png(data: bytes) -> np.ndarray:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, size = 8, b"", (0, 0)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind, body = data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        assert struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0] == zlib.crc32(kind + body)
        if kind == b"IHDR":
            size = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    width, height = size
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(height, 1 + width * 3)
    assert not raw[:, 0].any()  # filter type 0
    return raw[:, 1:].reshape(height, width, 3)


def test_png_writer(tmp_path):
    image = np.random.default_rng(1).integers(0, 256, (5, 7, 3), dtype=np.uint8)
    write_png(tmp_path / "a.png", image)
    assert (read_png((tmp_path / "a.png").read_bytes()) == image).all()


def test_preview_draws_the_boxes(tmp_path):
    capture = RawCapture(np.full((1, 800, 1200), 300.0), 225.0, 12, 1000.0, 1.0)
    preview_png(capture, ChartGeometry(SQUARE), tmp_path / "p.png")
    image = read_png((tmp_path / "p.png").read_bytes())
    assert image.shape == (400, 600, 3)  # one pixel per 2x2 Bayer cell
    assert (image == (255, 255, 0)).all(axis=-1).any()


# ---- colors ----------------------------------------------------------------------------------------------


def test_reference_xyz_of_white_under_equal_energy():
    xyz, white = reference_xyz([(nm, 1.0) for nm in range(360, 831)])
    assert white == pytest.approx([100, 100, 100], abs=0.1)  # a perfect white has Y = 100
    assert xyz[WHITE, 1] == pytest.approx(89, abs=2)  # white 9.5 reflects about 90 %
    assert xyz[WHITE, 1] > xyz[19, 1] > xyz[20, 1] > xyz[23, 1]  # neutral patches get darker
    assert len(PATCH_NAMES) == len(xyz) == 24


def test_ccm_fit_recovers_a_known_matrix():
    rng = np.random.default_rng(0)
    rgb = rng.uniform(0.01, 1, (24, 3))
    m = np.array([[0.7, 0.2, 0.1], [0.3, 0.6, 0.1], [0.0, 0.1, 0.9]]) * 100
    xyz = rgb @ m.T
    fitted = fit_ccm(rgb, xyz)
    assert fitted == pytest.approx(m)
    white = reference_xyz(spectrum("D65"))[1]
    assert delta_e2000(rgb @ fitted.T, white, xyz, white) == pytest.approx(0, abs=1e-6)


def synthetic_patches(name, camera, exposure=20000.0):
    """What an ideal linear camera (``xyz = camera @ rgb``) sees under the illuminant ``name``."""
    xyz, _ = reference_xyz(spectrum(name))
    rgb = xyz @ np.linalg.inv(camera).T  # DN above the black level, in proportion to the exposure
    rgb *= 2000 * exposure / 20000 / rgb[WHITE].max()
    return PatchData(rgb, rgb.max(axis=1) + 225, exposure, 1.0, 225.0, 4095.0)


def test_fit_illuminant_on_an_ideal_camera_and_excluding_patches():
    camera = np.array([[0.6, 0.3, 0.1], [0.2, 0.7, 0.1], [0.0, 0.2, 0.8]])
    patches = synthetic_patches("D65", camera)
    result = fit_illuminant("D65", spectrum("D65"), patches)
    assert result.accuracy.max == pytest.approx(0, abs=1e-6)
    assert result.accuracy.used.all()

    patches.peak[3] = 4095  # clipped
    patches.rgb[23] *= 0.001  # lost in the noise
    result = fit_illuminant("D65", spectrum("D65"), patches)
    assert not result.accuracy.used[3] and not result.accuracy.used[23]
    assert result.accuracy.used.sum() == 22
    patches.peak[WHITE] = 4095
    with pytest.raises(ValueError, match="white patch"):
        fit_illuminant("D65", spectrum("D65"), patches)


def test_cross_illuminant_error_of_the_same_light_is_zero():
    camera = np.array([[0.6, 0.3, 0.1], [0.2, 0.7, 0.1], [0.0, 0.2, 0.8]])
    d65 = fit_illuminant("D65", spectrum("D65"), synthetic_patches("D65", camera, 20000))
    again = fit_illuminant("D65 again", spectrum("D65"), synthetic_patches("D65", camera, 5000))  # other exposure
    cross = cross_accuracy(d65, again)
    assert cross.accuracy.max == pytest.approx(0, abs=1e-6)
    assert (cross.illuminant, cross.fitted_under) == ("D65 again", "D65")
    a = fit_illuminant("A", spectrum("A"), synthetic_patches("A", camera))
    assert 0 < cross_accuracy(d65, a).accuracy.mean < 20  # a different light: not perfect, but sensible


class SceneCamera(PicamWeb):
    """A uniform scene whose signal grows in proportion to the exposure (clipping at full scale)."""

    def __init__(self, exposure, signal_per_us):
        super().__init__("http://fake")
        self.exposure, self.signal_per_us, self.captures = exposure, signal_per_us, 0

    def exposure_range(self):
        return 7.0, 518818.0

    def metadata(self):
        return {"ExposureTime": self.exposure}

    def set_exposure(self, exposure_us, gain=1.0, timeout=15.0):
        self.exposure = exposure_us

    def capture(self, count=1):
        self.captures += 1
        value = min(225 + self.signal_per_us * self.exposure, 4095)
        return RawCapture(np.full((count, 1400, 1600), value), 225.0, 12, self.exposure, 1.0)


def test_auto_exposure_aims_at_60_percent_of_full_scale():
    cam = SceneCamera(20000, 0.01)  # 200 DN at 20 ms: far too dark
    exposure = auto_exposure(cam, ChartGeometry())
    assert exposure == pytest.approx(0.6 * (4095 - 225) / 0.01, rel=0.05)
    assert cam.captures <= 4
    cam = SceneCamera(100000, 0.1)  # clipped: halve until it is not
    assert auto_exposure(cam, ChartGeometry()) == pytest.approx(0.6 * (4095 - 225) / 0.1, rel=0.05)
    assert auto_exposure(SceneCamera(10, 1e-9), ChartGeometry()) == 518818.0  # too dark even at the longest exposure
