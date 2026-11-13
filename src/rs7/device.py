"""RS-7 ASCII command API (manual section 4) over a serial port."""
from __future__ import annotations

import contextlib
import enum
import time
from dataclasses import dataclass
from typing import Callable, Iterator, Optional

import serial

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUDRATE = 460800  # the unit can also be configured for 115200


class RS7Error(Exception):
    """The RS-7 answered a command with an error, e.g. ``?03 - unrecognized command``."""

    def __init__(self, code: str, message: str):
        super().__init__(f"?{code} - {message}")
        self.code = code
        self.message = message


class Units(enum.IntEnum):
    """What power and output numbers mean (the ``UNI`` command)."""

    RADIOMETRIC = 0  #: uW/cm2 (irradiance) or uW/cm2/sr (radiance)
    PHOTOMETRIC = 1  #: lux or nits
    INTERNAL = 2  #: 0-100 % of the photodiode output


class PeakType(enum.IntEnum):
    """How the wavelength of a channel is calculated (the ``PTY`` command)."""

    CENTROID = 0
    PEAK = 1
    CENTER = 2


@dataclass
class ChannelInfo:
    channel: int
    nominal_wavelength: float  #: nm, at the nominal power level (NPL)
    nominal_fwhm: float  #: nm
    wavelength: float  #: nm, at the present power; 0 if the channel is off
    fwhm: float  #: nm


