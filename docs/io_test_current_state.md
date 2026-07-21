# Volvo L60H PLC I/O Test — Current State

Last updated: 20 July 2026

## Current progress snapshot — 20 July 2026

The latest offline `volvo_l60h_io_test` project has been generated, compiled
and export-audited with **0 errors and 0 warnings**. The generated
`FC_OutputTest` contains the updated engine-running stage-17 logic described
below. The matching `io_test_gui.py`, SCL source, README and this state document
are synchronized on the S7 and in the persistent local snapshot folder.

At the time of this snapshot, the final stage-17 update still needs to be
downloaded from TIA Portal to the PLC, and the running GUI must be restarted to
load the updated Python file. Offline compile success alone does not change the
PLC program.

## Purpose and project location

`volvo_l60h_io_test` is the commissioning-only PLC project used to test the
Volvo L60H pressure inputs and physical outputs independently of the production
autonomous sequence.

- PLC: Siemens ET 200SP CPU 1510SP F-1 PN
- Engineering: TIA Portal V20
- PLC address: `10.90.11.200`
- Modbus TCP: port 502
- S7 project:
  `C:\Users\sensmore\Documents\Automation\volvo_l60h_io_test\volvo_l60h_io_test.ap20`
- GUI: `C:\Users\sensmore\Desktop\io_test_gui.py`
- Project documentation and source copies:
  `C:\Users\sensmore\Documents\Automation\volvo_l60h_io_test\UserFiles`

This project retains the real hardware and F-safety configuration. OB1 runs
only the Modbus server, five-channel pressure scaling, I/O test controller and
two-second heartbeat watchdog. The production sequencer and run-band pressure
monitor remain present but are not called by the test OB1.

## Current verified pressure configuration

The four channels of the `F-AI Pressures` module must be configured as
independent sensors using **1oo1 evaluation**, not 1oo2 evaluation.

The previous 1oo2 setting paired channels 0/2 and 1/3. This treated the two
shuttle sensors and the two E-stop-pressure sensors as redundant pairs and
could produce discrepancy diagnostics or substitute zero values. The hardware
configuration has now been changed to 1oo1.

| Channel | PLC tag | Address | Function |
|---|---|---:|---|
| AI0 | `Press_Shuttle_1` | `%IW35` | Shuttle pressure 1 |
| AI1 | `Press_Estop_1` | `%IW37` | E-stop pressure 1 |
| AI2 | `Press_Shuttle_2` | `%IW39` | Shuttle pressure 2 |
| AI3 | `Press_Estop_2` | `%IW41` | E-stop pressure 2 |
| Prop module AI0 | `Press_Prop` | `%IW7` | Proportional pressure |

All inputs use the configured 4–20 mA range. The PLC scaling is
`raw × 400 / 27648`, producing bar. At 4 mA the Siemens raw value is
approximately zero.

The GUI displays each channel as `bar | calculated mA | raw`. Current is
calculated from the signed raw input as `4 + raw × 16 / 27648`; values are not
clamped so sensor underrange and overrange remain visible. The same calculated
mA values are recorded in the telemetry CSV.

The GUI presentation order is Shuttle 1, Shuttle 2, E-stop 1, E-stop 2, Prop.
The Modbus register order remains unchanged for compatibility: Shuttle 1,
E-stop 1, Shuttle 2, E-stop 2, Prop.

The pressure sensors specify a maximum characteristic deviation of ±0.8% of
span. For the 0–400 bar range this is ±3.2 bar (equivalent to ±0.128 mA on the
4–20 mA span). Values at or below 3.2 bar are therefore normalized to 0 bar in
the pressure telemetry, while the signed raw count and calculated mA remain
unclamped for diagnostics. The 120–150 bar safety band is not widened.

Whenever the output test is newly armed, the Park Brake toggle defaults to ON
(brake enabled). The PLC request also defaults to parking brake ON in both Auto
and Manual; it can still be switched OFF explicitly after arming. In Manual,
both E-stop brake outputs are held ON/energized, which is the verified
disengaged state. Their OFF/resting state engages the E-stop brakes.

If an F-AI channel displays zero unexpectedly:

1. Monitor its raw tag, the corresponding `PressData` value and
   `F00035_F-AIPressures`.DIAG.
2. Check the channel-status/fault LEDs and confirm valid loop current at the
   module terminal.
3. Clear the underlying fault and press the physical `Rem_Ack` button to
   reintegrate passivated F-I/O.

## Removed signals

The following nonexistent or unused signals have been removed from the test
program, GUI, PLC tags, watch-table references, documentation and Linear I/O
test checklist:

- Ignition terminal 30 / `Ign_30` / `Req_Ign30`
- `LED_1`
- `LED_2`
- `Rem_Arm`

`%Q0.2` and `%I28.3` are currently unused.

The following remote safety signals remain and must not be removed:

