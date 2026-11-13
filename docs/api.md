# API reference

Everything is in `rs7.RS7`. Each method sends one or a few RS-7 commands; the command is named so
you can look it up in the user manual (section 4).

## Connection and raw commands

| Method | Command | Description |
|---|---|---|
| `RS7(port=None, baudrate=460800, timeout=10.0)` | | Open a port name, pyserial URL (`socket://host:5000`), or an open serial object. `None`: the first RS-7 found, see `find_port()` |
| `close()` | | Close the port (or use `with RS7(...)`) |
| `command(cmd, multiline=False)` | any | Send a raw command, get reply lines (`[]` for "Ok") |
| `on_command` | | Optional `callback(command, reply, is_error)` for logging |

## Finding the port

| Function | Description |
|---|---|
| `find_ports()` | List of serial ports that look like an RS-7 (FTDI FT232R, USB ID 0403:6001), e.g. `["/dev/ttyUSB0"]` or `["COM5"]` |
| `find_port()` | The first of those; raises `PortNotFoundError` if there is none |
| `PortNotFoundError` | Subclass of `OSError`; also raised by `RS7()` when no port is given and none is found |

```python
from rs7 import RS7, find_ports

print(find_ports())
rs7 = RS7(find_ports()[0])  # same as RS7()
```

## Channels

| Method | Command | Description |
|---|---|---|
| `channel_info()` | `LIN` | `ChannelInfo` (wavelength, FWHM) of each fitted channel |
| `channel_power(ch)` | `SCP ch` | Power of one channel |
| `channel_powers()` | `SCP 0` | `{channel: power}` of channels that are on |
| `set_channel_power(ch, p)` | `SCP ch,p` | Set one channel; returns when settled |
| `set_channel_powers({ch: p})` | `SCP ch,p,...` | Set several channels at once |
| `all_off()` | `SCP 0,0` | All channels off (forgets the spectrum) |

## Output and color

| Method | Command | Description |
|---|---|---|
| `units()` / `set_units(Units)` | `UNI` | Global units of power numbers |
| `using_units(Units)` | `UNI` | Context manager: switch the units inside a `with` block, then restore them (`None` leaves them alone) |
| `output(units=None)` | `OUT` | Total output |
| `set_output(level, units=None, keep_chromaticity=False)` | `OUT` / `OUTC` | Scale the whole spectrum |
| `actual_output(units=None)` | `OUTA` | Output measured by the monitor photodiode |
| `chromaticity()` / `set_chromaticity(x, y)` | `OXY` / `CCS x,y` | CIE 1931 x, y |
| `tristimulus()` | `OXYZ` | CIE X, Y, Z |
| `cct()` | `CCT` | Correlated color temperature (K) |

## Spectra and fitting

| Method | Command | Description |
|---|---|---|
| `wavelength_range()` / `set_wavelength_range(a, b)` | `WLR` | Range for spectra and fits (nm) |
| `spectrum(channel=0)` | `OSP` | `[(nm, value), ...]` of the output or of one channel |
| `target_spectrum()` / `set_target_spectrum(values)` | `TSP` | Target, one value per nm over the range |
| `fit(include_white=False, at_max=False)` | `FTS` | Least-squares fit to the target |
| `color_correct(xy=None)` | `CCS` | Match the target's (or given) chromaticity |
| `rms_error()` | `RPE` | Mismatch output vs. target in % RMS |

Helpers in `rs7.spectrum` (no hardware): `blackbody(cct, start, end)`, `load_csv(path)`,
`resample(points, start, end)`, `cct_to_xy(cct)`, `wavelength_to_rgb(nm)`.

## Presets

| Method | Command | Description |
|---|---|---|
| `presets()` | `PRE *` | `{number: name}` |
| `current_preset()` | `PRE` | `"NONE"` or `"n,name"` |
| `recall_preset(n)` | `PRE n` | Load a preset |
| `store_preset(n, name)` | `SPR` | Save the present output; preset 0 is the power-on state |
| `delete_preset(n)` | `DPR` | |

## Settings and housekeeping

| Method | Command | Description |
|---|---|---|
| `version()` | `VER` | Firmware version |
| `led_board_serial()` | `LSN` | |
| `calibration_type()` / `calibration_info()` | `CTY` / `CAL` | |
| `temperatures()` | `TMP` | TEC temperatures (LED board, wavelength monitor) |
| `alarm()` / `clear_alarm()` | `ALA` / `ALAR` | |
| `soft_limit()` / `set_soft_limit(pct)` | `SLM` | Max channel power, % |
| `feedback()` / `set_feedback(bool)` | `FBK` | Optical feedback |
| `working_distance()` / `set_working_distance(mm)` | `IRR` | Irradiance mode distance, 0 = radiance |
| `peak_type()` / `set_peak_type(PeakType)` | `PTY` | Centroid, peak or center wavelength |
| `observer()` / `set_observer(2 or 10)` | `SOB` | CIE standard observer |

Anything else (`SCA`, `PUL`, `ATF`, `IRI`, ...) can be sent with `command()`.

## Sharing over TCP

`rs7.bridge.serve(port, listen=5000, baudrate=460800, log=print)` forwards bytes between a serial port and
one TCP client at a time; it is what `rs7 bridge` runs. Connect with `RS7("socket://host:5000")`. No
authentication.

## Auto-generated reference

::: rs7.RS7
::: rs7.Units
::: rs7.PeakType
::: rs7.ChannelInfo
::: rs7.RS7Error
::: rs7.PortNotFoundError
::: rs7.find_port
::: rs7.find_ports
::: rs7.spectrum
::: rs7.bridge
