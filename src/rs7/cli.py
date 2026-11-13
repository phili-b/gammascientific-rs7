"""``rs7`` command line: control an RS-7 from a terminal."""

from __future__ import annotations

import csv
import enum
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import serial
import typer
from rich.console import Console
from rich.table import Table
from serial.tools import list_ports

from . import __version__
from .device import FTDI_IDS, RS7, PortNotFoundError, RS7Error, Units
from .spectrum import blackbody, cct_to_xy, load_csv, resample

app = typer.Typer(help="Control a Gamma Scientific SpectralLED RS-7 light source.", no_args_is_help=True)
preset_app = typer.Typer(help="List, load, store and delete presets.", no_args_is_help=True)
app.add_typer(preset_app, name="preset")
console = Console()
err = Console(stderr=True)


class UnitName(str, enum.Enum):
    radiometric = "radiometric"
    photometric = "photometric"
    internal = "internal"

    @property
    def units(self) -> Units:
        return Units[self.name.upper()]


class State:
    port: str | None = None
    baudrate: int = 460800
    verbose: bool = False


state = State()

PortOption = Annotated[
    str | None,
    typer.Option("--port", "-p", envvar="RS7_PORT", help="Serial port or pyserial URL; default: first RS-7 found."),
]
UnitsOption = Annotated[UnitName, typer.Option("--units", "-u", help="Units of the numbers.")]


@app.callback()
def main(
    port: PortOption = None,
    baudrate: Annotated[int, typer.Option("--baud", help="Baud rate (460800, or 115200 if configured).")] = 460800,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show every command and reply.")] = False,
):
    state.port, state.baudrate, state.verbose = port, baudrate, verbose


@contextmanager
def connect():
    """Open the RS-7, turning connection and device errors into a clean message and exit code."""
    try:
        rs7 = RS7(state.port, baudrate=state.baudrate)
    except (PortNotFoundError, serial.SerialException, OSError) as e:
        err.print(f"[red]Cannot open the RS-7:[/] {e}")
        raise typer.Exit(2) from e
    if state.verbose:
        rs7.on_command = lambda c, r, e: err.print(f"[dim]> {c}[/]  {'[red]' if e else ''}{r}")
    try:
        yield rs7
    except (RS7Error, TimeoutError) as e:
        err.print(f"[red]RS-7 error:[/] {e}")
        raise typer.Exit(1) from e
    finally:
        rs7.close()


# ---- discovery and status ----------------------------------------------------------------------


@app.command()
def version():
    """Show the package version."""
    console.print(f"gammascientific-rs7 {__version__}")


@app.command()
def ports():
    """List serial ports and mark the ones that look like an RS-7."""
    table = Table("Port", "Description", "RS-7?")
    for p in list_ports.comports():
        table.add_row(p.device, p.description, "[green]yes[/]" if (p.vid, p.pid) in FTDI_IDS else "")
    console.print(table)


@app.command()
def info():
    """Show what the unit is and what it is doing (changes nothing)."""
    with connect() as r:
        table = Table(show_header=False, box=None)
        table.add_row("Firmware", r.version())
        table.add_row("LED board", r.led_board_serial())
        table.add_row("Calibration", f"{r.calibration_type()}  {r.calibration_info()}")
        led, monitor = r.temperatures()
        table.add_row("Temperatures", f"LED {led:.2f} C, monitor {monitor:.2f} C")
        alarm = r.alarm()
        table.add_row("Alarm", alarm if alarm == "NONE" else f"[red]{alarm}[/]")
        table.add_row("Soft limit", f"{r.soft_limit()} %")
        table.add_row(
            "Output",
            f"{r.output(Units.INTERNAL):.3f} %   {r.output(Units.RADIOMETRIC):.4g} radiometric   "
            f"{r.output(Units.PHOTOMETRIC):.4g} photometric",
        )
        try:
            x, y = r.chromaticity()
            table.add_row("Color", f"x={x:.4f} y={y:.4f}  {r.cct():.0f} K")
        except RS7Error:
            table.add_row("Color", "(all channels off)")
        table.add_row("Preset", r.current_preset())
        console.print(table)