| Tag | Address | Purpose |
|---|---:|---|
| `RemEstop_1` | `%I28.0` | Remote E-stop safety channel 1 |
| `Rem_Ack` | `%I28.1` | Physical acknowledgement and F-I/O reintegration |
| `Rem_Start` | `%I28.2` | Remote start input/status |
| `RemEstop_2` | `%I28.4` | Remote E-stop safety channel 2 |

## Output map used by the test GUI

| GUI function | PLC tag | Address |
|---|---|---:|
| Main power | `MainPwr_Sw` | `%Q49.7` |
| MCU enable | `MCU_Enable` | `%Q49.6` |
| A/M relays | `AM_Relays` | `%Q0.3` |
| Ignition R | `Ign_R` | `%Q49.0` |
| Ignition 15/54 | `Ign_15_54` | `%Q49.1` |
| Ignition DR | `Ign_DR` | `%Q49.2` |
| Starter 50 | `Ign_50` | `%Q49.3` |
| Park brake (single GUI command) | Legacy control tag `ParkBrake_Unlock` | `%Q49.5` |
| Park brake complementary feedback | Legacy tag `ParkBrake_Lock` | `%Q49.4` |
| E-stop solenoid 1 | `Sol_Estop` | `%Q0.0` |
| E-stop solenoid 2 | `Sol_Estop_2` | `%Q0.1` |

Multiple GUI output toggles may be active simultaneously. The parking brake has
one semantic toggle: **ON means brake enabled; OFF means brake disabled**. The
legacy PLC tag names do not describe the observed machine behavior, so they are
shown only as physical-channel diagnostics. HR0 bit 9, formerly the separate
Park Lock command, is reserved and ignored. Both E-stop solenoid outputs are
controlled together.

The `%Q49` F-DQ command outputs drive downstream 5 A F-RQ relay modules. The GUI
shows both the PLC output-image state (`Q`) and the associated F-RQ readback
(`RQ`). A yellow mismatch means command and relay readback differ.

## Test safety behavior

The test project retains the dual-channel remote E-stop logic, physical
acknowledgement, communication watchdog and per-output hardware-disable gates.

The test-only A/M permission is:

`TestAutoOK = AutoMan_Sw1 OR TestManualEnable`

`TestManualEnable` becomes true only when all of the following are true:

- The GUI is armed with HR1 equal to `16#A55A`.
- The GUI heartbeat is healthy and `CommLost` is false.
- The GUI writes the exact HR13 permission value `16#4D4D`.

The GUI exposes this as the toggle **ALLOW OUTPUTS WITH A/M IN M**. It defaults
off and clears on disarm, ALL OFF, GUI close or communication loss. It permits
both manual output testing and the crank sequence with the physical A/M switch
in M. It does not bypass the remote E-stop, acknowledgement, heartbeat,
CommLost or hardware-disable logic.

The test project compiled after this change with **0 errors and 0 warnings**.

## Modbus register map

| HR | Direction | Meaning |
|---:|---|---|
| 0 | GUI → PLC | Independent manual-output request mask; bit 8 = Park Brake ON, bit 9 reserved/ignored |
| 1 | GUI → PLC | `16#A55A` arms the test; any other value disarms |
| 2 | PLC → GUI | Active manual mask echo, otherwise zero |
| 3 | PLC → GUI | Shuttle 1 pressure ×10 bar |
| 4 | PLC → GUI | E-stop 1 pressure ×10 bar |
| 5 | PLC → GUI | Shuttle 2 pressure ×10 bar |
| 6 | PLC → GUI | E-stop 2 pressure ×10 bar |
| 7 | PLC → GUI | Prop pressure ×10 bar |
| 8 | GUI → PLC | Incrementing heartbeat |
| 9 | PLC → GUI | Safety and test status bits |
| 10 | PLC → GUI | Actual output-image bits after safety gates |
| 11 | GUI → PLC | Crank stage: 0 manual; 14–17 crank stages |
| 12 | PLC → GUI | F-RQ relay readbacks for `%Q49.0..7` |
| 13 | GUI → PLC | `16#4D4D` permits testing in M while armed |
| 14 | PLC → GUI | Effective PLC request-image bits after ARM/heartbeat/crank selection |
| 15 | PLC → GUI | Direct SafeOK source values used by the watch table |
| 16 | PLC → GUI | Incrementing PLC telemetry sequence for stale-data detection |
| 17 | PLC → GUI | Raw signed Shuttle 1 input |
| 18 | PLC → GUI | Raw signed E-stop 1 input |
| 19 | PLC → GUI | Raw signed Shuttle 2 input |
| 20 | PLC → GUI | Raw signed E-stop 2 input |
| 21 | PLC → GUI | Raw signed Prop input |

HR9 status bits are:

| Bit | Meaning |
|---:|---|
| 0 | Test active |
| 1 | Heartbeat seen |
| 2 | Communication lost |
| 3 | SafeOK |
| 4 | Physical Auto mode |
| 5 | Remote E-stop channel 1 |
| 6 | MCU disable |
| 7 | A/M-relay disable (`AM_Disable`) |
| 8 | Park-brake disable |
| 9 | E-brake disable |
| 10 | Remote E-stop channel 2 |
| 11 | Remote acknowledgement |
| 12 | Remote start |
| 13 | Outputs-in-M permission active |

