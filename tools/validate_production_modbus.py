#!/usr/bin/env python3
"""Static invariants for the versioned production Modbus interface."""

import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "plc" / "production" / "ProductionModbus.scl"
LOG_SOURCE = ROOT / "plc" / "production" / "ProductionLogging.scl"
IO_SOURCE = ROOT / "plc" / "production" / "ProductionIO.scl"
CYCLE_SOURCE = ROOT / "plc" / "production" / "ProductionCycle.scl"
DOC = ROOT / "docs" / "production_modbus_v1.md"

text = SOURCE.read_text(encoding="utf-8")
log_text = LOG_SOURCE.read_text(encoding="utf-8")
io_text = IO_SOURCE.read_text(encoding="utf-8")
cycle_text = CYCLE_SOURCE.read_text(encoding="utf-8")
doc = DOC.read_text(encoding="utf-8")

for forbidden in ("Ign30", "Ign_30", "Aux", "Rem_Arm", "SimMode"):
    if forbidden in text or forbidden in doc:
        raise SystemExit(f"forbidden legacy identifier remains: {forbidden}")

required_source = (
    "{ S7_Optimized_Access := 'FALSE' }",
    "FOR #clearIndex := 0 TO 15 DO",
    '"ProductionModbusData".hold[#clearIndex] := W#16#0;',
    '"ProductionSeq_DB".SystemEnable := "ProductionModbusData".hold[0].%X0;',
    '"ProductionSeq_DB".SystemShutdownRequest := "ProductionModbusData".hold[0].%X5;',
    '"ProductionSeq_DB".ShutdownAcknowledged := "ProductionModbusData".hold[0].%X7;',
    '"ProductionSeq_DB".ComputeAlive := "ProductionComm_DB".CommHealthy',
    '"ProductionModbusData".hold[2] = W#16#0100',
    '"ProductionModbusData".hold[16] := #status;',
    '"ProductionModbusData".hold[32]',
    '"ProductionModbusData".hold[36]',
    '"ProductionModbusData".hold[37]',
    '"ProductionModbusData".hold[41]',
    '"ProductionModbusData".hold[48] := #requestImage;',
    '"ProductionModbusData".hold[49] := "ProductionIOData".OutputImage;',
    '"ProductionModbusData".hold[50] := "ProductionIOData".RelayReadback;',
    '"ProductionModbusData".hold[51] := "ProductionIOData".OutputMismatch;',
    '"ProductionModbusData".hold[52] := #safetyFlags;',
    '"ProductionModbusData".hold[53] := #brakeFlags;',
    '"ProductionModbusData".hold[54]',
    '"ProductionModbusData".hold[55]',
    '"ProductionModbusData".hold[116] := "ProductionIOData".ModeInputBits;',
)
for fragment in required_source:
    if fragment not in text:
        raise SystemExit(f"required Modbus invariant missing: {fragment}")

required_logging = (
    '"ProductionModbusData".hold[4]',
    '"ProductionModbusData".hold[5]',
    '"ProductionModbusData".hold[6]',
    '"ProductionModbusData".hold[56] := W#16#0100;',
    '"ProductionModbusData".hold[67] := "ProductionLogReadData".ResponseStatus;',
    '"ProductionModbusData".hold[68]',
    '"ProductionModbusData".hold[115] := "ProductionLogData".LastEventId;',
    '"ProductionModbusData".hold[117]',
)
for fragment in required_logging:
    if fragment not in log_text:
        raise SystemExit(f"required logging Modbus invariant missing: {fragment}")

required_io = (
    'FUNCTION "FC_ProductionIOPack" : Void',
    '"ProductionIOData".EstopSafe := "Main_Safety_RTG1_DB".estop_safe;',
    '#modeInputBits.%X0 := "AutoMan_Sw1";',
    '#modeInputBits.%X1 := "AutoMan_Sw2";',
    'byteOffset := 22,',
    '"ProductionSeq_DB".AutoMode := "AutoMan_Sw1";',
    '"ProductionSeq_DB".Abort := (NOT "ProductionIOData".EstopSafe) OR "PressData".PressTrip;',
    '#outputImage.%X7 := "Sol_Estop";',
    '#outputImage.%X8 := "Sol_Estop_2";',
    'byteOffset := 60',
    'byteOffset := 59',
    'byteOffset := 58',
    'byteOffset := 57',
    '"ProductionSeq_DB".Rq_ParkUnlock := #relayReadback.%X9;',
    '"ProductionSeq_DB".Rq_ParkLock := #relayReadback.%X10;',
    '#requestImage.%X7 := NOT "ProductionSeq_DB".Req_EstopBrakeCh1Apply;',
    '"ProductionSeq_DB".Rq_EstopBrakeCh1Applied := NOT #outputImage.%X7;',
)
for fragment in required_io:
    if fragment not in io_text:
        raise SystemExit(f"required production I/O invariant missing: {fragment}")

required_cycle_order = (
    '"FC_ProductionModbusServer"();',
    '"FC_Pressure"();',
    '"FC_ProductionIOPack"();',
    '"FC_ProductionModbusIn"();',
    '"ProductionComm_DB"();',
    '"FC_ProductionCommToSequencer"();',
    '"ProductionSeq_DB"();',
    '"FC_ProductionModbusOut"();',
)
position = -1
for fragment in required_cycle_order:
    next_position = cycle_text.find(fragment, position + 1)
    if next_position < 0:
        raise SystemExit(f"production cycle call missing/out of order: {fragment}")
    position = next_position

if 'MB_HOLD_REG := "ProductionModbusData".hold' not in cycle_text:
    raise SystemExit("production MB_SERVER is not bound to ProductionModbusData.hold")

# Each defined command/status bit must have one inbound use outside comments.
for bit in range(11):
    count = len(re.findall(rf'hold\[0\]\.\%X{bit}(?!\d)', text))
    if count != 1:
        raise SystemExit(f"HR0 bit {bit} has {count} source mappings; expected exactly 1")

required_docs = (
    "All command registers are non-retentive",
    "Compute schema version",
    "Incrementing PLC telemetry sequence",
    "Signed raw pressure inputs",
    "Safety-gated physical output image",
    "Packed F-RQ relay readback image",
    "E-stop brake channel 1 applied",
    "A/M Relays",
    "Auto/Manual input diagnostics",
)
for fragment in required_docs:
    if fragment not in doc:
        raise SystemExit(f"Modbus documentation invariant missing: {fragment}")

print("production Modbus static validation OK: schema 1.0 control plus mode diagnostics")
