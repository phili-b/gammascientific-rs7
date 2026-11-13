# API reference

Everything to control the unit is in `rs7.RS7`; the spectral matching and color quality functions are in
`rs7.illuminants`, `rs7.colorimetry` and `rs7.match` (see below). Each method sends one or a few RS-7 commands; the command is named so
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
| `spectrum(channel=0, start=None, end=None)` | `OSP` | `[(nm, value), ...]` of the output or of one channel, in uW/cm2/nm (uW/cm2/sr/nm for a radiant calibration). With `start` and `end` the wavelength range is set first (this changes the unit's range); otherwise the present range is used |
| `target_spectrum()` / `set_target_spectrum(values)` | `TSP` | Target, one value per nm over the range |
| `fit(include_white=False, at_max=False)` | `FTS` | Least-squares fit to the target |
| `color_correct(xy=None)` | `CCS` | Match the target's (or given) chromaticity |
| `rms_error()` | `RPE` | Mismatch output vs. target in % RMS |

To match a named illuminant at an absolute level in one call, use `rs7.match.match` (below) instead of these
steps.

Helpers in `rs7.spectrum` (no hardware): `blackbody(cct, start, end)`, `load_csv(path)`,
`resample(points, start, end)`, `cct_to_xy(cct)`, `wavelength_to_rgb(nm)`.

## Target spectra: `rs7.illuminants`

No hardware needed. A target is a name (`"D65"`, `"A"`, `"FL2"`, `"LED-B3"`, ...), `"D5000"` for CIE daylight
at 4000-25000 K, `"3000K"` or `"BB3000"` for a black body, or the path of a CSV file. See
[Targets](colorimetry.md#targets).

| Function | Description |
|---|---|
| `available()` | Sorted names of the CIE illuminants of the colour-science library |
| `describe(name)` | Readable description of a target name, e.g. `"CIE illuminant D65"` |
| `target_spectrum(name, start, end)` | Relative spectrum (peak 1) at 1 nm steps from `start` to `end`; 0 outside the illuminant's tabulated range. Raises `ValueError` for an unknown name |

## Colorimetry: `rs7.colorimetry`

No hardware needed. Spectra are `[(nm, value), ...]` at 1 nm steps in the RS-7's radiometric units
(uW/cm2/nm, or uW/cm2/sr/nm); photometric values come out in lux or cd/m2. The definitions and the physics are in
[Spectral matching and color quality](colorimetry.md).

| Function / class | Description |
|---|---|
| `analyze(spectrum, observer=2, quality=True)` | `ColorReport`: `radiometric`, `photometric`, `XYZ`, `xy`, `uv_prime`, `cct`, `duv` (Ohno 2013), `cri_ra`, `cri_r` (R1-R14, CIE 13.3), `tm30_rf`, `tm30_rg` (ANSI/IES TM-30-18), `peak_nm`, `centroid_nm`. Values that cannot be computed are `None`. `quality=False` skips CRI and TM-30 (faster) |
| `compare(output, target, output_spectrum, target_spectrum)` | `Comparison`: `delta_uv_prime`, `delta_cct`, `delta_duv`, `level_ratio`, `spectral_rms` |
| `spectral_rms(output, target)` | RMS difference of the area-normalized spectra over the target's range, in % of the target's mean |
| `photometric_per_unit(relative, start)` | Photometric value (lux or cd/m2) of a relative spectrum taken as 1 uW/cm2/nm per unit |

The analysis range is 360-830 nm. Photometric values always use V(lambda), the CIE 1931 2 degree `ybar`; CCT,
Duv, CRI and TM-30 use the 2 degree observer; `xy` can use the 10 degree observer (`observer=10`).

```python
from rs7.colorimetry import analyze
from rs7.illuminants import target_spectrum

d65 = [(360 + i, v) for i, v in enumerate(target_spectrum("D65", 360, 830))]
print(analyze(d65).cct)  # about 6504 K
```

## Matching a target: `rs7.match`

| Function | Description |
|---|---|
| `match(rs7, target, level=None, units=Units.PHOTOMETRIC, at_max=False, start=380, end=780, include_white=False, correct_chromaticity=True)` | Scale the target to `level`, fit the unit to it (`TSP`, `FTS`), correct the color (`CCS`) and set the exact level (`OUT` / `OUTC`). `level=None` keeps the present level; `at_max=True` fits at the highest output the soft limit allows. Returns a `MatchResult` |
| `measure(rs7)` | Read-only: the `ColorReport` of the present output |
| `measure_against(rs7, target, start=380, end=780)` | Read-only: a `MatchResult` comparing the present output with `target` at the same level (its `unit_rms_error` is NaN) |
| `scale_to_level(relative, start, level, units)` | Factor that turns a relative spectrum into absolute units with the given total level (photometric or radiometric) |

`MatchResult` has `target_name`, `target` and `output` (`ColorReport`), `comparison` (`Comparison`),
`unit_rms_error` (the RS-7's own spectral error, `RPE`, in %), and `target_spectrum` and `output_spectrum`
(`[(nm, value), ...]`, absolute; the target is scaled to the level the output reached).

```python
from rs7 import RS7
from rs7.match import match

with RS7() as rs7:
    result = match(rs7, "D65", level=500)  # 500 lux (or cd/m2)
    print(result.output.cct, result.comparison.delta_uv_prime, result.unit_rms_error)
```

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
::: rs7.illuminants
::: rs7.colorimetry
::: rs7.match
::: rs7.bridge
