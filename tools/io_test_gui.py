#!/usr/bin/env python3
"""Volvo L60H commissioning-only Modbus I/O test panel."""

import csv
import queue
import sys
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk

from pymodbus.client import ModbusTcpClient


PLC_IP = sys.argv[1] if len(sys.argv) > 1 else "10.90.11.200"
POLL_INTERVAL_MS = 250
ANALOG_RAW_FULL_SCALE = 27648.0
ANALOG_MIN_MA = 4.0
ANALOG_SPAN_MA = 16.0
PRESSURE_SPAN_BAR = 400.0
SENSOR_CHARACTERISTIC_DEVIATION_PERCENT = 0.8
PRESSURE_ZERO_DEADBAND_BAR = PRESSURE_SPAN_BAR * SENSOR_CHARACTERISTIC_DEVIATION_PERCENT / 100.0

LOG_OUTPUTS = (
    ("main_power", 0, 7),
    ("mcu_enable", 1, 6),
    ("am_relays", 2, None),
    ("ign_r", 4, 0),
    ("ign_15_54", 5, 1),
    ("ign_dr", 6, 2),
    ("starter_50", 7, 3),
    ("park_brake_control", 8, 5),
    ("park_brake_complement", 9, 4),
    ("estop_solenoid_1", 10, None),
    ("estop_solenoid_2", 11, None),
)

OUTPUTS = [
    (1, "Main power", "MainPwr_Sw  %Q49.7", (0,)),
    (2, "MCU enable", "MCU_Enable  %Q49.6", (1,)),
    (3, "A/M relays", "AM_Relays  %Q0.3", (2,)),
    (5, "Ignition R", "Ign_R  %Q49.0", (4,)),
    (6, "Ignition 15/54", "Ign_15_54  %Q49.1", (5,)),
    (7, "Ignition DR", "Ign_DR  %Q49.2", (6,)),
    (8, "Starter 50", "Ign_50  %Q49.3", (7,)),
    (9, "Park brake", "ON = brake enabled | physical channels %Q49.5 / %Q49.4", (8, 9)),
    (11, "E-stop solenoids", "Sol_Estop %Q0.0 + Sol_Estop_2 %Q0.1", (10, 11)),
]

PRESSURES = ("Shuttle 1", "Shuttle 2", "E-stop 1", "E-stop 2", "Prop")
# Modbus remains production-compatible: Shuttle1, Estop1, Shuttle2, Estop2, Prop.
# Reorder only the GUI presentation.
PRESSURE_DISPLAY_ORDER = (0, 2, 1, 3, 4)

STATUS_FIELDS = (
    ("ACTIVE", 0, True),
    ("HEARTBEAT", 1, True),
    ("COMM LOST", 2, False),
    ("SAFE OK", 3, True),
    ("AUTO MODE", 4, None),
    ("REMOTE E-STOP CH1", 5, True),
    ("MCU DISABLE", 6, False),
    ("A/M RELAYS DISABLE", 7, False),
    ("PARK DISABLE", 8, False),
    ("E-BRAKE DISABLE", 9, False),
    ("REMOTE E-STOP CH2", 10, True),
    ("REMOTE ACK", 11, None),
    ("REMOTE START", 12, None),
    ("OUTPUTS IN M ENABLED", 13, None),
)

SAFETY_DETAIL_FIELDS = (
    ("E-STOP LOGIC SAFE", 0, True),
    ("REMOTE E-STOP OK", 1, True),
    ("TEST AUTO OK", 2, True),
    ("PRESSURE TRIP", 3, False),
    ("COMM LOST (DIRECT)", 4, False),
    ("SAFE OK (DIRECT)", 5, True),
    ("TEST ACTIVE (DIRECT)", 6, True),
    ("COMM SEEN (DIRECT)", 7, True),
)

# GUI selector -> HR12 F-RQ readback bit. The readback bit order follows
# %Q49.0..7, while the GUI order is organized by machine function.
F_RQ_READBACK = {1: 7, 2: 6, 5: 0, 6: 1, 7: 2, 8: 3}
PARK_BRAKE_SELECTOR = 9
PARK_BRAKE_DEFAULT_MASK = 1 << (PARK_BRAKE_SELECTOR - 1)
ESTOP_SELECTOR = 11
ESTOP_SELECTOR_MASK = 1 << (ESTOP_SELECTOR - 1)
# Cranking may alter only the four ignition-key selectors. Preserve every
# independent non-ignition request; Park Brake is additionally forced ON.
CRANK_RETAINED_MASK = 0x0007 | PARK_BRAKE_DEFAULT_MASK | ESTOP_SELECTOR_MASK
PARK_BRAKE_CONTROL_Q_BIT = 8
PARK_BRAKE_COMPLEMENT_Q_BIT = 9
PARK_BRAKE_CONTROL_RQ_BIT = 5
PARK_BRAKE_COMPLEMENT_RQ_BIT = 4

# Ignition-only test equivalent of production states 6..10. Main power, MCU and
# A/M-relay outputs retain their pre-start states. Starter 50 is limited to 10 s.
CRANK_STAGES = (
    (14, 1.0, "IGNACCESSORY: R (1 s)"),
    (15, 3.0, "IGNRUN / glow: R + 15/54 + DR (3 s)"),
    (16, 10.0, "CRANK: DR + starter 50 (10 s maximum)"),
    (17, None, "STARTER OFF: run position — use SAFE DEFAULTS when finished"),
)


