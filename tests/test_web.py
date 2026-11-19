import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from rs7 import ChannelInfo, RS7Error, Units, web
from rs7.colorimetry import analyze, compare
from rs7.match import MatchResult


class FakeRS7:
    """Stands in for RS7: keeps a little state, records what the web app asks for."""

    def __init__(self):
        self.units = Units.INTERNAL
        self.powers = {1: 10.0, 2: 0.0}
        self.level = 25.0
        self.range = (380, 780)
        self.calls = []
        self.alarm_text = "NONE"
        self.fail_with: Exception | None = None
        self.stored = {0: "warm", 3: "cool"}
        self.current = "NONE"
        self.busy = 0
        self.max_busy = 0

    def _enter(self):
        self.busy += 1
        self.max_busy = max(self.max_busy, self.busy)
        time.sleep(0.01)
        self.busy -= 1

    def channel_info(self):
        return [ChannelInfo(1, 450.0, 20.0, 450.0, 20.0), ChannelInfo(2, 620.0, 15.0, 0.0, 0.0)]

    def set_units(self, units):
        self.units = units

    def working_distance(self):
        return 0

    def calibration_type(self):
        return "R"

    def version(self):
        return "1.2.3"

    def led_board_serial(self):
        return "SN42"

    def channel_powers(self):
        return {c: p for c, p in self.powers.items() if p > 0}

    def output(self, units=None):
        self._enter()
        return {Units.INTERNAL: self.level, Units.RADIOMETRIC: 7.0, Units.PHOTOMETRIC: 500.0}[units or self.units]

    def chromaticity(self):
        return 0.3127, 0.3290

    def cct(self):
        return 6504.0

    def set_wavelength_range(self, start, end):
        self.range = (start, end)

    def spectrum(self, channel=0, start=None, end=None):
        if start is not None and end is not None:
            self.set_wavelength_range(start, end)
        start, end = self.range
        return [(nm, 1.0 if channel == 0 else 0.5) for nm in range(start, end + 1)]

    def set_channel_power(self, channel, power):
        if self.fail_with:
            raise self.fail_with
        self.calls.append(("channel", channel, power))
        self.powers[channel] = power

    def set_output(self, level, units=None, keep_chromaticity=False):
        self.calls.append(("output", level, units, keep_chromaticity))
        self.level = level

    def all_off(self):
        self.calls.append(("all_off",))
        self.powers = {c: 0.0 for c in self.powers}

    def presets(self):
        return dict(self.stored)

    def current_preset(self):
        return self.current

    def recall_preset(self, number):
        self.calls.append(("recall", number))
        self.current = f"{number},{self.stored[number]}"

    def store_preset(self, number, name=""):
        self.calls.append(("store", number, name))
        self.stored[number] = name

    def delete_preset(self, number):
        self.calls.append(("delete", number))
        del self.stored[number]

    def alarm(self):
        self._enter()
        return self.alarm_text

    def clear_alarm(self):
        self.alarm_text = "NONE"


@pytest.fixture
def fake():
    return FakeRS7()


@pytest.fixture
def client(fake):
    return TestClient(web.create_app(fake))  # type: ignore[arg-type]


def test_info(client):
    r = client.get("/api/info")
    assert r.status_code == 200
    d = r.json()
    assert d["version"] == "1.2.3" and d["serial"] == "SN42"
    assert d["lum_label"] == "Luminance" and d["phot_unit"] == "cd/m2"
    assert [c["channel"] for c in d["channels"]] == [1, 2]
    assert d["channels"][0]["wavelength"] == 450.0 and d["channels"][0]["color"].startswith("#")
    assert "D65" in d["illuminants"]
    assert len(d["locus"]) > 10 and len(d["planckian"]) == 61


def test_state_without_target(client, fake):
    r = client.get("/api/state", params={"start": 400, "end": 700})
    assert r.status_code == 200
    d = r.json()
    assert d["power"] == 25.0 and d["rad"] == 7.0 and d["lum"] == 500.0
    assert d["cct"] == 6504.0 and d["xy"] == [0.3127, 0.329]
    assert d["powers"] == {"1": 10.0}
    assert d["spec"][0][0] == 400 and d["spec"][-1][0] == 700
    assert d["chan_specs"] == {}
    assert d["report"]["cri_ra"] is not None
    assert "target" not in d
    assert fake.units == Units.INTERNAL


def test_state_with_target_and_all_channels(client):
    d = client.get("/api/state", params={"plot_all": True, "target": "D65"}).json()
    assert set(d["chan_specs"]) == {"1", "2"}
    assert d["target"]["description"] == "CIE illuminant D65"
    assert d["target"]["comparison"]["delta_uv_prime"] is not None
    assert d["target"]["spectrum"][0][0] == 380


