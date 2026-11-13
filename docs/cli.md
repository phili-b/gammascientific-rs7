# Command line

The `rs7` command controls the unit from a terminal. `rs7 --help` lists the commands and
`rs7 COMMAND --help` the options of one.

## Global options

Put these before the command name.

| Option | Description |
|---|---|
| `--port`, `-p` | Serial port or pyserial URL (`/dev/ttyUSB0`, `COM5`, `socket://host:5000`). Also read from the environment variable `RS7_PORT`. Default: the first RS-7 found. |
| `--baud` | Baud rate, 460800 (default) or 115200 if the unit is configured for it. |
| `--verbose`, `-v` | Print every command sent to the unit and its reply (to stderr). |

```
rs7 -p COM5 info
rs7 -v set 5=10
RS7_PORT=socket://10.61.100.206:5000 rs7 channels
```

Exit codes: 0 on success, 1 if the unit answers with an error or times out, 2 if the port cannot be opened.

## Units

Commands with `--units` / `-u` take `radiometric`, `photometric` or `internal` (0-100 % of the internal
photodiode output). The units are switched only for that command and then put back. See
[Units](index.md#units).

## Commands

### version

Show the version of this package. Does not talk to the unit.

```
rs7 version
```

### ports

List the serial ports and mark the ones that look like an RS-7 (FTDI FT232R). Does not open any port.

```
rs7 ports
```

### info

Show firmware, LED board serial number, calibration, temperatures, alarm, soft limit, output in the three
units, color and the current preset. Changes nothing.

```
rs7 info
```

### channels

List the channels sorted by wavelength, with FWHM and power. Only channels that are on are shown; `--all`
(`-a`) shows all. Default units: `internal`.

```
rs7 channels
rs7 channels --all --units radiometric
```

### set

Set channel powers, given as `CHANNEL=POWER` pairs. `--only` first switches all other channels off. Default
units: `internal` (percent).

```
rs7 set 5=10
rs7 set 5=10 7=2.5 --only
rs7 set 5=100 --units photometric
```

### off

Switch every channel off.

```
rs7 off
```

### output

Read the total output, or set it when a level is given. `--keep-color` holds the chromaticity while scaling
(`OUTC`). Default units: `photometric`.

```
rs7 output
rs7 output 200
rs7 output 5 --units radiometric --keep-color
```

### color

Read the CIE 1931 chromaticity and CCT, or set it with `X Y` or with `--cct K` (black-body color at that
temperature).

```
rs7 color
rs7 color 0.3127 0.3290
rs7 color --cct 4000
```

### illuminants

List the target spectra that `match` and `measure` accept: the CIE illuminant library with each one's CCT, Duv,
xy and CRI Ra, computed from its spectrum. Does not talk to the unit. Besides the listed names, a target can be
`D<CCT>` (CIE daylight at 4000 to 25000 K, e.g. `D5000`), `<T>K` or `BB<T>` (black body, e.g. `3000K`) or the
name of a CSV file. See [Spectral matching and color quality](colorimetry.md#targets).

```
rs7 illuminants
```

### match

Make the RS-7 reproduce a target spectrum at an absolute level, and report how well it did. `TARGET` is a name
from `rs7 illuminants`, `D<CCT>`, `<T>K`, or a CSV file with `wavelength, value` lines (any step size,
interpolated to 1 nm). The steps (target, scale to level, fit, color correction, set level) are described in
[How `match` works](colorimetry.md#how-match-works).

| Option | Description |
|---|---|
| `--level`, `-l` | Total output to reach. Default: keep the present level (the maximum if the unit is off). |
| `--units`, `-u` | Units of `--level`: `photometric` (default; lux or cd/m2) or `radiometric`. |
| `--max` | As bright as the soft limit allows (`--level` is ignored). |
| `--start`, `--end` | Fit range in nm (default 380 to 780). |
| `--white` | Also use the white channels in the fit. |
| `--no-correct` | Do not correct the color after the fit (it is corrected by default). |
| `--csv FILE` | Write `nm, target, output` lines to this file. |

```
rs7 match D65 --level 500
rs7 match A --max
rs7 match D5000 --level 200 --start 400 --end 700
rs7 match 3000K --level 50 --units radiometric
rs7 match LED-B3 --level 300 --no-correct
rs7 match target.csv --csv result.csv
```

The output is a table with a Target, an Output and a Difference column, then a line with the spectral RMS and
the RS-7's own error (RPE). The rows are: level, radiometric power, CCT, Duv, x y, u' v', CRI Ra, CRI R9,
TM-30 Rf and Rg, and the centroid wavelength. The Δu'v' is green below 0.001, yellow below 0.005 and red above.

Values of one run on a unit with a radiant calibration (levels in cd/m2), `rs7 match D65 --level 500`:

| | Target (D65, 380-780 nm) | Output | Difference |
|---|---|---|---|
| Level (cd/m2) | 500 | 500 | 1.000 x |
| Radiometric (uW/cm2/sr) | 244.1 | 236.8 | |
| CCT (K) | 6502 | 6491 | -11 |
| Duv | +0.0032 | +0.0030 | -0.0002 |
| x, y | 0.3127, 0.3291 | 0.3130, 0.3288 | |
| u', v' | 0.1978, 0.4684 | 0.1981, 0.4683 | Δu'v' 0.0003 |
| CRI Ra | 100.0 | 96.9 | |
| CRI R9 (red) | 100.0 | 84.5 | |
| TM-30 Rf | 100.0 | 97.0 | |
| TM-30 Rg | 100.0 | 99.9 | |
| Centroid (nm) | 566.0 | 564.7 | |

followed by `spectral RMS 18.7 % (RS-7 RPE 18.31 %)`. More measured examples are in [Validation](colorimetry.md#validation).

### measure

Report the color quality of the present output: level, radiometric power, CCT, Duv, xy, u'v', CRI Ra and R9,
TM-30 Rf and Rg, and the centroid wavelength. With `--target` / `-t NAME` the report also shows that target
at the same level and the differences (and the spectral RMS), without the RPE since no target is loaded in the
unit. It changes nothing on the unit.
`--start` and `--end` set the range of the comparison (default 380 to 780).

```
rs7 measure
rs7 measure --target D65
rs7 measure -t 3000K --start 400 --end 700
```

### spectrum

Read the output spectrum in 1 nm steps. By default a rough bar chart is printed; `--csv FILE` writes
`nm,value` lines instead. `--channel` / `-c` selects one channel (0, the default, is the total output);
`--start` and `--end` set the range in nm (default 380 to 780).

```
rs7 spectrum
rs7 spectrum --channel 5 --start 400 --end 700
rs7 spectrum --csv out.csv
```

### preset

Manage the presets stored in the unit.

| Command | Description |
|---|---|
| `rs7 preset list` | List the presets; the loaded one is marked. |
| `rs7 preset load N` | Load preset N. |
| `rs7 preset store N [NAME]` | Store the present output as preset N. Preset 0 is the power-on state. |
| `rs7 preset delete N [-y]` | Delete preset N; asks first unless `--yes` / `-y` is given. |

```
rs7 preset list
rs7 preset load 0
rs7 preset store 3 "warm white"
rs7 preset delete 3 -y
```

### alarm

Show the alarm state (`NONE` or the alarm text); `--clear` clears it first.

```
rs7 alarm
rs7 alarm --clear
```

### send

Send raw RS-7 commands (user manual, section 4) and print the replies. Use `--list` / `-l` for commands that
answer with a list ended by an empty line (`SCP 0`, `LIN`, `PRE *`, `OSP`, `TSP`).

```
rs7 send VER "SCP 5"
rs7 send --list "PRE *"
```

### bridge

Share the unit over TCP so another machine can use it, for example when it is plugged into a Raspberry Pi.
`--listen` sets the TCP port (default 5000). Use the global `--port` to share a specific serial port.
One client at a time; there is no authentication, so only use it on a trusted network. Stop with Ctrl+C.

```
rs7 bridge
rs7 bridge --listen 5001
```

On the other machine use `socket://host:5000` as the port (`rs7 -p socket://host:5000 info`,
`RS7("socket://host:5000")`, or **Settings > Network Address** in the GUI).

### gui

Open the desktop GUI; needs the `gui` extra (PySide6). With a global `--port` it connects to that port.
See [GUI](gui.md).

```
rs7 gui
rs7 -p COM5 gui
```
