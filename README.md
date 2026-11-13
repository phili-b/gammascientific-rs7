# gammascientific-rs7

Python API and desktop GUI for the Gamma Scientific **SpectralLED RS-7** tunable light source.

- `rs7`: a small Python API over the RS-7's ASCII command set (user manual, section 4)
- `rs7-gui`: a desktop window laid out like the manufacturer's SpectralLED Assistant
- runs on Windows, Linux and the Raspberry Pi; it needs only `pyserial` (the GUI uses tkinter from the standard library)

![GUI](docs/img/gui.png)

## Install

    pip install git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git

On a Raspberry Pi, add your user to the `dialout` group once (`sudo usermod -aG dialout $USER`) to use `/dev/ttyUSB0`.

## Quick start

```python
from rs7 import RS7, Units

with RS7("/dev/ttyUSB0") as rs7:              # "COM5" on Windows
    print(rs7.version(), rs7.temperatures())

    rs7.set_units(Units.INTERNAL)              # power numbers are now 0-100 %
    rs7.set_channel_power(5, 10)               # returns once the output has settled
    print(rs7.channel_powers())                # {channel: power} for channels that are on

    rs7.recall_preset(0)
    print(rs7.output(Units.PHOTOMETRIC), "lux", rs7.chromaticity(), rs7.cct(), "K")
```

Start the GUI with:

    rs7-gui

It reconnects to the last port on start; pick a port under **Settings > Select COM Port**.

## Documentation

- [Getting started](docs/index.md)
- [API reference](docs/api.md)
- [GUI](docs/gui.md)
- [Serial protocol notes](docs/protocol.md)
- [Examples](examples/)

Build the HTML docs with `pip install -e .[docs]` then `mkdocs serve`.

## Development

    pip install -e .[test]
    pytest

The tests use a fake serial port, so no hardware is needed.
