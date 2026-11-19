"""Web interface (FastAPI): control the RS-7 from a browser. Start with ``rs7 web``.

One RS-7 connection is shared by all browsers. Serial access is not thread-safe, so every unit call runs under
one lock; the endpoints are plain ``def`` functions, which FastAPI runs in a thread pool. There is no login:
use it on a trusted network only.
"""

from __future__ import annotations

import dataclasses
import math
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..device import RS7, RS7Error, Units
from ..illuminants import available, describe
from ..match import match
from ..spectrum import SPECTRAL_LOCUS, cct_to_xy, wavelength_to_rgb
from ..state import read_state

T = TypeVar("T")
STATIC = Path(__file__).parent / "static"
PRESET_NUMBER = PathParam(ge=0, le=99)
PLANCKIAN_MARKS = ((2000, "2000K"), (3000, "3000"), (4000, "4000"), (6500, "6500"), (10000, "10k"))


class ChannelRequest(BaseModel):
    channel: int
    power: float = Field(ge=0, le=100)  #: % of the channel's capability


class OutputRequest(BaseModel):
    level: float = Field(ge=0, le=100)  #: main power level, %
    keep_chromaticity: bool = False


class PresetRequest(BaseModel):
    name: str = ""


class MatchRequest(BaseModel):
    target: str = Field(min_length=1)  #: illuminant name, D<CCT> or <T>K
    level: float | None = Field(default=None, gt=0)  #: None keeps the present level
    units: Literal["photometric", "radiometric"] = "photometric"
    at_max: bool = False
    start: int = Field(default=380, ge=360, le=1100)
    end: int = Field(default=780, ge=360, le=1100)
    method: Literal["local", "firmware"] = "local"
    correct_chromaticity: bool = True


