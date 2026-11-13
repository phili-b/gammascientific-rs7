# Getting started

## Hardware

The RS-7 has a USB type B port with an FTDI USB-serial chip. Plug it into the PC or Raspberry Pi:

| OS | Port name |
|---|---|
| Linux / Raspberry Pi | `/dev/ttyUSB0` (check with `dmesg` or `ls /dev/ttyUSB*`) |
| Windows | `COMn`: see Device Manager > Ports (COM & LPT) > "USB Serial Port" |

The unit talks at **460800 baud, 8N1** (it can be configured for 115200 instead; pass `baudrate=115200`).

## Install

    pip install git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git

## First steps

```python
from rs7 import RS7

rs7 = RS7("/dev/ttyUSB0")
print(rs7.version())            # firmware, e.g. "1.09"
print(rs7.channel_info())       # wavelength and FWHM of each fitted channel
print(rs7.channel_powers())     # channels that are on
rs7.close()
```

Use `with RS7(...) as rs7:` to close the port automatically.

## Units

Every power and output number is in the unit's **current units**, a global setting (`UNI`):

| `Units` | Meaning |
|---|---|
| `RADIOMETRIC` | uW/cm2 (irradiance) or uW/cm2/sr (radiance) |
| `PHOTOMETRIC` | lux or nits |
| `INTERNAL` | 0-100 % of the internal photodiode output |

`rs7.set_units(...)` changes it for everything that follows. `output()`, `set_output()` and
`actual_output()` accept a `units=` argument that switches temporarily and switches back.

## Errors

- The unit answering `?nn - text` raises `RS7Error` (`.code`, `.message`).
- No answer within the timeout (10 s per line by default) raises `TimeoutError`.
- Alarms are read with `alarm()` (returns `"NONE"` or the alarm text) and cleared with `clear_alarm()`.

## Using the RS-7 from another machine

When the RS-7 is plugged into a Raspberry Pi, share its port over TCP with
[`examples/serial_bridge.py`](../examples/serial_bridge.py) and connect from the PC with a pyserial URL:

```python
rs7 = RS7("socket://10.61.100.206:5000")
```

The GUI accepts the same URL under **Settings > Network Address**. The bridge has no authentication;
only run it on a trusted network.