def _timestamp_fields():
    now_utc = datetime.now(timezone.utc)
    return {
        "timestamp_utc": now_utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "timestamp_local": now_utc.astimezone().isoformat(timespec="milliseconds"),
    }


def raw_to_ma(raw: int) -> float:
    """Convert Siemens normalized 4–20 mA raw counts to calculated loop mA."""
    return ANALOG_MIN_MA + (raw * ANALOG_SPAN_MA / ANALOG_RAW_FULL_SCALE)


def pressure_word_to_bar(word: int) -> float:
    """Decode x10-bar telemetry and normalize the sensor's zero uncertainty."""
    signed = word - 0x10000 if word & 0x8000 else word
    pressure = signed / 10.0
    return 0.0 if pressure <= PRESSURE_ZERO_DEADBAND_BAR else pressure


class SessionCsvLogger:
    """Non-blocking CSV telemetry, command and event writer."""

    BASE_FIELDS = ("timestamp_utc", "timestamp_local", "run_id")
    TELEMETRY_FIELDS = BASE_FIELDS + (
        "elapsed_seconds", "plc_ip", "connection_ok", "error", "poll_latency_ms",
        "gui_heartbeat", "armed", "outputs_in_m_requested", "selected_mask",
        "crank_sequence_running", "crank_stage", "plc_active_mask",
        "shuttle1_bar", "estop1_bar", "shuttle2_bar", "estop2_bar", "prop_bar",
        "shuttle1_ma", "estop1_ma", "shuttle2_ma", "estop2_ma", "prop_ma",
        "shuttle1_raw", "estop1_raw", "shuttle2_raw", "estop2_raw", "prop_raw",
        "test_active", "heartbeat_seen", "comm_lost", "safe_ok", "auto_mode",
        "remote_estop_ch1", "remote_estop_ch2", "remote_ack", "remote_start",
        "mcu_disable", "am_relays_disable", "park_disable", "ebrake_disable",
        "outputs_in_m_enabled", "estop_logic_safe", "remote_estop_ok", "test_auto_ok",
        "pressure_trip", "comm_lost_direct", "safe_ok_direct", "test_active_direct",
        "comm_seen_direct", "request_mask", "output_mask", "relay_readback_mask",
        "plc_telemetry_sequence", "plc_telemetry_age_seconds",
    ) + tuple(
        field
        for name, _, rq_bit in LOG_OUTPUTS
        for field in ((f"req_{name}", f"q_{name}") + ((f"rq_{name}",) if rq_bit is not None else ()))
    ) + tuple(f"hr{index}" for index in range(22))
    COMMAND_FIELDS = BASE_FIELDS + (
        "elapsed_seconds", "plc_ip", "source", "command_name", "register",
        "value_decimal", "value_hex", "write_result", "modbus_error", "latency_ms",
        "armed", "crank_stage", "selected_mask",
    )
    EVENT_FIELDS = BASE_FIELDS + (
        "elapsed_seconds", "plc_ip", "severity", "event_type", "message",
        "state", "old_value", "new_value",
    )

    def __init__(self, plc_ip: str):
        self.plc_ip = plc_ip
        self.started_monotonic = time.monotonic()
        started = datetime.now().astimezone()
        self.run_id = f"{started:%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"
        self.log_dir = Path.home() / "Documents" / "VolvoL60H" / "logs" / f"{started:%Y-%m-%d}"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        prefix = self.log_dir / f"{started:%Y-%m-%d_%H-%M-%S}_{self.run_id}"
        self.paths = {
            "telemetry": Path(f"{prefix}_telemetry.csv"),
            "commands": Path(f"{prefix}_commands.csv"),
            "events": Path(f"{prefix}_events.csv"),
        }
        self._queue = queue.Queue(maxsize=50000)
        self._stop = threading.Event()
        self._error = ""
        self.dropped_rows = 0
        self._thread = threading.Thread(target=self._writer, name="volvo-csv-logger", daemon=True)
        self._thread.start()

    @property
    def error(self):
        return self._error

    @property
    def elapsed(self):
        return time.monotonic() - self.started_monotonic

    def _enqueue(self, kind: str, row: dict):
        item = dict(_timestamp_fields(), run_id=self.run_id, **row)
        try:
            self._queue.put_nowait((kind, item))
        except queue.Full:
            self.dropped_rows += 1
            self._error = f"CSV queue full; dropped {self.dropped_rows} row(s)"

    def telemetry(self, row: dict):
        self._enqueue("telemetry", row)

    def command(self, row: dict):
        self._enqueue("commands", row)

    def event(self, row: dict):
        self._enqueue("events", row)

    def close(self):
        self._stop.set()
        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            self._error = "CSV writer did not stop cleanly"

    def _writer(self):
        files = {}
        writers = {}
        schemas = {
            "telemetry": self.TELEMETRY_FIELDS,
            "commands": self.COMMAND_FIELDS,
            "events": self.EVENT_FIELDS,
        }
        try:
            for kind, path in self.paths.items():
                files[kind] = path.open("w", newline="", encoding="utf-8")
                writers[kind] = csv.DictWriter(files[kind], fieldnames=schemas[kind], extrasaction="ignore")
                writers[kind].writeheader()
            last_flush = time.monotonic()
            while not self._stop.is_set() or not self._queue.empty():
                try:
                    kind, row = self._queue.get(timeout=0.2)
                except queue.Empty:
                    kind = None
                if kind is not None:
                    writers[kind].writerow(row)
                now = time.monotonic()
                if now - last_flush >= 1.0 or (kind == "events"):
                    for handle in files.values():
                        handle.flush()
                    last_flush = now
        except Exception as exc:
            self._error = f"CSV writer error: {exc}"
        finally:
            for handle in files.values():
                try:
                    handle.flush()
                    handle.close()
                except Exception:
                    pass


class TestPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Volvo L60H I/O Test — {PLC_IP}")
        self.client = ModbusTcpClient(PLC_IP, port=502, timeout=0.8)
        self.heartbeat = 0
        # Begin every newly armed test with the parking brake requested ON.
        # The request is ignored by the PLC while the panel is disarmed.
        self.selected_mask = PARK_BRAKE_DEFAULT_MASK
        self.crank_stage = 0
        self.connected = False
        self.crank_sequence_running = False
        self.crank_stage_index = 0
        self.crank_stage_started = 0.0
        self.armed = tk.BooleanVar(value=False)
        self.allow_manual_mode = tk.BooleanVar(value=False)
        self.logging_enabled = tk.BooleanVar(value=True)
        self.connection_text = tk.StringVar(value="Disconnected")
        self.active_text = tk.StringVar(value="PLC active manual mask: 0x0000")
        self.telemetry_text = tk.StringVar(value="PLC telemetry: waiting")
        self.logging_text = tk.StringVar(value="CSV logging: starting")
        self.crank_sequence_text = tk.StringVar(value="Crank sequence: idle")
        self.status_vars = {name: tk.StringVar(value="—") for name, _, _ in STATUS_FIELDS}
        self.safety_detail_vars = {name: tk.StringVar(value="—") for name, _, _ in SAFETY_DETAIL_FIELDS}
        self.status_indicators: dict[str, tk.Label] = {}
        self.last_telemetry_sequence = None
        self.last_telemetry_change = time.monotonic()
        self.pressure_vars = [tk.StringVar(value="— bar") for _ in PRESSURES]
        self.buttons: dict[int, ttk.Button] = {}
        self.output_indicators: dict[int, tuple[tk.Label, tuple[int, ...]]] = {}
        self.logger = None
        self.last_event_values = {}
        self.last_written_controls = {}
        try:
            self.logger = SessionCsvLogger(PLC_IP)
            self.logging_text.set(f"CSV logging: {self.logger.log_dir}")
        except Exception as exc:
            self.logging_enabled.set(False)
            self.logging_text.set(f"CSV LOG ERROR: {exc}")
        self._build()
        self._log_event("INFO", "GUI_STARTED", "I/O test GUI started")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll)

    def _build(self):
        viewport = ttk.Frame(self.root)
        viewport.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        viewport.rowconfigure(0, weight=1)

        canvas = tk.Canvas(viewport, highlightthickness=0)
        vertical_scroll = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
        horizontal_scroll = ttk.Scrollbar(viewport, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical_scroll.set, xscrollcommand=horizontal_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical_scroll.grid(row=0, column=1, sticky="ns")
        horizontal_scroll.grid(row=1, column=0, sticky="ew")

        outer = ttk.Frame(canvas, padding=12)
        canvas_window = canvas.create_window((0, 0), window=outer, anchor="nw")
        outer.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))

        def resize_canvas(event):
            requested = outer.winfo_reqwidth()
            canvas.itemconfigure(canvas_window, width=max(event.width, requested))

        canvas.bind("<Configure>", resize_canvas)
        canvas.bind_all("<MouseWheel>", lambda event: canvas.yview_scroll(int(-event.delta / 120), "units"))

        ttk.Label(outer, text="COMMISSIONING I/O TEST", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=5, sticky="w"
        )
        ttk.Label(
            outer,
            text="Multiple output toggles may be active together. ARM and a live heartbeat are required.",
            foreground="#8a3b00",
        ).grid(row=1, column=0, columnspan=5, sticky="w", pady=(0, 8))

        ttk.Label(outer, textvariable=self.connection_text).grid(row=2, column=0, sticky="w")
        ttk.Label(outer, textvariable=self.active_text).grid(row=2, column=1, sticky="w")
        ttk.Label(outer, textvariable=self.telemetry_text).grid(row=2, column=2, sticky="w")
        ttk.Button(outer, text="SAFE DEFAULTS / DISARM", command=self.all_off).grid(row=2, column=4, sticky="e")

        arm = ttk.Checkbutton(outer, text="ARM OUTPUT TEST", variable=self.armed, command=self.arm_changed)
        arm.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 10))
        ttk.Checkbutton(
            outer,
            text="ALLOW OUTPUTS WITH A/M IN M",
            variable=self.allow_manual_mode,
            command=self.manual_mode_changed,
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 10))
        ttk.Checkbutton(
            outer,
            text="ENABLE CSV LOGGING",
            variable=self.logging_enabled,
            command=self.logging_changed,
        ).grid(row=3, column=4, sticky="e", pady=(8, 10))

        crank_sequence = ttk.LabelFrame(outer, text="Production crank sequence test", padding=8)
        crank_sequence.grid(row=4, column=0, columnspan=5, sticky="ew", pady=(0, 10))
        ttk.Button(crank_sequence, text="RUN CRANK SEQUENCE", command=self.start_crank_sequence).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(crank_sequence, text="ENGINE RUNNING / STOP STARTER", command=self.stop_starter).grid(
            row=0, column=1, padx=(0, 12)
        )
        ttk.Button(crank_sequence, text="ABORT CRANK", command=self.cancel_crank_sequence).grid(
            row=0, column=2, padx=(0, 12)
        )
        ttk.Label(crank_sequence, textvariable=self.crank_sequence_text).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        out_frame = ttk.LabelFrame(outer, text="Independent output toggles", padding=8)
        out_frame.grid(row=5, column=0, columnspan=5, sticky="nsew")
        for row, (selector, label, detail, output_bits) in enumerate(OUTPUTS):
            button = ttk.Button(out_frame, text="OFF", width=8, command=lambda s=selector: self.toggle(s))
            button.grid(row=row, column=0, padx=(0, 8), pady=2)
            ttk.Label(out_frame, text=label, width=20).grid(row=row, column=1, sticky="w")
            ttk.Label(out_frame, text=detail).grid(row=row, column=2, sticky="w")
            indicator = tk.Label(out_frame, text="UNKNOWN", width=36, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=3, padx=(10, 0), sticky="e")
            self.buttons[selector] = button
            self.output_indicators[selector] = (indicator, output_bits)

        lower_frame = ttk.Frame(outer)
        lower_frame.grid(row=6, column=0, columnspan=5, sticky="nsew", pady=(10, 0))
        for column in range(3):
            lower_frame.columnconfigure(column, weight=1)

        pressure_frame = ttk.LabelFrame(lower_frame, text="Pressure telemetry", padding=8)
        pressure_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        pressure_frame.columnconfigure(1, weight=1)
        for row, (name, var) in enumerate(zip(PRESSURES, self.pressure_vars)):
            ttk.Label(pressure_frame, text=name, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(pressure_frame, textvariable=var, width=32).grid(row=row, column=1, sticky="e")

        status_frame = ttk.LabelFrame(lower_frame, text="PLC safety/status", padding=8)
        status_frame.grid(row=0, column=1, sticky="nsew", padx=5)
        status_rows = (len(self.status_vars) + 1) // 2
        for index, (name, var) in enumerate(self.status_vars.items()):
            row = index % status_rows
            column = (index // status_rows) * 2
            ttk.Label(status_frame, text=name, width=20).grid(row=row, column=column, sticky="w", padx=(0, 3))
            indicator = tk.Label(status_frame, textvariable=var, width=9, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=column + 1, sticky="e", pady=1, padx=(0, 8))
            self.status_indicators[name] = indicator

        detail_frame = ttk.LabelFrame(lower_frame, text="SafeOK source values", padding=8)
        detail_frame.grid(row=0, column=2, sticky="nsew", padx=(5, 0))
        detail_rows = (len(self.safety_detail_vars) + 1) // 2
        for index, (name, var) in enumerate(self.safety_detail_vars.items()):
            row = index % detail_rows
            column = (index // detail_rows) * 2
            ttk.Label(detail_frame, text=name, width=22).grid(row=row, column=column, sticky="w", padx=(0, 3))
            indicator = tk.Label(detail_frame, textvariable=var, width=9, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=column + 1, sticky="e", pady=1, padx=(0, 8))
            self.status_indicators[name] = indicator

        ttk.Label(
            outer,
            text=("Park brake has one command: ON = brake enabled, OFF = brake disabled. "
                  "The two complementary physical channels remain visible as Q/RQ feedback. "
                  "Both E-stop solenoids operate together."),
            wraplength=760,
            foreground="#555555",
        ).grid(row=7, column=0, columnspan=5, sticky="w", pady=(10, 0))
        ttk.Label(outer, textvariable=self.logging_text, foreground="#555555").grid(
            row=8, column=0, columnspan=5, sticky="w", pady=(6, 0)
        )

    def arm_changed(self):
        if self.armed.get():
            ok = messagebox.askyesno(
                "Arm output test",
                "Confirm the machine is secured, engine start is inhibited where required, and a multimeter test is ready.",
            )
            if not ok:
                self.armed.set(False)
                self._log_event("INFO", "ARM_CANCELLED", "Operator cancelled arming")
                return
            self.selected_mask |= PARK_BRAKE_DEFAULT_MASK
        else:
            self.cancel_crank_sequence(write=False)
            self.selected_mask = 0
            self.allow_manual_mode.set(False)
        self._log_event("WARNING" if self.armed.get() else "INFO", "ARM_CHANGED", f"Armed={self.armed.get()}")
        self.write_controls(source="arm_changed")
        self.refresh_buttons()

    def manual_mode_changed(self):
        if self.allow_manual_mode.get():
            if not self.armed.get():
                self.allow_manual_mode.set(False)
                messagebox.showwarning("Not armed", "ARM OUTPUT TEST before enabling outputs in M.")
                return
            ok = messagebox.askyesno(
                "Allow outputs in Manual",
                "TEST PROJECT ONLY: allow real outputs while the physical A/M switch is in M?\n\n"
                "The remote E-stop, hardware acknowledgement, heartbeat and disable inputs remain active.",
            )
            if not ok:
                self.allow_manual_mode.set(False)
        self._log_event(
            "WARNING" if self.allow_manual_mode.get() else "INFO",
            "MANUAL_MODE_PERMISSION_CHANGED",
            f"Outputs-in-M permission requested={self.allow_manual_mode.get()}",
        )
        self.write_controls(source="manual_mode_changed")

    def logging_changed(self):
        if self.logging_enabled.get():
            if self.logger is not None:
                return
            try:
                self.logger = SessionCsvLogger(PLC_IP)
                self.logging_text.set(
                    f"CSV logging: {self.logger.log_dir} | run {self.logger.run_id}"
                )
                self._log_event("INFO", "LOGGING_ENABLED", "CSV logging enabled")
            except Exception as exc:
                self.logger = None
                self.logging_enabled.set(False)
                self.logging_text.set(f"CSV LOG ERROR: {exc}")
                messagebox.showerror("CSV logging error", str(exc))
        else:
            if self.logger is not None:
                logger = self.logger
                self._log_event("INFO", "LOGGING_DISABLED", "CSV logging disabled by operator")
                logger.close()
                error = logger.error
                self.logger = None
                self.logging_text.set(f"CSV logging: OFF{f' | {error}' if error else ''}")
            else:
                self.logging_text.set("CSV logging: OFF")

    def toggle(self, selector: int):
        if not self.armed.get():
            messagebox.showwarning("Not armed", "ARM OUTPUT TEST before selecting an output.")
            return
        if self.crank_sequence_running:
            if self.crank_stage != 17:
                messagebox.showwarning(
                    "Crank sequence active",
                    "Output toggles are locked until the starter has stopped and the sequence reaches engine-running stage 17.",
                )
                return
            if selector in (5, 6, 7, 8):
                messagebox.showinfo(
                    "Ignition controlled by sequence",
                    "R, 15/54, DR and Starter 50 are controlled by the crank sequence. "
                    "Use ABORT CRANK or SAFE DEFAULTS / DISARM to remove the run-position ignition requests.",
                )
                return
        bit = selector - 1
        mask = 1 << bit
        if self.selected_mask & mask:
            self.selected_mask &= ~mask
        else:
            self.selected_mask |= mask
        self._log_event(
            "WARNING",
            "OUTPUT_TOGGLE",
            f"Selector {selector} changed; selected mask=0x{self.selected_mask:04X}",
            state=self.crank_stage,
        )
        self.write_controls(source=f"toggle_{selector}")
        self.refresh_buttons()

    def all_off(self):
        self.cancel_crank_sequence(write=False)
        self.selected_mask = 0
        self.crank_stage = 0
        self.armed.set(False)
        self.allow_manual_mode.set(False)
        self._log_event("WARNING", "SAFE_DEFAULTS", "SAFE DEFAULTS / DISARM selected")
        self.write_controls(source="all_off")
        self.refresh_buttons()

    def start_crank_sequence(self):
        if not self.armed.get():
            messagebox.showwarning("Not armed", "ARM OUTPUT TEST before running the crank sequence.")
            return
        ok = messagebox.askyesno(
            "Run production crank sequence",
            "WARNING: This commands the real ignition and starter outputs and may start the engine.\n\n"
            "Only the ignition outputs are sequenced. Main Power, MCU and A/M relays retain "
            "their current ON/OFF settings throughout the sequence. The Park Brake is forced ON "
            "before cranking and remains ON when state 17 is reached.\n\n"
            "Confirm the machine is secured, the area is clear, brakes are engaged, and you are ready "
            "to press ENGINE RUNNING / STOP STARTER as soon as the engine catches.",
        )
        if not ok:
            return
        self.crank_sequence_running = True
        # Preserve every non-ignition request and force the parking brake ON for
        # the complete crank. State 17 inherits these bits; the operator may
        # then change independent outputs explicitly.
        self.selected_mask = (
            self.selected_mask & CRANK_RETAINED_MASK
        ) | PARK_BRAKE_DEFAULT_MASK
        self.crank_stage_index = 0
        self.crank_stage_started = time.monotonic()
        self.crank_stage = CRANK_STAGES[0][0]
        self.crank_sequence_text.set(f"Crank sequence: {CRANK_STAGES[0][2]}")
        self._log_event("WARNING", "CRANK_STARTED", "Crank sequence started", state=self.crank_stage)
        self.write_controls(source="crank_start")
        self.refresh_buttons()

    def cancel_crank_sequence(self, write=True):
        was_running = self.crank_sequence_running
        self.crank_sequence_running = False
        self.crank_stage_index = 0
        self.crank_stage = 0
        self.crank_sequence_text.set(
            "Crank sequence: aborted / ignition off; power settings retained"
            if was_running else "Crank sequence: idle"
        )
        if write and was_running:
            self._log_event("WARNING", "CRANK_ABORTED", "Crank sequence aborted", state=0)
            self.write_controls(source="crank_abort")
            self.refresh_buttons()

    def stop_starter(self):
        if not self.crank_sequence_running or self.crank_stage != 16:
            return
        self.crank_stage_index = 3
        self.crank_stage_started = time.monotonic()
        self.crank_stage = 17
        self.crank_sequence_text.set(f"Crank sequence: {CRANK_STAGES[3][2]}")
        self._log_event("INFO", "ENGINE_RUNNING_CONFIRMED", "Starter stopped; stage 17 selected", state=17)
        self.write_controls(source="engine_running")

    def advance_crank_sequence(self):
        if not self.crank_sequence_running:
            return
        _, duration, description = CRANK_STAGES[self.crank_stage_index]
        self.crank_sequence_text.set(f"Crank sequence: {description}")
        if duration is None or time.monotonic() - self.crank_stage_started < duration:
            return
        self.crank_stage_index += 1
        self.crank_stage_started = time.monotonic()
        selector, _, description = CRANK_STAGES[self.crank_stage_index]
        self.crank_stage = selector
        self.crank_sequence_text.set(f"Crank sequence: {description}")
        self._log_event("INFO", "CRANK_STAGE_CHANGED", description, state=self.crank_stage)
        self.write_controls(source="crank_advance")

    def _write_register(self, register: int, value: int, name: str, source: str):
        started = time.monotonic()
        result = "SUCCESS"
        error = ""
        try:
            response = self.client.write_register(register, value)
            if response.isError():
                result = "MODBUS_ERROR"
                error = str(response)
        except Exception as exc:
            result = "EXCEPTION"
            error = str(exc)
        if self.logger is not None:
            self.logger.command({
                "elapsed_seconds": f"{self.logger.elapsed:.3f}",
                "plc_ip": PLC_IP,
                "source": source,
                "command_name": name,
                "register": register,
                "value_decimal": value,
                "value_hex": f"0x{value:04X}",
                "write_result": result,
                "modbus_error": error,
                "latency_ms": f"{(time.monotonic() - started) * 1000.0:.3f}",
                "armed": self.armed.get(),
                "crank_stage": self.crank_stage,
                "selected_mask": f"0x{self.selected_mask:04X}",
            })
        return result == "SUCCESS"

    def write_controls(self, source="poll", force=False):
        controls = (
            (0, self.selected_mask, "MANUAL_OUTPUT_MASK"),
            (1, 0xA55A if self.armed.get() else 0, "ARM_OUTPUT_TEST"),
            (11, self.crank_stage, "CRANK_STAGE"),
            (13, 0x4D4D if self.armed.get() and self.allow_manual_mode.get() else 0, "ALLOW_OUTPUTS_IN_M"),
        )
        for register, value, name in controls:
            # Holding registers do not need identical writes every poll. Re-send
            # after reconnect or when a user/sequence action explicitly writes.
            if source == "poll" and not force and self.last_written_controls.get(register) == value:
                continue
            if self._write_register(register, value, name, source):
                self.last_written_controls[register] = value

    def _log_event(self, severity: str, event_type: str, message: str, state="", old_value="", new_value=""):
        if self.logger is None:
            return
        self.logger.event({
            "elapsed_seconds": f"{self.logger.elapsed:.3f}",
            "plc_ip": PLC_IP,
            "severity": severity,
            "event_type": event_type,
            "message": message,
            "state": state,
            "old_value": old_value,
            "new_value": new_value,
        })

    def _log_changed_event(self, key: str, value, severity="INFO"):
        if key not in self.last_event_values:
            self.last_event_values[key] = value
            return
        old_value = self.last_event_values[key]
        if old_value == value:
            return
        self.last_event_values[key] = value
        self._log_event(severity, f"{key}_CHANGED", f"{key}: {old_value} -> {value}", self.crank_stage, old_value, value)

    def _log_telemetry(self, regs, raw_inputs, poll_latency_ms, error=""):
        if self.logger is None:
            return
        status = regs[9] if regs else 0
        safety = regs[15] if regs else 0
        requests = regs[14] if regs else 0
        outputs = regs[10] if regs else 0
        readbacks = regs[12] if regs else 0
        row = {
            "elapsed_seconds": f"{self.logger.elapsed:.3f}",
            "plc_ip": PLC_IP,
            "connection_ok": bool(regs),
            "error": error,
            "poll_latency_ms": f"{poll_latency_ms:.3f}",
            "gui_heartbeat": self.heartbeat,
            "armed": self.armed.get(),
            "outputs_in_m_requested": self.allow_manual_mode.get(),
            "selected_mask": f"0x{self.selected_mask:04X}",
            "crank_sequence_running": self.crank_sequence_running,
            "crank_stage": self.crank_stage,
            "plc_active_mask": f"0x{regs[2]:04X}" if regs else "",
            "request_mask": f"0x{requests:04X}" if regs else "",
            "output_mask": f"0x{outputs:04X}" if regs else "",
            "relay_readback_mask": f"0x{readbacks:04X}" if regs else "",
        }
        if regs:
            pressure_names = ("shuttle1_bar", "estop1_bar", "shuttle2_bar", "estop2_bar", "prop_bar")
            current_names = ("shuttle1_ma", "estop1_ma", "shuttle2_ma", "estop2_ma", "prop_ma")
            raw_names = ("shuttle1_raw", "estop1_raw", "shuttle2_raw", "estop2_raw", "prop_raw")
            pressure_values = [pressure_word_to_bar(value) for value in regs[3:8]]
            row.update({name: f"{value:.1f}" for name, value in zip(pressure_names, pressure_values)})
            row.update({name: f"{raw_to_ma(raw):.3f}" for name, raw in zip(current_names, raw_inputs)})
            row.update(dict(zip(raw_names, raw_inputs)))
            status_values = {
                "test_active": 0, "heartbeat_seen": 1, "comm_lost": 2, "safe_ok": 3,
                "auto_mode": 4, "remote_estop_ch1": 5, "mcu_disable": 6,
                "am_relays_disable": 7, "park_disable": 8, "ebrake_disable": 9,
                "remote_estop_ch2": 10, "remote_ack": 11, "remote_start": 12,
                "outputs_in_m_enabled": 13,
            }
            safety_values = {
                "estop_logic_safe": 0, "remote_estop_ok": 1, "test_auto_ok": 2,
                "pressure_trip": 3, "comm_lost_direct": 4, "safe_ok_direct": 5,
                "test_active_direct": 6, "comm_seen_direct": 7,
            }
            row.update({name: bool(status & (1 << bit)) for name, bit in status_values.items()})
            row.update({name: bool(safety & (1 << bit)) for name, bit in safety_values.items()})
            row["plc_telemetry_sequence"] = regs[16]
            row["plc_telemetry_age_seconds"] = f"{time.monotonic() - self.last_telemetry_change:.3f}"
            for name, q_bit, rq_bit in LOG_OUTPUTS:
                row[f"req_{name}"] = bool(requests & (1 << q_bit))
                row[f"q_{name}"] = bool(outputs & (1 << q_bit))
                if rq_bit is not None:
                    row[f"rq_{name}"] = bool(readbacks & (1 << rq_bit))
            row.update({f"hr{index}": value for index, value in enumerate(regs)})
        self.logger.telemetry(row)

    def refresh_buttons(self):
        for selector, button in self.buttons.items():
            if self.crank_sequence_running and selector in (5, 6, 7, 8):
                button.configure(text="SEQUENCE")
                continue
            requested = bool(self.selected_mask & (1 << (selector - 1)))
            button.configure(text="ON" if self.armed.get() and requested else "OFF")

    def poll(self):
        poll_started = time.monotonic()
        try:
            self.advance_crank_sequence()
            if not self.client.connected:
                self.client.connect()
            self.heartbeat = (self.heartbeat + 1) & 0xFFFF
            self._write_register(8, self.heartbeat, "GUI_HEARTBEAT", "poll")
            self.write_controls(source="poll")
            response = self.client.read_holding_registers(0, count=22)
            if response.isError():
                raise RuntimeError(str(response))
            regs = response.registers
            was_connected = self.connected
            self.connected = True
            if not was_connected:
                self._log_event("INFO", "MODBUS_CONNECTED", f"Connected to {PLC_IP}:502")
            self.connection_text.set(f"Connected: {PLC_IP}:502")
            self.active_text.set(f"PLC active manual mask: 0x{regs[2]:04X}")
            raw_inputs = [value - 0x10000 if value & 0x8000 else value for value in regs[17:22]]
            pressure_values = [pressure_word_to_bar(value) for value in regs[3:8]]
            for var, index in zip(self.pressure_vars, PRESSURE_DISPLAY_ORDER):
                var.set(
                    f"{pressure_values[index]:.1f} bar | "
                    f"{raw_to_ma(raw_inputs[index]):.3f} mA | raw {raw_inputs[index]}"
                )
            bits = regs[9]
            auto_mode = bool(bits & (1 << 4))
            if not auto_mode and not (self.selected_mask & ESTOP_SELECTOR_MASK):
                self.selected_mask |= ESTOP_SELECTOR_MASK
                self._log_event(
                    "INFO",
                    "MANUAL_MODE_ESTOP_DEFAULT",
                    "Manual mode forced both E-stop outputs ON/brakes disengaged",
                )
                self.write_controls(source="manual_mode_estop_default")
                self.refresh_buttons()
            for name, bit, healthy_when in STATUS_FIELDS:
                value = bool(bits & (1 << bit))
                self._set_status(name, value, healthy_when)
            safety_detail = regs[15]
            for name, bit, healthy_when in SAFETY_DETAIL_FIELDS:
                value = bool(safety_detail & (1 << bit))
                self._set_status(name, value, healthy_when)

            telemetry_sequence = regs[16]
            now = time.monotonic()
            if telemetry_sequence != self.last_telemetry_sequence:
                self.last_telemetry_sequence = telemetry_sequence
                self.last_telemetry_change = now
            telemetry_age = now - self.last_telemetry_change
            self.telemetry_text.set(
                f"PLC telemetry: seq {telemetry_sequence} | "
                f"{'LIVE' if telemetry_age < 1.0 else f'STALE {telemetry_age:.1f}s'}"
            )
            output_bits = regs[10]
            request_bits = regs[14]
            relay_readbacks = regs[12]
            self._log_telemetry(
                regs,
                raw_inputs,
                (time.monotonic() - poll_started) * 1000.0,
            )
            self._log_changed_event("SAFE_OK", bool(bits & (1 << 3)), "WARNING")
            self._log_changed_event("COMM_LOST", bool(bits & (1 << 2)), "WARNING")
            self._log_changed_event("TEST_ACTIVE", bool(bits & (1 << 0)))
            self._log_changed_event("AUTO_MODE", bool(bits & (1 << 4)))
            self._log_changed_event("REMOTE_ESTOP_CH1", bool(bits & (1 << 5)), "WARNING")
            self._log_changed_event("REMOTE_ESTOP_CH2", bool(bits & (1 << 10)), "WARNING")
            self._log_changed_event("PRESSURE_TRIP", bool(safety_detail & (1 << 3)), "WARNING")
            for selector, (indicator, channel_bits) in self.output_indicators.items():
                values = [bool(output_bits & (1 << bit)) for bit in channel_bits]
                requests = [bool(request_bits & (1 << bit)) for bit in channel_bits]
                if selector == PARK_BRAKE_SELECTOR:
                    brake_requested = bool(request_bits & (1 << PARK_BRAKE_CONTROL_Q_BIT))
                    complement_requested = bool(request_bits & (1 << PARK_BRAKE_COMPLEMENT_Q_BIT))
                    control_q = bool(output_bits & (1 << PARK_BRAKE_CONTROL_Q_BIT))
                    complement_q = bool(output_bits & (1 << PARK_BRAKE_COMPLEMENT_Q_BIT))
                    control_rq = bool(relay_readbacks & (1 << PARK_BRAKE_CONTROL_RQ_BIT))
                    complement_rq = bool(relay_readbacks & (1 << PARK_BRAKE_COMPLEMENT_RQ_BIT))
                    text = (
                        f"REQ {'ON' if brake_requested else 'OFF'} | "
                        f"Q49.5 {'HIGH' if control_q else 'LOW'} / RQ {'HIGH' if control_rq else 'LOW'} | "
                        f"Q49.4 {'HIGH' if complement_q else 'LOW'} / RQ {'HIGH' if complement_rq else 'LOW'}"
                    )
                    color_ok = (
                        control_q == brake_requested
                        and complement_q == complement_requested
                        and control_q == control_rq
                        and complement_q == complement_rq
                    )
                elif len(values) == 1:
                    q_text = "HIGH" if values[0] else "LOW"
                    req_text = "HIGH" if requests[0] else "LOW"
                    if selector in F_RQ_READBACK:
                        rq_value = bool(relay_readbacks & (1 << F_RQ_READBACK[selector]))
                        text = f"REQ {req_text} | Q {q_text} | RQ {'HIGH' if rq_value else 'LOW'}"
                        color_ok = values[0] == rq_value and values[0] == requests[0]
                    else:
                        text = f"REQ {req_text} | Q {q_text}"
                        color_ok = values[0] == requests[0]
                else:
                    text = "REQ {} | CH1 {} / CH2 {}".format(
                        "HIGH" if all(requests) else "LOW",
                        "HIGH" if values[0] else "LOW", "HIGH" if values[1] else "LOW"
                    )
                    color_ok = True
                indicator.configure(
                    text=text,
                    bg=("#f3d36a" if not color_ok else
                        ("#7bd88f" if all(values) else ("#f3d36a" if any(values) else "#d9d9d9"))),
                )
        except Exception as exc:
            was_connected = self.connected
            self.connected = False
            self.last_written_controls.clear()
            self._log_telemetry(
                None,
                [],
                (time.monotonic() - poll_started) * 1000.0,
                str(exc),
            )
            if was_connected:
                self._log_event("ERROR", "MODBUS_DISCONNECTED", str(exc))
            self.connection_text.set(f"Disconnected: {exc}")
            for var in self.pressure_vars:
                var.set("— bar")
            self.telemetry_text.set("PLC telemetry: unavailable")
            for var in self.status_vars.values():
                var.set("—")
            for var in self.safety_detail_vars.values():
                var.set("—")
            for indicator in self.status_indicators.values():
                indicator.configure(bg="#d9d9d9")
            for indicator, _ in self.output_indicators.values():
                indicator.configure(text="UNKNOWN", bg="#d9d9d9")
        finally:
            if self.logger is not None:
                if self.logger.error:
                    self.logging_text.set(f"CSV LOG ERROR: {self.logger.error}")
                else:
                    self.logging_text.set(
                        f"CSV logging: {self.logger.log_dir} | run {self.logger.run_id}"
                    )
            self.root.after(POLL_INTERVAL_MS, self.poll)

    def _set_status(self, name: str, value: bool, healthy_when: bool | None):
        self.status_vars.get(name, self.safety_detail_vars.get(name)).set("TRUE" if value else "FALSE")
        if healthy_when is None:
            color = "#9fc5e8" if value else "#d9d9d9"
        else:
            color = "#7bd88f" if value == healthy_when else "#ef8b8b"
        self.status_indicators[name].configure(bg=color)

    def close(self):
        self.cancel_crank_sequence(write=False)
        self.selected_mask = 0
        self.crank_stage = 0
        self.armed.set(False)
        self.allow_manual_mode.set(False)
        self._log_event("INFO", "GUI_CLOSING", "GUI closing; output requests cleared")
        self.write_controls(source="gui_close", force=True)
        try:
            self.client.close()
        finally:
            if self.logger is not None:
                self.logger.close()
            self.root.destroy()


def main():
    root = tk.Tk()
    TestPanel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