class RS7:
    """One RS-7.

    ``port`` is a device name (``"/dev/ttyUSB0"``, ``"COM5"``, or any pyserial URL such as
    ``"socket://host:5000"``), or an already open serial object.

    >>> with RS7("/dev/ttyUSB0") as rs7:          # doctest: +SKIP
    ...     rs7.set_channel_power(5, 10)
    """

    def __init__(self, port=DEFAULT_PORT, baudrate: int = DEFAULT_BAUDRATE, timeout: float = 10.0):
        # timeout is per line: commands that wait for the output to settle can take seconds.
        #: Optional ``callback(command, reply, is_error)`` called for every command (used by the GUI).
        self.on_command: Optional[Callable[[str, str, bool], None]] = None
        if isinstance(port, str):
            port = serial.serial_for_url(port, baudrate=baudrate, timeout=timeout)
            # Opening the port can leave a stray character in the unit's input; flush it out.
            port.write(b"\r")
            time.sleep(0.2)
            port.reset_input_buffer()
        self._ser = port

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> "RS7":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- raw access ----------------------------------------------------------

    def command(self, cmd: str, *, multiline: bool = False) -> list[str]:
        """Send one command and return the reply lines (``[]`` for a plain "Ok").

        Use ``multiline=True`` for commands that answer with a list ended by an empty line.
        Raises :class:`RS7Error` if the unit reports an error and :class:`TimeoutError`
        if it does not answer.
        """
        try:
            lines = self._exchange(cmd, multiline)
        except RS7Error as e:
            self._log(cmd, str(e), True)
            raise
        self._log(cmd, "Ok" if not lines else lines[0] if len(lines) == 1 else f"{len(lines)} lines", False)
        return lines

    def _exchange(self, cmd: str, multiline: bool) -> list[str]:
        self._ser.reset_input_buffer()
        self._ser.write(cmd.encode("ascii") + b"\r")
        self._readline()  # every reply starts with a bare <CR><LF>
        first = self._readline()
        if first.startswith("?"):
            code, _, message = first[1:].partition(" - ")
            raise RS7Error(code, message)
        if first == "Ok":
            return []
        if not multiline:
            return [first]
        lines = []
        line = first
        while line != "":
            lines.append(line)
            line = self._readline()
        return lines

    def _readline(self) -> str:
        raw = self._ser.readline()
        if not raw.endswith(b"\n"):
            raise TimeoutError("no (complete) answer from the RS-7")
        return raw.decode("ascii", errors="replace").rstrip("\r\n")

    def _log(self, cmd: str, reply: str, is_error: bool) -> None:
        if self.on_command:
            self.on_command(cmd, reply, is_error)

    @contextlib.contextmanager
    def _in_units(self, units: Optional[Units]) -> Iterator[None]:
        """Temporarily switch the (global) units, then put them back."""
        old = self.units() if units is not None else None
        if units is not None and old != units:
            self.set_units(units)
        try:
            yield
        finally:
            if units is not None and old != units:
                self.set_units(old)

    # ---- identity and housekeeping --------------------------------------------

    def version(self) -> str:
        """Firmware version."""
        return self.command("VER")[0]

    def led_board_serial(self) -> str:
        return self.command("LSN")[0]

    def calibration_type(self) -> str:
        """``"R"`` radiant, ``"I"`` irradiant or ``"F"`` total flux source."""
        return self.command("CTY")[0]

    def calibration_info(self) -> str:
        return self.command("CAL")[0]

    def temperatures(self) -> tuple[float, float]:
        """TEC block temperatures in deg C: (LED board, wavelength monitor)."""
        led, monitor = self.command("TMP")[0].replace("C", "").split(",")
        return float(led), float(monitor)

    def alarm(self) -> str:
        """Present alarm, e.g. ``"?A1 - channel power limit"``; ``"NONE"`` if there is none."""
        try:
            return self.command("ALA")[0]
        except RS7Error as e:
            return str(e)

    def clear_alarm(self) -> None:
        self.command("ALAR")

    def soft_limit(self) -> int:
        """Maximum channel power in % of capability (default 90)."""
        return int(self.command("SLM")[0])

    def set_soft_limit(self, percent: int) -> None:
        self.command(f"SLM {int(percent)}")

    def feedback(self) -> bool:
        """Whether optical feedback holds the output steady."""
        return self.command("FBK")[0] == "1"

    def set_feedback(self, enabled: bool) -> None:
        self.command(f"FBK {int(enabled)}")

    def working_distance(self) -> int:
        """Irradiance-mode working distance in mm; 0 means radiance mode."""
        return int(self.command("IRR")[0])

    def set_working_distance(self, mm: int) -> None:
        self.command(f"IRR {int(mm)}")

    def peak_type(self) -> PeakType:
        return PeakType(int(self.command("PTY")[0]))

    def set_peak_type(self, peak_type: PeakType) -> None:
        self.command(f"PTY {int(peak_type)}")

    def observer(self) -> int:
        """CIE standard observer angle, 2 or 10 degrees."""
        return int(self.command("SOB")[0])

    def set_observer(self, degrees: int) -> None:
        self.command(f"SOB {degrees}")

    # ---- units -----------------------------------------------------------------

    def units(self) -> Units:
        return Units(int(self.command("UNI")[0]))

    def set_units(self, units: Units) -> None:
        """Choose what channel power and output numbers mean. This is a global setting."""
        self.command(f"UNI {int(units)}")

    # ---- channels ----------------------------------------------------------------

    def channel_power(self, channel: int) -> float:
        return float(self.command(f"SCP {channel}")[0])

    def channel_powers(self) -> dict[int, float]:
        """All channels that are on, as ``{channel: power}``."""
        lines = self.command("SCP 0", multiline=True)
        return {int(c): float(p) for c, p in (l.split(",") for l in lines)}

    def set_channel_power(self, channel: int, power: float) -> None:
        """Set one channel. Returns when the output has settled."""
        self.command(f"SCP {channel},{power}")

    def set_channel_powers(self, powers: dict[int, float]) -> None:
        """Set several channels at once; channels that are not listed are left alone."""
        self.command("SCP " + ",".join(f"{c},{p}" for c, p in powers.items()))

    def all_off(self) -> None:
        """Switch every channel off (this also forgets the spectrum)."""
        self.command("SCP 0,0")

    def channel_info(self) -> list[ChannelInfo]:
        """Wavelength and FWHM of every channel that is fitted."""
        out = []
        for line in self.command("LIN", multiline=True):
            channel, *values = line.split(",")
            values = [0.0 if v.strip().lower() == "nan" else float(v) for v in values]  # some units report nan
            if any(values):
                out.append(ChannelInfo(int(channel), *values))
        return out

    # ---- total output ---------------------------------------------------------------

    def output(self, units: Optional[Units] = None) -> float:
        """Total output. ``units`` temporarily overrides the current units."""
        with self._in_units(units):
            return float(self.command("OUT")[0])

    def set_output(self, level: float, units: Optional[Units] = None, keep_chromaticity: bool = False) -> None:
        """Set the total output, optionally touching up the spectrum to hold the chromaticity (``OUTC``)."""
        with self._in_units(units):
            self.command(f"{'OUTC' if keep_chromaticity else 'OUT'} {level}")

    def actual_output(self, units: Optional[Units] = None) -> float:
        """Output as sampled by the monitor photodiode (``OUTA``)."""
        with self._in_units(units):
            return float(self.command("OUTA")[0])

    def chromaticity(self) -> tuple[float, float]:
        """CIE 1931 x, y of the output."""
        x, y = self.command("OXY")[0].split(",")
        return float(x), float(y)

    def set_chromaticity(self, x: float, y: float) -> None:
        """Adjust the spectrum to the given CIE 1931 x, y (``CCS``)."""
        self.command(f"CCS {x},{y}")

    def tristimulus(self) -> tuple[float, float, float]:
        """CIE X, Y, Z of the output."""
        x, y, z = self.command("OXYZ")[0].split(",")
        return float(x), float(y), float(z)

    def cct(self) -> float:
        """Correlated color temperature of the output in kelvin."""
        return float(self.command("CCT")[0])

    # ---- spectra ------------------------------------------------------------------------

    def wavelength_range(self) -> tuple[int, int]:
        """Range in nm used for spectra and fits."""
        start, end = self.command("WLR")[0].split(",")
        return int(start), int(end)

    def set_wavelength_range(self, start: int, end: int) -> None:
        self.command(f"WLR {int(start)},{int(end)}")

    def spectrum(self, channel: int = 0) -> list[tuple[int, float]]:
        """Output spectrum as ``(nm, value)`` pairs at 1 nm steps over the wavelength range.

        ``channel=0`` is the combined output, otherwise the spectrum of one channel.
        """
        start, _ = self.wavelength_range()
        self.command("STM 1")
        lines = self.command(f"OSP {channel}", multiline=True)
        return [(start + i, float(v)) for i, v in enumerate(lines)]

    def target_spectrum(self) -> list[tuple[int, float]]:
        """The target spectrum as ``(nm, value)`` pairs."""
        start, _ = self.wavelength_range()
        self.command("STM 1")
        lines = self.command("TSP", multiline=True)
        return [(start + i, float(v)) for i, v in enumerate(lines)]

    def set_target_spectrum(self, values: list[float]) -> None:
        """Send a target spectrum: one value per nm over the wavelength range."""
        start, end = self.wavelength_range()
        if len(values) != end - start + 1:
            raise ValueError(f"need {end - start + 1} values for {start}-{end} nm, got {len(values)}")
        self.command("STM 0")
        self.command("TSP " + ",".join(f"{v:.9g}" for v in values))

    def fit(self, include_white: bool = False, at_max: bool = False) -> None:
        """Least-squares fit of the channels to the target spectrum.

        ``at_max`` scales the target so the output is as high as the soft limit allows.
        """
        self.command("FTS M" if at_max else "FTS W" if include_white else "FTS")

    def color_correct(self, xy: Optional[tuple[float, float]] = None) -> None:
        """Correct the output chromaticity to the target spectrum, or to ``xy``."""
        self.command(f"CCS {xy[0]},{xy[1]}" if xy else "CCS")

    def rms_error(self) -> float:
        """Spectral mismatch between output and target in % RMS."""
        return float(self.command("RPE")[0])

    # ---- presets -----------------------------------------------------------------------------

    def presets(self) -> dict[int, str]:
        """Stored presets as ``{number: name}``."""
        lines = self.command("PRE *", multiline=True)
        return {int(n): name for n, _, name in (l.partition(",") for l in lines)}

    def current_preset(self) -> str:
        """``"NONE"`` or ``"<number>,<name>"`` of the loaded preset."""
        return self.command("PRE")[0]

    def recall_preset(self, number: int) -> None:
        self.command(f"PRE {number}")

    def store_preset(self, number: int, name: str = "") -> None:
        """Store the present output as preset 0-99. Preset 0 is the power-on state."""
        self.command(f"SPR {number},{name}")

    def delete_preset(self, number: int) -> None:
        self.command(f"DPR {number}")
