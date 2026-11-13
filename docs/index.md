# Getting started

## Hardware

The RS-7 has a USB type B port with an FTDI USB-serial chip (FT232R, USB ID 0403:6001). Plug it into the PC or Raspberry Pi:

| OS | Port name |
|---|---|
| Linux / Raspberry Pi | `/dev/ttyUSB0` (check with `dmesg` or `ls /dev/ttyUSB*`) |
| Windows | `COMn`: see Device Manager > Ports (COM & LPT) > "USB Serial Port" |

On Linux your user must be in the `dialout` group to open `/dev/ttyUSB0`:
`sudo usermod -aG dialout $USER`, then log in again.

The unit talks at **460800 baud, 8N1** (it can be configured for 115200 instead; pass `baudrate=115200`, or `--baud 115200` on the command line).

## Install

Python 3.11 or newer is needed. The project uses [uv](https://docs.astral.sh/uv/). As a tool, with the `rs7` command and the GUI:

    uv tool install "gammascientific-rs7[gui] @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

Leave out `[gui]` for the command and the Python API only (no PySide6), e.g. on a headless Raspberry Pi.

As a library in your own project:

    uv add "gammascientific-rs7 @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

To work on the package itself, see the Development section of the README.

## Finding the port

`RS7()` with no port looks for the RS-7 itself: it takes the first serial port whose USB ID is that of the
FTDI FT232R. If there is none it raises `PortNotFoundError`. `find_ports()` lists all candidates and
`find_port()` returns the first; see the [API reference](api.md). With more than one RS-7 connected, or
another FTDI device, pass the port explicitly. The command line does the same: `rs7 ports` lists the ports
and marks the RS-7.

## First steps

```python
from rs7 import RS7

rs7 = RS7()  # or RS7("/dev/ttyUSB0"), RS7("COM5")
print(rs7.version())  # firmware, e.g. "1.09"
print(rs7.channel_info())  # wavelength and FWHM of each fitted channel
print(rs7.channel_powers())  # channels that are on
rs7.close()
```

Use `with RS7() as rs7:` to close the port automatically. The same from a terminal: `rs7 info`
(see [Command line](cli.md)).

## Units

Every power and output number is in the unit's **current units**, a global setting (`UNI`):

| `Units` | Meaning |
|---|---|
| `RADIOMETRIC` | uW/cm2 (irradiance) or uW/cm2/sr (radiance) |
| `PHOTOMETRIC` | lux or nits |
| `INTERNAL` | 0-100 % of the internal photodiode output |

`rs7.set_units(...)` changes it for everything that follows. `output()`, `set_output()` and
`actual_output()` accept a `units=` argument that switches temporarily and switches back. To do the
same around several calls, use the context manager `using_units`:

```python
with rs7.using_units(Units.PHOTOMETRIC):
    rs7.set_channel_power(5, 100)  # 100 lux from channel 5
```

## Errors

- The unit answering `?nn - text` raises `RS7Error` (`.code`, `.message`).
- No answer within the timeout (10 s per line by default) raises `TimeoutError`.
- No RS-7 found when no port is given raises `PortNotFoundError` (an `OSError`).
- Alarms are read with `alarm()` (returns `"NONE"` or the alarm text) and cleared with `clear_alarm()`.

## Using the RS-7 from another machine

When the RS-7 is plugged into a Raspberry Pi, run on the Pi:

    rs7 bridge

It shares the unit's serial port over TCP (port 5000; change it with `--listen`) and serves one client at
a time. Use `--port` to share a specific serial port. From the PC, connect with a pyserial URL:

```python
rs7 = RS7("socket://10.61.100.206:5000")
```

The command line takes the same URL (`rs7 --port socket://10.61.100.206:5000 info`, or set `RS7_PORT`), and
the GUI accepts it under **Settings > Network Address**. The bridge has no authentication; only run it on a
trusted network. The bridge itself is the function `rs7.bridge.serve`.