@app.command()
def channels(
    units: UnitsOption = UnitName.internal,
    all_: Annotated[bool, typer.Option("--all", "-a", help="Also list channels that are off.")] = False,
):
    """List the channels with wavelength, FWHM and power."""
    with connect() as r:
        infos = r.channel_info()
        with r.using_units(units.units):
            powers = r.channel_powers()
    table = Table("Channel", "Wavelength (nm)", "FWHM (nm)", f"Power ({units.value})")
    for c in sorted(infos, key=lambda c: c.nominal_wavelength):
        p = powers.get(c.channel, 0.0)
        if all_ or p:
            table.add_row(str(c.channel), f"{c.nominal_wavelength:.1f}", f"{c.nominal_fwhm:.1f}", f"{p:.4g}")
    console.print(table)


# ---- changing the output -------------------------------------------------------------------------


@app.command("set")
def set_channels(
    pairs: Annotated[list[str], typer.Argument(help="CHANNEL=POWER pairs, e.g. 5=10 7=2.5")],
    units: UnitsOption = UnitName.internal,
    exclusive: Annotated[bool, typer.Option("--only", help="Switch all other channels off first.")] = False,
):
    """Set channel powers."""
    try:
        powers = {int(c): float(p) for c, p in (pair.split("=") for pair in pairs)}
    except ValueError as e:
        raise typer.BadParameter("use CHANNEL=POWER, e.g. 5=10") from e
    with connect() as r, r.using_units(units.units):
        if exclusive:
            r.all_off()
        r.set_channel_powers(powers)
    console.print(f"set {', '.join(f'{c}={p:g}' for c, p in powers.items())} ({units.value})")


@app.command()
def off():
    """Switch every channel off."""
    with connect() as r:
        r.all_off()
    console.print("all channels off")


@app.command()
def output(
    level: Annotated[float | None, typer.Argument(help="New total output; leave out to read it.")] = None,
    units: UnitsOption = UnitName.photometric,
    keep_color: Annotated[bool, typer.Option("--keep-color", help="Hold the chromaticity (OUTC).")] = False,
):
    """Read or set the total output."""
    with connect() as r:
        if level is not None:
            r.set_output(level, units.units, keep_chromaticity=keep_color)
        console.print(f"{r.output(units.units):.6g} ({units.value})")


@app.command()
def color(
    xy: Annotated[list[float] | None, typer.Argument(help="CIE 1931 x y to set; leave out to read.")] = None,
    cct: Annotated[
        float | None, typer.Option("--cct", help="Set the color to this black-body temperature (K).")
    ] = None,
):
    """Read or set the chromaticity."""
    with connect() as r:
        if cct is not None:
            r.set_chromaticity(*(round(v, 4) for v in cct_to_xy(cct)))
        elif xy:
            if len(xy) != 2:
                raise typer.BadParameter("give two numbers: x y")
            r.set_chromaticity(xy[0], xy[1])
        x, y = r.chromaticity()
        console.print(f"x={x:.4f} y={y:.4f}  CCT {r.cct():.0f} K")


@app.command()
def fit(
    source: Annotated[str, typer.Argument(help="Black-body temperature in K (e.g. 3000) or a CSV file (nm, value).")],
    start: Annotated[int, typer.Option(help="Fit range start (nm).")] = 380,
    end: Annotated[int, typer.Option(help="Fit range end (nm).")] = 780,
    scale: Annotated[float, typer.Option(help="Multiply the target by this.")] = 1.0,
    at_max: Annotated[bool, typer.Option("--max", help="Fit at the highest output the soft limit allows.")] = False,
    white: Annotated[bool, typer.Option("--white", help="Include white channels.")] = False,
    correct: Annotated[bool, typer.Option(help="Correct the chromaticity after the fit.")] = True,
):
    """Fit the output to a target spectrum."""
    if Path(source).is_file():
        target = resample(load_csv(source), start, end)
    else:
        try:
            target = blackbody(float(source), start, end)
        except ValueError as e:
            raise typer.BadParameter(f"{source} is neither a file nor a temperature") from e
    with connect() as r:
        r.set_wavelength_range(start, end)
        r.set_target_spectrum([v * scale for v in target])
        r.fit(include_white=white, at_max=at_max)
        if correct:
            r.color_correct()
        x, y = r.chromaticity()
        console.print(f"RMS error {r.rms_error():.2f} %, x={x:.4f} y={y:.4f}, CCT {r.cct():.0f} K")


