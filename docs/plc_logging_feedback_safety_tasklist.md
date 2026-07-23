# Volvo L60H PLC logging, feedback and safety task list

Status date: 2026-07-23

Scope:

- Production development project: `volvo_l60h_production_dev`
- Promotion target after review: `volvo_l60h_main`
- PLC: Siemens ET 200SP CPU 1510SP F-1 PN, TIA Portal V20

This work is divided into gates. Logging is observational and must never be
placed in the F-safety decision path or inhibit deterministic control.

## Gate 0 — Freeze definitions before implementation

- [ ] Create one authoritative signal/polarity matrix covering every input,
  request, physical Q, F-RQ readback and physical machine effect.
  - Pass: every signal has tag, address, module/slot, normal state, energized
    state, failure state, safety relevance and verified source.
- [ ] Confirm terminology and remove misleading semantic names where practical.
  - Park legacy field: `Req_ParkUnlock`; verified TRUE means parking brake ON.
  - E-stop physical output: ON/energized means brake disengaged; OFF/resting
    means brake engaged.
  - Pass: code comments, Modbus documentation, GUI and test procedure agree.
- [ ] Assign stable event IDs, fault codes, transition reasons and severity
  levels in one versioned table.
  - Pass: no duplicate identifiers and every sequencer fault/transition has a
    documented human-readable meaning and required response.
- [ ] Decide logging capacity and retention:
  - event-ring record count;
  - periodic telemetry sample rate and duration;
  - retentive versus non-retentive fields;
  - behavior on warm restart, cold restart and memory reset.
  - Recommended starting point: 512 retentive event records plus a separate
    short non-retentive 5 Hz telemetry ring.

## Gate 1 — PLC event logging foundation

- [x] Define version-0.1 production and I/O-test event-record UDTs.
  - Required fields: monotonically increasing event sequence, PLC timestamp,
    boot/session ID, event ID, severity, current/previous state, fault code,
    transition reason and source block.
  - Include snapshots of command bits, request image, physical Q image, F-RQ
    image, mismatch image, safety flags, brake flags and communication status.
  - Include five scaled pressures and five signed raw analog values.
- [x] Create version-0.1 logging DBs with:
  - fixed-size event ring;
  - write index and valid-record count;
  - next event sequence;
  - wrap/overwrite counter;
  - boot/session ID;
  - logger health and diagnostic counters.
- [x] Implement bounded standard-program event loggers (`FC_*LogEvent` plus
  fixed edge detectors).
  - Non-blocking, bounded execution time and no dynamic allocation.
  - One scan may enqueue a bounded number of events.
  - Full buffer overwrites the oldest record and increments an overwrite
    counter; it must never stop the sequencer.
- [x] Obtain the PLC system timestamp with `RD_SYS_T` and publish its return
  status/validity.
  - Log UTC or record the configured timezone/offset unambiguously.
  - Set a `TimeValid` flag so an unset CPU clock cannot look trustworthy.
- [x] Log a boot/session event on every startup.
  - Include restart type if available, software/schema versions, collective
    F-signature reference and previous retained logger state.
- [x] Add time-read, ring-overwrite, invalid-index, event-count and last-event
  diagnostics.
  - Invalid timestamp, enqueue overflow, ring overwrite, bad event ID and
    unexpected index recovery must be observable through Modbus.
- [ ] Prove logging cannot affect control.
  - Pass: forced logger-full, invalid-time and logger-disabled tests cause no
    output change, state delay, watchdog trip or CPU STOP.

## Gate 2 — Event coverage

- [x] Log every production sequencer state transition once.
  - Snapshot old state, new state and `TransitionReason`.
- [x] Log production fault assertion, replacement and reset.
  - Do not lose the original fault when a secondary fault occurs.
- [ ] Log all safety-source edges:
  - `SafeOK`;
  - E-stop safety block output;
  - remote E-stop channels 1 and 2;
  - remote acknowledgement;
  - F-I/O passivation/reintegration indication where accessible;
  - hardware disable inputs;
  - `PressureTrip`;
  - `CommLost`.
- [ ] Log command acceptance and rejection.
  - Include command sequence, command bits, accepted/rejected mask and rejection
    reason such as wrong state, stale sequence, missing acknowledgement or
    incompatible schema.
- [x] Log communication-lost and recovered edges.
  - First valid heartbeat, timeout phase/value, communication lost and recovery.
- [x] Log request, physical Q, F-RQ and mismatch image changes.
  - Request edge, Q edge, F-RQ edge, mismatch asserted, mismatch cleared and
    mismatch timeout/trip.
