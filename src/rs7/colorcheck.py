"""How accurately a camera sees color under the RS-7's light, measured with an X-Rite ColorChecker Classic.

The idea: the RS-7 lights the chart with a known spectrum S (it measures its own output). The reflectance spectra
R of the 24 patches are known, so the true tristimulus of every patch is ``XYZ = k * sum(S * R * cmf)``, with ``k``
such that a perfect white (R = 1) has Y = 100. The camera gives raw linear R, G, B per patch. A 3x3 matrix M
(camera RGB -> XYZ) is fitted to the 24 patches by least squares; what is left over, the color difference
(CIE ΔE2000 in CIELAB with the light's white point) between ``M * RGB`` and the true XYZ, says how well this
camera can reproduce color under that light. Fitting under one light and using the matrix under another (after a
white balance on the white patch) shows how well one matrix serves different lights.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ._colour import colour
from .camera import PicamWeb, RawCapture, bayer_means
from .chart import ChartGeometry
from .colorimetry import Spectrum, _cmfs
from .device import RS7
from .match import match
from .snapshot import restore, take

PATCH_NAMES = (
    "dark skin", "light skin", "blue sky", "foliage", "blue flower", "bluish green",
    "orange", "purplish blue", "moderate red", "purple", "yellow green", "orange yellow",
    "blue", "green", "red", "yellow", "magenta", "cyan",
    "white 9.5", "neutral 8", "neutral 6.5", "neutral 5", "neutral 3.5", "black 2",
)  # fmt: skip
WHITE = 18  # index of the white patch
SATURATED = 0.98  # a patch with a raw value above this fraction of full scale is clipped
TOO_DARK = 0.01  # a patch whose brightest channel is below this fraction of the usable range is mostly noise
REFERENCE = "ColorChecker N Ohta"  # reflectance spectra, 380-780 nm


# ---- the true colors --------------------------------------------------------------------------------------


def reference_xyz(spectrum: Spectrum) -> tuple[np.ndarray, np.ndarray]:
    """XYZ of the 24 patches (24, 3) and of the light's white (3,) under ``spectrum`` (the 2 degree observer).

    Scaled so that a perfect white reflector has Y = 100.
    """
    cmfs = _cmfs(2)
    nm = cmfs.wavelengths
    s = np.interp(nm, *np.asarray(spectrum, dtype=float).T, left=0.0, right=0.0)
    sds = colour().SDS_COLOURCHECKERS[REFERENCE]
    reflectance = np.array([np.interp(nm, sd.wavelengths, sd.values) for sd in sds.values()])  # (24, n)
    k = 100 / (s @ cmfs.values[:, 1])
    return k * (reflectance * s) @ cmfs.values, k * s @ cmfs.values


def delta_e2000(xyz: np.ndarray, white: np.ndarray, ref_xyz: np.ndarray, ref_white: np.ndarray) -> np.ndarray:
    """ΔE2000 per patch between ``xyz`` (seen against ``white``) and ``ref_xyz`` (against ``ref_white``)."""
    c = colour()
    lab = c.XYZ_to_Lab(xyz / 100, c.XYZ_to_xy(white))
    ref_lab = c.XYZ_to_Lab(ref_xyz / 100, c.XYZ_to_xy(ref_white))
    return np.asarray(c.delta_E(lab, ref_lab, method="CIE 2000"), dtype=float)


# ---- the camera's colors ----------------------------------------------------------------------------------


@dataclass
class PatchData:
    """What the camera saw in each of the 24 patches."""

    rgb: np.ndarray  #: (24, 3) mean R, G, B in DN, black level subtracted, averaged over the frames
    peak: np.ndarray  #: (24,) highest raw DN in the patch, in any frame
    exposure_us: float
    gain: float
    black_level: float
    full_scale: float

    @property
    def normalized(self) -> np.ndarray:
        """RGB per us of exposure and unit gain, so captures at different exposures can be compared."""
        return self.rgb / (self.exposure_us * self.gain)

    @property
    def saturated(self) -> np.ndarray:
        return self.peak >= SATURATED * self.full_scale

    @property
    def too_dark(self) -> np.ndarray:
        return self.rgb.max(axis=1) < TOO_DARK * (self.full_scale - self.black_level)

    @property
    def excluded(self) -> np.ndarray:
        """Patches that are clipped or too dark to be measured."""
        return self.saturated | self.too_dark


def measure_patches(capture: RawCapture, geometry: ChartGeometry) -> PatchData:
    """Black-subtracted R, G, B mean of every patch, over all frames of the capture."""
    rois = geometry.patch_rois()
    rgb = np.zeros((len(rois), 3))
    peak = np.zeros(len(rois))
    for frame in capture.frames:
        for i, roi in enumerate(rois):
            means, high = bayer_means(frame, roi, capture.pattern, capture.black_level)
            rgb[i] += means / len(capture.frames)
            peak[i] = max(peak[i], high)
    return PatchData(rgb, peak, capture.exposure_us, capture.analogue_gain, capture.black_level, capture.full_scale)


def auto_exposure(cam: PicamWeb, geometry: ChartGeometry, target: float = 0.6, captures: int = 4) -> float:
    """Exposure time (us) at which the brightest channel of the white patch is ``target`` of full scale.

    Starts from the present exposure and refines it from what the camera sees (the response is linear), with at
    most ``captures`` images. The camera is left at the exposure returned. A clipped white patch only tells that
    it is too bright, so the exposure is halved then.
    """
    low, high = cam.exposure_range()
    exposure = float(np.clip(cam.metadata()["ExposureTime"], low, high))
    for _ in range(captures):
        capture = cam.capture()
        white = measure_patches(capture, geometry)
        level = white.rgb[WHITE].max() / (capture.full_scale - capture.black_level)
        wanted = capture.exposure_us / 2 if white.saturated[WHITE] else capture.exposure_us * target / max(level, 1e-6)
        exposure = float(np.clip(wanted, low, high))
        if abs(exposure / capture.exposure_us - 1) < 0.05:
            break
        cam.set_exposure(exposure, capture.analogue_gain)
    return exposure


# ---- fitting ----------------------------------------------------------------------------------------------


def fit_ccm(rgb: np.ndarray, xyz: np.ndarray, use: np.ndarray | None = None) -> np.ndarray:
    """3x3 matrix M with ``xyz ~ rgb @ M.T`` in the least-squares sense, over the patches where ``use`` is true."""
    use = np.ones(len(rgb), bool) if use is None else use
    a, *_ = np.linalg.lstsq(rgb[use], xyz[use], rcond=None)
    return a.T


@dataclass
class Accuracy:
    delta_e: np.ndarray  #: (24,) ΔE2000 of every patch
    used: np.ndarray  #: (24,) bool, the patches that count (not clipped or too dark)

    @property
    def mean(self) -> float:
        return float(self.delta_e[self.used].mean())

    @property
    def median(self) -> float:
        return float(np.median(self.delta_e[self.used]))

    @property
    def max(self) -> float:
        return float(self.delta_e[self.used].max())


@dataclass
class IlluminantResult:
    illuminant: str
    cct: float | None  #: of the light the RS-7 made, K
    delta_uv_prime: float | None  #: how far that light's chromaticity is from the target (Δu'v')
    patches: PatchData
    ref_xyz: np.ndarray  #: (24, 3) true XYZ under the measured spectrum, perfect white Y = 100
    white_xyz: np.ndarray  #: (3,) XYZ of the light's perfect white
    ccm: np.ndarray  #: (3, 3) normalized camera RGB -> XYZ
    accuracy: Accuracy

    @property
    def exposure_us(self) -> float:
        return self.patches.exposure_us


@dataclass
class CrossResult:
    """The matrix fitted under ``fitted_under``, used under ``illuminant`` after a white balance."""

    illuminant: str
    fitted_under: str
    accuracy: Accuracy


@dataclass
class ColorAccuracyResult:
    illuminants: list[IlluminantResult]
    cross: list[CrossResult]


def fit_illuminant(name: str, spectrum: Spectrum, patches: PatchData) -> IlluminantResult:
    """Fit the matrix under one light and score it. ``spectrum`` is the light the patches were seen under."""
    if patches.excluded[WHITE]:
        state = "clipped" if patches.saturated[WHITE] else "too dark"
        raise ValueError(f"the white patch is {state}: check the chart position and the exposure")
    ref_xyz, white_xyz = reference_xyz(spectrum)
    use = ~patches.excluded
    rgb = patches.normalized
    ccm = fit_ccm(rgb, ref_xyz, use)
    de = delta_e2000(rgb @ ccm.T, white_xyz, ref_xyz, white_xyz)
    return IlluminantResult(name, None, None, patches, ref_xyz, white_xyz, ccm, Accuracy(de, use))


def cross_accuracy(fitted: IlluminantResult, other: IlluminantResult) -> CrossResult:
    """Use the matrix of ``fitted`` on the patches of ``other``.

    The camera RGB is first scaled per channel so that the white patch reads as it did under ``fitted`` (a von
    Kries white balance), which also removes any difference in brightness. The result then looks like the chart
    under the first light, and is compared with the true colors under the second, each against its own white.
    """
    balance = fitted.patches.normalized[WHITE] / other.patches.normalized[WHITE]
    xyz = (other.patches.normalized * balance) @ fitted.ccm.T
    de = delta_e2000(xyz, fitted.white_xyz, other.ref_xyz, other.white_xyz)
    return CrossResult(other.illuminant, fitted.illuminant, Accuracy(de, ~other.patches.excluded))


# ---- the measurement --------------------------------------------------------------------------------------


def color_accuracy(
    rs7: RS7,
    cam: PicamWeb,
    geometry: ChartGeometry,
    illuminants: tuple[str, ...] | list[str] = ("D65", "A", "LED-B3"),
    level: float | None = None,
    frames: int = 4,
    method: str = "local",
    progress: Callable[[str], None] | None = None,
) -> ColorAccuracyResult:
    """Let the RS-7 make each illuminant in turn, photograph the chart and score the camera's color.

    ``level`` is the photometric level (lux) of the light; ``None`` keeps the present one. The RS-7 and the camera
    controls are put back as they were at the end, also when something fails.
    """
    say = progress or (lambda _: None)
    snapshot = take(rs7)
    results: list[IlluminantResult] = []
    try:
        with cam.manual_exposure(cam.metadata()["ExposureTime"]):
            for name in illuminants:
                say(f"{name}: matching the light")
                matched = match(rs7, name, level, method=method)
                say(f"{name}: setting the exposure")
                exposure = auto_exposure(cam, geometry)
                say(f"{name}: capturing {frames} frames at {exposure / 1000:.1f} ms")
                patches = measure_patches(cam.capture(frames), geometry)
                result = fit_illuminant(name, matched.output_spectrum, patches)
                result.cct = matched.output.cct
                result.delta_uv_prime = matched.comparison.delta_uv_prime
                results.append(result)
    finally:
        restore(rs7, snapshot)
    return ColorAccuracyResult(results, [cross_accuracy(results[0], other) for other in results[1:]])
