# Camera color accuracy

The RS-7 can light a color chart with a known spectrum, which makes it a reference for testing how accurately a
camera reproduces color. The package takes raw frames from a camera, finds the 24 patches of an X-Rite
ColorChecker Classic in them, and compares the colors the camera measures with the colors the patches should
have under the light the RS-7 is actually emitting. The result is a color difference (CIE ΔE2000) per patch and
per light.

| Module | What it does |
|---|---|
| `rs7.camera` | `PicamWeb`: client of the camera service. Raw frames, camera controls, Bayer means. |
| `rs7.chart` | `ChartGeometry`: where the 24 patches are in the raw image, and the overlay PNG used to check it. |
| `rs7.colorcheck` | `color_accuracy()`: makes the lights, captures, fits the color matrix and scores it. |

The CLI commands are `rs7 camera`, `rs7 chart` and `rs7 colorcheck` ([Command line](cli.md)). They need no
extra dependency beyond the core package (the camera client uses only the standard library and numpy).

## Setup

The numbers on this page were measured with

- an ams Mira220 color sensor (1600 x 1400 pixels, Bayer pattern GRBG, 12-bit raw) on a Raspberry Pi,
- an X-Rite ColorChecker Classic (24 patches),
- the RS-7 as the only light on the chart.

The chart has to be lit by the RS-7 alone: other light (room lights, a screen) adds to the chart and the
reference is computed from the RS-7's spectrum only. Cover or switch off everything else, and keep the chart
flat and square to the camera, with the camera and chart fixed during the run.

### The camera service

A camera can be opened by one process only, and on the Pi that process is the **picam-web** service (a FastAPI
application listening on port 80). The package therefore does not open the camera itself; it talks to the
service over HTTP. This also means the PC does not need to be the machine the camera is plugged into. The
service has to be running, reachable from the PC, and the camera must be in a raw mode that gives Bayer data.
The package uses these parts of its API:

| Endpoint | Used for |
|---|---|
| `/api/info` | Sensor model, sensor modes and the present mode (`rs7 camera`) |
| `/api/metadata` | Metadata of the latest frame: `ExposureTime` (us), `AnalogueGain`, `SensorBlackLevels` |
| `/api/controls` | Read and set the camera controls: auto exposure, exposure time, gain |
| `/api/capture/raw` | Raw frames, returned as an `.npz` file |

The `.npz` has the array `frames` (`uint16`, shape N x height x width, already in the digital numbers (DN) of
the 12-bit mode, so 0 to 4095), the JSON `metadata` of every frame, and a JSON `raw` entry with the bit depth.
The black level in the metadata is given in 16-bit units; the package scales it to the mode's bit depth (225 DN
for 3600 in 16-bit units here).

The URL of the service is `--camera URL` on the command line, or the environment variable `RS7_CAMERA`. The
default is `http://10.61.100.206`. In Python it is the argument of `PicamWeb(url)`.

The package changes the camera controls during a measurement (auto exposure off, a fixed exposure time and
gain) and puts them back afterwards, also if the run fails: `PicamWeb.manual_exposure()` is a context manager
that stores the controls before and restores them on exit.

## Chart geometry

The geometry is the position of the centers of the four corner patches in raw pixel coordinates, in the order
top-left (patch 1, dark skin), top-right (patch 6, bluish green), bottom-right (patch 24, black) and
bottom-left (patch 19, white). The other 20 patch centers follow from a projective mapping (homography) of the
regular 4 x 6 grid onto these four points, so a chart that is rotated or seen at a slight angle still works.
Patches are numbered 1 to 24 row by row from the top-left; white is 19 and black is 24.

The default for the lab setup is

| Corner | x | y |
|---|---|---|
| Top-left | 503 | 603 |
| Top-right | 1310 | 552 |
| Bottom-right | 1327 | 1043 |
| Bottom-left | 535 | 1063 |

In each patch a square region of interest (ROI) is measured. Its side is 35 % of the local patch pitch, so it
stays well inside the patch and away from the edges. Position and size are rounded to even pixels, which keeps
the Bayer phase: every ROI starts on the same color site and contains the same number of pixels of each color.
In an ROI the R, G and B means are taken from the pixels of that color (G from both green sites), so no
demosaicing is involved.

Check the placement before measuring:

```
rs7 chart --png chart.png
rs7 chart --corners "503,603 1310,552 1327,1043 535,1063" --png chart.png
```