def test_state_with_a_bad_target_reports_it_and_keeps_the_rest(client):
    d = client.get("/api/state", params={"target": "nonsense"}).json()
    assert "target_error" in d and "target" not in d
    assert d["power"] == 25.0


def test_state_rejects_a_bad_range(client):
    assert client.get("/api/state", params={"start": 700, "end": 400}).status_code == 400


def test_set_channel(client, fake):
    r = client.post("/api/channel", json={"channel": 2, "power": 33.5})
    assert r.status_code == 200
    assert ("channel", 2, 33.5) in fake.calls
    assert fake.powers[2] == 33.5


def test_channel_power_is_validated(client, fake):
    assert client.post("/api/channel", json={"channel": 2, "power": 150}).status_code == 422
    assert fake.calls == []


def test_device_error_becomes_400_with_the_message(client, fake):
    fake.fail_with = RS7Error("06", "channel at its limit")
    r = client.post("/api/channel", json={"channel": 1, "power": 50})
    assert r.status_code == 400
    assert r.json()["detail"] == "?06 - channel at its limit"


def test_timeout_becomes_504(client, fake):
    fake.fail_with = TimeoutError()
    assert client.post("/api/channel", json={"channel": 1, "power": 50}).status_code == 504


def test_output_and_all_off(client, fake):
    client.post("/api/output", json={"level": 40, "keep_chromaticity": True})
    assert ("output", 40.0, Units.INTERNAL, True) in fake.calls
    client.post("/api/all_off")
    assert ("all_off",) in fake.calls


def test_presets(client, fake):
    d = client.get("/api/presets").json()
    assert d == {"presets": [{"number": 0, "name": "warm"}, {"number": 3, "name": "cool"}], "current": None}
    assert client.post("/api/presets/3/recall").status_code == 200
    assert client.get("/api/presets").json()["current"] == 3
    assert client.put("/api/presets/5", json={"name": " noon "}).status_code == 200
    assert fake.stored[5] == "noon"
    assert client.delete("/api/presets/0").status_code == 200
    assert 0 not in fake.stored
    assert client.post("/api/presets/100/recall").status_code == 422


def test_alarm(client, fake):
    fake.alarm_text = "?A1 - channel power limit"
    assert client.get("/api/alarm").json() == {"alarm": "?A1 - channel power limit"}
    assert client.post("/api/alarm").json() == {"alarm": "NONE"}


def flat_result(name="D65"):
    spectrum = [(float(nm), 1.0) for nm in range(380, 781)]
    report = analyze(spectrum)
    return MatchResult(
        name, report, report, compare(report, report, spectrum, spectrum), float("nan"), spectrum, spectrum
    )


def test_match_is_called_like_the_gui_does(client, monkeypatch):
    seen = {}

    def fake_match(r, *args):
        seen["args"] = args
        return flat_result()

    monkeypatch.setattr(web, "match", fake_match)
    body = {"target": "D65", "level": 300, "units": "radiometric", "start": 400, "end": 700, "method": "firmware"}
    r = client.post("/api/match", json=body)
    assert r.status_code == 200, r.text
    # target, level, units, at_max, start, end, include_white, correct_chromaticity, method
    assert seen["args"] == ("D65", 300.0, Units.RADIOMETRIC, False, 400, 700, True, True, "firmware")
    d = r.json()
    assert d["description"] == "CIE illuminant D65"
    assert d["unit_rms_error"] is None  # NaN of the local fit is not valid JSON
    assert d["comparison"]["delta_uv_prime"] == pytest.approx(0.0, abs=1e-9)
    assert d["output"]["cri_ra"] is not None


def test_match_defaults_keep_the_level(client, monkeypatch):
    seen = {}

    def fake_match(r, *args):
        seen["args"] = args
        return flat_result()

    monkeypatch.setattr(web, "match", fake_match)
    assert client.post("/api/match", json={"target": "3000K", "at_max": True}).status_code == 200
    assert seen["args"] == ("3000K", None, Units.PHOTOMETRIC, True, 380, 780, True, True, "local")


def test_match_with_an_unknown_target_is_a_400(client):
    r = client.post("/api/match", json={"target": "D1", "level": 100})
    assert r.status_code == 400


def test_match_refuses_a_file_on_the_server(client, tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("500,1\n600,2\n")
    assert client.post("/api/match", json={"target": str(f)}).status_code == 400
    assert client.get("/api/state", params={"target": str(f)}).status_code == 400


def test_calls_to_the_unit_never_overlap(fake):
    client = TestClient(web.create_app(fake))  # type: ignore[arg-type]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: client.get("/api/alarm").status_code, range(16)))
    assert set(codes) == {200}
    assert fake.max_busy == 1


def test_the_page_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "RS-7 Control" in r.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_the_web_module_does_not_need_qt():
    code = "import sys, rs7.web, rs7.state; sys.exit('PySide6' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
