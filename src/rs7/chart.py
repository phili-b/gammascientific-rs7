"""Where the patches of a ColorChecker are in the raw image, and a preview PNG to check it by eye.

The four corner patches are given by the pixel position of their centers. Every other patch center follows from a
projective mapping (homography) of the regular patch grid onto those four points, so a chart that is rotated or
seen at a slight angle still works. Patches are numbered 1-24 row by row from the top-left (dark skin) to the
bottom-right (black); white is 19.
"""

from __future__ import annotations

import json
import struct
import zlib
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .camera import RawCapture

CHART_FILE = Path.home() / ".rs7" / "chart.json"
# Approximate centers (x, y in raw pixels) of the corner patches: top-left, top-right, bottom-right, bottom-left.
DEFAULT_CORNERS = ((503.0, 603.0), (1310.0, 552.0), (1327.0, 1043.0), (535.0, 1063.0))


@dataclass
class ChartGeometry:
    corners: tuple[tuple[float, float], ...] = DEFAULT_CORNERS  #: centers of the corner patches: TL, TR, BR, BL
    rows: int = 4
    cols: int = 6
    roi_fraction: float = 0.35  #: side of the measured square, as a fraction of the patch pitch

    def homography(self) -> np.ndarray:
        """3x3 matrix taking grid coordinates (column, row) to image pixels."""
        grid = [(0, 0), (self.cols - 1, 0), (self.cols - 1, self.rows - 1), (0, self.rows - 1)]
        a, b = [], []
        for (u, v), (x, y) in zip(grid, self.corners, strict=True):
            a += [[u, v, 1, 0, 0, 0, -x * u, -x * v], [0, 0, 0, u, v, 1, -y * u, -y * v]]
            b += [x, y]
        h = np.linalg.solve(np.array(a, dtype=float), np.array(b, dtype=float))
        return np.append(h, 1.0).reshape(3, 3)

    def project(self, u, v) -> np.ndarray:
        """Image position (x, y) of grid position (u, v); arrays in, array (..., 2) out."""
        p = self.homography() @ np.stack([np.ravel(u), np.ravel(v), np.ones(np.size(u))])
        return (p[:2] / p[2]).T

    def patch_centers(self) -> np.ndarray:
        """(rows * cols, 2) pixel positions of the patch centers, in patch order."""
        v, u = np.divmod(np.arange(self.rows * self.cols), self.cols)
        return self.project(u, v)

    def patch_rois(self) -> list[tuple[int, int, int, int]]:
        """(x, y, w, h) of the square measured in every patch. Even size and position keep the Bayer phase."""
        v, u = np.divmod(np.arange(self.rows * self.cols), self.cols)
        pitch = (  # local patch size in pixels, from the neighbouring half-steps
            np.linalg.norm(self.project(u + 0.5, v) - self.project(u - 0.5, v), axis=1)
            + np.linalg.norm(self.project(u, v + 0.5) - self.project(u, v - 0.5), axis=1)
        ) / 2
        rois = []
        for (cx, cy), p in zip(self.patch_centers(), pitch, strict=True):
            size = max(2, 2 * round(self.roi_fraction * p / 2))
            rois.append((2 * round((cx - size / 2) / 2), 2 * round((cy - size / 2) / 2), size, size))
        return rois

    def save(self, path: str | Path = CHART_FILE) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: str | Path = CHART_FILE) -> ChartGeometry:
        """The saved geometry, or the default one if nothing was saved."""
        path = Path(path)
        if not path.is_file():
            return cls()
        d = json.loads(path.read_text())
        d["corners"] = tuple((float(x), float(y)) for x, y in d["corners"])
        return cls(**d)


def parse_corners(text: str) -> tuple[tuple[float, float], ...]:
    """``"x1,y1 x2,y2 x3,y3 x4,y4"`` -> corners."""
    try:
        corners = tuple((float(x), float(y)) for x, y in (p.split(",") for p in text.split()))
    except ValueError as e:
        raise ValueError(
            "use four x,y pairs: 'x1,y1 x2,y2 x3,y3 x4,y4' (top-left, top-right, bottom-right, bottom-left)"
        ) from e
    if len(corners) != 4:
        raise ValueError("give four corner centers: top-left, top-right, bottom-right, bottom-left")
    return corners


# ---- preview ---------------------------------------------------------------------------------------------


def write_png(path: str | Path, rgb: np.ndarray) -> None:
    """8-bit RGB image (height, width, 3) as a PNG file."""
    height, width, _ = rgb.shape
    rows = np.concatenate([np.zeros((height, 1), np.uint8), rgb.reshape(height, width * 3)], axis=1)  # filter 0

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows.tobytes(), 6))
    png += chunk(b"IEND", b"")
    Path(path).write_bytes(png)


def preview_png(capture: RawCapture, geometry: ChartGeometry, path: str | Path) -> None:
    """Write the image (each 2x2 Bayer cell is one pixel) with the measured squares drawn on it.

    The brightness is stretched so the brightest pixels are white, then a gamma of 2.2 is applied: it shows where
    things are, not true colors. Patch 1 has a filled marker in its top-left corner.
    """
    frame = capture.frames.mean(axis=0) - capture.black_level
    cells = {c: [] for c in "RGB"}
    for i, color in enumerate(capture.pattern):
        cells[color].append(frame[i // 2 :: 2, i % 2 :: 2])
    rgb = np.stack([np.mean(cells[c], axis=0) for c in "RGB"], axis=-1)
    rgb = np.clip(rgb / max(np.percentile(rgb, 99.5), 1.0), 0, 1) ** (1 / 2.2)
    image = (rgb * 255).astype(np.uint8)
    for n, (x, y, w, h) in enumerate(geometry.patch_rois()):
        x, y, w, h = x // 2, y // 2, w // 2, h // 2
        for sl in (image[y, x : x + w], image[y + h - 1, x : x + w], image[y : y + h, x], image[y : y + h, x + w - 1]):
            sl[:] = (255, 255, 0)
        if n == 0:
            image[y : y + 4, x : x + 4] = (255, 0, 0)
    write_png(path, image)
