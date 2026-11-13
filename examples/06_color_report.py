"""Print the color quality of what the RS-7 is emitting now, without changing anything.

Usage: uv run python examples/06_color_report.py [PORT]
"""

import sys

from rs7 import RS7
from rs7.match import measure

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found

with RS7(port) as rs7:
    report = measure(rs7)  # read-only: spectrum in, no target

if report.xy is None or report.uv_prime is None:
    sys.exit("no light: switch some channels on first")

print(f"level        {report.photometric:.4g} (lux or cd/m2), {report.radiometric:.4g} radiometric")
print(f"CCT          {report.cct:.0f} K, Duv {report.duv:+.4f}" if report.cct else "CCT          -")
print(f"xy           {report.xy[0]:.4f}, {report.xy[1]:.4f}")
print(f"u'v'         {report.uv_prime[0]:.4f}, {report.uv_prime[1]:.4f}")
print(f"CRI Ra       {report.cri_ra:.1f}" if report.cri_ra is not None else "CRI Ra       -")
print("CRI R1-R14   " + " ".join(f"R{i}={v:.0f}" for i, v in sorted(report.cri_r.items())))
if report.tm30_rf is not None:
    print(f"TM-30        Rf {report.tm30_rf:.1f}, Rg {report.tm30_rg:.1f}")
print(f"peak {report.peak_nm} nm, centroid {report.centroid_nm:.1f} nm")
