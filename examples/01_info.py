"""Print what the RS-7 is and what it is doing, without changing anything."""

import sys

from rs7 import RS7, Units

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found

with RS7(port) as rs7:
    print("firmware     ", rs7.version())
    print("LED board    ", rs7.led_board_serial())
    print("calibration  ", rs7.calibration_type(), rs7.calibration_info())
    print("temperatures ", rs7.temperatures())
    print("alarm        ", rs7.alarm())
    print("output       ", rs7.output(Units.RADIOMETRIC), "radiometric,", rs7.output(Units.PHOTOMETRIC), "photometric")
    print("color        ", rs7.chromaticity(), rs7.cct(), "K")
    print("preset       ", rs7.current_preset())
    print("channels on  ", rs7.channel_powers())
    for c in rs7.channel_info():
        print(f"  channel {c.channel:2d}: {c.nominal_wavelength:7.1f} nm, FWHM {c.nominal_fwhm:5.1f} nm")