- [ ] Log pressure events.
  - Sensor/wire-break fault edges, zero-deadband entry/exit, band entry/exit,
    build/rebuild timeout, brake-test threshold crossing and pressure trip.
- [ ] Log brake-test stages and measured results.
  - Baseline, apply time, minimum shuttle pressure, other-channel deviation,
    rebuild time, supply-pressure extrema and pass/fail reason.
- [ ] Log crank/start/stop details.
  - Crank attempt, ignition stage, starter-on duration, engine-running
    confirmation, timeout, recrank and shutdown stages.
- [ ] Log reset workflow.
  - Reset requested, permitted/rejected, physical acknowledgement state and
    faults cleared.

## Gate 3 — Periodic telemetry and retrieval

- [ ] Define a separate telemetry-ring record.
  - Timestamp, state, pressures, raw analogs, request/Q/RQ/mismatch images,
    safety flags, heartbeat age and active timeout.
- [ ] Select a bounded sample rate.
  - Recommended initial rate: 5 Hz normally and 20 Hz during crank/brake test,
    subject to scan-time and memory measurement.
- [ ] Add pre-trigger/post-trigger retention if memory allows.
  - Preserve samples around first fault, safety trip, communication loss and
    brake-test failure.
- [x] Extend the production Modbus schema beyond HR55 with coherent indexed
  event retrieval.
  - Logger metadata: schema, newest/oldest sequence, count, overwrite count,
    health and time validity.
  - Indexed event-record read window with request sequence and coherent response
    sequence.
  - Indexed telemetry-record read window.
  - No client write may modify arbitrary PLC memory.
- [ ] Add explicit log-clear command protection.
  - Require compatible schema, fresh command sequence, permitted machine state
    and deliberate command edge.
  - Log the clear request before clearing or preserve an audit marker.
- [x] Extend the I/O-test commissioning GUI to download PLC records by sequence
  into a separate CSV and detect overwritten gaps.
  - Download PLC records by sequence without duplication.
  - Detect gaps/overwrites.
  - Write human-readable CSV/JSON with event-code decoding.
  - Keep existing live CSV logging separate from PLC historical retrieval.
- [ ] Test interrupted retrieval and reconnection.
  - Pass: no duplicate ambiguity, record tearing or silent gaps.

## Gate 4 — Performance and persistence verification

- [ ] Correct and verify I/O-test Modbus command remanence before promotion.
  - The 23 July Openness export shows the existing `ModbusData` members as
    `Retain`, despite the prior source comment calling the map non-retentive.
  - ARM and a fresh heartbeat still prevent stale output activation, but HR0,
    HR1, HR11 and HR13 must be explicitly made non-retentive or cleared on the
    first scan and then restart-tested.
- [ ] Measure normal and worst-case OB1 cycle time before and after logging.
- [ ] Measure work-memory/load-memory use and retained DB size.
- [ ] Generate simultaneous event storms and confirm bounded scan time.
- [ ] Power-cycle and warm-restart tests:
  - retained event history remains valid;
  - boot/session boundary is visible;
  - indices recover safely;
  - no stale command is executed.
- [ ] Run a 24-hour soak with heartbeat, pressure telemetry and repeated output
  feedback changes.
  - Pass: no CPU STOP, buffer corruption, unbounded queue or logger-induced
    communication loss.
- [ ] Document memory/cycle budgets and final sample rates.

## Gate 5 — Feedback verification

### Output feedback

- [ ] Verify every F-RQ input address against the physical relay module/slot.
- [ ] For each heavy-relay channel, test:
  - request OFF/ON;
  - F-DQ Q image;
  - F-RQ readback;
  - terminal voltage;
  - downstream contact voltage/current;
  - actual machine effect.
- [ ] Confirm Main Power and MCU Enable mappings on the actual machine.
- [ ] Confirm ignition R, 15/54, DR and Starter 50 mappings and readbacks.
- [ ] Confirm both complementary parking-brake channels:
  - verified command polarity;
  - brake ON/OFF state;
  - both F-RQ readbacks;
  - invalid both-high/both-low detection;
  - transition timeout.
- [ ] Resolve E-stop feedback limitation.
  - Current `Rq_EstopBrakeChXApplied` is derived by inverting the Q output image,
    not from an independent physical relay or mechanical brake signal.
  - Decide whether an independent electrical readback will be added.
  - Until then, name/document it as commanded-output state, not proof that the
    hydraulic brake physically moved.
- [ ] Document unavailable mechanical feedback explicitly:
  - no mechanical E-stop-brake engaged/released switch;
  - no mechanical parking-brake feedback;
  - no vehicle-speed feedback.
