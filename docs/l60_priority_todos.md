# Volvo L60H priority to-do list

Date: 2026-07-23

Scope: production development in `volvo_l60h_production_dev`. Nothing in this
list is approved for download until its acceptance tests pass.

## P0 — Guarantee Manual means manual control

### Current finding

The current production draft does not yet guarantee a clean autonomous-to-manual
handover:

- `ProductionIO` assigns `AutoMode` directly from `AutoMan_Sw1`; it does not
  consume a verified dual-channel Auto/Manual result.
- When `AutoMode` becomes false, `FB_ProductionSequencer` immediately changes
  to INIT.
- INIT/default processing requests:
  - Main Power OFF;
  - MCU Enable OFF;
  - A/M Relays OFF;
  - all ignition outputs OFF;
  - Parking Brake ON;
  - both PLC-controlled E-stop solenoids ON/disengaged in Manual.
- Therefore, changing the selector to M can stop the engine, remove machine/MCU
  power and command brake outputs. The PLC remains capable of changing machine
  behavior after Manual is selected.
- The commissioning I/O-test project deliberately contains an armed test-only
  Manual override (`TestManualEnable`/HR13). This must never be copied into
  production.

The exact F-LAD Auto/Manual gating and the physical A/M relay contact behavior
must be export-audited and tested on the machine before deciding the final
handover implementation.

Detailed evidence and the target authority boundary are recorded in
[`manual_mode_authority_audit.md`](manual_mode_authority_audit.md).

### Required behavior

Manual mode must mean:

- No Modbus command, compute-box status, standard sequencer state or retained
  PLC request can command or override normal manual machine operation.
- The PLC must not stop the engine, remove Main Power/MCU power, apply or
  release the parking brake, or apply/release service/E-stop brake channels
  merely because the selector changed to M.
- The autonomous A/M relays must drop to the verified manual-control position.
- The human/manual machine circuits must then own ignition, power and normal
  brake commands.
- Independent safety functions remain authoritative. Remote E-stop,
  passivation and other validated safety trips may still remove energy in
  Manual; this safety veto is not an autonomous-control override.

### Tasks

- [ ] Produce a complete Auto/Manual signal and contact-path diagram.
  - Include `AutoMan_Sw1`, `AutoMan_Sw2`, F-DI evaluation, A/M relay coils,
    every A/M relay contact and the downstream manual/autonomous circuits.
- [x] Export and review the current F-LAD equations for every physical output.
  - Identify whether Auto mode is part of each output gate.
  - Separate autonomous command authority from always-active safety authority.
- [ ] Replace the ambiguous `AutoMan_Sw1` production input with explicitly named
  `AutoModeValidated`/`ManualModeValidated` results from the F-program.
  - Openness and the Siemens module manual confirm `%I21.0` is already the
    F-DI's internally evaluated 1oo2 result for physical channels 0+4.
  - `%I22.0` is the required value-status bit; `%I21.4` must not be used as an
    independent channel in the F-program.
- [ ] Define the Auto-to-Manual transition during each phase:
  - wake/MCU boot;
  - ignition sequencing;
  - starter active;
  - pressure build/brake test;
  - ready for drive;
  - operational/driving;
  - controlled stop/shutdown;
  - fault and communication loss.
- [ ] Implement a dedicated Manual-handover state or F-program handover
  mechanism.
  - Drop A/M relays first.
  - Do not write autonomous safe defaults onto shared manual controls after the
    handover.
  - Starter 50 must not remain autonomously energized through the transition.
- [ ] Define Manual-to-Auto entry conditions.
  - Require a fresh explicit enable edge; never resume the old autonomous state.
  - Require a known stopped/secured condition, parking brake policy, healthy
    safety chain and compatible/fresh compute-box communication.
- [ ] Remove or structurally exclude all commissioning Manual overrides from
  production.
- [ ] Add mode state, both raw channels, validated mode, handover state and
  rejection reason to Modbus telemetry and PLC event logging.
  - Evaluated mode value, its high-order paired tag image, value status and
    current standard/F-LAD mode results are implemented in HR116 and event
    `0x0800`; validated mode, handover and rejection fields await the F-program
    and contact-path changes.
- [ ] Add a latched diagnostic for mode-channel discrepancy or invalid selector
  state.

### Mandatory tests

- [ ] In M, exercise every Modbus command and status bit.
  - Pass: no autonomous physical output changes and no change to manual engine,
    power or brake control.
- [ ] In M, start/restart the GUI, compute box, PLC standard program and Modbus
  connection.
  - Pass: no physical output pulse or autonomous takeover.
