"""Desktop front end for the RS-7, laid out like the manufacturer's SpectralLED Assistant."""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import serial
import serial.tools.list_ports

from ..device import RS7, PeakType, RS7Error, Units
from ..spectrum import SPECTRAL_LOCUS, blackbody, cct_to_xy, load_csv, resample, wavelength_to_rgb

CONFIG = Path.home() / ".rs7-gui.json"
ERRORS = (RS7Error, TimeoutError, serial.SerialException, OSError, ValueError)
DEBOUNCE_MS = 80  # slider drags are sent to the unit at most this often
CHART_W, CHART_H = 0.8, 0.9  # CIE chart extent


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RS-7 Control")
        self.geometry("1100x680")
        self.rs7: RS7 | None = None
        self.channels = []  # ChannelInfo of fitted channels
        self.sliders: dict[int, tk.Scale] = {}
        self.powers: dict[int, float] = {}
        self.pending: dict[int, float] = {}
        self.pending_main: float | None = None
        self.flush_id = None
        self.shift = False
        self.rel_peak = 1.0
        self.spec: list[tuple[int, float]] = []
        self.chan_specs: dict[int, list[tuple[int, float]]] = {}
        self.base = [(0.0, 1.0), (5000.0, 1.0)]  # base target spectrum: unity
        self.xy = (0.33, 0.33)

        self.relative = tk.BooleanVar(value=False)
        self.plot_all = tk.BooleanVar(value=False)
        self.target_visible = tk.BooleanVar(value=False)
        self.include_white = tk.BooleanVar(value=False)
        self.correct_after_fit = tk.BooleanVar(value=True)
        self.feedback = tk.BooleanVar(value=True)
        self.observer = tk.IntVar(value=2)
        self.peak = tk.IntVar(value=int(PeakType.CENTROID))
        self.status = tk.StringVar(value="Not connected: choose Settings > Select COM Port")
        self.alarm = tk.StringVar(value="No alarm")
        self.plot_start = tk.StringVar(value="380")
        self.plot_end = tk.StringVar(value="780")
        self.fit_start = tk.StringVar(value="380")
        self.fit_end = tk.StringVar(value="780")
        self.scale = tk.StringVar(value="1.0")
        self.base_name = tk.StringVar(value="none / unity")
        self.rms = tk.StringVar(value="")

        self._build_menu()
        self._build_ui()
        self.bind_all("<KeyPress-Shift_L>", lambda e: setattr(self, "shift", True))
        self.bind_all("<KeyRelease-Shift_L>", lambda e: setattr(self, "shift", False))
        self.protocol("WM_DELETE_WINDOW", self._quit)
        self.after(300, self._autoconnect)
        self.after(2000, self._poll_alarm)

    # ---- layout --------------------------------------------------------------------

    def _build_menu(self):
        menubar = tk.Menu(self)
        s = tk.Menu(menubar, tearoff=False, postcommand=lambda: self._fill_ports(ports))
        ports = tk.Menu(s, tearoff=False)
        s.add_cascade(label="Select COM Port", menu=ports)
        s.add_command(label="Network Address (socket://host:port)...", command=self._ask_address)
        s.add_command(label="Disconnect From COM Port", command=self.disconnect)
        s.add_separator()
        obs = tk.Menu(s, tearoff=False)
        for deg in (2, 10):
            obs.add_radiobutton(label=f"Tristimulus is {deg}° Standard Observer", value=deg,
                                variable=self.observer, command=lambda: self._do(self._set_observer))
        s.add_cascade(label="Standard Observer", menu=obs)
        pk = tk.Menu(s, tearoff=False)
        for p in PeakType:
            pk.add_radiobutton(label=p.name.title(), value=int(p), variable=self.peak,
                               command=lambda: self._do(self._set_peak))
        s.add_cascade(label="Peak Type", menu=pk)
        s.add_checkbutton(label="Include White Channels in Spectral Fit", variable=self.include_white)
        s.add_command(label="Working Distance (mm)...", command=self._ask_distance)
        s.add_checkbutton(label="Enable Optical Feedback", variable=self.feedback,
                          command=lambda: self._do(lambda: self.rs7.set_feedback(self.feedback.get())))
        menubar.add_cascade(label="Settings", menu=s)
        v = tk.Menu(menubar, tearoff=False)
        v.add_checkbutton(label="Target Spectrum", variable=self.target_visible, command=self._toggle_target)
        menubar.add_cascade(label="View", menu=v)
        self.config(menu=menubar)

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        # left: output pane + main power
        left = ttk.Frame(self, padding=6)
        left.grid(row=0, column=0, sticky="ns")
        pane = ttk.LabelFrame(left, text="Output", padding=6)
        pane.pack(fill="x")
        self.entries: dict[str, tk.StringVar] = {}
        self.out_labels: dict[str, ttk.Label] = {}
        for i, (key, label) in enumerate([("power", "Power Level %"), ("rad", "Radiance"), ("lum", "Luminance"),
                                          ("cct", "CCT (K)"), ("x", "CIE x"), ("y", "CIE y"), ("centroid", "Centroid (nm)")]):
            self.out_labels[key] = ttk.Label(pane, text=label)
            self.out_labels[key].grid(row=i, column=0, sticky="w")
            var = self.entries[key] = tk.StringVar()
            e = ttk.Entry(pane, textvariable=var, width=11, state="readonly" if key == "centroid" else "normal")
            e.grid(row=i, column=1, pady=1)
            e.bind("<Return>", lambda ev, k=key: self._entry(k, bool(ev.state & 1)))
        ttk.Label(left, text="Main power").pack(pady=(10, 0))
        self.main = tk.Scale(left, from_=100, to=0, resolution=0.01, length=300, showvalue=False)
        self.main.pack()
        self._on_drag(self.main, self._main_moved)
        ttk.Button(left, text="All Off", command=lambda: self._do(self._all_off)).pack(pady=6)

        # centre: plot and channel sliders
        mid = ttk.Frame(self, padding=6)
        mid.grid(row=0, column=1, sticky="nsew")
        mid.columnconfigure(0, weight=1)
        mid.rowconfigure(0, weight=1)
        self.plot = tk.Canvas(mid, bg="#101010", highlightthickness=0)
        self.plot.grid(row=0, column=0, sticky="nsew")
        self.plot.bind("<Configure>", lambda e: self._draw_plot())
        pbar = ttk.Frame(mid)
        pbar.grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Label(pbar, text="Plot from").pack(side="left")
        for var in (self.plot_start, self.plot_end):
            e = ttk.Entry(pbar, textvariable=var, width=6)
            e.pack(side="left", padx=2)
            e.bind("<Return>", lambda ev: self._do(self.refresh))
            if var is self.plot_start:
                ttk.Label(pbar, text="to").pack(side="left")
        ttk.Label(pbar, text="nm").pack(side="left")
        ttk.Checkbutton(pbar, text="Plot All Chan", variable=self.plot_all,
                        command=lambda: self._do(self.refresh)).pack(side="left", padx=10)
        ttk.Radiobutton(pbar, text="Abs", variable=self.relative, value=False, command=self._show_sliders).pack(side="right")
        ttk.Radiobutton(pbar, text="Rel", variable=self.relative, value=True, command=self._show_sliders).pack(side="right")
        # Many channels do not fit side by side, so the sliders scroll horizontally.
        holder = ttk.Frame(mid)
        holder.grid(row=2, column=0, sticky="ew")
        holder.columnconfigure(0, weight=1)
        scroller = tk.Canvas(holder, height=185, highlightthickness=0)
        scroller.grid(row=0, column=0, sticky="ew")
        bar = ttk.Scrollbar(holder, orient="horizontal", command=scroller.xview)
        bar.grid(row=1, column=0, sticky="ew")
        scroller.configure(xscrollcommand=bar.set)
        self.slider_frame = ttk.Frame(scroller)
        scroller.create_window(0, 0, window=self.slider_frame, anchor="nw")
        self.slider_frame.bind("<Configure>", lambda e: scroller.configure(scrollregion=scroller.bbox("all")))

        # right: presets and chromaticity chart / target pane
        right = ttk.Frame(self, padding=6)
        right.grid(row=0, column=2, sticky="ns")
        pre = ttk.LabelFrame(right, text="Presets", padding=6)
        pre.pack(fill="x")
        self.preset_box = ttk.Combobox(pre, state="readonly", width=30)
        self.preset_box.pack(fill="x")
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self._do(self._recall))
        self.preset_box.bind("<Delete>", lambda e: self._do(self._delete_preset))
        ttk.Button(pre, text="Store Preset", command=lambda: self._do(self._store_preset)).pack(pady=3)
        self.chart = tk.Canvas(right, width=330, height=370, bg="white", highlightthickness=1)
        self.chart.pack(pady=8)
        self.chart.bind("<Button-1>", self._chart_click)
        self._build_target_pane(right)
        self._draw_chart()

        # bottom: status and alarm
        bottom = ttk.Frame(self, padding=(6, 0, 6, 6))
        bottom.grid(row=1, column=0, columnspan=3, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        self.status_label = tk.Label(bottom, textvariable=self.status, anchor="w", relief="sunken", bg="#f0f0f0")
        self.status_label.grid(row=0, column=0, sticky="ew")
        self.alarm_label = tk.Label(bottom, textvariable=self.alarm, width=34, relief="sunken", bg="#f0f0f0")
        self.alarm_label.grid(row=0, column=1, padx=(6, 0))
        self.alarm_label.bind("<Button-1>", lambda e: self._do(self._clear_alarm))

    def _build_target_pane(self, parent):
        self.tpane = ttk.LabelFrame(parent, text="Target Spectrum", padding=6)
        t = self.tpane
        ttk.Button(t, text="Load CSV...", command=lambda: self._do(self._load_csv)).grid(row=0, column=0, sticky="w")
        ttk.Label(t, textvariable=self.base_name, width=24).grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Label(t, text="Black body CCT").grid(row=1, column=0, sticky="w")
        bb = ttk.Entry(t, width=8)
        bb.grid(row=1, column=1)
        bb.bind("<Return>", lambda e: self._do(lambda: self._blackbody(float(bb.get()))))
        ttk.Label(t, text="Scale factor").grid(row=2, column=0, sticky="w")
        sc = ttk.Entry(t, textvariable=self.scale, width=8)
        sc.grid(row=2, column=1)
        sc.bind("<Return>", lambda e: self._do(self._draw_plot))
        ttk.Label(t, text="Fit range (nm)").grid(row=3, column=0, sticky="w")
        ttk.Entry(t, textvariable=self.fit_start, width=6).grid(row=3, column=1)
        ttk.Entry(t, textvariable=self.fit_end, width=6).grid(row=3, column=2)
        ttk.Checkbutton(t, text="Correct chromaticity after fit", variable=self.correct_after_fit).grid(
            row=4, column=0, columnspan=3, sticky="w")
        ttk.Button(t, text="Fit To Target", command=lambda: self._do(lambda: self._fit(False))).grid(row=5, column=0, pady=4)
        ttk.Button(t, text="Fit At Max", command=lambda: self._do(lambda: self._fit(True))).grid(row=5, column=1, columnspan=2)
        ttk.Label(t, textvariable=self.rms).grid(row=6, column=0, columnspan=3, sticky="w")

    def _quit(self):
        self.disconnect()
        self.destroy()

    # ---- connection ------------------------------------------------------------------

    def _fill_ports(self, menu: tk.Menu):
        menu.delete(0, "end")
        for p in serial.tools.list_ports.comports():
            menu.add_command(label=f"{p.device}  {p.description}", command=lambda d=p.device: self.connect(d))

    def _ask_address(self):
        address = simpledialog.askstring("Network address", "pyserial URL of a shared RS-7 (see examples/serial_bridge.py):",
                                         parent=self, initialvalue="socket://10.61.100.206:5000")
        if address:
            self.connect(address)

    def _autoconnect(self):
        try:
            port = json.loads(CONFIG.read_text()).get("port")
        except (OSError, ValueError):
            port = None
        if port:
            self.connect(port)

    def connect(self, port: str):
        self.disconnect()
        try:
            self.rs7 = RS7(port)
            self.rs7.on_command = self._log
            self.rs7.set_units(Units.INTERNAL)
            self.channels = self.rs7.channel_info()
            self.observer.set(self.rs7.observer())
            self.peak.set(int(self.rs7.peak_type()))
            self.feedback.set(self.rs7.feedback())
            irr = self.rs7.working_distance() > 0
            self.out_labels["rad"].config(text="Irradiance" if irr or self.rs7.calibration_type() == "I" else "Radiance")
            self.out_labels["lum"].config(text="Illuminance" if irr or self.rs7.calibration_type() == "I" else "Luminance")
        except ERRORS as e:
            self.rs7 = None
            self.status.set(f"Could not connect to {port}: {e}")
            return
        try:
            CONFIG.write_text(json.dumps({"port": port}))
        except OSError:
            pass
        self.title(f"RS-7 Control - {port}")
        self._build_sliders()
        self._do(self._load_presets)
        self._do(self.refresh)

    def disconnect(self):
        if self.rs7:
            try:
                self.rs7.close()
            except ERRORS:
                pass
        self.rs7 = None
        self.title("RS-7 Control")

    # ---- error handling and status -------------------------------------------------------

    def _do(self, fn, *args):
        """Run a unit operation; on failure show the error in the status bar instead of crashing."""
        if not self.rs7:
            self.status.set("Not connected: choose Settings > Select COM Port")
            return None
        try:
            return fn(*args)
        except ERRORS as e:
            self._flash(str(e))
            return None

    def _log(self, cmd: str, reply: str, is_error: bool):
        self.status.set(f"{cmd}  ->  {reply}")
        if is_error:
            self._flash()

    def _flash(self, message: str | None = None):
        if message:
            self.status.set(message)
        self.status_label.config(bg="#ff6060")
        self.after(600, lambda: self.status_label.config(bg="#f0f0f0"))

    def _poll_alarm(self):
        if self.rs7 and not self.pending and self.flush_id is None:
            self.rs7.on_command = None  # polling should not overwrite the status bar
            alarm = self._do(self.rs7.alarm)
            if self.rs7:
                self.rs7.on_command = self._log
            if alarm is not None:
                active = alarm != "NONE"
                self.alarm.set(alarm if active else "No alarm")
                self.alarm_label.config(bg="#ff6060" if active else "#f0f0f0")
        self.after(2000, self._poll_alarm)

    def _clear_alarm(self):
        self.rs7.clear_alarm()

    # ---- channel sliders and main power -----------------------------------------------------

    def _build_sliders(self):
        for w in self.slider_frame.winfo_children():
            w.destroy()
        self.sliders = {}
        for info in self.channels:
            col = ttk.Frame(self.slider_frame)
            col.pack(side="left", padx=1)
            r, g, b = wavelength_to_rgb(info.nominal_wavelength)
            tk.Frame(col, bg=f"#{r:02x}{g:02x}{b:02x}", height=6, width=26).pack(fill="x")
            sl = tk.Scale(col, from_=100, to=0, resolution=0.01, length=130, width=14, showvalue=False)
            sl.pack()
            self._on_drag(sl, lambda value, ch=info.channel: self._slider_moved(ch, value))
            ttk.Label(col, text=str(info.channel), font=("TkDefaultFont", 7)).pack()
            self._tooltip(sl, f"Channel {info.channel}: {info.nominal_wavelength:g} nm, FWHM {info.nominal_fwhm:g} nm")
            self.sliders[info.channel] = sl

    def _on_drag(self, scale: tk.Scale, callback):
        """Call ``callback(value)`` only when the user moves ``scale``.

        Deliberately not ``Scale(command=...)``: that also fires after ``scale.set()`` from code,
        which would send the displayed value back to the unit.
        """
        def handler(event):
            self.shift = bool(event.state & 1)
            # The class binding moves the slider after this widget binding, so read it afterwards.
            self.after_idle(lambda: callback(float(scale.get())))

        for sequence in ("<B1-Motion>", "<ButtonRelease-1>"):
            scale.bind(sequence, handler)

    def _tooltip(self, widget, text):
        widget.bind("<Enter>", lambda e: self.status.set(text), add="+")

    def _show_sliders(self):
        # In Rel mode the sliders are scaled to the strongest channel at the time of display; keep that
        # scale fixed while dragging, otherwise dragging the strongest channel would rescale itself.
        self.rel_peak = max(self.powers.values(), default=0) or 1.0
        for ch, sl in self.sliders.items():
            p = self.powers.get(ch, 0.0)
            sl.set(p * 100 / self.rel_peak if self.relative.get() else p)

    def _slider_moved(self, ch: int, value: float):
        if self.relative.get():
            value = value * self.rel_peak / 100
        if abs(value - self.powers.get(ch, 0.0)) < 0.005:
            return  # a click that did not move it
        self.pending[ch] = value
        self.powers[ch] = value
        self._schedule_flush()

    def _main_moved(self, value: float):
        self.pending_main = value
        self._schedule_flush()

    def _schedule_flush(self):
        if self.flush_id is None:
            self.flush_id = self.after(DEBOUNCE_MS, self._flush)

    def _flush(self):
        """Send what the sliders asked for, then refresh the display."""
        self.flush_id = None
        pending, main, self.pending, self.pending_main = self.pending, self.pending_main, {}, None
        if self.rs7 is None:
            return
        shift = self.shift

        def send():
            if pending:
                self.rs7.set_channel_powers(pending)
            if main is not None:
                self.rs7.set_output(main, Units.INTERNAL, keep_chromaticity=shift)
            self.refresh(sliders=main is not None)

        self._do(send)

    def _all_off(self):
        self.rs7.all_off()
        self.refresh()

    # ---- refreshing the display -----------------------------------------------------------------

    def refresh(self, sliders: bool = True):
        r = self.rs7
        if sliders:
            self.powers = r.channel_powers()
            self._show_sliders()
        r.set_units(Units.RADIOMETRIC)
        rad = r.output()
        r.set_units(Units.PHOTOMETRIC)
        lum = r.output()
        r.set_units(Units.INTERNAL)
        power = r.output()
        try:
            self.xy = r.chromaticity()
        except RS7Error:  # no spectrum (all channels off)
            pass
        self.main.set(power)
        values = {"power": f"{power:.3f}", "rad": f"{rad:.4g}", "lum": f"{lum:.4g}",
                  "x": f"{self.xy[0]:.4f}", "y": f"{self.xy[1]:.4f}"}
        try:
            values["cct"] = f"{r.cct():.0f}"
        except RS7Error:
            values["cct"] = ""
        for k, v in values.items():
            self.entries[k].set(v)
        start, end = int(self.plot_start.get()), int(self.plot_end.get())
        r.set_wavelength_range(start, end)
        self.spec = r.spectrum()
        total = sum(v for _, v in self.spec)
        self.entries["centroid"].set(f"{sum(n * v for n, v in self.spec) / total:.1f}" if total > 0 else "")
        self.chan_specs = {i.channel: r.spectrum(i.channel) for i in self.channels} if self.plot_all.get() else {}
        self._draw_plot()
        self._draw_chart()

    def _entry(self, key: str, shift: bool):
        def apply():
            r = self.rs7
            v = float(self.entries[key].get())
            if key == "power":
                r.set_output(v, Units.INTERNAL, keep_chromaticity=shift)
            elif key == "rad":
                r.set_output(v, Units.RADIOMETRIC, keep_chromaticity=shift)
            elif key == "lum":
                r.set_output(v, Units.PHOTOMETRIC, keep_chromaticity=shift)
            elif key == "cct":
                r.set_chromaticity(*cct_to_xy(v))
            elif key in ("x", "y"):
                r.set_chromaticity(float(self.entries["x"].get()), float(self.entries["y"].get()))
            self.refresh()

        self._do(apply)

    # ---- plot and chart -----------------------------------------------------------------------------

    def _draw_plot(self):
        c = self.plot
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        left, bottom, top = 50, 24, 10
        try:
            start, end = int(self.plot_start.get()), int(self.plot_end.get())
        except ValueError:
            return
        target = []
        if self.target_visible.get():
            try:
                target = [(nm, v * float(self.scale.get())) for nm, v in zip(range(start, end + 1), resample(self.base, start, end))]
            except ValueError:
                pass
        series = [(self.spec, "white")] + [(s, "#%02x%02x%02x" % wavelength_to_rgb(next(
            i.nominal_wavelength for i in self.channels if i.channel == ch))) for ch, s in self.chan_specs.items()]
        series.append((target, "#4080ff"))
        ymax = max((v for s, _ in series for _, v in s), default=0) or 1.0
        X = lambda nm: left + (nm - start) / max(end - start, 1) * (w - left - 10)
        Y = lambda v: h - bottom - v / ymax * (h - bottom - top)
        c.create_line(left, top, left, h - bottom, fill="#808080")
        c.create_line(left, h - bottom, w - 10, h - bottom, fill="#808080")
        for nm in range(start - start % 50 + 50, end, 50):
            c.create_line(X(nm), h - bottom, X(nm), h - bottom + 4, fill="#808080")
            c.create_text(X(nm), h - bottom + 12, text=str(nm), fill="#c0c0c0", font=("TkDefaultFont", 8))
        for i in range(0, 5):
            c.create_text(left - 4, Y(ymax * i / 4), text=f"{ymax * i / 4:.3g}", anchor="e", fill="#c0c0c0", font=("TkDefaultFont", 8))
        for s, color in series:
            if len(s) > 1:
                c.create_line(*[p for nm, v in s for p in (X(nm), Y(v))], fill=color)

    def _draw_chart(self):
        c = self.chart
        c.delete("all")
        W, H = int(c["width"]), int(c["height"])
        P = lambda x, y: (10 + x / CHART_W * (W - 20), H - 10 - y / CHART_H * (H - 20))
        pts = [P(x, y) for _, x, y in SPECTRAL_LOCUS]
        c.create_polygon(*[v for p in pts for v in p], fill="#e8e8e8", outline="black")
        for nm, x, y in SPECTRAL_LOCUS:
            if nm % 20 == 0 and nm >= 460 and nm <= 620:
                px, py = P(x, y)
                left_side = x < 0.3 and px > 30  # keep labels inside the canvas
                c.create_text(px + (-14 if left_side else 14), py, text=str(nm), font=("TkDefaultFont", 7))
        px, py = P(*self.xy)
        c.create_oval(px - 5, py - 5, px + 5, py + 5, outline="black", width=2)

    def _chart_click(self, event):
        W, H = int(self.chart["width"]), int(self.chart["height"])
        x = (event.x - 10) / (W - 20) * CHART_W
        y = (H - 10 - event.y) / (H - 20) * CHART_H
        self._do(lambda: (self.rs7.set_chromaticity(round(x, 4), round(y, 4)), self.refresh()))

    # ---- presets ---------------------------------------------------------------------------------------

    def _load_presets(self):
        self.preset_list = self.rs7.presets()
        self.preset_box["values"] = [f"{n} - {name}" for n, name in self.preset_list.items()]
        current = self.rs7.current_preset()
        self.preset_box.set("" if current == "NONE" else current.replace(",", " - ", 1))

    def _recall(self):
        self.rs7.recall_preset(int(self.preset_box.get().split(" - ")[0]))
        self.refresh()

    def _delete_preset(self):
        n = int(self.preset_box.get().split(" - ")[0])
        if messagebox.askyesno("Delete preset", f"Delete preset {n}?"):
            self.rs7.delete_preset(n)
            self._load_presets()

    def _store_preset(self):
        n = simpledialog.askinteger("Store Preset", "Preset number (0-95):", minvalue=0, maxvalue=95, parent=self)
        if n is None:
            return
        name = simpledialog.askstring("Store Preset", "Description:", parent=self) or ""
        self.rs7.store_preset(n, name)
        self._load_presets()

    # ---- target spectrum ----------------------------------------------------------------------------------

    def _toggle_target(self):
        if self.target_visible.get():
            self.chart.pack_forget()
            self.tpane.pack(fill="x", pady=8)
        else:
            self.tpane.pack_forget()
            self.chart.pack(pady=8)
        self._draw_plot()

    def _load_csv(self):
        path = filedialog.askopenfilename(title="Base target spectrum", filetypes=[("CSV", "*.csv *.txt"), ("All", "*.*")])
        if path:
            self.base = load_csv(path)
            self.base_name.set(Path(path).name)
            self._draw_plot()

    def _blackbody(self, cct: float):
        start, end = int(self.plot_start.get()), int(self.plot_end.get())
        self.base = list(zip(range(start, end + 1), blackbody(cct, start, end)))
        self.base_name.set(f"black body {cct:g} K")
        self._draw_plot()

    def _fit(self, at_max: bool):
        r = self.rs7
        start, end = int(self.fit_start.get()), int(self.fit_end.get())
        r.set_wavelength_range(start, end)
        r.set_target_spectrum([v * float(self.scale.get()) for v in resample(self.base, start, end)])
        r.fit(include_white=self.include_white.get(), at_max=at_max)
        if self.correct_after_fit.get():
            r.color_correct()
        self.rms.set(f"RMS error: {r.rms_error():.3f} %")
        self.refresh()

    # ---- settings --------------------------------------------------------------------------------------------

    def _set_observer(self):
        self.rs7.set_observer(self.observer.get())
        self.refresh()

    def _set_peak(self):
        self.rs7.set_peak_type(PeakType(self.peak.get()))

    def _ask_distance(self):
        mm = simpledialog.askinteger("Working distance", "Working distance in mm (0 = radiance mode):",
                                     minvalue=0, parent=self, initialvalue=self._do(self.rs7.working_distance) if self.rs7 else 0)
        if mm is not None:
            self._do(lambda: (self.rs7.set_working_distance(mm), self.refresh()))


def main():
    try:  # sharp text on high-DPI Windows screens
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError, ImportError):
        pass
    App().mainloop()
