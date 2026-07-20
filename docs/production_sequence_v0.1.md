# Production sequence v0.1 development baseline

This is a development baseline only. It has not been imported into TIA Portal,
compiled as an F-project, downloaded, or approved for machine operation.

## Implemented in the draft

- Deterministic request image: every output request starts from an explicit safe
  default every PLC scan.
- No Ignition 30, Aux naming, or simulation bypass.
- Main Power followed by R + 15/54 + DR to wake the compute box.
- Sixty-second compute startup, MCU boot, and non-operational communication
  allowances.
- Rising-edge Engine Start, ReCrank, Begin Driving, Engine Stop, System
  Shutdown, Fault Reset and Shutdown Acknowledgement commands.
- A/M relays remain off until the brake test passes and Begin Driving is
  accepted.
- Independent semantic E-stop brake channel requests.
- After EngineRunning, both autonomous E-stop brake channels are disengaged so
  shuttle pressures can build while the parking brake remains locked and A/M
  remains off.
- Brake test mapping:
  - channel 1 acts on Shuttle 1;
  - channel 2 acts on Shuttle 2;
  - tested shuttle must reach at most 5 bar within 1 second;
  - restored shuttle must reach 30–50 bar within 1 second;
  - the non-tested shuttle may change by no more than 10 bar;
  - E-stop 1, E-stop 2 and Prop pressures must remain 120–150 bar.
- Both E-stop brake channels release after a passing test.
- PLC publishes ReadyForDrive and waits for BeginDrivingRequest.
- A/M relays enable before park unlock; park lock/unlock relay feedback is
  checked before DrivingEnabled.
- Manual mode explicitly disengages both PLC-controlled E-stop brake channels
  and cancels the autonomous sequence. The separate remote safety E-stop is not
  bypassed.
- Brake-test failure keeps the engine running, applies both brake channels,
  keeps parking locked and waits for reset or a stop/shutdown command.
- Engine Stop and complete System Shutdown are separate commands.
- Shutdown acknowledgement is required before Main Power removal.
- Phase-dependent heartbeat watchdog with 60-second startup/crank and
  configurable 3-second operational defaults.

## Deliberately incomplete / blocked

### Hardware polarity

`Req_EstopBrakeCh1Apply` and `Req_EstopBrakeCh2Apply` are semantic requests:
TRUE means the sequencer requires the brake applied. The final relationship to
the physical F-output must be established and validated in F-LAD. No safety
mapping has been generated from an assumption.

### Ignition shutdown

The exact ignition-off order and delays are not defined. Shutdown state 81
therefore holds Main Power, MCU power and engine-run ignition with A/M disabled
and brakes applied. It sets `ShutdownDefinitionRequired` and advances only if
EngineRunning is already false. This prevents an unreviewed shutdown sequence
from being treated as complete.

### Communication-loss stop

No vehicle-speed feedback exists. The draft revokes A/M, applies the E-stop
brake requests and keeps park unlock requested, then sets
`VehicleStopConfirmationRequired`. It does not guess when a moving machine is
safe for parking-brake application.

The current production safety equation includes CommLost in global SafeOK. That
must be refactored before a sequenced controlled communication-loss stop is
possible; otherwise F-LAD removes every output before the sequencer can control
the stop.

### E-stop channel feedback

The draft expects logical inputs `Rq_EstopBrakeCh1Applied` and
`Rq_EstopBrakeCh2Applied`. Their exact source/address and polarity must be mapped
to verified F-RQ feedback before TIA integration.
