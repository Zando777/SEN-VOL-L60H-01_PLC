#!/usr/bin/env python3
"""Volvo L60H commissioning-only Modbus I/O test panel."""

import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

from pymodbus.client import ModbusTcpClient


PLC_IP = sys.argv[1] if len(sys.argv) > 1 else "10.90.11.200"

OUTPUTS = [
    (1, "Main power", "MainPwr_Sw  %Q49.7", (0,)),
    (2, "MCU enable", "MCU_Enable  %Q49.6", (1,)),
    (3, "A/M relays", "AM_Relays  %Q0.3", (2,)),
    (5, "Ignition R", "Ign_R  %Q49.0", (4,)),
    (6, "Ignition 15/54", "Ign_15_54  %Q49.1", (5,)),
    (7, "Ignition DR", "Ign_DR  %Q49.2", (6,)),
    (8, "Starter 50", "Ign_50  %Q49.3", (7,)),
    (9, "Park unlock", "ParkBrake_Unlock  %Q49.5", (8,)),
    (10, "Park lock", "ParkBrake_Lock  %Q49.4 (complementary)", (9,)),
    (11, "E-stop solenoids", "Sol_Estop %Q0.0 + Sol_Estop_2 %Q0.1", (10, 11)),
]

PRESSURES = ("Shuttle 1", "E-stop 1", "Shuttle 2", "E-stop 2", "Prop")

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
F_RQ_READBACK = {1: 7, 2: 6, 5: 0, 6: 1, 7: 2, 8: 3, 9: 5, 10: 4}

# Ignition-only test equivalent of production states 6..10. Main power, MCU and
# A/M-relay outputs retain their pre-start states. Starter 50 is limited to 10 s.
CRANK_STAGES = (
    (14, 1.0, "IGNACCESSORY: R (1 s)"),
    (15, 3.0, "IGNRUN / glow: R + 15/54 + DR (3 s)"),
    (16, 10.0, "CRANK: DR + starter 50 (10 s maximum)"),
    (17, None, "STARTER OFF: run position — press ALL OFF when finished"),
)


