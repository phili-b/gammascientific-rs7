import pytest

from rs7 import RS7, RS7Error, Units


class FakePort:
    """Serial stand-in: each written command gets the next canned reply."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.sent = []
        self._buf = b""

    def reset_input_buffer(self):
        self._buf = b""

    def write(self, data):
        self.sent.append(data)
        self._buf = ("\r\n" + self.replies.pop(0)).encode()

    def readline(self):
        line, sep, self._buf = self._buf.partition(b"\n")
        return line + sep

    def close(self):
        pass


def rs7(*replies):
    port = FakePort(*replies)
    return RS7(port), port


def test_ok_reply_and_command_format():
    r, port = rs7("Ok\r\n")
    r.set_channel_power(5, 10)
    assert port.sent == [b"SCP 5,10\r"]


def test_single_value():
    r, _ = rs7("4.20152\r\n")
    assert r.channel_power(3) == 4.20152


def test_channel_list():
    r, _ = rs7("3,4.2\r\n5,10\r\n\r\n")
    assert r.channel_powers() == {3: 4.2, 5: 10.0}


def test_no_channels_on():
    r, _ = rs7("\r\n")
    assert r.channel_powers() == {}


def test_error_is_raised():
    r, _ = rs7("?03 - unrecognized command\r\n")
    with pytest.raises(RS7Error) as e:
        r.version()
    assert e.value.code == "03"


def test_alarm_is_returned_not_raised():
    r, _ = rs7("?A1 - channel power limit\r\n")
    assert r.alarm() == "?A1 - channel power limit"


def test_timeout():
    r, port = rs7("")
    port.readline = lambda: b""
    with pytest.raises(TimeoutError):
        r.version()


def test_units_and_temperatures():
    r, port = rs7("2\r\n", "Ok\r\n", "25.42C,24.99C\r\n")
    assert r.units() is Units.INTERNAL
    r.set_units(Units.PHOTOMETRIC)
    assert port.sent[-1] == b"UNI 1\r"
    assert r.temperatures() == (25.42, 24.99)


def test_output_in_other_units_restores_units():
    r, port = rs7("2\r\n", "Ok\r\n", "300\r\n", "Ok\r\n")
    assert r.output(Units.PHOTOMETRIC) == 300.0
    assert port.sent == [b"UNI\r", b"UNI 1\r", b"OUT\r", b"UNI 2\r"]


def test_set_output_keep_chromaticity():
    r, port = rs7("Ok\r\n")
    r.set_output(50, keep_chromaticity=True)
    assert port.sent == [b"OUTC 50\r"]


def test_presets():
    r, _ = rs7("0,D65 @200lux\r\n3,Bob's spectrum, v2\r\n\r\n")
    assert r.presets() == {0: "D65 @200lux", 3: "Bob's spectrum, v2"}


def test_channel_info_skips_unused():
    r, _ = rs7("1,546,11.4,545,11.5\r\n2,590,23.5,0,0\r\n3,0,0,0,0\r\n\r\n")
    info = r.channel_info()
    assert [c.channel for c in info] == [1, 2]
    assert info[1].wavelength == 0


def test_set_several_channels():
    r, port = rs7("Ok\r\n")
    r.set_channel_powers({2: 70, 3: 5.5})
    assert port.sent == [b"SCP 2,70,3,5.5\r"]


def test_spectrum():
    r, port = rs7("500,510\r\n", "Ok\r\n", "0.1\r\n0.2\r\n0.3\r\n\r\n")
    assert r.spectrum(12) == [(500, 0.1), (501, 0.2), (502, 0.3)]
    assert port.sent[-1] == b"OSP 12\r"


def test_set_target_spectrum_checks_length():
    r, port = rs7("500,502\r\n")
    with pytest.raises(ValueError):
        r.set_target_spectrum([1.0, 2.0])


def test_fit_commands():
    r, port = rs7("Ok\r\n", "Ok\r\n", "Ok\r\n", "Ok\r\n")
    r.fit()
    r.fit(include_white=True)
    r.fit(at_max=True)
    r.color_correct((0.3, 0.4))
    assert port.sent == [b"FTS\r", b"FTS W\r", b"FTS M\r", b"CCS 0.3,0.4\r"]


def test_on_command_callback():
    r, _ = rs7("?03 - unrecognized command\r\n")
    seen = []
    r.on_command = lambda cmd, reply, err: seen.append((cmd, reply, err))
    with pytest.raises(RS7Error):
        r.version()
    assert seen == [("VER", "?03 - unrecognized command", True)]
