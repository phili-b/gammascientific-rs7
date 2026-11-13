"""Make the RS-7 reproduce a CIE illuminant (default D65) at a given level and report the match.

Usage: uv run python examples/04_match_illuminant.py [PORT [TARGET [LEVEL [METHOD]]]]
TARGET: D65, A, FL2, LED-B3, D5000, 3000K, a CSV file ... (see `rs7 illuminants`); LEVEL in lux or cd/m2.
METHOD: local (default; solves the channel powers on the PC, measures every channel the first time, about 10 s)
or firmware (the RS-7's own fit).
"""

import sys

from rs7 import RS7, Units
from rs7.match import match

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found
TARGET = sys.argv[2] if len(sys.argv) > 2 else "D65"
LEVEL = float(sys.argv[3]) if len(sys.argv) > 3 else 500.0
METHOD = sys.argv[4] if len(sys.argv) > 4 else "local"

with RS7(port) as rs7:
    result = match(rs7, TARGET, level=LEVEL, units=Units.PHOTOMETRIC, method=METHOD)

out, target, cmp = result.output, result.target, result.comparison
print(f"target {TARGET}: CCT {target.cct:.0f} K, CRI Ra {target.cri_ra:.1f}")
print(f"output level  {out.photometric:.4g} (lux or cd/m2), {out.radiometric:.4g} radiometric")
print(f"output CCT    {out.cct:.0f} K, Duv {out.duv:+.4f}")
if out.xy and out.uv_prime:
    print(f"output xy     {out.xy[0]:.4f}, {out.xy[1]:.4f}   u'v' {out.uv_prime[0]:.4f}, {out.uv_prime[1]:.4f}")
print(f"CRI Ra {out.cri_ra:.1f}, R9 {out.cri_r[9]:.1f}; TM-30 Rf {out.tm30_rf:.1f}, Rg {out.tm30_rg:.1f}")
print(f"delta u'v' to target {cmp.delta_uv_prime:.4f} (0.001 is about one just-noticeable step)")
print(f"spectral RMS {cmp.spectral_rms:.1f} %")
if METHOD == "firmware":  # the RS-7's own error figure exists only for its own fit
    print(f"RS-7 RPE {result.unit_rms_error:.2f} %")