- [ ] Switch A to M in every sequencer phase listed above.
  - Pass: A/M relays transfer to Manual; starter cannot remain autonomous;
    manual machine operation is not stopped or overridden by sequencer defaults.
- [ ] Switch A to M while the machine is operational.
  - Pass: control transfers predictably to the operator; no automatic parking
    brake application or ignition/power removal occurs solely due to the mode
    change.
- [ ] While in M, operate manual ignition, engine stop/start and brakes.
  - Pass: PLC autonomous requests cannot countermand them.
- [ ] In M, press the remote E-stop and inject required safety faults.
  - Pass: the independent safety reaction still occurs and cannot be bypassed.
- [ ] Attempt M-to-A without each entry condition, then with all conditions.
  - Pass: unsafe/stale transitions are rejected and logged; valid transition
    begins from the defined initial state only.

## P0 — Implement the real engine-stop sequence

### Current finding

The production interface already defines an edge-triggered
`EngineStopRequest` at HR0 bit 4, but the final ignition shutoff order is not
implemented. The sequencer currently:

1. moves to shutdown-brake state 80;
2. applies the configured brake defaults and waits for feedback;
3. enters state 81;
4. holds Main Power, MCU power and run-position ignition while
   `EngineRunning` remains true;
5. reports `ShutdownDefinitionRequired`.

This deliberate hold prevents an unverified ignition order from being used, but
it is not a functioning engine-stop command.

### Tasks

- [ ] Determine and approve the exact ignition shutoff order.
  - Define the required order for Ignition R, 15/54 and DR.
  - Define every delay and maximum timeout.
  - Confirm whether Starter 50 must be explicitly checked OFF first.
  - Verify the sequence physically against the loader ignition circuit.
- [ ] Define engine-stop acceptance conditions.
  - Required sequencer states.
  - Vehicle stopped/secured confirmation while no speed feedback exists.
  - Required parking and E-stop brake state and feedback.
  - Behavior if the request arrives during crank, startup, brake test, driving,
    fault or communication loss.
- [ ] Decide how the compute box confirms that the vehicle is stopped.
  - Add a versioned Modbus command/status bit if explicit confirmation is
    required.
  - Reject and log engine-stop requests that do not meet the conditions.
- [ ] Replace `ST_SHUTDOWN_IGN_TBD` with explicit timed ignition-off states.
- [ ] Verify the engine has stopped using a debounced/plausible
  `EngineRunning = FALSE`, with timeout and fault handling.
- [ ] Keep Engine Stop separate from full System Shutdown.
  - Engine Stop may leave Main Power, MCU and compute-box support available.
  - Full shutdown must still wait for compute-box acknowledgement before Main
    Power removal.
- [ ] Publish stop stage, elapsed time, accepted/rejected status, rejection
  reason, engine-stopped confirmation and completion over Modbus.
- [ ] Log request, acceptance/rejection, every ignition edge, engine-running
  loss, timeout, brake verification and completion in the PLC event history.
- [ ] Add a production GUI **ENGINE STOP** button.
  - Require an explicit confirmation dialog.
  - Send a clean rising edge and increment command sequence.
  - Prevent accidental repeated writes while a stop is active.
  - Display the actual PLC stop stage, brake status, engine-running feedback,
    timeout/fault and completion.
  - Record the operator action and PLC result in CSV.

### Mandatory tests

- [ ] Bench/meter-test the approved ignition-off order and timing.
- [ ] Request Engine Stop from every allowed and disallowed state.
  - Pass: allowed requests execute once; rejected requests change no output and
    report/log the exact reason.
- [ ] Verify Starter 50 is OFF throughout the stop sequence.
- [ ] Verify A/M is revoked and required brakes are confirmed before ignition
  shutoff, without applying the parking brake to an unconfirmed moving machine.
- [ ] Simulate engine-running feedback stuck TRUE and stuck FALSE.
  - Pass: no false completion; deterministic timeout/fault.
- [ ] Interrupt the sequence with remote E-stop, Manual selection,
  communication loss and PLC/compute restart.
  - Pass: safety behavior wins, state recovery is deterministic and no
    automatic restart occurs.
- [ ] Verify Engine Stop completion leaves the specified support systems
  powered and allows only a fresh, valid subsequent start.
- [ ] Verify full System Shutdown still obtains shutdown acknowledgement before
  removing Main Power.

## Promotion gate

Neither item may be promoted to `volvo_l60h_main` until:

- the cause-and-effect and mode-handover design is reviewed;
- F-LAD and standard-program changes compile with a consistent F-signature;
- the complete test matrix passes first in the isolated development project;
- physical machine behavior matches watch-table, Modbus and logged evidence;
- the deployed source/export is committed and traceable.
