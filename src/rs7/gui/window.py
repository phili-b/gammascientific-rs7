"""Main window, laid out like the manufacturer's SpectralLED Assistant (user manual, section 3).

All RS-7 communication runs on the :class:`Worker` thread. Widgets are only touched in the GUI thread:
values are read before a job is queued, and results are shown when it comes back.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from serial.tools import list_ports

from ..colorimetry import ColorReport, analyze, compare
from ..device import FTDI_IDS, RS7, ChannelInfo, PeakType, RS7Error, Units
from ..illuminants import available, describe, target_spectrum
from ..match import ANALYSIS_RANGE, MatchResult, match, scale_to_level
from ..spectrum import cct_to_xy
from .widgets import CieChart, SpectrumPlot, wavelength_color
from .worker import Worker

DEBOUNCE_MS = 80  # slider drags are sent at most this often
STEPS = 100  # slider steps per percent (0.01 % resolution)
RED = "background: #ff6060;"


def read_state(
    r: RS7,
    start: int,
    end: int,
    channels: list[int],
    plot_all: bool,
    sliders: bool,
    target: tuple[str, int, int] | None = None,
) -> dict:
    """Everything the window shows, read from the unit and analyzed (worker thread). Leaves the units on INTERNAL.

    ``target`` = (name, start, end): also build that target at the output's level and compare.
    """
    st: dict[str, Any] = {}
    if sliders:
        st["powers"] = r.channel_powers()
    r.set_units(Units.RADIOMETRIC)
    st["rad"] = r.output()
    r.set_units(Units.PHOTOMETRIC)
    st["lum"] = r.output()
    r.set_units(Units.INTERNAL)
    st["power"] = r.output()
    for key, read in (("xy", r.chromaticity), ("cct", r.cct)):
        try:
            st[key] = read()
        except RS7Error:  # no spectrum (all channels off)
            st[key] = None
    lo, hi = min(start, ANALYSIS_RANGE[0]), max(end, ANALYSIS_RANGE[1])
    full = r.spectrum(0, lo, hi)  # one read serves the plot and the analysis
    st["spec"] = [(nm, v) for nm, v in full if start <= nm <= end]
    analysis_spec = [(nm, v) for nm, v in full if ANALYSIS_RANGE[0] <= nm <= ANALYSIS_RANGE[1]]
    report = st["report"] = analyze(analysis_spec)
    st["chan_specs"] = {c: r.spectrum(c, start, end) for c in channels} if plot_all else {}
    r.set_wavelength_range(start, end)
    if target:
        name, t_start, t_end = target
        try:
            relative = target_spectrum(name, t_start, t_end)
            level = report.photometric if report.photometric > 0 else 1.0
            scale = scale_to_level(relative, t_start, level, Units.PHOTOMETRIC)
            t_spec = [(t_start + i, v * scale) for i, v in enumerate(relative)]
            t_report = analyze(t_spec)
            st["target"] = (t_spec, t_report, compare(report, t_report, analysis_spec, t_spec))
        except ValueError as e:
            st["target_error"] = str(e)
    return st


def shift_held() -> bool:
    return bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)


class ChannelSlider(QWidget):
    """Vertical slider with the channel's color on top; ``moved`` is only called for user moves."""

    def __init__(self, info: ChannelInfo, moved: Callable[[int, float], None]):
        super().__init__()
        self.channel = info.channel
        lay = QVBoxLayout(self)
        lay.setContentsMargins(1, 0, 1, 0)
        lay.setSpacing(2)
        bar = QFrame()
        bar.setFixedSize(22, 6)
        bar.setStyleSheet(f"background: {wavelength_color(info.nominal_wavelength).name()};")
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setRange(0, 100 * STEPS)
        self.slider.setMinimumHeight(130)
        tip = f"Channel {info.channel}: {info.nominal_wavelength:g} nm, FWHM {info.nominal_fwhm:g} nm"
        self.slider.setToolTip(tip)
        # actionTriggered fires for drags, clicks and keys, never for setValue() from code; so displaying
        # a value can never send it back to the unit. sliderPosition() is already the new position here.
        self.slider.actionTriggered.connect(lambda _a: moved(self.channel, self.slider.sliderPosition() / STEPS))
        label = QLabel(str(info.channel))
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setToolTip(tip)
        lay.addWidget(bar, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.slider, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(label)

    def show_value(self, percent: float):
        if not self.slider.isSliderDown():  # never yank a slider out of the user's hand
            self.slider.setValue(round(percent * STEPS))


class MainWindow(QMainWindow):
    def __init__(self, port: str | None = None):
        super().__init__()
        self.setWindowTitle("RS-7 Control")
        self.resize(1200, 720)
        self.settings = QSettings("gammascientific-rs7", "rs7-gui")
        self.worker = Worker(self)
        self.rs7: RS7 | None = None
        self.channels: list[ChannelInfo] = []
        self.sliders: dict[int, ChannelSlider] = {}
        self.powers: dict[int, float] = {}
        self.pending: dict[int, float] = {}
        self.pending_main: float | None = None
        self.rel_peak = 1.0
        self.spec: list[tuple[int, float]] = []
        self.chan_specs: dict[int, list[tuple[int, float]]] = {}
        self.target_spec: list[tuple[int, float]] = []
        self.phot_unit = "cd/m2"
        self.xy: tuple[float, float] | None = None

        self.flush_timer = QTimer(self)
        self.flush_timer.setSingleShot(True)
        self.flush_timer.setInterval(DEBOUNCE_MS)
        self.flush_timer.timeout.connect(self._flush)
        self._build_ui()
        self._build_menu()
        self.worker.busy_changed.connect(lambda n: self.busy_label.setText("working..." if n else ""))
        self.alarm_timer = QTimer(self)
        self.alarm_timer.setInterval(2000)
        self.alarm_timer.timeout.connect(self._poll_alarm)
        self.alarm_timer.start()
        port = port or str(self.settings.value("port", "") or "")
        if port:
            QTimer.singleShot(0, lambda: self.connect_to(port))
        else:
            QTimer.singleShot(0, self._connect_first_found)

    # ---- layout ------------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        grid = QGridLayout(central)
        self.setCentralWidget(central)

        # left: output pane, main power, all off
        left = QVBoxLayout()
        out = QGroupBox("Output")
        form = QFormLayout(out)
        self.entries: dict[str, QLineEdit] = {}
        self.out_labels: dict[str, QLabel] = {}
        for key, label in [
            ("power", "Power Level %"),
            ("rad", "Radiance"),
            ("lum", "Luminance"),
            ("cct", "CCT (K)"),
            ("x", "CIE x"),
            ("y", "CIE y"),
            ("centroid", "Centroid (nm)"),
        ]:
            e = QLineEdit()
            e.setFixedWidth(95)
            if key == "centroid":
                e.setReadOnly(True)
            else:
                e.returnPressed.connect(lambda k=key: self._entry(k))
                e.setToolTip("Type a value and press Enter (Shift+Enter keeps the color)")
            self.entries[key] = e
            self.out_labels[key] = QLabel(label)
            form.addRow(self.out_labels[key], e)
        left.addWidget(out)
        left.addWidget(self._build_quality_pane())
        left.addWidget(QLabel("Main power"), alignment=Qt.AlignmentFlag.AlignHCenter)
        self.main = QSlider(Qt.Orientation.Vertical)
        self.main.setRange(0, 100 * STEPS)
        self.main.setMinimumHeight(150)
        self.main.setToolTip("Scale the whole spectrum; hold Shift to keep the color")
        self.main.actionTriggered.connect(lambda _a: self._main_moved(self.main.sliderPosition() / STEPS))
        left.addWidget(self.main, 1, alignment=Qt.AlignmentFlag.AlignHCenter)
        all_off = QPushButton("All Off")
        all_off.clicked.connect(lambda: self._run(lambda r: r.all_off()))
        left.addWidget(all_off)
        grid.addLayout(left, 0, 0)

        # centre: plot, plot controls, channel sliders
        mid = QVBoxLayout()
        self.plot = SpectrumPlot()
        mid.addWidget(self.plot, 1)
        bar = QHBoxLayout()
        self.plot_start, self.plot_end = QSpinBox(), QSpinBox()
        for sb, v in ((self.plot_start, 380), (self.plot_end, 780)):
            sb.setRange(360, 1100)
            sb.setValue(v)
            sb.setSuffix(" nm")
            sb.editingFinished.connect(lambda: self._run(sliders=False))
        self.plot_all = QCheckBox("Plot All Chan")
        self.plot_all.toggled.connect(lambda _c: self._run(sliders=False))
        bar.addWidget(QLabel("Plot from"))
        bar.addWidget(self.plot_start)
        bar.addWidget(QLabel("to"))
        bar.addWidget(self.plot_end)
        bar.addWidget(self.plot_all)
        bar.addStretch()
        self.rel = QRadioButton("Rel")
        abs_ = QRadioButton("Abs")
        abs_.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(abs_)
        group.addButton(self.rel)
        self.rel.toggled.connect(lambda _c: self._show_sliders())
        bar.addWidget(abs_)
        bar.addWidget(self.rel)
        mid.addLayout(bar)
        self.slider_row = QHBoxLayout()
        self.slider_row.setSpacing(0)
        holder = QWidget()
        holder.setLayout(self.slider_row)
        scroll = QScrollArea()
        scroll.setWidget(holder)
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(205)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        mid.addWidget(scroll)
        grid.addLayout(mid, 0, 1)
        grid.setColumnStretch(1, 1)

        # right: presets, CIE chart or target pane
        right = QVBoxLayout()
        presets = QGroupBox("Presets")
        pl = QVBoxLayout(presets)
        self.preset_box = QComboBox()
        self.preset_box.setMinimumWidth(260)
        self.preset_box.activated.connect(lambda _i: self._recall())  # user picks only
        pl.addWidget(self.preset_box)
        row = QHBoxLayout()
        store, delete = QPushButton("Store Preset"), QPushButton("Delete")
        store.clicked.connect(self._store_preset)
        delete.clicked.connect(self._delete_preset)
        row.addWidget(store)
        row.addWidget(delete)
        pl.addLayout(row)
        right.addWidget(presets)
        self.chart = CieChart()
        self.chart.clicked.connect(lambda x, y: self._run(lambda r: r.set_chromaticity(x, y)))
        right.addWidget(self.chart, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.target_pane = self._build_target_pane()
        self.target_pane.setVisible(False)
        right.addWidget(self.target_pane)
        right.addStretch()
        grid.addLayout(right, 0, 2)

        # status bar: command/reply, busy, alarm
        self.status_label = QLabel("Not connected: Settings > Select COM Port")
        self.busy_label = QLabel("")
        self.busy_label.setMinimumWidth(80)
        self.alarm_button = QPushButton("No alarm")
        self.alarm_button.setFlat(True)
        self.alarm_button.setMinimumWidth(260)
        self.alarm_button.setToolTip("Click to clear the alarm")
        self.alarm_button.clicked.connect(lambda: self._do(lambda r: r.clear_alarm(), lambda _: self._poll_alarm()))
        sb = self.statusBar()
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.busy_label)
        sb.addPermanentWidget(self.alarm_button)

    def _build_target_pane(self) -> QWidget:
        box = QGroupBox("Target Spectrum")
        f = QFormLayout(box)
        self.target_box = QComboBox()
        self.target_box.setEditable(True)
        self.target_box.addItems(available())
        self.target_box.setCurrentText("D65")
        self.target_box.setToolTip(
            "CIE illuminant (D65, A, FL2, LED-B3, ...), D<CCT> for daylight (D5000), <T>K for a black body (3000K), "
            "or a CSV file (nm, value)"
        )
        self.target_box.activated.connect(lambda _i: self._run(sliders=False))
        line_edit = self.target_box.lineEdit()
        if line_edit:
            line_edit.returnPressed.connect(lambda: self._run(sliders=False))
        load = QPushButton("CSV...")
        load.setToolTip("Load a target spectrum: one 'wavelength, value' per line, any step size")
        load.clicked.connect(self._load_csv)
        row = QHBoxLayout()
        row.addWidget(self.target_box, 1)
        row.addWidget(load)
        f.addRow("Target", row)
        self.level = QLineEdit()
        self.level.setPlaceholderText("keep present level")
        self.level_units = QComboBox()
        self.level_units.addItems(["photometric", "radiometric"])
        row = QHBoxLayout()
        row.addWidget(self.level, 1)
        row.addWidget(self.level_units)
        f.addRow("Level", row)
        self.at_max = QCheckBox("As bright as possible (soft limit)")
        f.addRow(self.at_max)
        self.fit_start, self.fit_end = QSpinBox(), QSpinBox()
        for sb, v in ((self.fit_start, 380), (self.fit_end, 780)):
            sb.setRange(360, 1100)
            sb.setValue(v)
            sb.setSuffix(" nm")
        rng = QHBoxLayout()
        rng.addWidget(self.fit_start)
        rng.addWidget(self.fit_end)
        f.addRow("Fit range", rng)
        self.correct = QCheckBox("Correct chromaticity after fit")
        self.correct.setChecked(True)
        f.addRow(self.correct)
        button = QPushButton("Match")
        button.setToolTip("Fit the channels to the target, correct the color and set the level")
        button.clicked.connect(self._match)
        f.addRow(button)
        self.match_result = QLabel("")
        self.match_result.setWordWrap(True)
        f.addRow(self.match_result)
        return box

    def _build_quality_pane(self) -> QWidget:
        box = QGroupBox("Color quality")
        f = QFormLayout(box)
        self.quality: dict[str, QLabel] = {}
        for key, label in [
            ("level", "Level"),
            ("cct", "CCT / Duv"),
            ("uv", "u', v'"),
            ("cri", "CRI Ra / R9"),
            ("tm30", "TM-30 Rf / Rg"),
            ("target", "Target"),
            ("delta", "\u0394u'v' to target"),
            ("rms", "Spectral RMS"),
        ]:
            self.quality[key] = QLabel("-")
            f.addRow(label, self.quality[key])
        self.quality["delta"].setToolTip("Chromaticity difference; 0.001 is about one just-noticeable step")
        self.quality["rms"].setToolTip("RMS difference of the area-normalized spectra over the fit range, % of mean")
        return box

    def _build_menu(self):
        settings = self.menuBar().addMenu("&Settings")
        self.port_menu = settings.addMenu("Select COM Port")
        self.port_menu.aboutToShow.connect(self._fill_ports)
        settings.addAction("Network Address (socket://host:port)...", self._ask_address)
        settings.addAction("Disconnect From COM Port", self.disconnect_unit)
        settings.addSeparator()

        obs = settings.addMenu("Standard Observer")
        self.observer_group = QActionGroup(self)
        for deg in (2, 10):
            a = QAction(f"Tristimulus is {deg}° Standard Observer", self, checkable=True, checked=deg == 2)
            a.setData(deg)
            a.triggered.connect(lambda _c, d=deg: self._run(lambda r: r.set_observer(d), sliders=False))
            self.observer_group.addAction(a)
            obs.addAction(a)
        peak = settings.addMenu("Peak Type")
        self.peak_group = QActionGroup(self)
        for pt in PeakType:
            a = QAction(pt.name.title(), self, checkable=True, checked=pt == PeakType.CENTROID)
            a.setData(int(pt))
            a.triggered.connect(lambda _c, t=pt: self._do(lambda r: r.set_peak_type(t)))
            self.peak_group.addAction(a)
            peak.addAction(a)
        self.include_white = QAction("Include White Channels in Spectral Fit", self, checkable=True)
        settings.addAction(self.include_white)
        settings.addAction("Working Distance (mm)...", self._ask_distance)
        self.feedback = QAction("Enable Optical Feedback", self, checkable=True, checked=True)
        self.feedback.triggered.connect(lambda on: self._do(lambda r: r.set_feedback(on)))
        settings.addAction(self.feedback)
        settings.addSeparator()
        settings.addAction("Quit", QKeySequence.StandardKey.Quit, self.close)

        view = self.menuBar().addMenu("&View")
        self.target_action = QAction("Target Spectrum", self, checkable=True)
        self.target_action.toggled.connect(self._toggle_target)
        view.addAction(self.target_action)

    # ---- worker helpers ---------------------------------------------------------------------

    def _do(self, action: Callable[[RS7], Any], then: Callable[[Any], None] | None = None):
        """Run ``action(rs7)`` on the worker; ``then(result)`` in the GUI thread. Errors go to the status bar."""
        if not self.rs7:
            self.status_label.setText("Not connected: Settings > Select COM Port")
            return
        r = self.rs7
        self.worker.submit(lambda: action(r), then, self._error)

    def _run(
        self,
        action: Callable[[RS7], Any] | None = None,
        sliders: bool = True,
        then: Callable[[Any], None] | None = None,
    ):
        """Like :meth:`_do`, then read the unit's state back and show it."""
        args = (
            self.plot_start.value(),
            self.plot_end.value(),
            [c.channel for c in self.channels],
            self.plot_all.isChecked(),
            sliders,
            self._target_args(),
        )

        def job(r: RS7):
            result = action(r) if action else None
            return result, read_state(r, *args)

        def done(res):
            result, state = res
            if then:
                then(result)
            self._show_state(state)

        self._do(job, done)

    def _target_args(self) -> tuple[str, int, int] | None:
        name = self.target_box.currentText().strip()
        if not self.target_action.isChecked() or not name:
            return None
        return name, self.fit_start.value(), self.fit_end.value()

    def _error(self, e: Exception):
        self._flash(str(e) or type(e).__name__)

    def _log(self, cmd: str, reply: str, is_error: bool):
        self.status_label.setText(f"{cmd}  →  {reply}")
        if is_error:
            self._flash()

    def _flash(self, message: str | None = None):
        if message:
            self.status_label.setText(message)
        self.status_label.setStyleSheet(RED)
        QTimer.singleShot(600, lambda: self.status_label.setStyleSheet(""))

    # ---- connection -----------------------------------------------------------------------------

    def _fill_ports(self):
        self.port_menu.clear()
        for p in list_ports.comports():
            mark = "  (RS-7)" if (p.vid, p.pid) in FTDI_IDS else ""
            self.port_menu.addAction(f"{p.device}  {p.description}{mark}", lambda d=p.device: self.connect_to(d))
        if self.port_menu.isEmpty():
            self.port_menu.addAction("(no serial ports)").setEnabled(False)

    def _connect_first_found(self):
        ports = [p.device for p in list_ports.comports() if (p.vid, p.pid) in FTDI_IDS]
        if ports:
            self.connect_to(ports[0])

    def _ask_address(self):
        address, ok = QInputDialog.getText(
            self,
            "Network address",
            "pyserial URL of a shared RS-7 (rs7 bridge):",
            text=str(self.settings.value("address", "socket://raspberrypi.local:5000")),
        )
        if ok and address:
            self.settings.setValue("address", address)
            self.connect_to(address)

    def connect_to(self, port: str):
        self.disconnect_unit()
        self.status_label.setText(f"Connecting to {port}...")

        def open_unit():
            r = RS7(port)
            try:
                r.set_units(Units.INTERNAL)
                irradiant = r.working_distance() > 0 or r.calibration_type() == "I"
                return r, r.channel_info(), r.observer(), r.peak_type(), r.feedback(), irradiant
            except Exception:
                r.close()
                raise

        def opened(res):
            r, self.channels, observer, peak, feedback, irradiant = res
            self.rs7 = r
            # called on the worker thread: hop to the GUI thread before touching widgets
            r.on_command = lambda c, reply, err: QTimer.singleShot(0, self, lambda: self._log(c, reply, err))
            for a in self.observer_group.actions():
                a.setChecked(a.data() == observer)
            for a in self.peak_group.actions():
                a.setChecked(a.data() == int(peak))
            self.feedback.setChecked(feedback)
            self.out_labels["rad"].setText("Irradiance" if irradiant else "Radiance")
            self.out_labels["lum"].setText("Illuminance" if irradiant else "Luminance")
            self.phot_unit = "lux" if irradiant else "cd/m2"
            self.settings.setValue("port", port)
            self.setWindowTitle(f"RS-7 Control - {port}")
            self._build_sliders()
            self._load_presets()
            self._run()

        self.worker.submit(open_unit, opened, lambda e: self._flash(f"Could not connect to {port}: {e}"))

    def disconnect_unit(self):
        if self.rs7:
            r, self.rs7 = self.rs7, None
            r.on_command = None
            self.worker.submit(r.close)  # after any job still queued for it
        self.setWindowTitle("RS-7 Control")

    def closeEvent(self, event):
        self.alarm_timer.stop()
        self.disconnect_unit()
        self.worker.stop()
        super().closeEvent(event)

    # ---- alarm --------------------------------------------------------------------------------------

    def _poll_alarm(self):
        if not self.rs7 or self.worker.busy or self.flush_timer.isActive():
            return

        def read(r: RS7):
            hook, r.on_command = r.on_command, None  # polling should not overwrite the status bar
            try:
                return r.alarm()
            finally:
                r.on_command = hook

        self._do(read, self._show_alarm)

    def _show_alarm(self, alarm: str):
        active = alarm != "NONE"
        self.alarm_button.setText(alarm if active else "No alarm")
        self.alarm_button.setStyleSheet(RED if active else "")

    # ---- sliders -----------------------------------------------------------------------------------

    def _build_sliders(self):
        while self.slider_row.count():
            item = self.slider_row.takeAt(0)
            widget = item.widget() if item else None
            if widget:
                widget.deleteLater()
        self.sliders = {}
        for info in self.channels:
            s = ChannelSlider(info, self._slider_moved)
            self.sliders[info.channel] = s
            self.slider_row.addWidget(s)
        self.slider_row.addStretch()

    def _show_sliders(self):
        # In Rel mode sliders are scaled to the strongest channel at display time; that scale stays fixed
        # while dragging, otherwise dragging the strongest channel would rescale itself.
        self.rel_peak = max(self.powers.values(), default=0) or 1.0
        for ch, s in self.sliders.items():
            p = self.powers.get(ch, 0.0)
            s.show_value(p * 100 / self.rel_peak if self.rel.isChecked() else p)

    def _slider_moved(self, ch: int, value: float):
        if self.rel.isChecked():
            value = value * self.rel_peak / 100
        if abs(value - self.powers.get(ch, 0.0)) < 0.005:
            return
        self.pending[ch] = value
        self.powers[ch] = value
        self.flush_timer.start()

    def _main_moved(self, value: float):
        self.pending_main = value
        self.flush_timer.start()

    def _flush(self):
        """Send the latest slider positions. While the unit is busy keep collecting, so a fast drag
        never builds up a queue of stale commands."""
        if not self.pending and self.pending_main is None:
            return
        if self.worker.busy:
            self.flush_timer.start()
            return
        pending, main = self.pending, self.pending_main
        self.pending, self.pending_main = {}, None
        shift = shift_held()

        def send(r: RS7):
            if pending:
                r.set_channel_powers(pending)
            if main is not None:
                r.set_output(main, Units.INTERNAL, keep_chromaticity=shift)

        self._run(send, sliders=main is not None)

    # ---- showing the state ------------------------------------------------------------------------------

    def _show_state(self, st: dict):
        if "powers" in st:
            self.powers = st["powers"]
            self._show_sliders()
        if not self.main.isSliderDown():
            self.main.setValue(round(st["power"] * STEPS))
        if st["xy"]:
            self.xy = st["xy"]
        xy = self.xy or (0.0, 0.0)
        values = {
            "power": f"{st['power']:.3f}",
            "rad": f"{st['rad']:.4g}",
            "lum": f"{st['lum']:.4g}",
            "x": f"{xy[0]:.4f}",
            "y": f"{xy[1]:.4f}",
            "cct": f"{st['cct']:.0f}" if st["cct"] else "",
        }
        for k, v in values.items():
            if not (self.entries[k].hasFocus() and self.entries[k].isModified()):  # keep what the user is typing
                self.entries[k].setText(v)
        self.spec, self.chan_specs = st["spec"], st["chan_specs"]
        total = sum(v for _, v in self.spec)
        self.entries["centroid"].setText(f"{sum(n * v for n, v in self.spec) / total:.1f}" if total > 0 else "")
        self._show_quality(st)
        self.chart.set_xy(self.xy)
        self._draw_plot()

    def _show_quality(self, st: dict):
        rep: ColorReport = st["report"]
        q = self.quality

        def fmt(v, spec):
            return "-" if v is None else format(v, spec)

        q["level"].setText(f"{rep.photometric:.4g} {self.phot_unit}")
        q["cct"].setText(f"{fmt(rep.cct, '.0f')} K / {fmt(rep.duv, '+.4f')}")
        q["uv"].setText(f"{rep.uv_prime[0]:.4f}, {rep.uv_prime[1]:.4f}" if rep.uv_prime else "-")
        q["cri"].setText(f"{fmt(rep.cri_ra, '.1f')} / {fmt(rep.cri_r.get(9), '.1f')}")
        q["cri"].setToolTip("  ".join(f"R{i} {v:.0f}" for i, v in sorted(rep.cri_r.items())))
        q["tm30"].setText(f"{fmt(rep.tm30_rf, '.1f')} / {fmt(rep.tm30_rg, '.1f')}")
        self.target_spec = []
        self.chart.set_target(None)
        if "target" in st:
            self.target_spec, t_rep, cmp = st["target"]
            name = self.target_box.currentText().strip()
            q["target"].setText(f"{describe(name)}: {fmt(t_rep.cct, '.0f')} K, Ra {fmt(t_rep.cri_ra, '.0f')}")
            delta = cmp.delta_uv_prime
            color = "" if delta is None else "#2a2" if delta < 0.001 else "#c80" if delta < 0.005 else "#d33"
            q["delta"].setText(f"<b style='color:{color}'>{fmt(delta, '.4f')}</b>")
            q["rms"].setText(f"{fmt(cmp.spectral_rms, '.1f')} %")
            self.chart.set_target(t_rep.xy)
        else:
            q["target"].setText(st.get("target_error", "-"))
            q["delta"].setText("-")
            q["rms"].setText("-")

    def _entry(self, key: str):
        shift = shift_held()
        try:
            v = float(self.entries[key].text())
            xy = (float(self.entries["x"].text()), float(self.entries["y"].text()))
        except ValueError:
            self._flash("Not a number")
            return
        units = {"power": Units.INTERNAL, "rad": Units.RADIOMETRIC, "lum": Units.PHOTOMETRIC}

        def apply(r: RS7):
            if key in units:
                r.set_output(v, units[key], keep_chromaticity=shift)
            elif key == "cct":
                r.set_chromaticity(*(round(c, 4) for c in cct_to_xy(v)))
            else:
                r.set_chromaticity(*xy)

        self.entries[key].clearFocus()
        self._run(apply)

    def _draw_plot(self):
        start, end = self.plot_start.value(), self.plot_end.value()
        colors = {i.channel: wavelength_color(i.nominal_wavelength) for i in self.channels}
        channels = [(s, colors.get(ch, QColor("red"))) for ch, s in self.chan_specs.items()]
        target: list[tuple[float, float]] = []
        if self.target_action.isChecked():
            target = [(float(nm), v) for nm, v in self.target_spec if start <= nm <= end]
        self.plot.set_data(
            start,
            end,
            [(float(n), v) for n, v in self.spec],
            [([(float(n), v) for n, v in s], c) for s, c in channels],
            target,
        )

    # ---- presets -------------------------------------------------------------------------------------------

    def _load_presets(self):
        def show(res):
            presets, current = res
            self.preset_box.clear()
            for n, name in presets.items():
                self.preset_box.addItem(f"{n} - {name}", n)
            loaded = current.split(",")[0]
            self.preset_box.setCurrentIndex(self.preset_box.findData(int(loaded)) if loaded.isdigit() else -1)

        self._do(lambda r: (r.presets(), r.current_preset()), show)

    def _recall(self):
        n = self.preset_box.currentData()
        if n is not None:
            self._run(lambda r: r.recall_preset(n))

    def _delete_preset(self):
        n = self.preset_box.currentData()
        if (
            n is not None
            and QMessageBox.question(self, "Delete preset", f"Delete preset {n}?") == QMessageBox.StandardButton.Yes
        ):
            self._do(lambda r: r.delete_preset(n), lambda _: self._load_presets())

    def _store_preset(self):
        n, ok = QInputDialog.getInt(self, "Store Preset", "Preset number (0-95):", 0, 0, 95)
        if not ok:
            return
        name, ok = QInputDialog.getText(self, "Store Preset", "Description:")
        if ok:
            self._do(lambda r: r.store_preset(n, name), lambda _: self._load_presets())

    # ---- target spectrum ---------------------------------------------------------------------------------------

    def _toggle_target(self, on: bool):
        self.target_pane.setVisible(on)
        self._run(sliders=False)

    def _load_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Target spectrum", "", "CSV (*.csv *.txt);;All files (*)")
        if path:
            self.target_box.setCurrentText(path)
            self._run(sliders=False)

    def _match(self):
        name = self.target_box.currentText().strip()
        text = self.level.text().strip()
        try:
            level = float(text) if text else None
        except ValueError:
            self._flash("Level must be a number (or empty to keep the present level)")
            return
        units = Units.PHOTOMETRIC if self.level_units.currentIndex() == 0 else Units.RADIOMETRIC
        at_max, white, correct = self.at_max.isChecked(), self.include_white.isChecked(), self.correct.isChecked()
        start, end = self.fit_start.value(), self.fit_end.value()

        def run(r: RS7) -> MatchResult:
            return match(r, name, level, units, at_max, start, end, white, correct)

        self.match_result.setText("matching...")
        self._run(run, then=self._show_match)

    def _show_match(self, res: MatchResult):
        c = res.comparison
        delta = "-" if c.delta_uv_prime is None else f"{c.delta_uv_prime:.4f}"
        self.match_result.setText(
            f"Matched {describe(res.target_name)} at {res.output.photometric:.4g} {self.phot_unit}: "
            f"\u0394u'v' {delta}, RS-7 spectral error {res.unit_rms_error:.1f} %"
        )

    # ---- settings -------------------------------------------------------------------------------------------------

    def _ask_distance(self):
        def ask(current: int):
            mm, ok = QInputDialog.getInt(
                self, "Working distance", "Working distance in mm (0 = radiance mode):", current, 0, 100000
            )
            if ok:
                self._run(lambda r: r.set_working_distance(mm), sliders=False)

        self._do(lambda r: r.working_distance(), ask)