def clean(value: Any) -> Any:
    """Turn dataclasses, tuples and NaN/inf into something ``json`` accepts (NaN becomes ``null``)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def check_target(name: str) -> None:
    """The web page may only use library illuminants, D<CCT> and <T>K, never a file on the server."""
    if Path(name).is_file():
        raise HTTPException(400, "A target file is not supported here; use an illuminant name, D5000 or 3000K")


def create_app(rs7: RS7) -> FastAPI:
    """The web app for an open unit. All calls to ``rs7`` are made one at a time."""
    app = FastAPI(title="RS-7 Control", version=__version__)
    lock = threading.Lock()

    def call(action: Callable[[RS7], T]) -> T:
        """Run ``action(rs7)`` while holding the lock; errors of the unit become HTTP errors."""
        with lock:
            try:
                return action(rs7)
            except TimeoutError as e:  # before OSError, which it is a subclass of
                raise HTTPException(504, "The RS-7 did not answer") from e
            except (RS7Error, ValueError) as e:
                raise HTTPException(400, str(e)) from e
            except OSError as e:
                raise HTTPException(503, f"Connection to the RS-7 failed: {e}") from e

    channels = call(lambda r: r.channel_info())
    call(lambda r: r.set_units(Units.INTERNAL))

    @app.get("/api/info")
    def info():
        def read(r: RS7):
            irradiant = r.working_distance() > 0 or r.calibration_type() == "I"
            return r.version(), r.led_board_serial(), irradiant

        version, serial, irradiant = call(read)
        return clean(
            {
                "version": version,
                "serial": serial,
                "package_version": __version__,
                "rad_label": "Irradiance" if irradiant else "Radiance",
                "lum_label": "Illuminance" if irradiant else "Luminance",
                "phot_unit": "lux" if irradiant else "cd/m2",
                "channels": [
                    {
                        "channel": c.channel,
                        "wavelength": c.nominal_wavelength,
                        "fwhm": c.nominal_fwhm,
                        "color": "#{:02x}{:02x}{:02x}".format(*wavelength_to_rgb(c.nominal_wavelength)),
                    }
                    for c in channels
                ],
                "illuminants": available(),
                "locus": SPECTRAL_LOCUS,
                "planckian": [cct_to_xy(1667 * (25000 / 1667) ** (i / 60)) for i in range(61)],
                "planckian_marks": [[label, *cct_to_xy(t)] for t, label in PLANCKIAN_MARKS],
            }
        )

    @app.get("/api/state")
    def get_state(
        plot_all: bool = False,
        start: int = 380,
        end: int = 780,
        target: str = "",
        fit_start: int = 380,
        fit_end: int = 780,
    ):
        """Output readings, spectrum and color quality; with ``target`` also that target and the comparison."""
        if not 360 <= start < end <= 1100 or not 360 <= fit_start < fit_end <= 1100:
            raise HTTPException(400, "The wavelength range must lie within 360-1100 nm, start below end")
        target = target.strip()
        if target:
            check_target(target)
        wanted = (target, fit_start, fit_end) if target else None
        st = call(lambda r: read_state(r, start, end, [c.channel for c in channels], plot_all, True, wanted))
        if "target" in st:
            spectrum, report, comparison = st["target"]
            st["target"] = {
                "description": describe(target),
                "spectrum": spectrum,
                "report": report,
                "comparison": comparison,
            }
        return clean(st)

    @app.post("/api/channel")
    def set_channel(req: ChannelRequest):
        call(lambda r: r.set_channel_power(req.channel, req.power))
        return {"ok": True}

    @app.post("/api/output")
    def set_output(req: OutputRequest):
        call(lambda r: r.set_output(req.level, Units.INTERNAL, keep_chromaticity=req.keep_chromaticity))
        return {"ok": True}

    @app.post("/api/all_off")
    def all_off():
        call(lambda r: r.all_off())
        return {"ok": True}

    @app.get("/api/presets")
    def get_presets():
        presets, current = call(lambda r: (r.presets(), r.current_preset()))
        loaded = current.split(",")[0]
        return {
            "presets": [{"number": n, "name": name} for n, name in sorted(presets.items())],
            "current": int(loaded) if loaded.isdigit() else None,
        }

    @app.post("/api/presets/{number}/recall")
    def recall_preset(number: int = PRESET_NUMBER):
        call(lambda r: r.recall_preset(number))
        return {"ok": True}

    @app.put("/api/presets/{number}")
    def store_preset(req: PresetRequest, number: int = PRESET_NUMBER):
        call(lambda r: r.store_preset(number, req.name.strip()))
        return {"ok": True}

    @app.delete("/api/presets/{number}")
    def delete_preset(number: int = PRESET_NUMBER):
        call(lambda r: r.delete_preset(number))
        return {"ok": True}

    @app.post("/api/match")
    def run_match(req: MatchRequest):
        """What the GUI's Match button does (``include_white`` on, as in the GUI's default)."""
        check_target(req.target)
        units = Units.PHOTOMETRIC if req.units == "photometric" else Units.RADIOMETRIC
        args = (
            req.target,
            req.level,
            units,
            req.at_max,
            req.start,
            req.end,
            True,
            req.correct_chromaticity,
            req.method,
        )
        result = call(lambda r: match(r, *args))
        return clean(
            {
                "target_name": result.target_name,
                "description": describe(result.target_name),
                "output": result.output,
                "target": result.target,
                "comparison": result.comparison,
                "unit_rms_error": result.unit_rms_error,
            }
        )

    @app.get("/api/alarm")
    def get_alarm():
        return {"alarm": call(lambda r: r.alarm())}

    @app.post("/api/alarm")
    def clear_alarm():
        call(lambda r: r.clear_alarm())
        return {"alarm": call(lambda r: r.alarm())}

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app


def main(port_name: str | None = None, host: str = "0.0.0.0", port: int = 8000) -> None:
    """Open the unit (``port_name``: serial port or ``socket://host:5000``; default: the first RS-7 found)
    and serve the web interface until interrupted."""
    import uvicorn

    rs7 = RS7(port_name)
    try:
        uvicorn.run(create_app(rs7), host=host, port=port)
    finally:
        rs7.close()


__all__ = ["create_app", "main"]
