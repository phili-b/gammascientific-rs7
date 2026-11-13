"""``rs7`` command line: control an RS-7 from a terminal."""

from __future__ import annotations

import csv
import enum
import io
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import serial
import typer
from rich.console import Console
from rich.table import Table
from serial.tools import list_ports

from . import __version__
from .camera import DEFAULT_URL as DEFAULT_CAMERA
from .chart import CHART_FILE
from .device import FTDI_IDS, RS7, PortNotFoundError, RS7Error, Units
from .spectrum import cct_to_xy

# A console or pipe in cp1252 cannot show the delta of Δu'v' and ΔE: print "?" there instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    if isinstance(_stream, io.TextIOWrapper):
        _stream.reconfigure(errors="replace")

app = typer.Typer(help="Control a Gamma Scientific SpectralLED RS-7 light source.", no_args_is_help=True)
preset_app = typer.Typer(help="List, load, store and delete presets.", no_args_is_help=True)
app.add_typer(preset_app, name="preset")
console = Console()
err = Console(stderr=True)


class UnitName(enum.StrEnum):
    radiometric = "radiometric"
    photometric = "photometric"
    internal = "internal"

    @property
    def units(self) -> Units:
        return Units[self.name.upper()]


class Method(enum.StrEnum):
    local = "local"
    firmware = "firmware"


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
def illuminants():
    """List the target spectra that `match` and `measure` accept."""
    from .colorimetry import analyze
    from .illuminants import available, target_spectrum

    table = Table("Name", "CCT (K)", "Duv", "x", "y", "CRI Ra", title="CIE illuminant library")
    for name in available():
        try:
            rep = analyze([(360 + i, v) for i, v in enumerate(target_spectrum(name, 360, 830))])
        except ValueError:
            continue
        x, y = rep.xy or (0, 0)
        table.add_row(
            name, _fmt(rep.cct, ".0f"), _fmt(rep.duv, "+.4f"), f"{x:.4f}", f"{y:.4f}", _fmt(rep.cri_ra, ".1f")
        )
    console.print(table)
    console.print(
        "Also: [bold]D<CCT>[/] CIE daylight at any 4000-25000 K (e.g. D5000), "
        "[bold]<T>K[/] black body (e.g. 3000K), or a CSV file (nm, value)."
    )


@app.command()
def match(
    target: Annotated[
        str, typer.Argument(help="D65, A, FL2, LED-B3, D5000, 3000K, a CSV file... (see `rs7 illuminants`)")
    ],
    level: Annotated[
        float | None, typer.Option("--level", "-l", help="Total output to reach; default: keep the present level.")
    ] = None,
    units: Annotated[UnitName, typer.Option("--units", "-u", help="Units of --level.")] = UnitName.photometric,
    at_max: Annotated[bool, typer.Option("--max", help="As bright as the soft limit allows.")] = False,
    start: Annotated[int, typer.Option(help="Fit range start (nm).")] = 380,
    end: Annotated[int, typer.Option(help="Fit range end (nm).")] = 780,
    white: Annotated[bool, typer.Option("--white", help="Also use the white channels.")] = False,
    correct: Annotated[bool, typer.Option(help="Correct the color exactly after the spectral fit.")] = True,
    out: Annotated[Path | None, typer.Option("--csv", help="Write nm, target, output to this CSV file.")] = None,
    method: Annotated[
        Method,
        typer.Option("--method", "-m", help="local: solve on the PC (better spectra); firmware: the RS-7's fit."),
    ] = Method.local,
):
    """Make the RS-7 reproduce a target spectrum (e.g. D65 at 500 lux) and report the match."""
    from .match import match as do_match

    with connect() as r:
        try:
            result = do_match(r, target, level, units.units, at_max, start, end, white, correct, method.value)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        labels = _unit_labels(r)
    _print_match(result, labels)
    if out:
        _write_pair_csv(out, result.target_spectrum, result.output_spectrum)


@app.command()
def measure(
    target: Annotated[
        str | None, typer.Option("--target", "-t", help="Also compare with this target (e.g. D65).")
    ] = None,
    start: Annotated[int, typer.Option(help="Comparison range start (nm).")] = 380,
    end: Annotated[int, typer.Option(help="Comparison range end (nm).")] = 780,
):
    """Color quality of the present output: CCT, Duv, xy, u'v', CRI, TM-30 (changes nothing)."""
    from .match import measure as do_measure
    from .match import measure_against

    with connect() as r:
        labels = _unit_labels(r)
        if target is None:
            _print_reports([("Output", do_measure(r))], labels)
            return
        try:
            result = measure_against(r, target, start, end)
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
    _print_match(result, labels)