# ---- spectra, presets, raw ------------------------------------------------------------------------


@app.command()
def spectrum(
    channel: Annotated[int, typer.Option("--channel", "-c", help="One channel; 0 = the total output.")] = 0,
    start: Annotated[int, typer.Option(help="Start (nm).")] = 380,
    end: Annotated[int, typer.Option(help="End (nm).")] = 780,
    out: Annotated[Path | None, typer.Option("--csv", help="Write nm,value to this CSV file.")] = None,
):
    """Read the output spectrum (1 nm steps)."""
    with connect() as r:
        r.set_wavelength_range(start, end)
        data = r.spectrum(channel)
    if out:
        with out.open("w", newline="") as f:
            csv.writer(f).writerows([("nm", "value"), *data])
        console.print(f"wrote {len(data)} points to {out}")
        return
    peak = max((v for _, v in data), default=0) or 1.0
    for nm, v in data[:: max(1, len(data) // 40)]:
        console.print(f"{nm:5d} nm {v:12.5g} [cyan]{'#' * round(v / peak * 50)}[/]")


@preset_app.command("list")
def preset_list():
    """List stored presets."""
    with connect() as r:
        presets, current = r.presets(), r.current_preset()
    table = Table("#", "Name")
    for n, name in presets.items():
        mark = " [green](loaded)[/]" if current.split(",")[0] == str(n) else ""
        table.add_row(str(n), name + mark)
    console.print(table)


@preset_app.command("load")
def preset_load(number: int):
    """Load a preset."""
    with connect() as r:
        r.recall_preset(number)
    console.print(f"preset {number} loaded")


@preset_app.command("store")
def preset_store(number: int, name: Annotated[str, typer.Argument(help="Description")] = ""):
    """Store the present output as a preset (preset 0 is the power-on state)."""
    with connect() as r:
        r.store_preset(number, name)
    console.print(f"stored as preset {number}")


@preset_app.command("delete")
def preset_delete(number: int, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask.")] = False):
    """Delete a preset."""
    if not yes:
        typer.confirm(f"Delete preset {number}?", abort=True)
    with connect() as r:
        r.delete_preset(number)
    console.print(f"preset {number} deleted")


@app.command()
def alarm(clear: Annotated[bool, typer.Option("--clear", help="Clear the alarm.")] = False):
    """Show (or clear) the alarm state."""
    with connect() as r:
        if clear:
            r.clear_alarm()
        console.print(r.alarm())


@app.command()
def send(
    commands: Annotated[list[str], typer.Argument(help="Raw RS-7 commands, e.g. VER 'SCP 5'")],
    multiline: Annotated[
        bool, typer.Option("--list", "-l", help="The reply is a list ended by an empty line.")
    ] = False,
):
    """Send raw commands (see the manual, section 4) and print the replies."""
    with connect() as r:
        for c in commands:
            lines = r.command(c, multiline=multiline)
            console.print(f"[dim]> {c}[/]")
            console.print("\n".join(lines) if lines else "Ok", markup=False)


# ---- bridge and GUI --------------------------------------------------------------------------------


@app.command()
def bridge(listen: Annotated[int, typer.Option(help="TCP port to listen on.")] = 5000):
    """Share the RS-7 over TCP (no authentication; trusted networks only)."""
    from .bridge import serve
    from .device import find_port

    try:
        serve(state.port or find_port(), listen, state.baudrate, log=console.print)
    except KeyboardInterrupt:
        pass
    except (PortNotFoundError, serial.SerialException, OSError) as e:
        err.print(f"[red]{e}[/]")
        raise typer.Exit(2) from e


@app.command()
def gui():
    """Open the desktop GUI (needs the 'gui' extra: PySide6)."""
    try:
        from .gui import main as gui_main
    except ImportError as e:
        err.print(f"[red]The GUI needs PySide6:[/] install with  uv tool install 'gammascientific-rs7[gui]'  ({e})")
        raise typer.Exit(2) from e
    gui_main(state.port)
