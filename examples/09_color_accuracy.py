"""Color accuracy of a camera under D65 and A, from a ColorChecker lit by the RS-7.

Usage: uv run python examples/09_color_accuracy.py [PORT [CAMERA_URL]]
CAMERA_URL is the camera service (picam-web) on the Raspberry Pi, default http://10.61.100.206.

WARNING: this changes the light. The RS-7 makes D65 and then A at its present output level, and the camera
exposure is changed. The RS-7 state and the camera controls are restored afterwards, also if something fails, but
do not run it while something else depends on the light. The chart must be lit by the RS-7 only, and its position
must be right: check it first with `rs7 chart --png chart.png` (the position is read from ~/.rs7/chart.json, or
the default of the lab setup is used).
"""

import sys

from rs7 import RS7
from rs7.camera import DEFAULT_URL, PicamWeb
from rs7.chart import ChartGeometry
from rs7.colorcheck import color_accuracy

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found
camera_url = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_URL

camera = PicamWeb(camera_url)
geometry = ChartGeometry.load()

with RS7(port) as rs7:
    result = color_accuracy(rs7, camera, geometry, ["D65", "A"], progress=print)

print()
print("matrix fitted and scored under each light (CIE DE2000)")
for res in result.illuminants:
    acc = res.accuracy
    excluded = int((~acc.used).sum())
    cct = f"{res.cct:.0f} K" if res.cct else "-"
    print(
        f"{res.illuminant:<8} {cct:>7}  exposure {res.exposure_us / 1000:5.1f} ms  "
        f"mean {acc.mean:5.2f}  median {acc.median:5.2f}  max {acc.max:5.2f}"
        + (f"  ({excluded} patches excluded)" if excluded else "")
    )

for cross in result.cross:
    acc = cross.accuracy
    print(
        f"{cross.illuminant:<8} with the matrix of {cross.fitted_under}, white-balanced:  "
        f"mean {acc.mean:5.2f}  median {acc.median:5.2f}  max {acc.max:5.2f}"
    )