def _fmt(v, spec: str, none: str = "-") -> str:
    return none if v is None else format(v, spec)


def _unit_labels(r: RS7) -> tuple[str, str]:
    """(radiometric, photometric) unit names for this unit's calibration."""
    irradiant = r.working_distance() > 0 or r.calibration_type() == "I"
    return ("uW/cm2", "lux") if irradiant else ("uW/cm2/sr", "cd/m2")


def _print_reports(columns, labels: tuple[str, str], extra=None):
    rad, phot = labels
    table = Table("", *(name for name, _ in columns), *(["Difference"] if extra else []))
    rows = [
        (f"Level ({phot})", lambda c: _fmt(c.photometric, ".4g")),
        (f"Radiometric ({rad})", lambda c: _fmt(c.radiometric, ".4g")),
        ("CCT (K)", lambda c: _fmt(c.cct, ".0f")),
        ("Duv", lambda c: _fmt(c.duv, "+.4f")),
        ("x, y", lambda c: f"{c.xy[0]:.4f}, {c.xy[1]:.4f}" if c.xy else "-"),
        ("u', v'", lambda c: f"{c.uv_prime[0]:.4f}, {c.uv_prime[1]:.4f}" if c.uv_prime else "-"),
        ("CRI Ra", lambda c: _fmt(c.cri_ra, ".1f")),
        ("CRI R9 (red)", lambda c: _fmt(c.cri_r.get(9), ".1f")),
        ("TM-30 Rf", lambda c: _fmt(c.tm30_rf, ".1f")),
        ("TM-30 Rg", lambda c: _fmt(c.tm30_rg, ".1f")),
        ("Centroid (nm)", lambda c: _fmt(c.centroid_nm, ".1f")),
    ]
    for label, get in rows:
        table.add_row(label, *(get(c) for _, c in columns), *([extra.get(label, "")] if extra else []))
    console.print(table)


def _print_match(result, labels):
    from .illuminants import describe

    cmp = result.comparison
    duv = cmp.delta_uv_prime
    color = "green" if duv is not None and duv < 0.001 else "yellow" if duv is not None and duv < 0.005 else "red"
    extra = {
        "CCT (K)": _fmt(cmp.delta_cct, "+.0f"),
        "Duv": _fmt(cmp.delta_duv, "+.4f"),
        "u', v'": f"[{color}]Δu'v' {_fmt(duv, '.4f')}[/]",
        f"Level ({labels[1]})": _fmt(cmp.level_ratio, ".3f", "") + " x" if cmp.level_ratio else "",
    }
    console.print(f"[bold]{describe(result.target_name)}[/]")
    _print_reports([("Target", result.target), ("Output", result.output)], labels, extra)
    rms = f"spectral RMS {_fmt(cmp.spectral_rms, '.1f')} %"
    if result.unit_rms_error == result.unit_rms_error:  # not NaN
        rms += f" (RS-7 RPE {result.unit_rms_error:.2f} %)"
    console.print(rms + ";  Δu'v' < 0.001 is about one just-noticeable color step")


def _write_pair_csv(path: Path, target, output):
    t, o = dict(target), dict(output)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nm", "target", "output"])
        for nm in sorted(set(t) | set(o)):
            w.writerow([nm, t.get(nm, ""), o.get(nm, "")])
    console.print(f"wrote {path}")


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


# ---- local fit basis, monochromatic steps ------------------------------------------------------------


@app.command()
def basis(remeasure: Annotated[bool, typer.Option("--remeasure", help="Measure again (about 10 s).")] = False):
    """Show (or measure) the per-channel spectra the local fit uses; cached per LED board in ~/.rs7."""
    from .optimize import load_basis
    from .spectrum import centroid

    with connect() as r:
        b = load_basis(r, remeasure, progress=lambda i, n: err.print(f"measuring channel {i}/{n}", end="\r"))
    table = Table(
        "Group", "Channels", "Centroid (nm)", "Peak per 1 %", title=f"Board {b.board}, measured at {b.power:g} %"
    )
    for lead, spec in sorted(b.spectra.items(), key=lambda kv: centroid(_points(b, kv[1])) or 0):
        pts = _points(b, spec)
        table.add_row(str(lead), ",".join(map(str, b.groups[lead])), _fmt(centroid(pts), ".1f"), f"{max(spec):.4g}")
    console.print(table)


def _points(b, spec):
    return [(b.start + i, v) for i, v in enumerate(spec)]


