# Production Modbus TCP interface — schema 1.0 draft

All command registers are non-retentive and are also cleared by the PLC on its
first scan. Multi-action commands are rising-edge-qualified by the sequencer.
The compute box increments HR3 for each new command set; the PLC echoes the last
observed value in HR26.

## Compute box to PLC

| HR | Bit | Name | Behavior |
|---:|---:|---|---|
| 0 | 0 | SystemEnable | Maintained |
| 0 | 1 | EngineStartRequest | Rising edge |
| 0 | 2 | ReCrankRequest | Rising edge |
| 0 | 3 | BeginDrivingRequest | Rising edge |
| 0 | 4 | EngineStopRequest | Rising edge |
| 0 | 5 | SystemShutdownRequest | Rising edge |
| 0 | 6 | FaultResetRequest | Rising edge |
| 0 | 7 | ShutdownAcknowledged | Rising edge |
| 0 | 8 | ComputeReady | Maintained status |
| 0 | 9 | McuBooted | Maintained status |
| 0 | 10 | EngineRunning | Maintained status |
| 1 | — | Heartbeat | Increment continuously |
| 2 | — | Compute schema version | Must equal `16#0100` |
| 3 | — | Command sequence | Increment for each new command set |
| 4–15 | — | Reserved | Write zero |

`ComputeAlive` requires a changing heartbeat, compatible HR2 and ComputeReady.
A static writable bit alone is not accepted as proof of communication.

## PLC to compute box

| HR | Meaning |
|---:|---|
| 16 | Main production status flags |
| 17 | Current sequencer state |
| 18 | Previous sequencer state |
| 19 | Fault code |
| 20 | Last transition-reason code |
| 21 | State elapsed time in 100 ms units |
| 22 | Crank-attempt count |
| 23 | Incrementing PLC telemetry sequence |
| 24 | PLC schema version (`16#0100`) |
| 25 | Sequencer version (`16#0001`) |
| 26 | Last observed command sequence from HR3 |
| 27 | Echo of active command bits |
| 28–31 | Reserved |
| 32–36 | Pressures ×10 bar: Shuttle1, Estop1, Shuttle2, Estop2, Prop |
| 37–41 | Signed raw pressure inputs in the same order |
| 42 | Per-channel pressure sensor/wire-break faults |
| 43 | Per-channel pressure band/threshold diagnostics |
| 44–47 | Reserved |
| 48 | Sequencer request image |
| 49 | Safety-gated physical output image |
| 50 | Packed F-RQ relay readback image |
| 51 | Request/output/readback mismatch image |
| 52 | Safety-source flags |
| 53 | Brake-test/request/readback flags |
| 54 | Heartbeat age in 100 ms units |
| 55 | Active heartbeat timeout in 100 ms units |
| 56–127 | Reserved for detailed diagnostics/fault history |

### HR16 status flags

| Bit | Meaning |
|---:|---|
| 0 | ComputeAlive |
| 1 | ReadyForDrive |
| 2 | DrivingEnabled |
| 3 | EstopBrakeTestPassed |
| 4 | EstopBrakeChannelsReleased |
| 5 | MajorFaultActive |
| 6 | PhysicalAckRequired |
| 7 | ShutdownReady |
| 8 | ShutdownComplete |
| 9 | ShutdownDefinitionRequired |
| 10 | VehicleStopConfirmationRequired |
| 11 | CommLost |
| 12 | AutoMode |
| 13 | SafeOK |
| 14 | EngineRunning |
| 15 | McuBooted |

### HR48–HR51 packed output bits

| Bit | Signal |
|---:|---|
| 0 | Main Power |
| 1 | MCU Enable |
| 2 | A/M Relays |
| 3 | Ignition R |
| 4 | Ignition 15/54 |
| 5 | Ignition DR |
| 6 | Starter 50 |
| 7 | E-stop brake channel 1 applied |
| 8 | E-stop brake channel 2 applied |
| 9 | Parking-brake unlock |
| 10 | Parking-brake lock feedback (Q/F-RQ diagnostics only) |

The same bit order is used for request, Q, F-RQ and mismatch words. A/M and the
two E-stop solenoids do not have F-RQ modules; their F-RQ bits remain zero.
Parking lock is complementary to unlock and therefore has no independent
sequencer request bit. A readback bit is valid only after its physical source
and polarity have been verified.

### HR43 pressure-band flags

| Bit | Meaning |
|---:|---|
| 0 | Shuttle 1 in 30–50 bar rebuild band |
| 1 | E-stop 1 in 120–150 bar supply band |
| 2 | Shuttle 2 in 30–50 bar rebuild band |
| 3 | E-stop 2 in 120–150 bar supply band |
| 4 | Prop in 120–150 bar supply band |
| 8 | Shuttle 1 at or below 5 bar |
| 9 | Shuttle 2 at or below 5 bar |

### HR52 safety flags

| Bit | Meaning |
|---:|---|
| 0 | SafeOK |
| 1 | E-stop safety block output |
| 2 | Remote E-stop channel 1 |
| 3 | Remote E-stop channel 2 |
| 4 | Physical acknowledgement input |
| 5 | ResetPermitted |
| 6 | MCU disable |
| 7 | A/M disable |
| 8 | Park disable |
| 9 | E-stop brake disable |
| 10 | Sequencer Abort |
| 11 | SafetyTripActive |