`rs7 chart` captures one frame at the present camera settings, writes an overlay PNG and prints the R, G and B
means of each patch. In the PNG every 2 x 2 Bayer cell is one pixel; the brightness is stretched and a gamma of
2.2 applied, so it shows where things are, not true colors. The measured squares are drawn in yellow and patch 1
has a red marker in its corner. All 24 squares must lie inside their patches; if not, give new corners from the
pixel positions in the image (they are the raw coordinates, twice the position in the PNG, which has half the
resolution) and look again. `--corners` saves the geometry in `~/.rs7/chart.json`, where `rs7 colorcheck` and
`ChartGeometry.load()` read it.

The table printed by `rs7 chart` marks a patch as `saturated` if any pixel in its ROI is at 98 % of full scale or
higher, and as `too dark` if its brightest channel is below 1 % of the usable range (full scale minus the black
level). Such a patch is not used in the fit and does not count in the statistics below. At the exposure the
camera happens to have, the white patch may well be clipped; `rs7 colorcheck` sets its own exposure.

## Method

For each illuminant the package does the following.

1. **Light.** The RS-7 makes the illuminant with `match()` (the local fit by default, `--method firmware`
   possible), at the present level or at `--level`. The spectrum of the light is the RS-7's own measurement of its
   output, `S(λ)`, not the ideal illuminant. It also gives the CCT and the Δu'v' between the output and the
   target.
2. **Exposure.** The exposure time is adjusted so that the brightest channel of the white patch is about 60 % of
   full scale. The camera starts from its present exposure and each capture refines the estimate (the response
   is linear), with at most 4 captures. If the white patch is clipped, the exposure is halved. The gain is not
   changed.
3. **Capture.** `--frames` raw frames (default 4) are taken at that exposure and averaged.
4. **Camera color.** For each patch the mean R, G and B in the ROI, minus the black level, is divided by the
   exposure time `t` and the gain `g`:

   ```
   c = (mean DN - black level) / (t x g)
   ```

   `c` is linear in the light (no gamma) and does not depend on the exposure, so captures at different
   exposures can be compared.
5. **True color.** The reflectance spectra `R_j(λ)` of the 24 patches are those of "ColorChecker N Ohta" in
   colour-science (380 to 780 nm). With the 2 degree observer functions `x̄, ȳ, z̄`,

   ```
   XYZ_j = k x sum( S(λ) R_j(λ) [x̄ ȳ z̄](λ) )          k = 100 / sum( S(λ) ȳ(λ) )
   ```

   so that a perfect white reflector (R = 1) has Y = 100. Its tristimulus value is the white point of the light,
   `XYZ_w`.
6. **Fit.** A 3 x 3 matrix `M` (camera RGB to XYZ, no offset term) is fitted by least squares to the patches
   that count:

   ```
   M = argmin  sum_j | M c_j - XYZ_j |^2
   ```

   A patch counts if it is not clipped (peak below 98 % of full scale) and not too dark (below 1 % of the usable
   range). The fit minimizes the error in XYZ, not in ΔE, so the bright patches weigh more. If the white patch
   itself is clipped or too dark, the run stops with a message.
7. **Error.** For each patch the XYZ from the camera, `M c_j`, and the true `XYZ_j` are converted to CIELAB with
   the white point `XYZ_w` of the light, and the CIE ΔE2000 between them is taken. Mean, median and maximum are
   over the patches that count.

The camera RGB is not converted with a matrix that is known in advance: the matrix is fitted to the same
patches it is then scored on. The error is therefore what is left over when a single linear 3 x 3 transform is
the best that can be done, not an error to be expected for an unseen scene.

### One matrix for several lights

A color matrix depends on the light, because the camera's spectral sensitivities do not match the observer's.
To see how much it matters, the matrix fitted under the first light is also used under each other light. The
camera RGB of every patch is first multiplied per channel so that the white patch reads as it did under the
first light (a von Kries white balance on the white patch; this also removes any difference in brightness), then
transformed with `M`. The result is compared with the true colors under the second light, in CIELAB each
against its own white point. This is `cross_accuracy()`, and the second table of `rs7 colorcheck`.

### Restoring the setup

The RS-7 state (channel powers, units, wavelength range) is saved in a snapshot before the first light and put
back at the end, also when the run fails or is interrupted. The camera controls are restored too (see above). A
run does change the light while it is running, so do not start it when something else depends on the RS-7.

