# Spectral matching and color quality

The package can make the RS-7 reproduce a target spectrum (a CIE illuminant, a black body or a measured
spectrum from a CSV file) at an absolute level, and it reports the colorimetry and color quality of the
result. The numbers are computed on the PC from the spectrum the unit reports (`OSP`), not taken from the
firmware, so the same metrics are available for the output and for the target and can be compared directly.

| Module | What it does |
|---|---|
| `rs7.illuminants` | Target spectra by name: CIE illuminants, D-series daylight, black bodies, CSV files. |
| `rs7.colorimetry` | `analyze()` computes a `ColorReport` from a spectrum; `compare()` compares an output with a target. |
| `rs7.match` | `match()` fits the RS-7 to a target and returns a `MatchResult`; `measure()` reports the present output and `measure_against()` compares it with a target. |
| `rs7.optimize` | The local fit: solves the channel powers on the PC (the default method of `match()`). |

The CLI commands are `rs7 illuminants`, `rs7 match` and `rs7 measure` ([Command line](cli.md)). The GUI has the
same functions under **View > Target Spectrum** and in the **Color quality** panel ([GUI](gui.md)). The CIE
tables and the metrics come from [colour-science](https://www.colour-science.org/), a core dependency of the
package (it needs numpy); the local fit also needs [SciPy](https://scipy.org/).

## Targets

A target is named by a string (`rs7.illuminants.target_spectrum`):

| Name | Meaning |
|---|---|
| `D65`, `A`, `FL2`, `LED-B3`, ... | Any illuminant in the colour-science CIE library: A, B, C, D50, D55, D60, D65, D75, E, FL1-FL12, FL3.1-FL3.15, HP1-HP5, LED-B1 to LED-B5, LED-BH1, LED-RGB1, LED-V1, LED-V2, ID50, ID65, ISO 7589 and more. Case does not matter. `available()` lists them and `rs7 illuminants` prints them with their CCT, Duv, xy and CRI. |
| `D5000` | CIE daylight (D-series) at that correlated color temperature, 4000 to 25000 K. |
| `3000K`, `BB3000` | Black body (Planck radiator) at that temperature. |
| `path/to/file.csv` | `wavelength, value` lines, any step size; interpolated to 1 nm. |

`target_spectrum(name, start, end)` returns the spectrum at 1 nm steps from `start` to `end`, relative with the
peak set to 1. It is 0 outside the range in which the illuminant is tabulated (some tables cover only
380-780 nm, for example). The absolute level is set later by `match()`.

## Units and conversion

The RS-7 reports spectra in uW/cm2/nm for an irradiance (irradiant) calibration and in uW/cm2/sr/nm for a
radiance (radiant) calibration. The colorimetry functions take such a spectrum as `[(nm, value), ...]` at 1 nm
steps. Photometric values are

```
photometric = 683.002 lm/W x 0.01 x sum( S(lambda) x ybar(lambda) )      (1 nm steps)
```

where 0.01 converts uW/cm2 to W/m2 and `ybar` is the CIE 1931 2 degree color matching function, which is
V(lambda). The result is in lux for an irradiant source and in cd/m2 (nits) for a radiant one. `radiometric` in
the report is `sum(S)` over the analysis range, in uW/cm2 (or uW/cm2/sr).

Which unit applies follows the unit's calibration: the CLI and GUI show lux when the unit is in irradiance mode
(working distance above 0 or calibration type `I`) and cd/m2 otherwise.

## Observers and range

- **Photometric quantities** always use V(lambda), that is `ybar` of the CIE 1931 2 degree observer.
- **CCT, Duv, CRI and TM-30** are defined on the 2 degree observer and always use it.
- **XYZ and xy** use the observer chosen in `analyze(spectrum, observer=2)`; 10 selects the CIE 1964 10 degree
  observer. `match()` and `measure()` use 2.
- The analysis range is 360 to 830 nm, the range of the tabulated observer functions. Data outside is ignored;
  missing wavelengths count as 0. `RS7.spectrum(channel, start, end)` reads that range from the unit.

The target is analyzed over its own range only. A D65 target fitted over 380-780 nm therefore reports a CCT of
6502 K, not the 6504 K of the full CIE table (360-830 nm), while the unit's output, which can emit outside the
fit range, is analyzed over the full 360-830 nm.

## Metrics

### Chromaticity: xy and u'v'

x, y are the CIE 1931 chromaticity coordinates, `x = X / (X + Y + Z)`. u', v' are the CIE 1976 coordinates,

```
u' = 4X / (X + 15Y + 3Z)      v' = 9Y / (X + 15Y + 3Z)
```

The u'v' plane is closer to perceptually uniform than xy, so a distance there is a better measure of how
different two colors look. The package reports

```
delta u'v' = sqrt( (u'_out - u'_target)^2 + (v'_out - v'_target)^2 )
```

A difference of about 0.001 is roughly one just noticeable difference for a side-by-side comparison (a rule of
thumb that depends on the viewing conditions and the observer). The CLI and GUI color the value green below
0.001, orange below 0.005 and red above.

### CCT and Duv

Correlated color temperature is the temperature of the black body whose chromaticity is closest to the
source's, measured in the CIE 1960 (u, v) plane. Duv is the signed distance from the Planckian locus in that
plane; it is positive above the locus (greenish) and negative below (pinkish). The CCT of a source far from the
locus has little meaning, which is why Duv is reported with it (CIE daylight, for example, has a positive Duv of
a few thousandths). The package uses the method of Ohno (`"Ohno 2013"` in colour-science), a cascade
expansion search along the locus described in Ohno (2014). CCT and Duv are `None` if the method fails, for
example for a chromaticity far from the locus.

### CRI: CIE 13.3

`cri_ra` is the CIE general color rendering index Ra of CIE 13.3-1995: the mean of the special indices R1 to R8,
each measuring how far one of eight test color samples moves in the CIE 1964 U*V*W* space when lit by the
source instead of a reference illuminant. The reference is a black body below 5000 K and CIE daylight at and
above it. `cri_r` holds R1-R14; R9 (saturated red) is often the one that matters for LED sources, and is shown
separately in the CLI and GUI. CRI is only defined for sources close to the Planckian locus (CIE 13.3 sets a
chromaticity distance of about 0.0054 in uv), and it is a known weak metric for narrow-band sources. Use TM-30
for a better description.

### TM-30: Rf and Rg

`tm30_rf` (fidelity) and `tm30_rg` (gamut) are the indices of ANSI/IES TM-30-18. They use 99 color evaluation
samples that cover the hue circle more evenly than the 14 CRI samples, computed in the CAM02-UCS color space
with the CIE 224:2017 fidelity formula. Rf is 100 for a perfect match with the reference illuminant (black body
or daylight, blended between 4500 and 5500 K) and Rg compares the area of the gamut of the 99 samples with the
reference (100 means equal; larger is more saturated, smaller less). The package computes them from the
380-780 nm part of the spectrum.

### Spectral RMS

`spectral_rms` measures how closely the shape of the output follows the shape of the target, independent of
level:

1. Take the wavelengths in the target's range (the fit range) at 1 nm steps.
2. Divide the output and the target each by their sum over those wavelengths (equal area, so the level drops
   out).
3. Take the RMS of the difference over the wavelengths and divide it by the mean of the normalized target, in %.

```
spectral RMS = 100 x sqrt( mean( (o_i - t_i)^2 ) ) / mean( t_i )         o, t: area-normalized
```

0 is a perfect match. The RS-7's own error figure (`RPE`, `RS7.rms_error()`, `unit_rms_error` in
`MatchResult`) is the firmware's own, similar spectral RMS error between its output and the target you loaded.
It is not computed the same way as `spectral_rms`, so the two numbers are close but not identical; compare
numbers from the same source. The RPE exists only for the firmware fit; `rs7 measure` and the local fit load
no target in the unit, so `unit_rms_error` is NaN there and `spectral_rms` is the number to use.

### Other values

`peak_nm` is the wavelength of the maximum and `centroid_nm` the power-weighted mean wavelength of the
spectrum. For a single channel or another narrow spectrum, `rs7.spectrum.centroid()` and `fwhm()` give the
centroid and the full width at half maximum, and `photon_flux()` the photon flux
([Spectral tools](tools.md#photon-units)). `compare()` returns `delta_uv_prime`, `delta_cct`, `delta_duv`, `level_ratio` (output over target
photometric level) and `spectral_rms`. `photometric_per_unit(relative, start)` gives the photometric value
of a relative spectrum taken as 1 uW/cm2/nm per unit; `match()` uses it to scale a target to a level.

## How `match` works

`rs7.match.match()` (and `rs7 match`) has two methods: `method="local"` (the default) and `method="firmware"`
(`--method` / `-m` on the command line). With `method="local"`:

1. Build the relative target for the fit range (`start` to `end`, default 380-780 nm).
2. Scale it to the requested level. A photometric level uses `photometric_per_unit`; a radiometric level uses
   the plain sum. With `level=None` the present output level is kept (the maximum is used if the unit is off).
   With `at_max=True` the target is first scaled to a moderate level and the fit then scales it up (step 3).
3. `rs7.optimize.fit()` solves the channel powers on the PC and sets them (see
   [Local fit vs firmware fit](#local-fit-vs-firmware-fit)). It uses the measured spectrum of every channel
   group and corrects itself against the output the unit really gives.
4. Unless `at_max` is set and a level is known, `OUT` sets the exact requested level. If the unit refuses
   because a channel is at its limit, the level the fit reached is kept.
5. `CCS`: color correction to the chromaticity of the target (skipped with `correct_chromaticity=False`). It
   comes last because `OUTC` after `CCS` would undo the correction. At full output `CCS` can hit the soft limit:
   the output is then stepped down to 97, 90 and 80 % until the correction fits; if it never does, the color stays
   as the fit left it and the report shows the remaining error.
6. The output spectrum is read for 360-830 nm and analyzed, the target is analyzed at the level that was actually
   reached, and both are compared. The unit's wavelength range is set back to what it was.

With `method="firmware"` the steps are:

1. Build the relative target for the fit range (`start` to `end`, default 380-780 nm).
2. Scale it to the requested level, as above. With `at_max=True` no scaling is done and the firmware fits at the
   highest output the soft limit allows.
3. Load it into the unit: `WLR` (range), `TSP` (target spectrum).
4. `FTS`: the firmware's least-squares fit of the channel powers to the target. `include_white` adds the white
   channels (it applies to the firmware fit only; the local fit uses every channel).
5. `CCS`: color correction, which moves the output to the chromaticity of the target (skipped with
   `correct_chromaticity=False`).
6. Unless `at_max` is set and a level is known, `OUTC` sets the exact requested level (`OUT` if the color
   correction is off). `OUTC` scales the whole spectrum without changing the chromaticity.
7. `RPE` is read, the output spectrum is read for 360-830 nm and analyzed, the target is analyzed at the level
   that was actually reached, and both are compared. The unit's wavelength range is set back to the fit range.

`measure()` / `measure_against()` (and `rs7 measure`) do only the last step: it reads the present output, analyzes it, and
optionally compares it with a target scaled to the same level. It changes nothing on the unit (the wavelength
range is set back after reading the spectrum).

### Why `correct_chromaticity` is on by default

A least-squares fit weights every wavelength equally. The eye does not: the color is dominated by where the
error sits relative to the color matching functions. A fit with a low spectral RMS can therefore still be off in
color. The color correction step adjusts the channel powers until the chromaticity equals the target's, which
moves the spectrum slightly away from the least-squares optimum. It trades a (usually small) increase of the
spectral error for an exact color. With `--no-correct --method firmware` the fit is the firmware's least-squares
result and the color can be off by a few thousandths in u'v' (see the LED-B3 example below). The local fit already
holds the color in its solution (the XYZ rows), so the correction there only removes a small remainder. For a metameric match, where color is what counts,
keep it on; for a study of the spectral shape, turn it off.

### Limits

- The RS-7 has a finite number of LED channels, each with its own center wavelength and bandwidth (`rs7
  channels --all` lists them). It cannot reproduce narrow spectral features: the lines of a fluorescent lamp (FL series),
  the sharp edges of a measured spectrum, or anything finer than the channel spacing and width. The spectral
  RMS of such targets stays large even when color and CRI match well.
- The fit only considers the fit range. A target that has power outside it (D65 beyond 780 nm, for example) is
  compared as if it had none; widen `--start` / `--end` to include more, up to the range the channels cover.
- The soft limit (`rs7 info`) caps the channel power, and with it the highest level a target can reach. Check
  the output level in the report against the level you asked for.
- The reported values are those of the spectrum the unit reads back (`OSP`), so they are only as accurate as
  the unit's calibration of that spectrum.
- Chromaticities far from the Planckian locus have no meaningful CCT, and CRI is not defined for them.

## Local fit vs firmware fit

The RS-7's own fit (`FTS`) is a least-squares fit inside the unit. The local method does the fit on the PC, with
the measured spectrum of each channel, and uses the unit's spectrum readout to correct itself. It is the default
of `match()`, `rs7 match` and the GUI. On the unit tested it gave a closer spectral shape and color than the
firmware fit.

### Method

1. **Basis.** Each channel group's spectrum is measured once, at 70 % drive, over 360-1100 nm. Each group is
   switched on briefly and put back; this takes about 10 s for the 35 groups of the unit tested. The spectra are
   stored per 1 % of power in `~/.rs7/basis-<board>.json` (`ChannelBasis`) and used from then on. They are measured
   again when the LED board or the calibration is different or the range changes, or on request with
   `rs7 basis --remeasure`. `load_basis()` and `measure_basis()` do this in Python.
2. **Bounded least squares.** `solve()` finds the channel powers (0 to the limit) whose summed spectra are closest
   to the target, with `scipy.optimize.lsq_linear`. The rows are:
    - the spectrum over the fit range;
    - three rows for CIE X, Y and Z, weighted by `COLOR_WEIGHT` (50), so color and level are matched and not
      only the shape;
    - rows for the wavelengths outside the fit range, with target 0 and weight `LEAK_WEIGHT` (0.5), to avoid light
      there. Silicon sensors see near infrared, so light outside the fit range can matter.

   Channels with less than 5 % of their power inside the fit range are not used. The powers are limited to 95 % of
   the soft limit, which leaves headroom to trim the level at the end.
3. **Error feedback.** The fit sets the powers and reads the real output spectrum. The basis is only a model: LEDs
   shift in wavelength with drive current, and the basis was measured at one power. The remaining error (target
   minus measured) is added to the target and the problem is solved again, 2 times.
4. **Level, then color.** `OUT` sets the level and `CCS x,y` corrects the color last, because `OUTC` after `CCS`
   would undo the correction.

At maximum output (`at_max`) the local fit scales the target until one channel reaches the limit and keeps the
spectral shape. The firmware lets channels saturate: it gets brighter, but the spectrum is less faithful.

### Measured comparison

One unit (firmware 1.09, radiant calibration, levels in cd/m2). Spectral RMS is over 380-780 nm; "Outside" is the
share of the radiant power outside 380-780 nm, measured over 360-1100 nm.

| Target | Method | Level | Δu'v' | Spectral RMS | Ra | R9 | TM-30 Rf | Outside |
|---|---|---|---|---|---|---|---|---|
| D65 500 cd/m2 | firmware | 500.0 | 0.0003 | 18.7 % | 96.9 | 84.5 | 97.0 | 0.5 % |
| D65 500 cd/m2 | local | 499.7 | 0.0001 | 17.0 % | 97.2 | 90.9 | 97.5 | 1.1 % |
| A 300 cd/m2 | firmware | 300.0 | 0.0003 | 22.8 % | 95.1 | 79.2 | 96.1 | 0.8 % |
| A 300 cd/m2 | local | 300.0 | 0.0000 | 19.5 % | 98.1 | 96.1 | 98.3 | 2.2 % |
| LED-B3 300 cd/m2 | firmware | 300.0 | 0.0003 | 12.9 % | 84.2 | 17.7 | 84.4 | 0.2 % |
| LED-B3 300 cd/m2 | local | 299.8 | 0.0002 | 7.0 % | 85.4 | 22.0 | 85.9 | 0.4 % |
| D50 max | firmware | 41119 | 0.0017 | 12.2 % | 97.5 | 89.4 | 98.8 | 0.9 % |
| D50 max | local | 20432 | 0.0000 | 11.5 % | 99.1 | 98.3 | 98.9 | 1.1 % |

A match takes about 5 s with either method once the basis is cached.

### Trade-offs

- The local fit holds the spectral shape and the color better: a lower spectral RMS in all four cases, a Δu'v' of
  0.0002 or less, and a higher Ra and R9 (R9 96.1 against 79.2 for illuminant A).
- It puts slightly more light outside the fit range: 2.2 % against 0.8 % for illuminant A. The rows with target 0
  limit this but do not remove it. If your sensor sees near infrared, look at this number; use
  `method="firmware"` if it matters.
- At maximum output the firmware is brighter (41119 against 20432 for D50) because it lets channels saturate. The
  local fit keeps the shape and reaches the exact color; it is the better choice when the spectrum matters more
  than the last factor of 2 in level.
- The local fit needs SciPy and the cached basis; the first match on a new unit or LED board takes about 10 s longer.

```
rs7 match D65 --level 500                     # local (default)
rs7 match D65 --level 500 --method firmware   # the RS-7's own fit
rs7 basis                                     # show the measured channel spectra
```

## Validation

### Unit tests (no hardware)

`tests/test_colorimetry.py` checks the local computation against published values:

| Check | Published value |
|---|---|
| D65 | x, y = 0.3127, 0.3290; CCT 6504 K; CRI Ra 100 |
| Illuminant A | x, y = 0.4476, 0.4074; CCT 2856 K; Duv 0; CRI Ra 100 |
| FL2 | CRI Ra 64 (CIE 15); TM-30 Rf 70; CCT about 4230 K |

### Measured on a unit

These were measured on one RS-7 (firmware 1.09, radiant calibration, so cd/m2). They show what to expect, not a
specification of the instrument.

**Local analysis against the firmware**, for the same output:

| | Local (this package) | RS-7 firmware |
|---|---|---|
| Luminance | 1631 cd/m2 | 1631.2 cd/m2 |
| x, y | 0.3549, 0.3894 | 0.3549, 0.3894 |
| CCT | 4806 K | 4805.6 K |

**D65 at 500 cd/m2** with the firmware fit (`rs7 match D65 --level 500 --method firmware`): level 500 cd/m2, CCT 6491 K (the target gives 6502 K over
380-780 nm), Duv +0.0030, delta u'v' 0.0003, CRI Ra 96.9, R9 84.5, TM-30 Rf 97.0, Rg 99.9, spectral RMS 18.7 %
(RS-7 RPE 18.31 %).

**Illuminant A at maximum output**, firmware fit (`rs7 match A --max --method firmware`): 18470 cd/m2, CCT 2855 K, delta u'v' 0.0001, Ra 97.8,
Rf 98.2.

**LED-B3 without color correction**, firmware fit (`rs7 match LED-B3 --level 300 --no-correct --method firmware`): delta u'v' 0.0026, Ra 83.7
against 84.8 for the target. The runs above with the correction on have delta u'v' of 0.0001 to 0.0003.
The same targets with the local fit are in [Local fit vs firmware fit](#measured-comparison).

For D65 the color and the rendering indices are close to the target while the spectral RMS is 17 to 19 %: the
spectrum is not identical, which is the limit of a finite set of LED channels (see Limits).

## Example

```python
from rs7 import RS7, Units
from rs7.match import match, measure

with RS7() as rs7:
    result = match(rs7, "D65", level=500, units=Units.PHOTOMETRIC)  # method="local" is the default
    print(result.output.cct, result.output.duv, result.comparison.delta_uv_prime)
    print(result.output.cri_ra, result.output.tm30_rf, result.comparison.spectral_rms)

    fw = match(rs7, "D65", level=500, method="firmware")  # the RS-7's own fit
    print(fw.comparison.spectral_rms, fw.unit_rms_error)  # unit_rms_error (RPE) is only set for this method

    report = measure(rs7)  # read-only
    print(report.xy, report.cri_r[9])
```

`examples/04_match_illuminant.py` and `examples/06_color_report.py` are complete scripts.

## References

- CIE 15:2018, *Colorimetry*, 4th edition (CIE 1931 and 1964 observers, u'v', illuminants A and D65, D-series).
- CIE 13.3-1995, *Method of Measuring and Specifying Colour Rendering Properties of Light Sources* (CRI, R1-R14).
- ANSI/IES TM-30-18, *IES Method for Evaluating Light Source Color Rendition* (Rf, Rg); fidelity formula from
  CIE 224:2017.
- Y. Ohno, "Practical Use and Calculation of CCT and Duv", *LEUKOS* 10(1), 47-55 (2014).
- T. Mansencal et al., [colour-science](https://www.colour-science.org/), the Python library used for the CIE
  tables, CCT/Duv, CRI and TM-30.
