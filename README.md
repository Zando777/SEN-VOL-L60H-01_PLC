# Volvo L60H PLC

PLC control and commissioning tooling for the Sensmore Volvo L60H wheel-loader
automation project.

## Platform

- Siemens ET 200SP CPU 1510SP F-1 PN
- TIA Portal V20
- SCL standard program with F-LAD safety gating
- Modbus TCP interface for the compute box and commissioning GUI

## Repository contents

- `plc/io-test/` — current commissioning I/O-test SCL sources
- `plc/production/` — production sequencer/watchdog development sources; not yet
  approved or downloaded
- `tools/io_test_gui.py` — Modbus GUI for pressure telemetry, safety state and
  independent output testing
- `tools/computebox_sim.py` — command-line compute-box simulator
- `docs/io_map.md` — verified physical I/O map
- `docs/io_test_current_state.md` — current implementation and deployment status
- `docs/compute_box_ros_handover.md` — compute-box Modbus/ROS handover
- `docs/volvo_l60h_design.md` — system design notes
- `docs/test_plan.md` — commissioning test plan

The native `.ap20` TIA Portal projects remain on the engineering workstation.
This repository intentionally tracks reviewable source and documentation rather
than generated project archives.

## Current I/O-test behavior

The commissioning project continuously publishes all five pressure channels and
detailed safety state over Modbus. Multiple outputs may be requested together,
but every physical output remains gated by the fail-safe program.

The crank sequence controls ignition stages 14–17. Main Power, MCU Enable and
A/M Relays retain their pre-start states. In engine-running stage 17, non-ignition
outputs can be tested without cancelling the run-position ignition requests.

The GUI automatically records each session under
`Documents/VolvoL60H/logs/YYYY-MM-DD/` as three CSV files: continuous telemetry,
every outgoing Modbus write, and state/fault/operator events. CSV writes run on
a background thread and do not block Modbus polling. `ENABLE CSV LOGGING` can
flush/close the current session and start a fresh Run ID when enabled again.

See [`docs/io_test_current_state.md`](docs/io_test_current_state.md) for the
complete register map, safety behavior and current deployment status.

Production development status and deliberately blocked assumptions are tracked
in [`docs/production_sequence_v0.1.md`](docs/production_sequence_v0.1.md).

## Safety

This software operates real heavy machinery and can energize the starter,
release brakes and start the engine. Modbus commands do not bypass the F-program,
remote E-stop, acknowledgement, communication watchdog or hardware-disable
gates. Commissioning must follow the approved machine isolation and safety
procedure.
