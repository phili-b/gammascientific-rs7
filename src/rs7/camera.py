"""Raw images from the camera service ``picam-web`` (a Raspberry Pi with an ams Mira220 color sensor).

Only the standard library and numpy are used. ``/api/capture/raw`` returns an ``.npz`` with the raw Bayer frames
in digital numbers (DN) of the sensor mode (12 bit: 0-4095) and the metadata of every frame; the black level in the
metadata (``SensorBlackLevels``) is given in 16-bit units, so it is scaled to the mode's bit depth.

Color from a raw frame: every pixel sees one color through the Bayer filter. The mean of the pixels of one color in
a patch, minus the black level, is proportional to the light (linear, no gamma) and to the exposure time.
"""

from __future__ import annotations

import io
import json
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np

DEFAULT_URL = "http://10.61.100.206"
PATTERN = "GRBG"  # the 2x2 Bayer cell of the Mira220, row by row from the top-left pixel


class CameraError(Exception):
    """The camera service cannot be reached or refused a request."""


@dataclass
class RawCapture:
    frames: np.ndarray  #: (count, height, width), float64, DN of the sensor mode (black level not subtracted)
    black_level: float  #: DN
    bit_depth: int
    exposure_us: float
    analogue_gain: float
    pattern: str = PATTERN
    metadata: tuple[dict[str, Any], ...] = ()  #: of every frame

    @property
    def full_scale(self) -> float:
        """Highest DN the sensor can give."""
        return 2.0**self.bit_depth - 1


def parse_npz(data: bytes) -> RawCapture:
    """Read the ``.npz`` of ``/api/capture/raw``: ``frames`` (count, H, W), ``metadata`` (JSON list), ``raw`` (JSON)."""
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        frames = z["frames"].astype(np.float64)
        metadata = tuple(json.loads(str(z["metadata"])))
        bit_depth = int(json.loads(str(z["raw"]))["bit_depth"])
    last = metadata[-1]
    black = float(np.mean(last["SensorBlackLevels"])) * 2.0 ** (bit_depth - 16)
    return RawCapture(
        frames, black, bit_depth, float(last["ExposureTime"]), float(last["AnalogueGain"]), PATTERN, metadata
    )


class PicamWeb:
    """Client of the picam-web service. Reading never changes the camera; ``set_controls`` does."""

    def __init__(self, url: str = DEFAULT_URL, timeout: float = 30.0):
        self.url = url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, body: dict | None = None, timeout: float | None = None) -> bytes:
        request = urllib.request.Request(self.url + path)
        if body is not None:
            request.add_header("Content-Type", "application/json")
            request.data = json.dumps(body).encode()
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            raise CameraError(f"{self.url}{path}: {e.code} {e.read()[:200].decode(errors='replace')}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise CameraError(f"cannot reach the camera at {self.url}: {e}") from e

    def _json(self, path: str, body: dict | None = None) -> Any:
        return json.loads(self._request(path, body))

    def info(self) -> dict[str, Any]:
        """Sensor properties, sensor modes and the present configuration."""
        return self._json("/api/info")

    def metadata(self) -> dict[str, Any]:
        """Metadata of the latest frame (ExposureTime in us, AnalogueGain, SensorBlackLevels...)."""
        return self._json("/api/metadata")

    def controls(self) -> dict[str, Any]:
        """Present value of every control that has one, e.g. ``{"AeEnable": False, "ExposureTime": 67402}``."""
        return {k: v["value"] for k, v in self._json("/api/controls").items() if v["value"] is not None}

    def exposure_range(self) -> tuple[float, float]:
        """Shortest and longest exposure time, us."""
        limits = self._json("/api/controls")["ExposureTime"]
        return float(limits["min"]), float(limits["max"])

    def set_controls(self, **controls: Any) -> None:
        """Change libcamera controls, e.g. ``set_controls(AeEnable=False, ExposureTime=20000)``."""
        self._json("/api/controls", controls)

    def capture(self, count: int = 1) -> RawCapture:
        """``count`` raw frames at the present settings."""
        return parse_npz(self._request(f"/api/capture/raw?count={count}&format=npz", timeout=60 + 3 * count))

    def set_exposure(self, exposure_us: float, gain: float = 1.0, timeout: float = 15.0) -> None:
        """Fixed exposure and gain (auto exposure off). Returns once the frames use them."""
        self.set_controls(AeEnable=False, ExposureTime=round(exposure_us), AnalogueGain=gain)
        deadline = time.monotonic() + timeout
        while True:
            meta = self.metadata()
            if abs(meta["ExposureTime"] - exposure_us) <= max(0.01 * exposure_us, 20) and (
                abs(meta["AnalogueGain"] / gain - 1) < 0.01
            ):
                break
            if time.monotonic() > deadline:
                raise CameraError(f"the camera did not change to {exposure_us:.0f} us, gain {gain:g}")
            time.sleep(0.1)
        # The frames in the pipeline were still taken with the old settings: let a few go by.
        time.sleep(4 * meta["FrameDuration"] * 1e-6)

    @contextmanager
    def manual_exposure(self, exposure_us: float, gain: float = 1.0) -> Generator[None, None, None]:
        """Fixed exposure inside the ``with`` block; the previous auto exposure / exposure / gain come back after."""
        before = self.controls()
        try:
            self.set_exposure(exposure_us, gain)
            yield
        finally:
            # A control that was never set is at its default, and auto exposure is on by default.
            if before.get("AeEnable", True):
                self.set_controls(AeEnable=True)
            else:
                fixed = {k: before[k] for k in ("ExposureTime", "AnalogueGain") if k in before}
                self.set_controls(AeEnable=False, **fixed)


def bayer_means(
    frame: np.ndarray, roi: tuple[int, int, int, int], pattern: str = PATTERN, black: float = 0.0
) -> tuple[np.ndarray, float]:
    """Mean R, G, B of the pixels of each color in ``roi`` = (x, y, w, h), black level subtracted.

    G is the mean of both green sites. Also returns the highest raw value in the ROI, to detect saturation.
    """
    x, y, w, h = roi
    sites: dict[str, list[tuple[int, int]]] = {"R": [], "G": [], "B": []}
    for i, color in enumerate(pattern):
        sites[color].append((i // 2, i % 2))
    means = []
    for color in "RGB":
        # absolute pixel parity decides the color, so an ROI at an odd position works too
        values = np.concatenate(
            [frame[y + (py - y) % 2 : y + h : 2, x + (px - x) % 2 : x + w : 2].ravel() for py, px in sites[color]]
        )
        means.append(values.mean() - black)
    return np.array(means), float(frame[y : y + h, x : x + w].max())
