#!/usr/bin/env python3
"""Static invariants for the production SCL draft before TIA compilation."""

import re
from pathlib import Path


SOURCE = Path(__file__).parents[1] / "plc" / "production" / "FB_ProductionSequencer.scl"
text = SOURCE.read_text(encoding="utf-8")
instances = (SOURCE.parent / "ProductionInstances.scl").read_text(encoding="utf-8")

for forbidden in ("Req_Ign30", "Ign_30", "SimMode", "Req_AuxRelays", "Aux_Relays"):
    if forbidden in text:
        raise SystemExit(f"forbidden identifier remains: {forbidden}")

required = (
    "#Req_AMRelays := FALSE;",
    "#Req_Ign50 := FALSE;",
    "#Req_EstopBrakeCh1Apply := #AutoMode;",
    "#Req_EstopBrakeCh2Apply := #AutoMode;",
    "#Req_ParkUnlock := TRUE;",
    "#Req_ParkUnlock := FALSE;",
    "IF NOT #Rq_ParkUnlock AND #Rq_ParkLock THEN",
    "AND #Rq_ParkUnlock AND NOT #Rq_ParkLock THEN",
    "State : Int := 0;",
    "FaultCode : Word := W#16#0000;",
    "CrankAttempts : USInt := 0;",
    "IF NOT #AutoMode THEN",
    "#ST_BRAKE_CH1_APPLY:",
    "#Shuttle1_bar <= 5.0",
    "#Shuttle1_bar >= 30.0",
    "#Shuttle1_bar <= 50.0",
    "ABS(#Shuttle2_bar - #otherShuttleBaseline) <= 10.0",
    "#ST_BRAKE_CH2_APPLY:",
    "#Shuttle2_bar <= 5.0",
    "ABS(#Shuttle1_bar - #otherShuttleBaseline) <= 10.0",
    "#ST_ENABLE_AM:",
    "#ST_PARK_UNLOCK:",
    "#ShutdownDefinitionRequired := TRUE;",
    "#VehicleStopConfirmationRequired := TRUE;",
)
for fragment in required:
    if fragment not in text:
        raise SystemExit(f"required invariant missing: {fragment}")

for fragment in (
    'DATA_BLOCK "ProductionSeq_DB"',
    '"FB_ProductionSequencer"',
    'DATA_BLOCK "ProductionComm_DB"',
    '"FB_ProductionCommWatch"',
    "NON_RETAIN",
):
    if fragment not in instances:
        raise SystemExit(f"production instance DB invariant missing: {fragment}")

constant_states = set(re.findall(r"^\s+(ST_[A-Z0-9_]+)\s*:\s*Int\s*:=", text, re.MULTILINE))
case_states = set(re.findall(r"^\s+#(ST_[A-Z0-9_]+):", text, re.MULTILINE))
missing_cases = constant_states - case_states
if missing_cases:
    raise SystemExit(f"state constants without CASE branch: {sorted(missing_cases)}")

print(f"production sequencer static validation OK: {len(case_states)} states")