- [ ] Define mismatch debounce and reaction for each channel.
  - Immediate diagnostic versus latched major fault versus safety trip.
- [ ] Fault-injection test stuck-low, stuck-high, delayed and contradictory
  readbacks.

### Input feedback

- [ ] Verify dual remote E-stop F-DI channels independently.
  - Open each channel alone and both together.
  - Confirm discrepancy behavior, passivation, output reaction and diagnostics.
- [ ] Verify physical `Rem_Ack` reintegration.
  - Acknowledgement must not start the engine or clear an unsafe condition.
- [ ] Verify Auto/Manual input and all hardware-disable inputs.
- [ ] Verify engine-running feedback source, polarity, debounce and plausibility.
- [ ] Verify `McuBooted` and all compute-box status inputs against real behavior.
- [ ] Verify all pressure channels:
  - tag/address/channel;
  - 4–20 mA scaling;
  - ±3.2 bar zero deadband;
  - wire-break/underrange/overrange diagnostics;
  - plausible maximum;
  - watch table, Modbus and calibrated pressure source agreement.

## Gate 6 — Safety-function review

- [ ] Freeze and review the exact `SafeOK` equation.
  - Identify which conditions require immediate F-output removal.
  - Controlled communication loss currently conflicts with folding `CommLost`
    directly into global `SafeOK`; resolve this before production promotion.
- [ ] Produce a cause-and-effect matrix for:
  - remote E-stop;
  - F-I/O fault/passivation;
  - pressure safety trip;
  - communication loss by phase;
  - Auto-to-Manual transition;
  - disable inputs;
  - sequencer fault;
  - CPU restart.
- [ ] Verify brake fail-state behavior with physical polarity:
  - E-stop output ON = disengaged;
  - E-stop output OFF/resting = engaged;
  - parking brake defaults ON;
  - A/M relays remain OFF until driving confirmation.
- [ ] Validate the two-channel E-stop brake test end to end.
  - Tested shuttle ≤5 bar in 1 s.
  - Rebuilt shuttle 30–50 bar in 1 s.
  - Other shuttle changes by no more than 10 bar.
  - E-stop 1, E-stop 2 and Prop remain 120–150 bar.
- [ ] Verify pressure thresholds do not silently widen the 120–150 bar safety
  band when accounting for sensor zero uncertainty.
- [ ] Define and verify reset permissions.
  - All major faults require physical acknowledgement.
  - Unsafe E-stop, active trip, invalid feedback or active command must block
    reset.
  - Remote reset must not immediately restart the sequence.
- [ ] Verify anti-restart behavior after E-stop, fault, communication loss,
  mode change and CPU restart.
- [ ] Finalize engine shutdown ignition order and timing.
- [ ] Define stopped confirmation before applying parking brake after a
  controlled communication-loss stop.
  - Vehicle-speed feedback is currently unavailable; production release is
    blocked until an acceptable method is defined.
- [ ] Validate PROFIsafe watchdog settings over the Blitzfunk link under packet
  loss and reconnection.
- [ ] Confirm no commissioning bypass (`SimMode`) exists in production.
- [ ] Review standard-to-F-program data boundaries.
  - Standard requests may only request an action; F-LAD remains authoritative.
  - Invalid/stale standard data must result in the defined safe state.

## Gate 7 — Formal commissioning and promotion

- [ ] Update the full machine test procedure with expected request/Q/RQ,
  pressure, state, fault and event-log evidence for every test.
- [ ] Run tests first in `volvo_l60h_production_dev`.
- [ ] Peer-review SCL, F-LAD, hardware configuration, Modbus schema and event
  code table.
- [ ] Compile twice and require:
  - zero errors;
  - understood/closed warnings;
  - consistent offline safety program;
  - recorded collective F-signature.
- [ ] Compare offline/online software before download.
- [ ] Use Software-only download unless a reviewed hardware change is intended.
- [ ] Record load preview, CPU serial, safety signature, software commit and
  test evidence.
- [ ] Execute staged dry test, engine test, brake test, controlled fault
  injection and recovery.
- [ ] Promote reviewed sources from `volvo_l60h_production_dev` to
  `volvo_l60h_main`.
- [ ] Archive the exact TIA project and export matching the commissioned PLC.

## Immediate next actions

1. Complete Gate 0 signal/polarity and event-code tables.
2. Verify all F-RQ addresses and parking-brake complementary feedback.
3. Decide how to represent the lack of independent E-stop mechanical feedback.
4. Resolve `CommLost` versus `SafeOK` behavior.
5. Implement the bounded event ring and Modbus retrieval interface.
6. Use the resulting event evidence during the remaining safety tests.