class TestPanel:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"Volvo L60H I/O Test — {PLC_IP}")
        self.client = ModbusTcpClient(PLC_IP, port=502, timeout=0.8)
        self.heartbeat = 0
        self.selected_mask = 0
        self.crank_stage = 0
        self.connected = False
        self.crank_sequence_running = False
        self.crank_stage_index = 0
        self.crank_stage_started = 0.0
        self.armed = tk.BooleanVar(value=False)
        self.allow_manual_mode = tk.BooleanVar(value=False)
        self.connection_text = tk.StringVar(value="Disconnected")
        self.active_text = tk.StringVar(value="PLC active manual mask: 0x0000")
        self.telemetry_text = tk.StringVar(value="PLC telemetry: waiting")
        self.crank_sequence_text = tk.StringVar(value="Crank sequence: idle")
        self.status_vars = {name: tk.StringVar(value="—") for name, _, _ in STATUS_FIELDS}
        self.safety_detail_vars = {name: tk.StringVar(value="—") for name, _, _ in SAFETY_DETAIL_FIELDS}
        self.status_indicators: dict[str, tk.Label] = {}
        self.last_telemetry_sequence = None
        self.last_telemetry_change = time.monotonic()
        self.pressure_vars = [tk.StringVar(value="— bar") for _ in PRESSURES]
        self.buttons: dict[int, ttk.Button] = {}
        self.output_indicators: dict[int, tuple[tk.Label, tuple[int, ...]]] = {}
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self.poll)

    def _build(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        ttk.Label(outer, text="COMMISSIONING I/O TEST", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=4, sticky="w"
        )
        ttk.Label(
            outer,
            text="Multiple output toggles may be active together. ARM and a live heartbeat are required.",
            foreground="#8a3b00",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(0, 8))

        ttk.Label(outer, textvariable=self.connection_text).grid(row=2, column=0, sticky="w")
        ttk.Label(outer, textvariable=self.active_text).grid(row=2, column=1, sticky="w")
        ttk.Label(outer, textvariable=self.telemetry_text).grid(row=2, column=2, sticky="w")
        ttk.Button(outer, text="ALL OFF / DISARM", command=self.all_off).grid(row=2, column=3, sticky="e")

        arm = ttk.Checkbutton(outer, text="ARM OUTPUT TEST", variable=self.armed, command=self.arm_changed)
        arm.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 10))
        ttk.Checkbutton(
            outer,
            text="ALLOW OUTPUTS WITH A/M IN M",
            variable=self.allow_manual_mode,
            command=self.manual_mode_changed,
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(8, 10))

        crank_sequence = ttk.LabelFrame(outer, text="Production crank sequence test", padding=8)
        crank_sequence.grid(row=4, column=0, columnspan=4, sticky="ew", pady=(0, 10))
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
        out_frame.grid(row=5, column=0, columnspan=4, sticky="nsew")
        for row, (selector, label, detail, output_bits) in enumerate(OUTPUTS):
            button = ttk.Button(out_frame, text="OFF", width=8, command=lambda s=selector: self.toggle(s))
            button.grid(row=row, column=0, padx=(0, 8), pady=2)
            ttk.Label(out_frame, text=label, width=20).grid(row=row, column=1, sticky="w")
            ttk.Label(out_frame, text=detail).grid(row=row, column=2, sticky="w")
            indicator = tk.Label(out_frame, text="UNKNOWN", width=36, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=3, padx=(10, 0), sticky="e")
            self.buttons[selector] = button
            self.output_indicators[selector] = (indicator, output_bits)

        pressure_frame = ttk.LabelFrame(outer, text="Pressure telemetry", padding=8)
        pressure_frame.grid(row=6, column=0, columnspan=2, sticky="nsew", pady=(10, 0), padx=(0, 5))
        for row, (name, var) in enumerate(zip(PRESSURES, self.pressure_vars)):
            ttk.Label(pressure_frame, text=name, width=14).grid(row=row, column=0, sticky="w")
            ttk.Label(pressure_frame, textvariable=var, width=24).grid(row=row, column=1, sticky="e")

        status_frame = ttk.LabelFrame(outer, text="PLC safety/status", padding=8)
        status_frame.grid(row=6, column=2, columnspan=2, sticky="nsew", pady=(10, 0), padx=(5, 0))
        for row, (name, var) in enumerate(self.status_vars.items()):
            ttk.Label(status_frame, text=name, width=18).grid(row=row, column=0, sticky="w")
            indicator = tk.Label(status_frame, textvariable=var, width=9, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=1, sticky="e", pady=1)
            self.status_indicators[name] = indicator

        detail_frame = ttk.LabelFrame(outer, text="SafeOK source values (direct PLC/watch-table values)", padding=8)
        detail_frame.grid(row=6, column=4, sticky="nsew", pady=(10, 0), padx=(5, 0))
        for row, (name, var) in enumerate(self.safety_detail_vars.items()):
            ttk.Label(detail_frame, text=name, width=22).grid(row=row, column=0, sticky="w")
            indicator = tk.Label(detail_frame, textvariable=var, width=9, bg="#d9d9d9", relief="sunken")
            indicator.grid(row=row, column=1, sticky="e", pady=1)
            self.status_indicators[name] = indicator

        ttk.Label(
            outer,
            text=("Park Lock and Park Unlock are complementary in F-LAD; one of that pair is commanded "
                  "whenever the safety program is active. Both E-stop solenoids operate together."),
            wraplength=760,
            foreground="#555555",
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def arm_changed(self):
        if self.armed.get():
            ok = messagebox.askyesno(
                "Arm output test",
                "Confirm the machine is secured, engine start is inhibited where required, and a multimeter test is ready.",
            )
            if not ok:
                self.armed.set(False)
                return
        else:
            self.cancel_crank_sequence(write=False)
            self.selected_mask = 0
            self.allow_manual_mode.set(False)
        self.write_controls()
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
        self.write_controls()

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
                    "Use ABORT CRANK or ALL OFF / DISARM to remove the run-position ignition requests.",
                )
                return
        bit = selector - 1
        mask = 1 << bit
        if self.selected_mask & mask:
            self.selected_mask &= ~mask
        else:
            # Park Lock and Park Unlock are physically complementary.
            if selector == 9:
                self.selected_mask &= ~(1 << 9)
            elif selector == 10:
                self.selected_mask &= ~(1 << 8)
            self.selected_mask |= mask
        self.write_controls()
        self.refresh_buttons()

    def all_off(self):
        self.cancel_crank_sequence(write=False)
        self.selected_mask = 0
        self.crank_stage = 0
        self.armed.set(False)
        self.allow_manual_mode.set(False)
        self.write_controls()
        self.refresh_buttons()

    def start_crank_sequence(self):
        if not self.armed.get():
            messagebox.showwarning("Not armed", "ARM OUTPUT TEST before running the crank sequence.")
            return
        ok = messagebox.askyesno(
            "Run production crank sequence",
            "WARNING: This commands the real ignition and starter outputs and may start the engine.\n\n"
            "Only the ignition outputs are sequenced. Main Power, MCU and A/M relays retain "
            "their current ON/OFF settings throughout the sequence.\n\n"
            "Confirm the machine is secured, the area is clear, brakes are engaged, and you are ready "
            "to press ENGINE RUNNING / STOP STARTER as soon as the engine catches.",
        )
        if not ok:
            return
        self.crank_sequence_running = True
        # Preserve only the three power-support settings. The PLC passes these
        # retained HR0 bits through unchanged while sequencing ignition.
        self.selected_mask &= 0x0007
        self.crank_stage_index = 0
        self.crank_stage_started = time.monotonic()
        self.crank_stage = CRANK_STAGES[0][0]
        self.crank_sequence_text.set(f"Crank sequence: {CRANK_STAGES[0][2]}")
        self.write_controls()
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
            self.write_controls()
            self.refresh_buttons()

    def stop_starter(self):
        if not self.crank_sequence_running or self.crank_stage != 16:
            return
        self.crank_stage_index = 3
        self.crank_stage_started = time.monotonic()
        self.crank_stage = 17
        self.crank_sequence_text.set(f"Crank sequence: {CRANK_STAGES[3][2]}")
        self.write_controls()

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
        self.write_controls()

    def write_controls(self):
        try:
            self.client.write_register(0, self.selected_mask)
            self.client.write_register(1, 0xA55A if self.armed.get() else 0)
            self.client.write_register(11, self.crank_stage)
            self.client.write_register(13, 0x4D4D if self.armed.get() and self.allow_manual_mode.get() else 0)
        except Exception:
            pass

    def refresh_buttons(self):
        for selector, button in self.buttons.items():
            if self.crank_sequence_running and selector in (5, 6, 7, 8):
                button.configure(text="SEQUENCE")
                continue
            requested = bool(self.selected_mask & (1 << (selector - 1)))
            button.configure(text="ON" if self.armed.get() and requested else "OFF")

    def poll(self):
        try:
            self.advance_crank_sequence()
            if not self.client.connected:
                self.client.connect()
            self.heartbeat = (self.heartbeat + 1) & 0xFFFF
            self.client.write_register(8, self.heartbeat)
            self.write_controls()
            response = self.client.read_holding_registers(0, count=22)
            if response.isError():
                raise RuntimeError(str(response))
            regs = response.registers
            self.connected = True
            self.connection_text.set(f"Connected: {PLC_IP}:502")
            self.active_text.set(f"PLC active manual mask: 0x{regs[2]:04X}")
            raw_inputs = [value - 0x10000 if value & 0x8000 else value for value in regs[17:22]]
            for var, pressure, raw in zip(self.pressure_vars, regs[3:8], raw_inputs):
                var.set(f"{pressure / 10.0:.1f} bar | raw {raw}")
            bits = regs[9]
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
            for selector, (indicator, channel_bits) in self.output_indicators.items():
                values = [bool(output_bits & (1 << bit)) for bit in channel_bits]
                requests = [bool(request_bits & (1 << bit)) for bit in channel_bits]
                if len(values) == 1:
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
            self.connected = False
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
            self.root.after(250, self.poll)

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
        self.write_controls()
        try:
            self.client.close()
        finally:
            self.root.destroy()


root = tk.Tk()
TestPanel(root)
root.mainloop()
