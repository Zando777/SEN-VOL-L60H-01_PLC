#!/usr/bin/env python3
"""Static invariants for the commissioning I/O-test interface."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
SCL = (ROOT / "plc" / "io-test" / "io_test.scl").read_text(encoding="utf-8")
GUI = (ROOT / "tools" / "io_test_gui.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "io_test_current_state.md").read_text(encoding="utf-8")

required_scl = (
    "#requestMask.%X9 := FALSE;",
    '"Seq_DB".Req_ParkUnlock := #requestMask.%X8;',
    'AND NOT "Seq_DB".Req_ParkUnlock;',
    'IF "PressData".Shuttle1_bar <= 3.2 THEN "ModbusData".hold[3] := W#16#0;',
    'IF "PressData".Prop_bar <= 3.2 THEN "ModbusData".hold[7] := W#16#0;',
    '"Seq_DB".Req_ParkUnlock := TRUE;',
    'IF "AutoMan_Sw1" THEN',
    '"Seq_DB".Req_EbrakeRel := TRUE;',
    '"Seq_DB".Req_EbrakeRel := NOT "AutoMan_Sw1";',
)
for fragment in required_scl:
    if fragment not in SCL:
        raise SystemExit(f"I/O-test parking-brake invariant missing: {fragment}")

if '#requestMask.%X8 AND NOT #requestMask.%X9' in SCL:
    raise SystemExit("retired independent Park Lock command still gates Park Brake")

crank_plc = SCL.split("IF #crankActive THEN", 1)[1].split(
    "ELSE\n         // Manual test mode", 1
)[0]
for fragment in (
    '"Seq_DB".Req_MainPwr := #requestMask.%X0;',
    '"Seq_DB".Req_MCU := #requestMask.%X1;',
    '"Seq_DB".Req_AMRelays := #requestMask.%X2;',
    '"Seq_DB".Req_EbrakeRel := #requestMask.%X10;',
):
    if fragment not in crank_plc:
        raise SystemExit(f"crank no longer preserves a non-ignition request: {fragment}")
if '"Seq_DB".Req_ParkUnlock := FALSE;' in crank_plc:
    raise SystemExit("crank contains a parking-brake OFF assignment")

required_gui = (
    '(9, "Park brake", "ON = brake enabled',
    "PARK_BRAKE_SELECTOR = 9",
    "PARK_BRAKE_DEFAULT_MASK = 1 << (PARK_BRAKE_SELECTOR - 1)",
    "CRANK_RETAINED_MASK = 0x0007 | PARK_BRAKE_DEFAULT_MASK | ESTOP_SELECTOR_MASK",
    "self.selected_mask & CRANK_RETAINED_MASK",
    ") | PARK_BRAKE_DEFAULT_MASK",
    'text="SAFE DEFAULTS / DISARM"',
    "self.selected_mask |= PARK_BRAKE_DEFAULT_MASK",
    "ESTOP_SELECTOR_MASK = 1 << (ESTOP_SELECTOR - 1)",
    "self.selected_mask |= ESTOP_SELECTOR_MASK",
    "Q49.5",
    "Q49.4",
    "def raw_to_ma(raw: int) -> float:",
    "PRESSURE_DISPLAY_ORDER = (0, 2, 1, 3, 4)",
    "PRESSURE_ZERO_DEADBAND_BAR = PRESSURE_SPAN_BAR * SENSOR_CHARACTERISTIC_DEVIATION_PERCENT / 100.0",
    "def pressure_word_to_bar(word: int) -> float:",
    "ANALOG_MIN_MA + (raw * ANALOG_SPAN_MA / ANALOG_RAW_FULL_SCALE)",
    'f"{pressure_values[index]:.1f} bar | "',
    '"shuttle1_ma", "estop1_ma", "shuttle2_ma", "estop2_ma", "prop_ma"',
)
for fragment in required_gui:
    if fragment not in GUI:
        raise SystemExit(f"I/O-test GUI parking-brake invariant missing: {fragment}")

crank_gui = GUI.split("def start_crank_sequence(self):", 1)[1].split(
    "def cancel_crank_sequence", 1
)[0]
for forbidden in ("self.selected_mask = 0", "self.selected_mask &= 0x0007"):
    if forbidden in crank_gui:
        raise SystemExit(f"crank destructively clears retained outputs: {forbidden}")

if '(10, "Park lock"' in GUI or '(10, "Park Lock"' in GUI:
    raise SystemExit("retired Park Lock GUI button remains")

if "ON means brake enabled; OFF means brake disabled" not in DOC:
    raise SystemExit("semantic Park Brake behavior is not documented")

print("I/O-test static validation OK: one semantic Park Brake toggle, HR0 bit 9 retired")
