"""Save the state of the RS-7 to a JSON file and put it back.

Usage: uv run python examples/08_snapshot.py [PORT [FILE]]
Reading the state changes nothing; restoring sets the same channel powers, units and wavelength range again.
Do your experiment between the two steps (a snapshot is an exact way to leave the unit as you found it).
"""

import sys

from rs7 import RS7
from rs7.snapshot import Snapshot, restore, take

port = sys.argv[1] if len(sys.argv) > 1 else None  # None: first RS-7 found
FILE = sys.argv[2] if len(sys.argv) > 2 else "rs7-state.json"

with RS7(port) as rs7:
    snapshot = take(rs7, note="saved by examples/08_snapshot.py")
    snapshot.save(FILE)
    print(
        f"saved {len(snapshot.powers)} channels to {FILE}: {snapshot.photometric:.4g} (lux or cd/m2), xy {snapshot.xy}"
    )

    # ... change the unit here: channel powers, a match, a scan ...

    saved = Snapshot.load(FILE)
    restore(rs7, saved)  # raises RS7Error if the file is from another LED board
    print(f"restored the state of {saved.time}")
