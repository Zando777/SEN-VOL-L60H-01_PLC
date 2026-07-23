# Volvo L60H PLC event logging v1

Status: production-development and I/O-test-logging-development only
Date: 2026-07-23

Offline verification:

- `volvo_l60h_production_dev`: compiled with 0 errors and 0 warnings; Openness
  inventory verified the event UDT/DBs and three logger FCs.
- `volvo_l60h_io_test_logging_dev`: compiled with 0 errors and 0 warnings;
  Openness export verified the event UDT/DBs, three logger FCs, calls from
  `FC_OutputTest`, and the 128-word Modbus array.
- Neither development project has been downloaded to the PLC.

The logger is observational standard PLC code. No logger DB, retrieval request,
event code or logger-health value is consumed by the sequencer, F-program or
physical-output equations.

## Common behavior

- Fixed ring capacity: 128 event records.
- Execution is bounded. Production has thirteen fixed edge checks per scan.
  I/O test has eleven checks per `FC_OutputTest` invocation and the existing
  test `Main` invokes that FC twice per scan.
- A full ring overwrites the oldest record and increments `OverwriteCount`.
- Every record contains a PLC `DTL` timestamp and the `RD_SYS_T` return status.
- `TimeValid` is true only when `RD_SYS_T` returned zero.
- Sequence numbers are monotonically increasing during the current PLC run.
- Version 0.1 is intentionally non-retentive. Power-cycle retention will be
  enabled only after target memory and restart behavior have been measured.
- Retrieval is by event sequence, with a request token and a coherent response
  buffer. A client can detect overwritten gaps from oldest/newest sequence and
  overwrite count.

## Production event identifiers

| Event ID | Meaning | Source |
|---:|---|---|
| `0001` | Logger/PLC session started | logger |
| `0100` | Sequencer state changed | production sequencer |
| `0200` | Fault asserted or replaced | production sequencer |
| `0201` | Fault cleared | production sequencer |
| `0300` | Packed safety-source flags changed | I/O/safety boundary |
| `0350` | Physical acknowledgement requirement changed | sequencer |
| `0400` | Compute-box communication lost | communication watchdog |
| `0401` | Compute-box communication recovered | communication watchdog |
| `0500` | Command bits or command sequence changed | Modbus |
| `0600` | Sequencer request image changed | sequencer |
| `0610` | Physical Q image changed | I/O |
| `0620` | F-RQ readback image changed | I/O |
| `0630` | Output mismatch asserted/changed | diagnostics |
| `0631` | Output mismatch cleared | diagnostics |
| `0700` | Pressure fault bits changed | pressure diagnostics |
| `0710` | Pressure-band bits changed | pressure diagnostics |
| `0800` | Auto/Manual input diagnostic word changed | safety/I/O boundary |

Sources: logger `1`, sequencer `2`, safety/I/O `3`, communication `4`, Modbus
commands `5`, output diagnostics `6`, pressure diagnostics `7`.

Severities: information `1`, warning `2`, fault `3`, safety-relevant edge `4`.

### Production Modbus retrieval

Compute-box-owned requests:

| HR | Meaning |
|---:|---|
| 4 | Requested event sequence, low word; zero with HR5 zero selects newest |
| 5 | Requested event sequence, high word |
| 6 | Request token; change after writing HR4/HR5 |

PLC-owned response:

| HR | Meaning |
|---:|---|
| 56 | Log schema `0x0100` |
| 57 | Flags: initialized, time valid, full, request processed, found, time error, index recovery |
| 58–59 | Oldest sequence, low/high |
| 60–61 | Newest sequence, low/high |
| 62 | Valid record count |
| 63 | Capacity (`128`) |
| 64–65 | Overwrite count, low/high |
| 66 | Echoed request token |
| 67 | Response status: `1` found, `2` not found |
| 68–111 | Coherent event record |
| 112–115 | Logger diagnostic counters and last event ID |
| 116 | Live Auto/Manual input diagnostic word |
| 117 | Selected event record Auto/Manual input diagnostic word |

The record window contains sequence, event ID/severity/source, old/new values,
UTC system time components, sequencer state/fault/reason, command and command
sequence, request/Q/F-RQ/mismatch images, safety/brake flags, pressure
fault/band flags, five pressures, five signed raw inputs, heartbeat age,
watchdog timeout, boot/session number and the Auto/Manual input diagnostic word.

## I/O-test event identifiers

| Event ID | Meaning |
|---:|---|
| `0001` | Logger/PLC session started |
| `1100` | GUI-requested output mask changed |
| `1110` | ARM word changed |
| `1120` | Manual-mode permission word changed |
| `1130` | Crank stage changed |
| `1140` | PLC-active mask changed |
| `1200` | Packed PLC status changed |
| `1210` | Direct SafeOK-source values changed |
| `1300` | Physical Q image changed |
| `1310` | F-RQ readback image changed |
| `1320` | Effective request image changed |
| `1400` | Pressure-band flags changed |

### I/O-test Modbus retrieval

The existing HR0–HR21 commissioning interface is unchanged.

| HR | Owner | Meaning |
|---:|---|---|
| 22–23 | GUI | Requested event sequence, low/high; zero selects newest |
| 24 | GUI | Request token |
| 56 | PLC | Log schema `0x0100` |
| 57–67 | PLC | Flags, oldest/newest, count, capacity, overwrites, token and status |
| 68–103 | PLC | Coherent event record |
| 104–107 | PLC | Logger diagnostics |

When GUI CSV logging is enabled, the GUI downloads historical PLC records in
sequence order into a separate `*_plc_events.csv`. It detects overwritten gaps,
while retaining the existing live telemetry, GUI command and GUI event CSV
files. CSV logging remains OFF by default.

## Deliberate version-0.1 limits

- The event ring is non-retentive.
- There is no periodic PLC telemetry ring yet; periodic telemetry remains in
  the GUI CSV logger.
- Production command acceptance/rejection and individual safety-source event
  IDs will be added after the command and feedback requirements are frozen.
- Pressure fault event quality depends on completing the production pressure
  diagnostic bit packing.
- Logger worst-case scan time and memory use still require target measurement.