## Running it

```
rs7 camera                                  # model, mode, exposure, gain, black level
rs7 chart --png chart.png                   # check where the chart is
rs7 colorcheck                              # D65, A and LED-B3 at the present level
rs7 colorcheck --illuminants D65,A --frames 8 --csv results.csv
```

`rs7 camera` only reads. `rs7 chart` captures one frame but changes no setting. `rs7 colorcheck` changes the light
and the camera exposure and restores both. A run with three lights takes about one minute. The options and the
tables printed are described in [Command line](cli.md#colorcheck).

In Python:

```python
from rs7 import RS7
from rs7.camera import PicamWeb
from rs7.chart import ChartGeometry
from rs7.colorcheck import color_accuracy

cam = PicamWeb("http://10.61.100.206")
with RS7() as rs7:
    result = color_accuracy(rs7, cam, ChartGeometry.load(), ["D65", "A"])

for res in result.illuminants:
    a = res.accuracy
    print(res.illuminant, f"mean {a.mean:.2f}  median {a.median:.2f}  max {a.max:.2f}")
```

`result.illuminants` has one `IlluminantResult` per light (the patch data, the true XYZ, the fitted matrix and the
`Accuracy`) and `result.cross` the `CrossResult` of the other lights. See [API reference](api.md#camera-rs7camera)
and `examples/09_color_accuracy.py`.

## Measured example

One run on the lab unit (RS-7 LED board LHX0416, firmware 1.09) with the camera and chart described above: local
fit, the present output level kept, 4 frames per light. The exposure was about 87 ms and the white patch about
60 % of full scale. No patch was clipped or too dark.

Matrix fitted and scored under each light:

| Light | CCT (K) | Δu'v' of the light | Mean ΔE | Median ΔE | Max ΔE |
|---|---|---|---|---|---|
| D65 | 6515 | 0.0003 | 4.18 | 4.18 | 7.48 (cyan) |
| A | 2856 | 0.0000 | 3.05 | 2.62 | 8.30 (black 2) |
| LED-B3 | 4107 | 0.0002 | 3.61 | 3.52 | 7.65 (black 2) |

The matrix fitted under D65, used under the other lights after the white balance:

| Light | Mean ΔE | Median ΔE | Max ΔE |
|---|---|---|---|
| A | 6.01 | 5.65 | 12.03 |
| LED-B3 | 4.49 | 4.31 | 8.11 |

For reference, a ΔE2000 below 1 is hardly visible and 2 to 3 is a small difference to a trained eye.

These numbers come from one camera, one lens, one chart and one setup. They are an example of what the method
gives, not a specification of the sensor or of the RS-7.

## Interpretation and limits

The error here is that of a single 3 x 3 matrix, with no lens shading correction and no offset. It contains
more than the camera's color processing:

- **Spectral mismatch.** The camera's R, G and B sensitivities are not a linear combination of the CIE
  observer functions. A matrix cannot remove the resulting error. This measurement does not separate it from
  the other items below.
- **Stray light and flare.** Light scattered in the lens and in the scene lifts dark patches. The black patch
  is the most affected: it has the largest error under A and LED-B3. Its reference is far darker than anything
  else on the chart, so a small additive error is a large color difference there.
- **Non-uniform lighting.** The illumination is not exactly equal over the 24 patches. Without a flat-field
  correction a difference in brightness between patches is read as a color error.
- **Black level.** The black level is subtracted as a constant (225 DN here). Any error in it matters most for
  the dark patches.
- **Reference.** The reflectance spectra are typical values for this chart design, not the spectra of the
  chart that was used, which can differ from them. The spectrum of the light is the RS-7's
  own calibrated model of its output, with its own uncertainty.
- **Fit.** The matrix is fitted in XYZ, not for the smallest ΔE, and the fit is over 24 patches with 9
  coefficients.

One matrix serving several lights costs about 1.5 to 3 ΔE in this example (the mean ΔE under A goes from
3.05 to 6.01, under LED-B3 from 3.61 to 4.49). For accuracy a color matrix per illuminant is better, or an
approach based on the camera's spectral response instead of a matrix.

The same setup can later be used to measure the camera's spectral response (`rs7 scan` with the camera, see
[Scans](tools.md#scans)) and its linearity.
