# gammascientific-rs7

Python API, command line tool and desktop GUI for the Gamma Scientific **SpectralLED RS-7** tunable light source.

- `rs7` (Python): a small API over the RS-7's ASCII command set (user manual, section 4)
- `rs7` (command): control the unit from a terminal (`rs7 set`, `rs7 fit`, `rs7 spectrum`, ...)
- `rs7-gui`: a desktop window (PySide6) laid out like the manufacturer's SpectralLED Assistant
- runs on Linux (including the Raspberry Pi) and Windows; the CLI and API need only `pyserial`, `typer` and `rich`

![GUI](docs/img/gui.png)

## Install

The project uses [uv](https://docs.astral.sh/uv/). CLI and GUI:

    uv tool install "gammascientific-rs7[gui] @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

CLI and Python API only (e.g. a headless Raspberry Pi), without PySide6:

    uv tool install "gammascientific-rs7 @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

As a library in your own project:

    uv add "gammascientific-rs7 @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

On Linux, add your user to the `dialout` group once (`sudo usermod -aG dialout $USER`, then log in again) to be allowed to use `/dev/ttyUSB0`.

## Quick start

`RS7()` without a port picks the first RS-7 it finds (the unit's FTDI FT232R USB-serial chip, USB ID 0403:6001) and raises `PortNotFoundError` if there is none. You can also pass a port such as `"/dev/ttyUSB0"`, `"COM5"` or `"socket://host:5000"`.

```python
from rs7 import RS7, Units

with RS7() as rs7:
    print(rs7.version(), rs7.temperatures())

    rs7.set_units(Units.INTERNAL)  # power numbers are now 0-100 %
    rs7.set_channel_power(5, 10)  # returns once the output has settled
    print(rs7.channel_powers())  # {channel: power} for channels that are on

    rs7.recall_preset(0)
    print(rs7.output(Units.PHOTOMETRIC), "lux", rs7.chromaticity(), rs7.cct(), "K")
```

## Command line

```
rs7 ports                    # list serial ports, the RS-7 is marked
rs7 info                     # firmware, temperatures, alarm, output, color
rs7 channels                 # channels that are on, with wavelength and power
rs7 set 5=10 --only          # channel 5 to 10 %, all other channels off
rs7 preset load 0            # load preset 0
rs7 output 100 --keep-color  # 100 lux, keeping the chromaticity
rs7 fit 3000 --max           # imitate a 3000 K black body at the highest output
rs7 spectrum --csv out.csv   # write the output spectrum to a file
rs7 off
```

Without `--port` / `-p` (or the `RS7_PORT` environment variable) the first RS-7 found is used. `rs7 --help` lists all commands; they are described in [docs/cli.md](docs/cli.md). `rs7 bridge` shares the unit over TCP so another machine can use it.

## GUI

    rs7-gui

or `rs7 gui` or `python -m rs7.gui`. Pick a port under **Settings > Select COM Port**; it is remembered, and if none is stored the first RS-7 found is used. All unit communication runs on a background thread, so the window does not freeze. See [docs/gui.md](docs/gui.md).

## Documentation

- [Getting started](docs/index.md)
- [Command line](docs/cli.md)
- [API reference](docs/api.md)
- [GUI](docs/gui.md)
- [Serial protocol notes](docs/protocol.md)
- [Examples](examples/)

Serve the HTML docs locally with `uv run --group docs mkdocs serve`.

## Development

    uv sync
    uv run pytest
    uv run ruff check
    uv run ruff format
    uv run ty check

The tests use a fake serial port, so no hardware is needed. The dev tools (pytest, ruff, ty, and PySide6 so the GUI is tested and type-checked) are in the `dev` dependency group, which `uv sync` installs by default. Tested on Windows 11 and Raspberry Pi OS (aarch64).
