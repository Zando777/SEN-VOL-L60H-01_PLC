# Volvo L60H Auto/Manual authority audit

Date: 2026-07-23

Status: current behavior proven unsafe for production promotion; remediation
design in progress in `volvo_l60h_production_dev`.

## Audited projects

Both projects were exported read-only through TIA Portal Openness on 23 July
2026:

- `volvo_l60h_production_dev`
- `volvo_l60h_main`

Evidence hashes:

| Artifact | SHA-256 |
|---|---|
| production-dev `Main_Safety_RTG1` | `9c015a226d43d453811b6cf5b9c31e38b4e67fbaa971cd8dba2dbc31060f439e` |
| main `Main_Safety_RTG1` | `1d0cd489b52bb90d4b6b497e312cb849a7e94ee401e06f53a82eedfba9172c4c` |
| production-dev default tag table | `8142e67a4cb150b98e0de57bc64411642647bb710692ea528fff1bf9cda0dc4f` |
| production-dev hardware inventory | `0bc1954507557cfc86976606f8f6440f1f32b1ff352a26da9d3f74e2681e74ec` |

## Proven current behavior

The mode tags are:

| Tag | Address | Current use |
|---|---:|---|
| `AutoMan_Sw1` | `%I21.0` | Internally evaluated 1oo2 result; used by current logic |
| `AutoMan_Sw2` | `%I21.4` | High-order paired channel; not independently accessible in F-program |
| planned `AutoMan_ValueStatus` | `%I22.0` | Evaluated channel validity; read-only telemetry added, F-tag pending |

Openness reports `Failsafe_SensorEvaluation = 0` for channels 0 and 4, while
the independently evaluated channels report `1`. The pair has a configured
discrepancy time of `5` and reintegration-after-discrepancy parameter `0`.
The Siemens equipment manual confirms channels 0+4 are combined under 1oo2
evaluation, only DI0 may be accessed in the safety program, and value status
for DI0 is at input byte `x+1`, bit 0.

Reference: Siemens, *Digital input module F-DI 8x24VDC HF
(6ES7136-6BA01-0CA0), Equipment Manual*, section 4.3:
<https://support.industry.siemens.com/cs/attachments/109803402/et200sp_f-di_8x24vdc_hf_manual_en-US_en-US.pdf>.

The current exported F-LAD equations are:

### `volvo_l60h_main`

`SafeOK = estop_safe AND AutoMan_Sw1 AND NOT PressTrip AND NOT CommLost`

`Seq_DB.AutoMode = AutoMan_Sw1 AND SafeOK`

### `volvo_l60h_production_dev`

`SafeOK = estop_safe AND ModbusData.TestAutoOK AND NOT PressTrip AND NOT CommLost`

`Seq_DB.AutoMode = AutoMan_Sw1 AND SafeOK`

`ModbusData.TestAutoOK` is the commissioning-only
`AutoMan_Sw1 OR TestManualEnable` permission. This is useful for an armed I/O
test but is forbidden in production.

In both projects, every physical-output network is downstream of the same
`SafeOK`:

| Physical function | Current F-LAD request path |
|---|---|
| Main Power | request AND `SafeOK` |
| MCU Enable | request AND `SafeOK` AND NOT hardware disable |
| A/M relays | request AND `SafeOK` AND NOT hardware disable |
| Ignition R, 15/54, DR, Starter 50 | request AND `SafeOK` |
| Parking-brake pair | request/complement AND `SafeOK` AND NOT hardware disable |
| Both E-stop solenoids | common release request AND `SafeOK` AND NOT hardware disable |

The production standard source separately assigns
`ProductionSeq_DB.AutoMode := AutoMan_Sw1`. When that bit becomes false,
`FB_ProductionSequencer` immediately enters INIT and requests Main Power, MCU,
A/M and ignition OFF, parking brake ON and both E-stop outputs
ON/brakes-disengaged.

Therefore switching to M currently has two independent output effects:

1. F-LAD makes `SafeOK` false and removes every gated output.
2. The standard sequencer changes to INIT and writes its autonomous defaults.

This can stop the engine, remove power and change brake state. Manual is not
currently a genuine control handover.

There is a second defect in the same gate: `CommLost` is part of `SafeOK`, so
communication loss removes outputs immediately even though the approved
requirement is a controlled stop.

## Authority boundary required

Three concepts must be separate:

1. **Safety permit** — independent safety chain only. Remote E-stop,
   passivation and validated safety trips may remove energy in both A and M.
2. **Validated Auto authority** — the F-program's evaluated selector result.
   Only this permits autonomous output requests.
3. **Manual authority** — physical manual circuits own normal machine commands.
   Modbus and the standard sequencer have no command path in M.

`AutoMode`, `CommLost` and test permissions must not be folded into the common
safety permit.

The intended output ownership is:

| Function | Auto | Manual | Always-active veto |
|---|---|---|---|
| A/M relay | Sequencer, validated-Auto gated | De-energized/manual contact position | safety chain |
| Main/MCU/ignition/starter | Sequencer through autonomous contact path | Physical manual circuit | safety chain where required by risk assessment |
| Parking brake normal command | Sequencer through autonomous contact path | Physical manual control | safety chain where required |
| E-stop brake release | Sequencer/brake-test state | Disengaged by the approved Manual branch | Remote E-stop/passivation must engage |

