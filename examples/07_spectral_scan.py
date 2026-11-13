"""Step through the narrow channels at equal photon flux, measure at each step and write the steps to a CSV file.

Usage: uv run python examples/07_spectral_scan.py [PORT [START END [PHOTONS]]]
START, END in nm (default 400 to 1000); PHOTONS in photons/s/cm2 (or /sr for a radiant calibration), default 1e13.
The unit's channel powers are put back at the end. Replace take_measurement() with your own measurement.
"""

import csv
import sys
from dataclasses import asdict

from rs7 import RS7
from rs7.mono import MonoStep, mono_scan

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found
START = int(sys.argv[2]) if len(sys.argv) > 3 else 400
END = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
PHOTONS = float(sys.argv[4]) if len(sys.argv) > 4 else 1e13
CSV_FILE = "spectral_scan.csv"


def take_measurement(step: MonoStep) -> None:
    """Placeholder: read your sensor or take a camera frame here. Use step.centroid_nm as the wavelength."""
    centroid = f"{step.centroid_nm:.1f}" if step.centroid_nm else "-"
    print(
        f"channel {step.channel:2d}  nominal {step.nominal_nm:6.1f} nm  centroid {centroid:>6} nm  "
        f"drive {step.power:7.3f} %  {step.photon_flux:.3e} photons/s/cm2" + ("  (at limit)" if step.at_limit else "")
    )


steps: list[MonoStep] = []
with RS7(port) as rs7:
    for step in mono_scan(rs7, START, END, photons=PHOTONS):
        take_measurement(step)
        steps.append(step)

if steps:
    with open(CSV_FILE, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(steps[0])))
        writer.writeheader()
        for step in steps:
            writer.writerow(asdict(step) | {"members": " ".join(map(str, step.members))})
    print(f"wrote {len(steps)} steps to {CSV_FILE}")
else:
    print("no narrow channels in that range")
