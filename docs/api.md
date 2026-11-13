# API reference

Everything to control the unit is in `rs7.RS7`; the spectral matching and color quality functions are in
`rs7.illuminants`, `rs7.colorimetry` and `rs7.match`; the local fit, monochromatic steps, characterization and
snapshots are in `rs7.optimize`, `rs7.mono`, `rs7.characterize` and `rs7.snapshot` (see below). Each `RS7`
method sends one or a few RS-7 commands; the command is named so you can look it up in the user manual
(section 4). The package needs Python 3.11 or newer.

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
| `channel_groups()` | `GRP`, `CGL` | `{leader: [members]}`: fitted channels that are set together. With grouping on, setting any member sets the whole group; a channel that is in no group maps to itself, e.g. `{3: [3, 5, 30], 4: [4], ...}`. The key is the first channel of the group |
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

Helpers in `rs7.spectrum` (no hardware):

| Function | Description |
|---|---|
| `blackbody(cct, start, end)` | Planck spectrum at 1 nm steps, peak 1 |
| `load_csv(path)` | `[(nm, value), ...]` from `wavelength, value` lines |
| `resample(points, start, end)` | Interpolate to 1 nm steps |
| `cct_to_xy(cct)` | CIE 1931 x, y of the Planckian locus |
| `wavelength_to_rgb(nm)` | Approximate display color of a wavelength |
| `centroid(spectrum)` | Power-weighted mean wavelength (nm) of `[(nm, value), ...]`; `None` if there is no power |
| `fwhm(spectrum)` | Full width at half maximum (nm), from the outermost half-power crossings, linearly interpolated; `None` if empty or no peak |
| `photon_flux(spectrum)` | Photons/s/cm2 (or /sr) of a spectrum in uW/cm2/nm (or /sr) at 1 nm steps: the sum of `S x 1e-6 W x lambda x 1e-9 m / (h c)`. See [Photon units](tools.md#photon-units) |

```python
from rs7.spectrum import centroid, fwhm, photon_flux

s = rs7.spectrum(5, 360, 1100)  # one channel
print(centroid(s), fwhm(s), photon_flux(s))
```

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
| `match(rs7, target, level=None, units=Units.PHOTOMETRIC, at_max=False, start=380, end=780, include_white=False, correct_chromaticity=True, method="local")` | Scale the target to `level`, fit the unit to it, set the exact level and correct the color (`CCS`). `method="local"` (default) solves the channel powers on the PC (`rs7.optimize`); `method="firmware"` uses the RS-7's own fit (`TSP`, `FTS`). `level=None` keeps the present level; `at_max=True` fits at the highest output the soft limit allows. `include_white` applies to the firmware fit only. Returns a `MatchResult`; raises `ValueError` for another `method` |
| `measure(rs7)` | Read-only: the `ColorReport` of the present output |
| `measure_against(rs7, target, start=380, end=780)` | Read-only: a `MatchResult` comparing the present output with `target` at the same level (its `unit_rms_error` is NaN) |
| `scale_to_level(relative, start, level, units)` | Factor that turns a relative spectrum into absolute units with the given total level (photometric or radiometric) |

`MatchResult` has `target_name`, `target` and `output` (`ColorReport`), `comparison` (`Comparison`),
`unit_rms_error` (the RS-7's own spectral error, `RPE`, in %; NaN for the local fit), and `target_spectrum` and `output_spectrum`
(`[(nm, value), ...]`, absolute; the target is scaled to the level the output reached).

```python
from rs7 import RS7
from rs7.match import match

with RS7() as rs7:
    result = match(rs7, "D65", level=500)  # 500 lux (or cd/m2), local fit
    print(result.output.cct, result.comparison.delta_uv_prime, result.comparison.spectral_rms)
```

The two methods are compared in [Local fit vs firmware fit](colorimetry.md#local-fit-vs-firmware-fit).

## Local fit: `rs7.optimize`

The fit that `match(method="local")` uses; it can also be called directly. It needs SciPy.

| Function / class | Description |
|---|---|
| `ChannelBasis` | The spectrum per 1 % of power of every channel group, 1 nm steps over `start`-`end` (360-1100 nm). Fields `board`, `start`, `end`, `power` (the % it was measured at), `groups` (leader to members) and `spectra` (leader to a list). `save(path)` and `ChannelBasis.load(path)` read and write JSON |
| `measure_basis(rs7, power=70.0, progress=None)` | Measure every group at `power` % (each is switched on briefly and put back; about 10 s). `progress(done, total)` is called after each group |
| `load_basis(rs7, remeasure=False, progress=None)` | The basis cached in `~/.rs7/basis-<board>.json`; measured and cached first if there is none, if `remeasure` is true, or if the board, calibration or range differ |
| `solve(basis, target, start, max_power=100.0, color_weight=50.0, fit_range=None)` | Channel powers `{leader: %}` whose summed spectra are closest to `target` (absolute, uW/cm2/nm or /sr, 1 nm from `start`). Bounded least squares over `fit_range` (default: the target's range), plus three XYZ rows and rows with target 0 outside the fit range. No hardware |
| `apply(rs7, basis, powers)` | Set every group to its power (internal %); groups not in `powers` go off |
| `fit(rs7, target, start, at_max=False, iterations=2, basis=None)` | Solve, set, read the real spectrum, add the remaining error to the target and solve again (`iterations` times). Powers are limited to 95 % of the soft limit. With `at_max` the target is first scaled up until a channel reaches the limit. Returns the powers that were set. It does not set the level or the color; `match()` does that afterwards |

Constants: `COLOR_WEIGHT` (50), `LEAK_WEIGHT` (0.5), `MIN_INSIDE` (0.05: channels with less of their power inside
the fit range are not used), `BASIS_RANGE` (360, 1100). The method is explained in
[Local fit vs firmware fit](colorimetry.md#local-fit-vs-firmware-fit).

```python
from rs7 import RS7, Units
from rs7.illuminants import target_spectrum
from rs7.match import scale_to_level
from rs7.optimize import fit, load_basis

relative = target_spectrum("D65", 380, 780)
scale = scale_to_level(relative, 380, 500, Units.PHOTOMETRIC)  # 500 lux or cd/m2
target = [v * scale for v in relative]  # absolute, uW/cm2/nm

with RS7() as rs7:
    basis = load_basis(rs7)  # measured the first time, then cached
    print(fit(rs7, target, 380, basis=basis))  # {group leader: power %}
```

## Monochromatic steps: `rs7.mono`

One narrow channel (group) at a time, at a chosen photon flux, radiant power or drive level; see
[Spectral tools](tools.md#monochromatic-steps).

| Function / class | Description |
|---|---|
| `mono_channels(rs7, start=360, end=1100, max_fwhm=60.0)` | `[(leader, members, nominal_nm, nominal_fwhm), ...]` for the narrow channels with a nominal wavelength in the range, sorted by wavelength; white channels (FWHM above `max_fwhm`) are left out |
| `set_mono(rs7, channel, photons=None, radiometric=None, power=None)` | Switch everything off except the group of `channel` and set it to exactly one of `photons` (photons/s/cm2 or /sr), `radiometric` (uW/cm2 or /sr) or `power` (%, internal units). For a flux the drive level is iterated, up to 4 tries, until it is within 0.2 %. Returns a `MonoStep`. Raises `ValueError` for no or several goals, or a channel that is not fitted |
| `mono_scan(rs7, start=360, end=1100, photons=None, radiometric=None, power=None, max_fwhm=60.0)` | Generator of `MonoStep`, one per narrow channel by nominal wavelength. The unit's channel powers are restored when the generator ends, also on an error or when the loop is left early |
| `MonoStep` | `channel` (group leader), `members`, `nominal_nm`, `centroid_nm`, `peak_nm`, `fwhm_nm`, `power` (%), `radiometric`, `photon_flux`, `at_limit` (the goal needed more than the soft limit allows) |

```python
from rs7 import RS7
from rs7.mono import mono_scan

with RS7() as rs7:
    for step in mono_scan(rs7, 400, 1000, photons=1e13):
        print(step.centroid_nm, step.power, step.photon_flux)
```

## Characterization: `rs7.characterize`

How the unit dims and how stable it is; see [Spectral tools](tools.md#dimming).

| Function | Description |
|---|---|
| `dimming(rs7, levels=None, channel=None)` | Generator of one dict per level (%, internal units; default `DEFAULT_LEVELS`, 1 to 100). Without `channel` the present spectrum is scaled and the rows have `level`, `actual` (`OUTA`), `photometric`, `x`, `y`, `cct`, `centroid_nm`. With `channel` only that channel is on and the rows have `level`, `radiometric`, `photon_flux`, `centroid_nm`, `peak_nm`, `fwhm_nm`. The channel powers are restored afterwards |
| `monitor(rs7, interval=10.0, duration=600.0, units=Units.PHOTOMETRIC)` | Generator of one dict per reading: `time_s`, `output` (`OUT`), `actual` (`OUTA`), `x`, `y`, `cct`, `led_temp_c`, `monitor_temp_c`. `duration=0` runs until you stop iterating. Changes nothing on the unit |

## Snapshots: `rs7.snapshot`

| Function / class | Description |
|---|---|
| `take(rs7, note="")` | Read the present state into a `Snapshot`; changes nothing |
| `restore(rs7, snapshot)` | Switch all channels off, set the snapshot's channel powers, units and wavelength range. Raises `RS7Error` for a snapshot from another LED board |
| `Snapshot` | Dataclass with `time`, `board`, `units`, `wavelength_range`, `powers` (% internal units), `spectrum` (360-830 nm), `photometric`, `xy`, `cct` and `note`. `save(path)` writes JSON and `Snapshot.load(path)` reads it |

```python
from rs7 import RS7
from rs7.snapshot import Snapshot, restore, take

with RS7() as rs7:
    take(rs7, "before").save("state.json")
    # ... experiment ...
    restore(rs7, Snapshot.load("state.json"))
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
::: rs7.optimize
::: rs7.mono
::: rs7.characterize
::: rs7.snapshot
::: rs7.bridge