Starter 50 must be removed immediately when Auto authority is lost. The A/M
relay must transfer to its verified manual-contact position. Whether the
remaining autonomous relay outputs should drop or retain an image is secondary:
their contacts must be physically unable to countermand manual controls in M.

## Required F-program structure

The target F-program must provide explicit diagnostic results:

- `AutoModeValidated`
- `ManualModeValidated`
- `ModeDiscrepancy`
- `SafetyPermit`
- `AutoAuthority`

The verified mode equations are:

- `ModeValid = AutoMan_ValueStatus`
- `AutoModeValidated = ModeValid AND AutoMan_Sw1`
- `ManualModeValidated = ModeValid AND NOT AutoMan_Sw1`
- `ModeDiscrepancy = NOT ModeValid`

`AutoMan_Sw2` must not appear in an F-program equation. The F-DI already
compares the two physical channels internally; its lower process bit and value
status are the safe interface.

After verification:

- autonomous normal-output networks require `AutoAuthority`;
- A/M relays require `AutoAuthority`;
- the Manual E-stop-release branch requires `ManualModeValidated`;
- all branches remain downstream of the independent safety permit;
- `CommLost` is handled by the sequencer's controlled-stop path, not by
  immediate global output removal;
- no `TestAutoOK`, `TestManualEnable` or Modbus test word exists in the
  production F-program.

## Auto-to-Manual behavior by phase

The required reaction is the same in every sequencer phase:

1. Remove autonomous starter command immediately.
2. De-energize A/M relays to the verified manual-contact position.
3. Cancel the autonomous state and invalidate all pending command edges.
4. Do not execute the normal autonomous shutdown sequence merely because M was
   selected.
5. Do not automatically resume when A is reselected.
6. Keep the independent safety chain authoritative.

This applies during wake, MCU boot, ignition, crank, pressure build, brake test,
ready, driving, controlled stop, shutdown and fault handling. The physical
contact-path test must prove that steps 1–3 do not remove or countermand manual
engine, power, parking-brake or operator controls.

## Manual-to-Auto entry

Auto may start only from a fresh, secured entry:

- selector is validly Auto with no discrepancy;
- remote safety chain is healthy and acknowledged;
- parking/vehicle-secured condition is confirmed;
- starter is not active;
- production interface version is compatible;
- heartbeat and ComputeReady are fresh;
- `SystemEnable` has first been observed low, then deliberately raised;
- no old state, retained command or stale Modbus bit is resumed.

## Instrumentation added

Production telemetry HR116 and every new PLC event record now capture:

- bit 0: evaluated lower-channel `AutoMan_Sw1`;
- bit 1: high-order paired `AutoMan_Sw2` tag image, diagnostic only;
- bit 2: evaluated-channel value status read from `%I22.0`;
- bit 3: current production-sequencer `AutoMode` input;
- bit 4: current F-LAD `Seq_DB.AutoMode`.
- bit 5: production Manual-handover state active;
- bit 6: production mode-input fault active.

Event `0x0800` records changes. This instrumentation is observational and is not
used by any output or sequence decision.

The symbolic `AutoMan_ValueStatus` tag is intentionally pending because TIA
classifies creation at `%I22.0` as a safety-program modification. It must be
created under Safety Administration login as part of the controlled F-program
edit. The current standard telemetry uses a read-only `PEEK_BOOL` and does not
write or control any F-I/O.

The standard sequencer now implements state `90` for Manual handover and state
`91` for invalid mode input. A return to Auto always goes through INIT and
requires a new `SystemEnable` low-then-high sequence after Auto selection. This
removes autonomous state resumption on the standard side; it does not replace
the pending F-LAD and physical-contact authority changes.

### Offline verification

The updated standard sequencer, I/O packing, Modbus and logging sources were generated in
`volvo_l60h_production_dev`, compiled and saved through Openness:

- compile errors: `0`;
- compile warnings: `0`;
- existing safety program: consistent and not recompiled;
- verified post-save export SHA-256:
  `a40f855013f219bd82a1bc735115fa8674018d120a138fbc4b62f2b619364196`.

The post-save XML export contains states 90/91, the initialized internal state
memory, `ModeInputBits`, the `%I22.0` read, event `0x0800`, HR116 and HR117.
The unrelated pre-existing inconsistent
`Watch table_2` remains non-exportable; all program blocks exported normally.

## Open physical verification

These points cannot be proven by the PLC project:

- every A/M relay pole, its de-energized position and downstream circuit;
- whether manual ignition, Main Power, MCU, parking brake and drive controls
  are electrically independent of de-energized autonomous relays;
- transition timing/contact overlap while the engine is running.

The available `volvo_l60h_labels.pdf` and `volvo_l60h_roll.pdf` were rendered
and inspected. They confirm `%Q0.3` is labeled `Auton Enable` and identify the
F-DQ/F-RQ terminals, but they are label sheets rather than circuit schematics
and contain no A/M relay pole/contact paths.

No production download is permitted until those contact-path items are traced
from the electrical drawing and meter-tested.
