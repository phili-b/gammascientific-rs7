"""Sweep the total illuminance of the present spectrum, keeping its color, e.g. for a sensor linearity test."""
import sys
import time

from rs7 import RS7, Units

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
LEVELS = [10, 20, 50, 100, 200, 500]  # lux (or nits)

with RS7(port) as rs7:
    start = rs7.output(Units.PHOTOMETRIC)
    try:
        for level in LEVELS:
            rs7.set_output(level, Units.PHOTOMETRIC, keep_chromaticity=True)
            measured = rs7.actual_output(Units.PHOTOMETRIC)
            print(f"set {level:6.1f}  measured {measured:8.2f}  xy {rs7.chromaticity()}")
            time.sleep(1)  # take your measurement here
    finally:
        rs7.set_output(start, Units.PHOTOMETRIC)
