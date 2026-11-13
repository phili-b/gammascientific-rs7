"""Save the unit's state (channel powers and the spectrum they give) to a JSON file, and put it back later."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .colorimetry import analyze
from .device import RS7, RS7Error, Units


@dataclass
class Snapshot:
    time: str  #: ISO 8601, local time
    board: str  #: LED board serial number
    units: int  #: the unit's units setting (UNI) at the time
    wavelength_range: tuple[int, int]
    powers: dict[int, float]  #: channel powers in % (internal units)
    spectrum: list[tuple[int, float]]  #: 360-830 nm, uW/cm2/nm (or /sr)
    photometric: float
    xy: tuple[float, float] | None
    cct: float | None
    note: str = ""

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=1))

    @classmethod
    def load(cls, path: str | Path) -> Snapshot:
        d = json.loads(Path(path).read_text())
        d["powers"] = {int(k): v for k, v in d["powers"].items()}
        d["spectrum"] = [tuple(p) for p in d["spectrum"]]
        d["wavelength_range"] = tuple(d["wavelength_range"])
        d["xy"] = tuple(d["xy"]) if d["xy"] else None
        return cls(**d)


def take(rs7: RS7, note: str = "") -> Snapshot:
    """Read the present state. Changes nothing (the wavelength range is put back)."""
    units = int(rs7.units())
    wlr = rs7.wavelength_range()
    with rs7.using_units(Units.INTERNAL):
        powers = rs7.channel_powers()
    spectrum = rs7.spectrum(0, 360, 830)
    rs7.set_wavelength_range(*wlr)
    a = analyze(spectrum, quality=False)
    return Snapshot(
        time=datetime.now().isoformat(timespec="seconds"),
        board=rs7.led_board_serial(),
        units=units,
        wavelength_range=wlr,
        powers=powers,
        spectrum=spectrum,
        photometric=a.photometric,
        xy=a.xy,
        cct=a.cct,
        note=note,
    )


def restore(rs7: RS7, snapshot: Snapshot) -> None:
    """Set the channel powers, units and wavelength range of ``snapshot``."""
    board = rs7.led_board_serial()
    if snapshot.board and board != snapshot.board:
        raise RS7Error("--", f"snapshot is from LED board {snapshot.board}, this unit has {board}")
    rs7.set_units(Units.INTERNAL)
    rs7.all_off()
    if snapshot.powers:
        rs7.set_channel_powers(snapshot.powers)
    rs7.set_units(Units(snapshot.units))
    rs7.set_wavelength_range(*snapshot.wavelength_range)
