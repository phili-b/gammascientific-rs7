"""List presets, load each one for a few seconds and report its color."""

import sys
import time

from rs7 import RS7, Units

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found

with RS7(port) as rs7:
    for number, name in rs7.presets().items():
        rs7.recall_preset(number)
        x, y = rs7.chromaticity()
        print(f"{number:2d} {name:30s} {rs7.output(Units.PHOTOMETRIC):10.2f} lux/nits  x={x:.4f} y={y:.4f}")
        time.sleep(2)
