# Web interface

`rs7 web` serves a web page that controls the RS-7 from any browser on the network, including a phone. It does what
the [GUI](gui.md) does for everyday work (sliders, spectrum, presets, target match, color quality), without needing
PySide6 or a display, so it suits a headless Raspberry Pi next to the unit.

!!! warning "No login"
    Anyone who can reach the page can change the light, store and delete presets and clear alarms. Use it on a
    trusted lab network only. It listens on every interface (`0.0.0.0`) by default; use `--host 127.0.0.1` to
    allow this machine only. There is one unit and one shared state: with several browsers open, the last
    write wins.

## Install and start

The web interface is the `web` extra (FastAPI and uvicorn):

    uv tool install "gammascientific-rs7[web] @ git+https://gittf.ams-osram.info/cis_solutions/hardware/gammascientific-rs7.git"

**On the Raspberry Pi with the unit plugged in** (serial port `/dev/ttyUSB0`):

    rs7 web --device /dev/ttyUSB0

Without `--device` the first RS-7 found is used (the global `--port` / `-p` or `RS7_PORT` also work). Open
`http://<pi address>:8000` in a browser, for example `http://10.61.100.206:8000`.

**On a PC, with the unit shared by `rs7 bridge`** on the Pi (see [Getting started](index.md#using-the-rs-7-from-another-machine)):

    rs7 web --device socket://10.61.100.206:5000

then open `http://localhost:8000`. The bridge accepts one client, so the web page and, for example, `rs7-gui`
cannot use the same bridge at the same time. The same holds for a serial port: only one program can have it open.

Options: `--host` (default `0.0.0.0`), `--port` (default 8000), `--device`. Stop with Ctrl+C. The connection is
opened when the server starts; if the unit is switched off or unplugged, restart `rs7 web`.

### Start at boot (Raspberry Pi)

To have the page always available, run it as a systemd service. Save as `/etc/systemd/system/rs7-web.service`,
adjusting `User` and the path of `rs7` (`which rs7`):

    [Unit]
    Description=RS-7 web interface
    After=network.target

    [Service]
    User=pi
    ExecStart=/home/pi/.local/bin/rs7 web --device /dev/ttyUSB0
    Restart=on-failure
    RestartSec=5

    [Install]
    WantedBy=multi-user.target

Then enable it with `sudo systemctl enable --now rs7-web`, and follow the log with `journalctl -u rs7-web -f`. The
user must be allowed to use the serial port (group `dialout`). `Restart=on-failure` also brings the page back
after the unit was unplugged and plugged in again.

## The page

| Area | What it does |
|---|---|
| Output | Power level %, radiance and luminance (irradiance and illuminance for an irradiance calibration), CCT, CIE x and y, read from the unit. **Main power** scales the whole spectrum; tick **keep chromaticity** to touch up the color while doing so (the GUI's Shift). **All Off** switches every channel off. |
| Output spectrum | The output spectrum, drawn in the plotted range (default 380-780 nm). **plot all channels** adds each channel's own spectrum in its color. If a target is entered, it is drawn in blue. |
| Channels | One slider per channel with its wavelength color, 0-100 %. Moving a slider sends the value (at most about every 150 ms, and the final value when you let go); the page never sends back what it only displays. |
| Color quality | Level, CCT / Duv, u', v', CRI Ra / R9, TM-30 Rf / Rg of the present output, and the target's CCT and Ra, the chromaticity difference Δu'v' to the target (green below 0.001, orange below 0.005, red above) and the spectral RMS. See [Spectral matching and color quality](colorimetry.md). The CIE 1931 chart shows the present chromaticity (circle), the target (blue cross) and the Planckian locus. |
| Target match | Fits the channels to a target, as the GUI's **Target Spectrum** pane (and `rs7 match`) does. **Target**: a CIE illuminant from the list (D65, A, FL2, ...), `D5000` for CIE daylight at that CCT, or `3000K` for a black body. **Level**: empty keeps the present level, otherwise photometric (lux or cd/m2) or radiometric; **as bright as possible** uses the soft limit instead. **Fit range** in nm (default 380-780). **Fit with**: the local optimizer (solved on the PC; the first run on a unit measures every channel, about 25 s) or the RS-7 firmware. **correct chromaticity** (on by default) adjusts the color after the fit. The result line shows the reached level, Δu'v' and the spectral RMS. A CSV file as target is not available in the web page; use `rs7 match` or the GUI. |
| Presets | The stored presets; the loaded one is marked. **Recall** loads the selected preset, **Delete** deletes it (after a confirmation). **Store** saves the present output as the given number (0-99) and name; an existing number is only overwritten after a confirmation. |
| Alarm | Top right, red while the unit reports an alarm; click it to clear the alarm. |
| Status line | Bottom of the page: the last action, or the error message (red) when the unit refuses something. |

The page reads the unit again after every change and every 2.5 s, so changes made elsewhere show up too. While a
match runs the page waits for it.

## API

The page uses a small JSON API under `/api`, which you can also call from scripts (interactive documentation is at
`/docs`).

| Request | What it does |
|---|---|
| `GET /api/info` | Firmware, LED board serial, channels (wavelength, FWHM, color), unit labels, illuminant names |
| `GET /api/state?plot_all=0&start=380&end=780&target=D65&fit_start=380&fit_end=780` | Power, radiance, luminance, CCT, xy, channel powers, spectrum, color quality, and with `target` the target spectrum and comparison |
| `POST /api/channel` `{channel, power}` | Set one channel, % |
| `POST /api/output` `{level, keep_chromaticity}` | Set the main power level, % |
| `POST /api/all_off` | All channels off |
| `GET /api/presets`, `POST /api/presets/{n}/recall`, `PUT /api/presets/{n}` `{name}`, `DELETE /api/presets/{n}` | List, recall, store, delete presets (n is 0-99) |
| `POST /api/match` `{target, level, units, at_max, start, end, method, correct_chromaticity}` | Fit to a target; returns the output and target color reports and the comparison |
| `GET /api/alarm`, `POST /api/alarm` | Read the alarm, clear it |

Errors are returned as `{"detail": "<message>"}`, and the page shows the message:

| Status | Meaning |
|---|---|
| 400 | The unit refused the command, or a value is wrong (for example a target file, or a wavelength range outside 360-1100 nm) |
| 422 | The request body or a parameter has the wrong type or is out of range (for example a preset number above 99) |
| 503 | The connection to the unit failed (unplugged, bridge gone) |
| 504 | The unit did not answer in time |

All calls to the unit are made one at a time, so a long match delays other requests until it is done.

Examples with `curl`:

    curl http://10.61.100.206:8000/api/state
    curl -X POST http://10.61.100.206:8000/api/output -H 'Content-Type: application/json' -d '{"level": 50}'
    curl -X POST http://10.61.100.206:8000/api/match -H 'Content-Type: application/json'          -d '{"target": "D65", "level": 500, "units": "photometric"}'

## Troubleshooting

| Symptom | Cause and remedy |
|---|---|
| `rs7 web` stops at start with a port or device error | No RS-7 found, or another program (`rs7-gui`, a bridge client, a second `rs7 web`) has the serial port or bridge. Close it, or pass `--device`. |
| `The web interface needs FastAPI` | Install the `web` extra, see [Install and start](#install-and-start). |
| `Address already in use` | Another program uses port 8000; choose another with `--port`. |
| Page does not load from another computer | The server was started with `--host 127.0.0.1`, or a firewall blocks the port. |
| Status line turns red with "Connection to the RS-7 failed" | The unit was switched off or unplugged. Restart `rs7 web` (or let systemd do it). |
| A match seems to hang | The first local-optimizer run measures every channel, about 25 s; the page waits for it. |
