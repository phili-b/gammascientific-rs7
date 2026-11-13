# Spectral tools

Besides matching a target spectrum ([Spectral matching and color quality](colorimetry.md)), the package has
tools to use the RS-7 as a tunable monochromatic source (spectral response and QE measurements), to
characterize how the unit dims and drifts, and to save and restore its state.

| Task | Command | Python |
|---|---|---|
| One narrow channel at a chosen flux | `rs7 mono` | `rs7.mono.set_mono` |
| Step through the narrow channels at equal flux | `rs7 scan` | `rs7.mono.mono_scan` |
| Output, color and wavelength against drive level | `rs7 dimming` | `rs7.characterize.dimming` |
| Log output, color and temperature over time | `rs7 monitor` | `rs7.characterize.monitor` |
| Save and put back the state of the unit | `rs7 save`, `rs7 restore` | `rs7.snapshot` |

The numbers below were measured on one unit (firmware 1.09, LED board LHX0416, radiant calibration, so levels
are in cd/m2 and radiance in uW/cm2/sr). Channel grouping is on (35 groups; see
[`RS7.channel_groups()`](api.md#channels)). They show what to expect, not a specification of the instrument.

## Monochromatic steps

`rs7 mono WAVELENGTH` switches everything off except the narrow channel whose nominal wavelength is closest to
`WAVELENGTH`, and sets it to one of:

| Option | Meaning |
|---|---|
| `--photons F` | Photon flux in photons/s/cm2 (photons/s/cm2/sr for a radiant calibration) |
| `--radiometric P` | Radiant power in uW/cm2 (uW/cm2/sr) |
| `--power L` | Drive level in % of the channel's maximum (internal units). The default, 50 %, if none of the three is given |

Give only one of them. The channel is a group leader: with grouping on, all channels of its group are set
together (`channel_groups()`).

```
rs7 mono 550 --photons 1e13
rs7 mono 630 --radiometric 100
rs7 mono 450 --power 20
```

The table shows the channels that were set, their nominal wavelength, and the centroid, peak and FWHM of the
spectrum the unit measures at that drive level, the drive level, and the radiant power and photon flux.

With `--photons` or `--radiometric` the drive level is found by iteration: start at 10 %, measure, scale the
level by goal over measured, and repeat (up to 4 tries) until the measured value is within 0.2 % of the goal.
LED output is close to proportional to the drive level but not exactly. If the goal needs more than the unit's
soft limit allows, the channel stays at the limit and the step is marked `at limit` (`at_limit` in Python).
The unit is not restored afterwards: the channel stays on, so you can measure.

A channel is "narrow" if its nominal FWHM is at most 60 nm; the white (broadband) channels are skipped.

### Photon units

The photon flux is computed on the PC from the spectrum the unit reports (`OSP`), 1 nm steps over 360-1100 nm:

```
photon flux = sum( S(lambda) x 1e-6 W x lambda x 1e-9 m / (h c) )       per nm step
```

where S is in uW/cm2/nm (or /sr) and `h c / lambda` is the energy of one photon. The result is in
photons/s/cm2 (or photons/s/cm2/sr). It is the sum over the whole spectrum of the channel, so it includes the
tails of the LED line, not only a band around the centroid. `rs7.spectrum.photon_flux(spectrum)` does the same
for any spectrum. At equal radiant power there are more photons at longer wavelengths (the photon energy is
lower), so a scan at equal photon flux has a smaller radiant power at the blue end than at the red end.

The spectrum helpers `centroid(spectrum)` (power-weighted mean wavelength) and `fwhm(spectrum)` (outermost
half-power crossings, linearly interpolated) are in `rs7.spectrum` too.

### Nominal wavelength against centroid

The wavelength in the channel list is nominal. The LED shifts with drive current and temperature, so the
centroid at the drive level you use can differ. For channel 34, nominal 428.8 nm: centroid 430.1 nm, FWHM 14.1 nm,
at 0.264 % drive for 4.617 uW/cm2/sr (1e13 photons/s/cm2/sr). For channel 4, nominal 510.8 nm: the centroid is
526.5 nm at the low drive level of a 1e13 scan (FWHM 28.7 nm). Use the measured centroid (`centroid_nm` in
`MonoStep`) as the wavelength of the step, not the nominal one. See also [Dimming](#dimming).

## Scans

`rs7 scan` steps through the narrow channels from `--start` to `--end` nm (default 360-1100) in order of
nominal wavelength, sets each one as `rs7 mono` does, and waits `--dwell` seconds (default 1) on each so you can
take a measurement. The unit is restored to its earlier state at the end, also on Ctrl+C. `--csv FILE` writes
one row per step: `channel`, `members`, `nominal_nm`, `centroid_nm`, `peak_nm`, `fwhm_nm`, `power`,
`radiometric`, `photon_flux`, `at_limit`.

```
rs7 scan --start 400 --end 700 --photons 1e13 --dwell 1 --csv scan.csv
```

Measured, 400-700 nm at 1e13 photons/s/cm2/sr: 19 steps, every step within 0.2 % of the target flux, drive
levels 0.12 to 0.31 %. This flux needs only a small fraction of the channels' maximum.

In Python, `mono_scan` is a generator: do your measurement in the loop body. The unit's channel powers are put
back when the loop ends, also when it is left early or raises an error.

```python
from rs7 import RS7
from rs7.mono import mono_scan

with RS7() as rs7:
    for step in mono_scan(rs7, 400, 1000, photons=1e13):
        measure(step)  # your measurement, e.g. a camera frame or a photodiode reading
```

`MonoStep` has: `channel` (group leader), `members` (all channels of the group), `nominal_nm`, `centroid_nm`,
`peak_nm`, `fwhm_nm`, `power` (drive level, %), `radiometric`, `photon_flux`, and `at_limit`.
`mono_channels(rs7, start, end)` lists the channels a scan would use, and `set_mono(rs7, channel, photons=...,
radiometric=..., power=...)` sets one. `examples/07_spectral_scan.py` is a complete script.

### Measuring a quantum efficiency

For a sensor of unknown spectral response, step through the wavelengths at equal photon flux. The response at
each step divided by the photon flux, plotted against the centroid wavelength, is the relative quantum
efficiency. For an absolute value, measure the same steps with a calibrated reference detector and divide.

```python
from rs7 import RS7
from rs7.mono import mono_scan

PHOTONS = 1e13  # photons/s/cm2/sr at the source

rows = []
with RS7() as rs7:
    for step in mono_scan(rs7, 400, 1000, photons=PHOTONS):
        if step.at_limit:  # the flux could not be reached at this wavelength
            continue
        signal = read_sensor()  # your sensor: counts, volts, ...
        rows.append((step.centroid_nm, signal / step.photon_flux))
```

Here `read_sensor` stands for your own code. Keep these in mind:

- The geometry matters: the flux is per cm2 (and per sr for a radiant calibration) at the unit's output, so
  place the sensor as the calibration assumes, or measure a reference at the same place.
- The unit returns from a step once the output has settled; add your own wait if the sensor needs one.
- The photon flux is that of the whole channel spectrum, not of a narrow band. For a narrow band, filter, or
  correct with the measured spectrum (`step` does not keep the spectrum; read it with `rs7.spectrum(...)` in the
  loop body).
- Only channels with a nominal wavelength inside `start` to `end` are used.

## Dimming

`rs7 dimming` shows how the unit behaves as the drive level changes. It restores the earlier channel powers
afterwards. `--levels` takes a comma-separated list in % (default `1,2,5,10,20,50,100`); `--csv FILE` writes the
rows.

**Whole spectrum** (the default): scales the present spectrum with `OUT` and reads the result. Rows: `level`,
`actual` (the output the monitor photodiode measures, `OUTA`), `photometric`, `x`, `y`, `cct` and `centroid_nm`.
It shows whether the color changes when you dim, and how well the nominal level and the measured one agree.

```
rs7 dimming
rs7 dimming --levels 1,5,10,50,100 --csv dim.csv
```

**One channel** (`--channel N`): channel N alone, others off. Rows: `level`, `radiometric`, `photon_flux`,
`centroid_nm`, `peak_nm` and `fwhm_nm`.

```
rs7 dimming --channel 4 --levels 10,50,100
```

Measured on channel 4 (green):

| Drive level | Radiometric (uW/cm2/sr) | Per % | Centroid (nm) | FWHM (nm) |
|---|---|---|---|---|
| 10 % | 192.7 | 19.3 | 520.2 | 27.8 |
| 50 % | 987.9 | 19.8 | 512.5 | 30.2 |
| 100 % | 1997.6 | 20.0 | 508.9 | 33.3 |

The radiant power is not exactly proportional to the drive level (19.3 to 20.0 uW/cm2/sr per %), and the green
LED shifts about 11 nm to shorter wavelength and gets broader as the current rises. This is why
`rs7 mono --photons` iterates and why the local fit corrects its model against the measured spectrum
([Local fit vs firmware fit](colorimetry.md#local-fit-vs-firmware-fit)).

In Python, `dimming(rs7, levels=None, channel=None)` is a generator of dicts, one per level.

## Monitoring and stability

`rs7 monitor` reads the unit at a fixed interval and changes nothing on it. It is for warm-up and drift
measurements. `--interval` is the time between readings in seconds (default 10), `--duration` the total time
(default 600; 0 runs until Ctrl+C), `--csv FILE` the log. The file is rewritten after every reading, so it is
current while the run is going and complete after Ctrl+C.

```
rs7 monitor --interval 10 --duration 600 --csv log.csv
rs7 monitor --interval 60 --duration 0 --csv overnight.csv
```

Columns: `time_s`, `output` (the set output, `OUT`), `actual` (`OUTA`, measured by the monitor photodiode), `x`,
`y`, `cct`, `led_temp_c` and `monitor_temp_c`. Output and `actual` are in photometric units. `x`, `y` and `cct`
are empty when the unit reports an error for them (for example when there is no light).

`actual` against `output` shows how much the output drifts from what was set. The temperatures are those of
the TECs (`TMP`): the LED board and the wavelength monitor. The unit tested does not have the optional wavelength
monitor (MON) fitted, so its second temperature (`monitor_temp_c`) is not meaningful.

In Python, `monitor(rs7, interval=10.0, duration=600.0, units=Units.PHOTOMETRIC)` is a generator of dicts that
sleeps between readings; stop it by leaving the loop.

## Snapshots

A snapshot is the state of the unit in a JSON file: the channel powers, and the spectrum and colorimetry they
give.

```
rs7 save state.json --note "D65 500 cd/m2 before the test"
rs7 restore state.json
```

`rs7 save` changes nothing on the unit. `rs7 restore` switches all channels off, sets the saved channel powers, and
puts the units and the wavelength range back. It refuses a snapshot from another LED board. It is a way to
leave the unit exactly as you found it after an experiment. The GUI has the same under **File > Save Snapshot / Restore Snapshot** ([GUI](gui.md#file-menu)).

The JSON file has these fields:

| Field | Meaning |
|---|---|
| `time` | ISO 8601, local time |
| `board` | LED board serial number |
| `units` | The unit's units setting (`UNI`) at the time |
| `wavelength_range` | `[start, end]` in nm (`WLR`) |
| `powers` | `{channel: power}`, in % (internal units); only channels that are on |
| `spectrum` | `[[nm, value], ...]` for 360-830 nm, uW/cm2/nm (or /sr) |
| `photometric`, `xy`, `cct` | Colorimetry of that spectrum, computed on the PC |
| `note` | Free text |

```python
from rs7 import RS7
from rs7.snapshot import Snapshot, restore, take

with RS7() as rs7:
    snap = take(rs7, note="before the test")
    snap.save("state.json")
    # ... change the unit ...
    restore(rs7, Snapshot.load("state.json"))
```

The spectrum in a snapshot can also be shown in the GUI as a reference ([GUI](gui.md#reference-spectra)).
`examples/08_snapshot.py` is a complete script.