FluxOptions = tuple[float | None, float | None, float | None]


def _one_flux(photons, radiometric, power) -> FluxOptions:
    if sum(x is not None for x in (photons, radiometric, power)) > 1:
        raise typer.BadParameter("give only one of --photons, --radiometric, --power")
    if photons is None and radiometric is None and power is None:
        power = 50.0
    return photons, radiometric, power


PhotonsOption = Annotated[float | None, typer.Option("--photons", help="Photon flux, photons/s/cm2 (or /sr).")]
RadiometricOption = Annotated[float | None, typer.Option("--radiometric", help="Radiant power, uW/cm2 (or /sr).")]
PowerOption = Annotated[float | None, typer.Option("--power", help="Drive level, % (default 50 if none given).")]


def _mono_table(title: str) -> Table:
    return Table(
        "Channel", "Nominal (nm)", "Centroid", "Peak", "FWHM", "Power %", "Radiometric", "Photons/s/cm2", title=title
    )


def _mono_row(table: Table, s) -> None:
    table.add_row(
        ",".join(map(str, s.members)),
        f"{s.nominal_nm:.1f}",
        _fmt(s.centroid_nm, ".1f"),
        _fmt(s.peak_nm, ".0f"),
        _fmt(s.fwhm_nm, ".1f"),
        f"{s.power:.3f}" + (" [red](limit)[/]" if s.at_limit else ""),
        f"{s.radiometric:.4g}",
        f"{s.photon_flux:.4e}",
    )


@app.command()
def mono(
    wavelength: Annotated[float, typer.Argument(help="Wavelength (nm); the narrow channel closest to it is used.")],
    photons: PhotonsOption = None,
    radiometric: RadiometricOption = None,
    power: PowerOption = None,
):
    """Switch on one channel only, closest to WAVELENGTH, at a photon flux, radiant power or drive level."""
    from .mono import mono_channels, set_mono

    photons, radiometric, power = _one_flux(photons, radiometric, power)
    with connect() as r:
        channels = mono_channels(r)
        lead = min(channels, key=lambda c: abs(c[2] - wavelength))[0]
        step = set_mono(r, lead, photons, radiometric, power)
    table = _mono_table("Monochromatic output")
    _mono_row(table, step)
    console.print(table)


@app.command()
def scan(
    start: Annotated[int, typer.Option(help="From (nm).")] = 360,
    end: Annotated[int, typer.Option(help="To (nm).")] = 1100,
    photons: PhotonsOption = None,
    radiometric: RadiometricOption = None,
    power: PowerOption = None,
    dwell: Annotated[float, typer.Option(help="Seconds to stay on each channel.")] = 1.0,
    out: Annotated[Path | None, typer.Option("--csv", help="Write the steps to this CSV file.")] = None,
):
    """Step through the narrow channels by wavelength, one at a time (e.g. for spectral response / QE).

    The unit's original state is restored at the end (also on Ctrl+C).
    """
    import time

    from .mono import mono_scan

    photons, radiometric, power = _one_flux(photons, radiometric, power)
    table = _mono_table(f"Scan {start}-{end} nm")
    steps = []
    with connect() as r:
        try:
            for step in mono_scan(r, start, end, photons, radiometric, power):
                steps.append(step)
                console.print(
                    f"{step.nominal_nm:7.1f} nm  channel {step.channel:2d}  {step.power:7.3f} %  "
                    f"{step.photon_flux:.3e} photons/s/cm2" + ("  (at limit)" if step.at_limit else "")
                )
                time.sleep(dwell)
        except KeyboardInterrupt:
            err.print("stopped; original state restored")
    for step in steps:
        _mono_row(table, step)
    console.print(table)
    if out:
        _write_rows(out, [vars(s) | {"members": " ".join(map(str, s.members))} for s in steps])


# ---- characterizing the unit --------------------------------------------------------------------------


@app.command()
def dimming(
    channel: Annotated[
        int | None, typer.Option("--channel", "-c", help="One channel (others off) instead of the whole spectrum.")
    ] = None,
    levels: Annotated[str, typer.Option(help="Comma-separated levels in %.")] = "1,2,5,10,20,50,100",
    out: Annotated[Path | None, typer.Option("--csv", help="Write the rows to this CSV file.")] = None,
):
    """How the output, color and wavelength change with the drive level. Restores the unit afterwards."""
    from .characterize import dimming as run

    values = [float(v) for v in levels.split(",")]
    rows = []
    with connect() as r:
        for row in run(r, values, channel):
            rows.append(row)
            console.print("  ".join(f"{k} {_fmt(v, '.5g') if isinstance(v, float) else v}" for k, v in row.items()))
    if out:
        _write_rows(out, rows)


