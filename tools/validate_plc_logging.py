#!/usr/bin/env python3
"""Static safety and schema invariants for production and I/O-test PLC logging."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
PROD = (ROOT / "plc/production/ProductionLogging.scl").read_text(encoding="utf-8")
PROD_CYCLE = (ROOT / "plc/production/ProductionCycle.scl").read_text(encoding="utf-8")
IO = (ROOT / "plc/io-test/IoTestLogging.scl").read_text(encoding="utf-8")
IO_MAIN = (ROOT / "plc/io-test/io_test.scl").read_text(encoding="utf-8")
GUI = (ROOT / "tools/io_test_gui.py").read_text(encoding="utf-8")
DOC = (ROOT / "docs/plc_event_logging_v1.md").read_text(encoding="utf-8")


def require(text: str, fragments: tuple[str, ...], label: str) -> None:
    for fragment in fragments:
        if fragment not in text:
            raise SystemExit(f"{label} invariant missing: {fragment}")


require(PROD, (
    'TYPE "UDT_ProductionEventRecord"',
    'Records : Array[0..127] of "UDT_ProductionEventRecord";',
    '#timeStatus := RD_SYS_T(#timestamp);',
    '"ProductionLogData".OverwriteCount := "ProductionLogData".OverwriteCount + 1;',
    'EventId := W#16#0100',
    'EventId := W#16#0200',
    'EventId := W#16#0300',
    'EventId := W#16#0400',
    'EventId := W#16#0500',
    'EventId := W#16#0600',
    'EventId := W#16#0610',
    'EventId := W#16#0620',
    'EventId := W#16#0630',
    'EventId := W#16#0700',
    '"ProductionModbusData".hold[56] := W#16#0100;',
    '"ProductionModbusData".hold[115] := "ProductionLogData".LastEventId;',
), "production logger")

require(PROD_CYCLE, (
    '"FC_ProductionModbusOut"();',
    '"FC_ProductionLogging"();',
    '"FC_ProductionLogModbus"();',
), "production scan")
if not (
    PROD_CYCLE.index('"FC_ProductionModbusOut"();')
    < PROD_CYCLE.index('"FC_ProductionLogging"();')
    < PROD_CYCLE.index('"FC_ProductionLogModbus"();')
):
    raise SystemExit("production logging calls are out of order")

require(IO, (
    'TYPE "UDT_IoTestEventRecord"',
    'Records : Array[0..127] of "UDT_IoTestEventRecord";',
    '#timeStatus := RD_SYS_T(#timestamp);',
    'EventId := W#16#1100',
    'EventId := W#16#1110',
    'EventId := W#16#1130',
    'EventId := W#16#1200',
    'EventId := W#16#1300',
    'EventId := W#16#1310',
    'EventId := W#16#1400',
    '"ModbusData".hold[56] := W#16#0100;',
    '"ModbusData".hold[107] := "IoTestLogData".LastEventId;',
), "I/O-test logger")

require(IO_MAIN, (
    "hold : Array[0..127] of Word;",
    '"FC_IoTestLogging"();',
    '"FC_IoTestLogModbus"();',
), "I/O-test standard scan")

# Logger sources must remain observational: they may write only their own DBs
# and the documented Modbus response window, never requests or physical tags.
for name, text in (("production", PROD), ("I/O test", IO)):
    for forbidden in (
        '"ProductionSeq_DB".Req_',
        '"Seq_DB".Req_',
        '"MainPwr_Sw" :=',
        '"MCU_Enable" :=',
        '"AM_Relays" :=',
        '"Sol_Estop" :=',
        '"ParkBrake_Unlock" :=',
    ):
        if forbidden in text:
            raise SystemExit(f"{name} logger contains forbidden control write: {forbidden}")

require(GUI, (
    'self.logging_enabled = tk.BooleanVar(value=False)',
    '"plc_events": Path(f"{prefix}_plc_events.csv")',
    "def _download_plc_event_history(self):",
    "self.client.read_holding_registers(56, count=52)",
    'self._write_register(24, self.plc_log_request_token',
), "I/O-test GUI")

require(DOC, (
    "The logger is observational standard PLC code.",
    "Fixed ring capacity: 128 event records.",
    "Version 0.1 is intentionally non-retentive.",
    "`*_plc_events.csv`",
), "logging documentation")

print("PLC logging static validation OK: bounded 128-record rings and coherent Modbus retrieval")
