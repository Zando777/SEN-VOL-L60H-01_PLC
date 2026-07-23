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
- The parking brake defaults ON in both Auto and Manual. The existing PLC field
  is still named `Req_ParkUnlock`, but verified machine polarity is TRUE = brake
  ON/enabled and FALSE = brake OFF/disabled. Production disables it only after
  the brake test passes, driving is confirmed and A/M relays are enabled.
- E-stop output polarity is verified: output ON/energized = brake disengaged;
  output OFF/resting = brake engaged. In Auto both channels are commanded
  applied (outputs OFF) for safety abort/E-stop, fault hold, communication-loss
  stop and shutdown. Manual holds both outputs ON/disengaged.
- Brake-test failure keeps the engine running, applies both brake channels,
  keeps parking locked and waits for reset or a stop/shutdown command.
- Engine Stop and complete System Shutdown are separate commands.
- Shutdown acknowledgement is required before Main Power removal.
- Phase-dependent heartbeat watchdog with 60-second startup/crank and
  configurable 3-second operational defaults.

## Auto/Manual handover

- State `90` is an explicit Manual-handover/inactive state. Entering it cancels
  the autonomous cycle and no previous state can resume.
- State `91` is an invalid selector input (value status false). It is a major
  fault, requests both E-stop brakes applied and requires physical
  acknowledgement.
- `%I21.0` is the F-DI internally evaluated 1oo2 result for channels 0+4.
  `%I22.0` is its value status. The high-order `%I21.4` bit is not used as an
  independent channel.
- Returning to Auto forces INIT and clears the enable guard. The PLC must see
  `SystemEnable` low after Auto selection, then a new high, before starting.
- Physical Manual ownership still depends on the pending F-LAD authority split
  and verified A/M relay contact path; this standard state alone is not approved
  for production download.

## Deliberately incomplete / blocked

### E-stop hardware polarity

`Req_EstopBrakeCh1Apply` and `Req_EstopBrakeCh2Apply` are semantic requests:
TRUE means the sequencer requires the brake applied. The physical output has
the inverse polarity: ON = disengaged and OFF/resting = engaged. `ProductionIO`
therefore inverts the semantic request at the hardware boundary and inverts the
output image again for the semantic applied feedback.

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