@app.command()
def monitor(
    interval: Annotated[float, typer.Option(help="Seconds between readings.")] = 10.0,
    duration: Annotated[float, typer.Option(help="Total seconds (0 = until Ctrl+C).")] = 600.0,
    out: Annotated[Path | None, typer.Option("--csv", help="Write the rows to this CSV file.")] = None,
):
    """Log output, measured output, color and temperatures over time (warm-up, drift). Changes nothing."""
    from .characterize import monitor as run

    rows = []
    with connect() as r:
        try:
            for row in run(r, interval, duration):
                rows.append(row)
                console.print("  ".join(f"{k} {_fmt(v, '.6g') if isinstance(v, float) else v}" for k, v in row.items()))
                if out:
                    _write_rows(out, rows, quiet=True)  # keep the file current during long runs
        except KeyboardInterrupt:
            pass
    if out:
        console.print(f"wrote {out}")


def _write_rows(path: Path, rows: list[dict], quiet: bool = False) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if not quiet:
        console.print(f"wrote {path}")


# ---- snapshots ------------------------------------------------------------------------------------------


@app.command()
def save(
    path: Annotated[Path, typer.Argument(help="JSON file to write.")],
    note: Annotated[str, typer.Option(help="Free text stored with it.")] = "",
):
    """Save the channel powers and the spectrum they give (changes nothing)."""
    from .snapshot import take

    with connect() as r:
        snap = take(r, note)
    snap.save(path)
    xy = f"x={snap.xy[0]:.4f} y={snap.xy[1]:.4f}" if snap.xy else "off"
    console.print(f"saved {len(snap.powers)} channels, {snap.photometric:.4g} photometric, {xy} to {path}")


@app.command()
def restore(path: Annotated[Path, typer.Argument(help="JSON file written by `rs7 save`.")]):
    """Put the unit back to a saved state."""
    from .snapshot import Snapshot
    from .snapshot import restore as do_restore

    snap = Snapshot.load(path)
    with connect() as r:
        do_restore(r, snap)
    console.print(f"restored {path} ({snap.time}{', ' + snap.note if snap.note else ''})")


# ---- camera and color accuracy -----------------------------------------------------------------------------

CameraOption = Annotated[
    str, typer.Option("--camera", envvar="RS7_CAMERA", help="URL of the camera service (picam-web).")
]


@contextmanager
def camera(url: str):
    """The camera client, turning a connection problem into a clean message and exit code."""
    from .camera import CameraError, PicamWeb

    try:
        yield PicamWeb(url)
    except CameraError as e:
        err.print(f"[red]Camera error:[/] {e}")
        raise typer.Exit(2) from e


@app.command("camera")
def camera_info(url: CameraOption = DEFAULT_CAMERA):
    """Show the camera and its present settings (changes nothing)."""
    with camera(url) as cam:
        info, meta, controls = cam.info(), cam.metadata(), cam.controls()
    mode = info["sensor_modes"][info["mode"]]
    black = meta["SensorBlackLevels"][0] * 2 ** (mode["bit_depth"] - 16)
    table = Table(show_header=False, box=None)
    table.add_row("Camera", f"{info['properties']['Model']} ({info['sensor']})")
    table.add_row("Mode", f"{mode['size'][0]} x {mode['size'][1]}, {mode['bit_depth']} bit, {mode['format']}")
    table.add_row("Auto exposure", "on" if controls.get("AeEnable") else "off")
    table.add_row("Exposure", f"{meta['ExposureTime'] / 1000:.3f} ms")
    table.add_row("Analogue gain", f"{meta['AnalogueGain']:.3f}")
    table.add_row("Black level", f"{black:g} DN of {2 ** mode['bit_depth'] - 1}")
    console.print(table)


def _patch_table(data, title: str) -> Table:
    from .colorcheck import PATCH_NAMES

    table = Table("#", "Patch", "R", "G", "B", "Peak", "", title=title)
    for i, name in enumerate(PATCH_NAMES):
        note = "[red]saturated[/]" if data.saturated[i] else "[yellow]too dark[/]" if data.too_dark[i] else ""
        table.add_row(str(i + 1), name, *(f"{v:.1f}" for v in data.rgb[i]), f"{data.peak[i]:.0f}", note)
    return table


