# GUI

The GUI is built with PySide6 and is an optional part of the package (the `gui` extra, see
[Getting started](index.md#install)). Start it with `rs7-gui`, `rs7 gui` or `python -m rs7.gui`.
The layout follows the manufacturer's SpectralLED Assistant (user manual, section 3); the numbers in brackets are the manual's labels.

![GUI](img/gui.png)

| Area | What it does |
|---|---|
| Output pane (1a) | Power level %, radiance/irradiance, luminance/illuminance, CCT, CIE x, y, centroid. Type a value and press Enter to set it. **Shift+Enter** on a power value keeps the chromaticity. |
| Main power (1b) | Drag to scale the whole spectrum; hold **Shift** to keep the chromaticity. |
| Channel sliders (1c) | One per fitted channel, with its color on top; hover to see its wavelength in the status bar. Scroll sideways for more channels. Sliders only send a value when you move them, never when the program updates them. |
| Abs / Rel (1d) | Show channel powers as absolute %, or relative to the strongest channel. |
| All Off (1e) | Switch every channel off. |
| Spectral plot (1f-1h) | Output spectrum (white); **Plot All Chan** adds each channel in its color; set the plotted range under the plot. |
| Color quality panel | Under the output pane: level, CCT / Duv, u' v', CRI and TM-30 of the present output, and the comparison with the target. See [Color quality](#color-quality). |
| CIE 1931 chart (1i) | The circle is the present chromaticity; click anywhere to move the color there. The Planckian locus is drawn as a gray line with 2000K, 3000, 4000, 6500 and 10k marked, and the target (if any) as a blue cross. |
| Status bar (1j) | Last command and reply; flashes red on an error. Shows "working..." while the unit is busy. |
| Presets (1k) | Pick one in the combo box to load it; **Store Preset** saves the present output; **Delete** deletes the selected one. |
| Alarm box (1m) | Polled every 2 s; red while an alarm is active; click to clear. |

## Settings menu

- **Select COM Port**: connect; the port is remembered (Qt `QSettings`) and reused at the next start. If none is stored, the first RS-7 found is used.
- **Network Address**: connect to a port shared with `rs7 bridge` (`socket://host:5000`).
- **Standard Observer** (2 or 10 degrees), **Peak Type**, **Optical Feedback**, **Working Distance**.
- **Include White Channels in Spectral Fit**.

## Color quality

The **Color quality** panel in the left column is updated every time the output is read. It shows:

| Row | Meaning |
|---|---|
| Level | Photometric level of the output (lux, or cd/m2 for a radiance calibration) |
| CCT / Duv | Correlated color temperature and distance from the Planckian locus (Ohno 2013) |
| u', v' | CIE 1976 chromaticity |
| CRI Ra / R9 | CIE 13.3 general index and the red index R9; hover for R1-R14 |
| TM-30 Rf / Rg | ANSI/IES TM-30-18 fidelity and gamut index |
| Target | With a target pane open: the target and its CCT and Ra |
| Δu'v' to target | Chromaticity distance between output and target: green below 0.001 (about one just-noticeable step), orange below 0.005, red otherwise |
| Spectral RMS | RMS difference of the area-normalized spectra over the fit range, in % of the mean (see [Spectral RMS](colorimetry.md#spectral-rms)) |

The values are computed on the PC from the spectrum the unit reports over 360-830 nm; the definitions are in
[Spectral matching and color quality](colorimetry.md).

## Target spectrum (View > Target Spectrum)

Shows the target pane under the CIE chart. The target is drawn in blue on the spectral plot, scaled to the level
of the output, and as a blue cross on the CIE chart. The Color quality panel then compares the output with it.

| Control | What it does |
|---|---|
| Target | An editable list: a CIE illuminant from the library (D65, A, FL2, LED-B3, ...), or typed `D5000` (CIE daylight, 4000-25000 K) or `3000K` (black body). Press Enter to show it. **CSV...** loads a file with `wavelength, value` lines, any step size. |
| Level | The level to reach, with the units (photometric or radiometric). Empty keeps the present level. |
| As bright as possible (soft limit) | Fit at the highest output the soft limit allows; the level is ignored. |
| Fit range | Wavelengths used for the fit (default 380-780 nm). |
| Correct chromaticity after fit | After the fit, correct the color to the target's exactly (on by default). Costs a little spectral match; see [Why correct_chromaticity](colorimetry.md#why-correct_chromaticity-is-on-by-default). |
| Match | Scale the target to the level, fit the channels, correct the color and set the level. The result line below shows the target, the level reached, Δu'v' and the RS-7's own spectral error (RPE). |

**Settings > Include White Channels in Spectral Fit** applies to the fit. The steps of a match are described
under [How `match` works](colorimetry.md#how-match-works).

The earlier controls (black body CCT, scale factor, Fit To Target, Fit At Max) are gone: type a temperature such
as `3000K` in the Target box, give the level in the Level box and press Match.

## Not (yet) in this GUI

Offline mode with a calibration file, the ColorChecker library, export to CSV, accessory transfer functions
and the iris. All of these can still be reached with `RS7.command()` (the CLI can export a spectrum:
`rs7 spectrum --csv`, and a target and output pair: `rs7 match --csv`). The CIE illuminant library is available
as targets.

## Threading

All communication with the unit runs on a background worker thread, so the window does not freeze while the
RS-7 settles. A "working..." indicator in the status bar shows while a command is in progress.
