"""Make the RS-7 imitate a black body (default 3000 K), as bright as possible, and report the match."""
import sys

from rs7 import RS7
from rs7.spectrum import blackbody, cct_to_xy

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
CCT = float(sys.argv[2]) if len(sys.argv) > 2 else 3000.0
START, END = 400, 700

with RS7(port) as rs7:
    rs7.set_wavelength_range(START, END)
    rs7.set_target_spectrum(blackbody(CCT, START, END))
    rs7.fit(at_max=True)          # scales the target to the highest output the soft limit allows
    rs7.color_correct()           # then match its chromaticity exactly
    print(f"target CCT {CCT:.0f} K, xy {cct_to_xy(CCT)}")
    print(f"output CCT {rs7.cct():.0f} K, xy {rs7.chromaticity()}")
    print(f"spectral RMS error {rs7.rms_error():.2f} %")