@app.command()
def chart(
    corners: Annotated[
        str | None,
        typer.Option(help="Centers of the corner patches in raw pixels: 'x1,y1 x2,y2 x3,y3 x4,y4' (TL TR BR BL)."),
    ] = None,
    png: Annotated[Path, typer.Option(help="Write the image with the measured squares to this PNG file.")] = Path(
        "chart.png"
    ),
    url: CameraOption = DEFAULT_CAMERA,
):
    """Check where the ColorChecker is: one raw image at the present camera settings (changes nothing)."""
    from .chart import ChartGeometry, parse_corners, preview_png
    from .colorcheck import measure_patches

    geometry = ChartGeometry.load()
    if corners:
        try:
            geometry = ChartGeometry(parse_corners(corners))
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e
        geometry.save()
        console.print(f"saved the chart position to {CHART_FILE}")
    with camera(url) as cam:
        capture = cam.capture()
    preview_png(capture, geometry, png)
    console.print(f"wrote {png}")
    data = measure_patches(capture, geometry)
    title = f"Mean raw values (DN, black level {capture.black_level:g} subtracted), {capture.exposure_us / 1000:.1f} ms"
    console.print(_patch_table(data, title))


@app.command()
def colorcheck(
    illuminants: Annotated[str, typer.Option(help="Comma-separated lights to make (see `rs7 illuminants`).")] = (
        "D65,A,LED-B3"
    ),
    level: Annotated[
        float | None, typer.Option("--level", "-l", help="Light level in lux; default: keep the present level.")
    ] = None,
    frames: Annotated[int, typer.Option(help="Raw frames to average per light.")] = 4,
    method: Annotated[
        Method, typer.Option("--method", "-m", help="How the RS-7 is fitted to each light.")
    ] = Method.local,
    out: Annotated[Path | None, typer.Option("--csv", help="Write the ΔE of every patch to this CSV file.")] = None,
    url: CameraOption = DEFAULT_CAMERA,
):
    """Color accuracy of the camera under the RS-7's light, from a ColorChecker (changes the light, restores it)."""
    from .chart import ChartGeometry
    from .colorcheck import PATCH_NAMES, color_accuracy

    names = [n.strip() for n in illuminants.split(",") if n.strip()]
    if not names:
        raise typer.BadParameter("give at least one illuminant")
    with connect() as r, camera(url) as cam:
        try:
            result = color_accuracy(
                r,
                cam,
                ChartGeometry.load(),
                names,
                level,
                frames,
                method.value,
                progress=lambda m: err.print(f"[dim]{m}[/]"),
            )
        except ValueError as e:
            raise typer.BadParameter(str(e)) from e

    summary = Table("Light", "CCT (K)", "Δu'v' of the light", "Exposure (ms)", "Mean ΔE", "Median ΔE", "Max ΔE")
    for res in result.illuminants:
        a = res.accuracy
        summary.add_row(
            res.illuminant,
            _fmt(res.cct, ".0f"),
            _fmt(res.delta_uv_prime, ".4f"),
            f"{res.exposure_us / 1000:.1f}",
            f"{a.mean:.2f}",
            f"{a.median:.2f}",
            f"{a.max:.2f}",
        )
    console.print(summary)

    table = Table("#", "Patch", *(res.illuminant for res in result.illuminants), title="ΔE2000 per patch")
    for i, name in enumerate(PATCH_NAMES):
        cells = []
        for res in result.illuminants:
            cell = f"{res.accuracy.delta_e[i]:.2f}"
            cells.append(cell if res.accuracy.used[i] else f"[dim]{cell} (excluded)[/]")
        table.add_row(str(i + 1), name, *cells)
    console.print(table)

    if result.cross:
        first = result.cross[0].fitted_under
        cross = Table("Light", "Mean ΔE", "Median ΔE", "Max ΔE", title=f"Matrix fitted under {first}, white-balanced")
        for c in result.cross:
            cross.add_row(c.illuminant, f"{c.accuracy.mean:.2f}", f"{c.accuracy.median:.2f}", f"{c.accuracy.max:.2f}")
        console.print(cross)
    console.print("ΔE2000 below 1 is hardly visible; 2-3 is a small difference to a trained eye.")

    if out:
        rows = []
        for i, name in enumerate(PATCH_NAMES):
            row = {"patch": i + 1, "name": name}
            for res in result.illuminants:
                row[res.illuminant] = round(float(res.accuracy.delta_e[i]), 3)
                row[f"{res.illuminant} used"] = bool(res.accuracy.used[i])
            for c in result.cross:
                row[f"{c.illuminant} (matrix from {c.fitted_under})"] = round(float(c.accuracy.delta_e[i]), 3)
            rows.append(row)
        _write_rows(out, rows)


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
