"""Switch each channel on in turn (by wavelength) and measure the output, then restore the spectrum."""
import sys

from rs7 import RS7, Units

port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
POWER = 20  # % of each channel's maximum

with RS7(port) as rs7:
    rs7.set_units(Units.INTERNAL)
    before = rs7.channel_powers()
    try:
        for c in sorted(rs7.channel_info(), key=lambda c: c.nominal_wavelength):
            rs7.all_off()
            rs7.set_channel_power(c.channel, POWER)
            uw = rs7.output(Units.RADIOMETRIC)
            print(f"channel {c.channel:2d} {c.nominal_wavelength:7.1f} nm: {uw:9.3f} radiometric units")
    finally:
        rs7.all_off()
        if before:
            rs7.set_channel_powers(before)