HR15 mirrors the direct safety sources: `estop_safe`, `remote_estop_ok`,
`TestAutoOK`, `PressTrip`, `CommLost`, `SafeOK`, test active and communication
seen. The GUI color-codes these values, displays separate `REQ`, `Q` and `RQ`
states for each output, shows raw analog counts beside scaled bar values, and
marks telemetry stale if HR16 stops advancing.

The updated GUI reads HR0 through HR21. If it receives Modbus exception 2
(`Illegal Data Address`) while reading 22 registers, an older PLC test program
is still downloaded and the latest test project must be loaded.

## Crank-sequence test

The crank sequence may operate the real starter and start the engine. At crank
entry, the GUI retains the current Main Power, MCU power and A/M-relay request
bits, and the PLC passes each state through unchanged during the sequence. The
sequence changes only the ignition requests; it does not automatically enable
or disable those three support outputs. Brakes and solenoids are not carried
into crank.

| Stage | Duration | Requests |
|---:|---:|---|
| 14 | 1 s | R and DR |
| 15 | 3 s | R, 15/54 and DR |
| 16 | Maximum 10 s | DR and Starter 50 |
| 17 | Until ALL OFF/abort | R, 15/54 and DR |

Press **ENGINE RUNNING / STOP STARTER** immediately when the engine catches.
The starter is limited to ten seconds even if the button is not pressed.

In stage 17, the sequence continues to hold R, 15/54 and DR in the run position.
Main Power, MCU, A/M relays, the single Park Brake command and the E-stop/brake-solenoid pair may
then be toggled without cancelling the sequence or removing ignition. The four
manual ignition toggles are locked while the sequence owns them.

All GUI controls are exposed through Modbus: HR0 carries the independent output
mask, HR11 selects crank stages 14–17, HR1 arms the test, HR13 permits testing
with the physical A/M switch in M, and HR8 is the heartbeat. These requests
remain subject to SafeOK, dual-channel remote E-stop logic, physical
acknowledgement, communication watchdog and hardware-disable gates.

## Running the GUI

```powershell
C:\Users\sensmore\Desktop\dev\siemens\.venv\Scripts\python.exe C:\Users\sensmore\Desktop\io_test_gui.py 10.90.11.200
```

Normal test flow:

1. Put the machine in a mechanically safe test condition.
2. Release the remote E-stop and press the physical `Rem_Ack` button.
3. Start the GUI and confirm live pressure/status data.
4. Select **ARM OUTPUT TEST**.
5. If the A/M switch is in M, explicitly enable
   **ALLOW OUTPUTS WITH A/M IN M**.
6. Toggle the required outputs and verify `Q`, `RQ` and the physical voltage.
7. Use **ALL OFF / DISARM** when finished.

## CSV session logging

The GUI automatically creates a session directory at:

`C:\Users\sensmore\Documents\VolvoL60H\logs\YYYY-MM-DD`

Each GUI run writes three files with a shared run ID:

- `*_telemetry.csv`: every polling cycle, including all 22 holding registers,
  scaled and raw pressures, SafeOK sources, requests, output images and F-RQ
  readbacks.
- `*_commands.csv`: every outgoing Modbus register write with source, value,
  result, exception and latency.
- `*_events.csv`: connection changes, SafeOK/CommLost/E-stop/pressure-trip
  changes, arming, output toggles and crank stages.

The writer runs in a background thread, flushes at least once per second and
shows its directory/run ID or an error on the GUI. Failed Modbus polls create
explicit disconnected telemetry rows instead of silent gaps.

`ENABLE CSV LOGGING` controls recording. Turning it off flushes and closes all
three current files; enabling it again starts a new session and Run ID. The GUI
uses compact multi-column status panels plus vertical and horizontal scrolling
so all values remain accessible at smaller RDP resolutions.

## Production-project status

The production project remains separate and unchanged by this test-project
update:

`C:\Users\sensmore\Documents\Automation\volvo_l60h_main\volvo_l60h_main.ap20`

An accidental partial offline rename attempt in the production project was
fully reverted on 20 July 2026. The original Aux-relay safety block and tags
were restored, the temporary A/M tags were removed, and the complete production
project compiled with **0 errors and 0 warnings**. Nothing from that attempt was
downloaded to the PLC.

The A/M naming, enhanced Modbus telemetry, manual-mode permission and
ignition-only crank behavior documented here apply to `volvo_l60h_io_test`
only. Do not copy the test-only `TestAutoOK`/HR13 permission into production.

## Important deployment note

Offline compile success does not update the PLC. After any project or hardware
change, compile hardware/software/safety, download the complete relevant change,
accept the F-CPU identity/signature prompts and perform the required physical
F-I/O acknowledgement. Confirm the CPU is in RUN and Modbus port 502 accepts
connections before starting the GUI.
