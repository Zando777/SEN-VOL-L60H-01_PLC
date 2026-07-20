# Volvo L60H — Autonomous Engine-Start PLC Control System

**Engineering Design & Reference Document**

| | |
|---|---|
| **Machine** | Volvo L60H wheel loader — autonomous engine-start control |
| **TIA project** | `volvo_l60h_alex` (`…\Automation\volvo_l60h_alex\volvo_l60h_alex.ap20`) |
| **CPU** | ET 200SP **CPU 1510SP F-1 PN** (fail-safe), art. `6ES7 510-1SK03-0AB0`, FW V4.0 |
| **Safety integrity** | SIL 2 / F-capable, F-monitoring 150 ms, F-source addr 1, F-dest range 1–99 |
| **Toolchain** | TIA Portal V20 + PLCSIM V20 |
| **Audience** | Controls engineer (understand / test / maintain / hand off) |

---

## 1. Overview & Purpose

This system autonomously starts the diesel engine of a Volvo L60H wheel loader and brings
the machine to an operational, brakes-released state, entirely under command of an external
**compute box** over Modbus TCP. It replaces the human at the ignition key: it sequences
main power, boots the drive-by-wire MCUs, performs the four-stage ignition/crank cycle
(with a crank-fail path), verifies that the hydraulic system builds and holds working
pressure, and finally releases the e-stop brake and parking brake so the machine can drive.

The controlling principle is a strict separation between a **standard "brain"** that decides
*what should happen* and a **fail-safe "safe hands"** that decides *whether it is allowed to
happen*. The safety layer holds an absolute, continuous veto over every physical output in
every state — including when the sequencer is stalled, stopped, or faulted. Because all
machine outputs are fail-safe (F-DQ driving F-RQ relays), any wire break, passivation, or
CPU stop reads as "tripped" and de-energizes the machine into its safe state (brakes applied,
ignition off).

### Design intent

- **E-stops function at all times.** E-stop evaluation lives only in the always-on F-runtime,
  independent of OB1 / the sequencer. This is a firm safety requirement, not an emergent property.
- **The sequencer only requests; it can never directly energize anything.** Every real output
  is `Request AND SafeOK`.
- **Fail-safe by default.** De-energized = safe. Loss of any F-signal collapses `SafeOK`.

---

## 2. System Architecture — the Request → Gate → Output model

The application is split across two co-resident programs on the same F-CPU:

- **Standard program (SCL) — the brain.** `FB_Sequencer` runs an 18-state CASE machine and
  emits `Req_*` **request bits**. Standard glue (`FC_Pressure`, `FC_ModbusIn/Out`) feeds it
  scaled pressures and the compute-box command word, and publishes status back. The standard
  program is fully simulatable.
- **Fail-safe program (F-LAD) — the safe hands.** `Main_Safety_RTG1` evaluates the e-stops,
  composes a single `SafeOK` permissive, and drives **every real F-output** as
  `output = Req_x AND SafeOK`. It also folds in the pressure trip and handles F-I/O
  passivation/reintegration.

The handoff — the F-program *reading* the standard `Seq_DB.Req_*` bits — is the deliberate
"route a signal from standard into safety" pattern. Reading standard tags in an F-block is
permitted (compiler infos only); the reverse gating guarantees a request can never bypass the
safety evaluation.

```
   COMPUTE BOX (MacBook / real)                     PHYSICAL MACHINE
   ───────────────────────────                      ────────────────
        │  Modbus TCP (PLC = MB_SERVER)                    ▲
        ▼                                                  │ F-DQ 8x → F-RQ 5A relays
  ┌───────────────┐   HR0 cmd     ┌──────────────────┐     │  + F-DQ 2A
  │  ModbusData   │──────────────▶│  FC_ModbusIn     │     │
  │  hold[0..9]   │◀──────────────│  FC_ModbusOut    │  ┌──┴─────────────────────────┐
  └───────────────┘   HR1..7 sts  └────────┬─────────┘  │  Main_Safety_RTG1 (F-LAD)  │
                                           │            │  "SAFE HANDS"              │
   Press_* (5× 4-20mA F-AI)                ▼            │                            │
        │        ┌──────────────┐   MB_* inputs  ┌──────┴───────┐   estop_safe       │
        └───────▶│ FC_Pressure  │───────────────▶│ FB_Sequencer │   PressTrip        │
                 │  → PressData │  PressBuildOK   │  18-state    │        │           │
                 └──────┬───────┘                │  CASE machine│   SafeOK = estop_safe
                        │                        └──────┬───────┘        AND NOT PressTrip
                        │  PressData.bar                │  Req_* request bits          │
                        ▼                               ▼                              │
                 ┌─────────────┐               each F-output = Req_x AND SafeOK ───────┘
                 │  FB_PressMon│──── PressTrip ─────────────▲
                 │  run-band   │  (folds into SafeOK)
                 └─────────────┘

   Abort = NOT SafeOK  ──▶  snaps FB_Sequencer to State 0 (INIT); all outputs de-energize.
```

### Scan order (OB1 / standard cycle)

1. `FC_ModbusIn` — copy HR0 command word → `Seq_DB.MB_*` inputs (before the sequencer).
2. `FC_Pressure` — scale the 5 raw analog inputs → bar, set `Seq_DB.PressBuildOK`.
3. `Seq_DB()` — run `FB_Sequencer` (updates `State` and `Req_*`).
4. `FB_PressMon` — run-band monitor → `PressData.PressTrip`.
5. `FC_ModbusOut` — publish status word, state, and pressures → HR1..HR7 (after the sequencer).

> Note: the on-box `Main` OB1 currently shown in `FC_Pressure.scl` calls `FC_Pressure` then
> `Seq_DB` only. The Modbus glue and `FB_PressMon` are additional blocks in the same cycle;
> confirm the final OB1 call order against the live project (see Open Items).

The **F-runtime (`Main_Safety_RTG1`) executes independently** of OB1 on its own F-cycle, which
is why the e-stop veto survives any fault or stall of the standard program.

---

## 3. Hardware & I/O Summary

Full pin-by-pin detail — with schematic cross-references and the ignition key-position table —
lives in **`/Users/alexandersteffen/Documents/PLC-Course/volvo_l60h_IO_map.md`**. That file is
the source of truth for addresses. This section summarizes only what is needed to read the logic.

**Stations:** `ET 200SP station_1` (CPU + I/O) and a remote `RemoteEStop` station (ET 200SP,
IM 155-6 PN) carrying the operator pendant.

### Output hub

The **`F-DQ 8x24VDC/0.5A PP HF`** card (`%Q49.0–.7`, slot 6 / J5) is the output hub: each logic
channel energizes the coil of a high-current **F-RQ 5A relay** (J6–J13) that does the real
switching. The F-RQ modules are passive muscle (no tags). `Plc_ign_30` (term 30) is a common
always-on power rail feeding the ignition relays — not a switched output.

| Output tag | Addr | Function |
|---|---|---|
| `Ign_R` | %Q49.0 | Ignition terminal **R (58)** — key pos I |
| `Ign_15_54` | %Q49.1 | Ignition **15/54** |
| `Ign_DR` | %Q49.2 | Ignition **DR (17)** |
| `Ign_50` | %Q49.3 | Ignition **50** — starter / crank |
| `ParkBrake_Lock` | %Q49.4 | Parking brake **LOCK** |
| `ParkBrake_Unlock` | %Q49.5 | Parking brake **UNLOCK** |
| `MCU_Enable` | %Q49.6 | MRS MCU power (Enable_MRS_cabin) |
| `MainPwr_Sw` | %Q49.7 | Main power switches 1–4 (ignition "P1") |
| `Sol_Estop` | %Q0.0 | E-stop solenoid / e-brake (F-DQ 2A, both poles) |
| `Aux_Relays` | %Q0.1 | Autonomous / aux relays enable (F-DQ 2A) |

**Ignition ↔ key positions:** pos I = R · pos II (run) = R + 15/54 + DR · pos III = 15/54 + DR
· pos IV (crank) = DR + 50. Term 30 = always-on rail.

### Inputs

| Input tag | Addr | Function |
|---|---|---|
| `AutoMan_Sw1` | %I21.0 | Auto/Manual selector ch1 (closed = Auto) |
| `AutoMan_Sw2` | %I21.4 | Auto/Manual selector ch2 (dual channel) |
| `Press_Shuttle_1` | %IW7 | Shuttle (main hyd) pressure ch A (4-20 mA) |
| `Press_Estop_1` | %IW9 | E-stop hydraulic pressure ch A |
| `Press_Shuttle_2` | %IW11 | Shuttle pressure ch B (redundant) |
| `Press_Estop_2` | %IW13 | E-stop hydraulic pressure ch B (redundant) |
| `Press_Prop` | %IW35 | Proportional system pressure |
| `RemEstop_1` | %I28.0 | Remote E-stop button ch1 (**evaluated 1oo2 result**) |
| `RemEstop_2` | %I28.4 | Remote E-stop button ch2 (disabled — see §5) |
| `Rem_Ack` | %I28.1 | Remote acknowledge / fault reset |
| `Rem_Start` | %I28.2 | Remote start button |
| `Rem_Arm` | %I28.3 | Remote arm button |

All five pressure sensors are 4-20 mA, **0–400 bar**, with 0 mA = wire-break fault. Standard DQ
`%Q6.0/.1` on the remote station drive indicator LEDs.

The compute-box handshake signals (alive / turn-on / MCU-booted / engine-running / brake
releases / error-reset / re-crank) are **not physical I/O** — they arrive as Modbus holding-
register bits (§6).

---

## 4. The Startup State Machine (`FB_Sequencer`)

`FB_Sequencer` (FB3, instance `Seq_DB`) is an 18-state CASE machine (`State` 0..17). It is
called with **unconnected pins**: it reads/writes its own instance-DB, so operators drive and
monitor it directly through `Seq_DB` (or via the Modbus glue).

**Timing model.** A single `StateTimer` (`TON_TIME`, `PT := T#200S`) measures **time-in-state**.
`newState := (State <> prevState)` is true on the scan a transition occurs; the timer runs on
`IN := NOT newState`, so it **auto-resets to zero on every state change**. States compare
`StateTimer.ET` against their dwell.

**Global abort.** At the very top of the block, `IF Abort THEN State := 0;`. `Abort` is driven
by the safety program (`= NOT SafeOK`). So an e-stop or pressure trip in *any* state snaps the
sequencer back to INIT, where every `Req_*` is cleared — and, gated through `SafeOK = 0`, every
physical output de-energizes (brakes apply).

### 4.1 State table

| # | State | Actions / requests set | Exit transition | Timing |
|---|---|---|---|---|
| 0 | **INIT** | Clear **all** `Req_*` bits | `AutoMode` → 1 | — |
| 1 | **MAINPOWER** | `Req_MainPwr` (main switch / ignition "P1") | `MB_Alive` → 2 | — |
| 2 | **WAITTURNON** | (hold) | `MB_TurnOn` → 3 | — |
| 3 | **POWERMCU** | `Req_MCU` (power both MRS MCUs) | `MB_McuBooted` → 4 | — |
| 4 | **MCU_SETTLE** | — (MCU stays powered) | `ET ≥ 5s` → 5 | 5 s settle |
| 5 | **AUTONRELAYS** | `Req_AuxRelays` (autonomous relays) | `ET ≥ 5s` → 6 | 5 s settle |
| 6 | **IGNACCESSORY** | `Req_IgnR` (key pos I = R) | `ET ≥ 1s` → 7 | 1 s |
| 7 | **IGNRUN** | `Req_Ign1554`, `Req_IgnDR` (key pos II, R+15/54+DR) | `ET ≥ 3s` → 8 | 3 s glow |
| 8 | **CRANK** | drop `Req_IgnR` & `Req_Ign1554`; set `Req_Ign50` (starter, key pos IV; DR held) | `MB_EngineRunning` → 10; else `ET ≥ 10s` → 9 | 10 s crank timeout |
| 9 | **CRANKFAIL** | `Req_Ign50` off; back to run pos (`Req_IgnR`, `Req_Ign1554`); `Req_CrankFail` raised | `MB_ReCrank` → 8 (clears `Req_CrankFail`) | **no auto-retry**; waits indefinitely |
| 10 | **ENGINERUN** | run pos (`Req_IgnR`, `Req_Ign1554`); `Req_Ign50` off; `Req_PostPress` on | unconditional → 11 | — |
| 11 | **PRESSBUILD** | (hold, pressures posting) | `PressBuildOK` → 14; else `ET ≥ 20s` → 12 | 20 s build timeout |
| 12 | **PRESSFAULT** | `Req_Error` | `MB_ErrorReset` → 13 | waits for reset |
| 13 | **ENGINEOFF** | all ignition low; clear `Req_PostPress`, `Req_Error`, `Req_RunMon` | `ET ≥ 1s` → 0 | 1 s, then INIT |
| 14 | **RUNNING** | `Req_RunMon` (arms run-band monitor) | `MB_EbrakeRelease` → 15 | — |
| 15 | **EBRAKERELEASED** | `Req_EbrakeRel` (release e-stop brake first) | `MB_ParkRelease` → 16 | — |
| 16 | **PARKRELEASED** | `Req_ParkUnlock` (unlock parking brake) | unconditional → 17 | — |
| 17 | **OPERATIONAL** | (hold — fully running, brakes released) | — (terminal; only `Abort` leaves) | — |

### 4.2 Notable behaviors

- **Crank:** `PressBuildOK` is the *build* gate; `MB_EngineRunning` (from the compute box) is
  what ends CRANK. The starter (`Ign_50`) is only ever requested in state 8.
- **Crank fail is operator-driven, not automatic.** State 9 returns to the "run" ignition
  position, raises `Req_CrankFail` to the compute box, and waits indefinitely for `MB_ReCrank`.
  There is no retry counter and no timeout out of CRANKFAIL.
- **Brake release order:** e-brake (`Req_EbrakeRel`, state 15) **before** parking brake
  (`Req_ParkUnlock`, state 16). Both are compute-box-gated (`MB_EbrakeRelease`, `MB_ParkRelease`).
- **Pressure fault** (state 12) drops back through ENGINEOFF (13) to INIT (0) once the operator
  clears the error — it does not stay latched at the engine.

---

## 5. Safety Program (`Main_Safety_RTG1`, F-LAD)

Hand-built fail-safe ladder in the always-on F-runtime. It never imports from source (F-blocks
must be built click-by-click); it is the core safety infrastructure of the machine.

### 5.1 E-stop evaluation

- **`remote_estop_ok = RemEstop_1`** (`%I28.0`). The `RemoteEStop` F-DI is configured **1oo2**
  at the module, so channel 0 already carries the evaluated dual-channel result. **Do not AND in
  `RemEstop_2` (`%I28.4`)** — that second channel is disabled at the tag level; ANDing it would
  double-count the redundancy.
- **`ESTOP1`** instruction: `E_STOP ← remote_estop_ok`, `ACK_NEC = 1`, `ACK ← Rem_Ack`,
  `TIME_DEL = 0`, `Q → estop_safe`. Because `ACK_NEC = 1`, after any trip the e-stop stays
  latched safe until the operator presses `Rem_Ack` — no auto-restart.

### 5.2 `SafeOK` composition

```
SafeOK = estop_safe  AND  NOT PressData.PressTrip
```

`SafeOK` is the single machine permissive. It is TRUE only when the remote e-stop is clear
(and acknowledged) **and** the run-band pressure monitor has not tripped.

### 5.3 Output gating

Every real F-output is recomputed each F-cycle from a request bit ANDed with `SafeOK`:

| F-output | Gate expression |
|---|---|
| `MainPwr_Sw` | `Req_MainPwr AND SafeOK` |
| `MCU_Enable` | `Req_MCU AND SafeOK` |
| `Aux_Relays` | `Req_AuxRelays AND SafeOK` |
| `Ign_R` | `Req_IgnR AND SafeOK` |
| `Ign_15_54` | `Req_Ign1554 AND SafeOK` |
| `Ign_DR` | `Req_IgnDR AND SafeOK` |
| `Ign_50` | `Req_Ign50 AND SafeOK` |
| `ParkBrake_Unlock` | `Req_ParkUnlock AND SafeOK` |
| `ParkBrake_Lock` | `NOT (Req_ParkUnlock AND SafeOK)` — via a NOT element (see below) |
| `Sol_Estop` (e-brake) | `Req_EbrakeRel AND SafeOK` |

Because gating is unconditional and re-evaluated every F-cycle, `SafeOK` dropping to 0 forces
**all** of these low simultaneously — regardless of what the sequencer requests.

### 5.4 Fail-safe brake logic

Both brakes are **fail-safe applied**:

- **Parking brake:** `ParkBrake_Lock` is the *complement* of the unlock permissive. F-programs
  **cannot read the process image of outputs (`%Q`)**, so lock is not read back from unlock — it
  is **recomputed from the same inputs** through a NOT element:
  `ParkBrake_Lock = NOT (Req_ParkUnlock AND SafeOK)`. Any loss of `SafeOK` (or the request)
  immediately re-locks the park brake.
- **E-stop brake:** `Sol_Estop = Req_EbrakeRel AND SafeOK`. On trip it de-energizes and the brake
  applies.

De-energized = braked, so wire break, passivation, or CPU stop all leave the machine braked.

### 5.5 Abort and Auto-mode hand-back into the standard program

- **`Seq_DB.Abort = NOT SafeOK`** — the F-program writes the sequencer's abort input, snapping it
  to INIT on any trip.
- **`Seq_DB.AutoMode = AutoMan_Sw1 AND SafeOK`** — the sequencer can only start when the
  Auto/Manual switch is in Auto *and* the safety chain is healthy.

### 5.6 Passivation / reintegration (`ACK_GL`)

F-I/O powers up **passivated** (substitute value 0, `QBAD` set) and must be reintegrated.
`ACK_GL` (global acknowledge) is wired `ACK_GLOB ← Rem_Ack`, so a single press of the remote
acknowledge both reintegrates passivated F-I/O and (via `ESTOP1.ACK`) re-arms the e-stop after
a trip.

### 5.7 Pressure trip fold-in

`FB_PressMon` (standard program) computes `PressData.PressTrip`; the F-program reads it and folds
it into `SafeOK` (§5.2). This lets a *standard-computed* analog condition contribute to the safe
state through the single gate, without the F-program itself doing floating-point scaling.

---

## 6. Pressure Monitoring

Two standard-program stages: **scaling + build check** (`FC_Pressure`) and the **run-band safety
monitor** (`FB_PressMon`). Both operate on the shared `PressData` DB.

### 6.1 Scaling & build check (`FC_Pressure`)

For each of the five sensors:

```
bar = INT_TO_REAL(raw) * 400.0 / 27648.0        // 0..27648 counts = 0..400 bar
fault = (raw < -1000)                             // 0 mA / wire-break: raw well below 4 mA zero
```

`PressBuildOK` (written to both `PressData` and `Seq_DB`) is TRUE only when **all five** sensors
are healthy **and ≥ 120 bar**:

```
PressBuildOK = for each sensor:  (NOT fault) AND (bar >= 120.0)
```

This is what releases state 11 (PRESSBUILD) → 14 (RUNNING). Any single unhealthy or low sensor
holds the build and, after 20 s, drops to PRESSFAULT.

### 6.2 Run-band monitor (`FB_PressMon`)

Active **only while `Seq_DB.Req_RunMon` is set** (state 14 onward). Enforces a 120–150 bar
working band with graded trips:

| Condition | Threshold | Action |
|---|---|---|
| **Soft** — any sensor outside band | `< 120` or `> 150` bar, held **≥ 3 s** | trip (via 3 s `softTimer`) |
| **Hard** — any sensor > 5% outside band | `< 112.5` or `> 157.5` bar | **immediate** trip |
| **Fault** — any sensor 0 mA / wire-break | `fault` flag set | **immediate** trip |

On trip, `tripLatch` is set and **latched** into `PressData.PressTrip` until cleared by
`Seq_DB.MB_ErrorReset`. `PressTrip` feeds the `SafeOK` gate (NC — `SafeOK = … AND NOT PressTrip`),
so a run-band excursion drops `SafeOK`, aborts the sequencer, and applies the brakes.

> The soft 3 s tolerance absorbs transient pressure ripple; the hard ±5% and wire-break paths are
> immediate. Note the FB header comment references `State >= 13`; the implemented gate is
> `Req_RunMon` (set at state 14). Treat `Req_RunMon` as authoritative.

---

## 7. Modbus TCP Interface

The PLC is the **Modbus server (`MB_SERVER`)**. The compute box is the client. All exchange is
through the `ModbusData` DB (`hold : Array[0..9] of Word`, **non-optimized access** so the byte
layout is stable for Modbus). `FC_ModbusIn` runs before the sequencer; `FC_ModbusOut` after.

### 7.1 Holding-register map

| Reg | Dir (from compute box) | Contents |
|---|---|---|
| **HR0** | WRITE | Command word — see bit table below |
| **HR1** | READ | Status word — see bit table below |
| **HR2** | READ | `State` (0..17) |
| **HR3** | READ | `Shuttle1_bar × 10` |
| **HR4** | READ | `Estop1_bar × 10` |
| **HR5** | READ | `Shuttle2_bar × 10` |
| **HR6** | READ | `Estop2_bar × 10` |
| **HR7** | READ | `Prop_bar × 10` |

**HR0 — command bits** (compute box writes → `Seq_DB.MB_*`):

| Bit | Name | Sequencer input |
|---|---|---|
| 0 | Alive | `MB_Alive` |
| 1 | TurnOn | `MB_TurnOn` |
| 2 | McuBooted | `MB_McuBooted` |
| 3 | EngineRunning | `MB_EngineRunning` |
| 4 | ParkRelease | `MB_ParkRelease` |
| 5 | EbrakeRelease | `MB_EbrakeRelease` |
| 6 | ErrorReset | `MB_ErrorReset` |
| 7 | ReCrank | `MB_ReCrank` |

**HR1 — status bits** (compute box reads):

| Bit | Name | Source |
|---|---|---|
| 0 | Error | `Seq_DB.Req_Error` |
| 1 | CrankFail | `Seq_DB.Req_CrankFail` |
| 2 | PostPress | `Seq_DB.Req_PostPress` |
| 3 | PressTrip | `PressData.PressTrip` |

Pressures are transmitted as tenths of a bar (`bar × 10`), i.e. HR value 1234 = 123.4 bar.

### 7.2 Compute-box simulator (`computebox_sim.py`)

`/Users/alexandersteffen/Documents/PLC-Course/computebox_sim.py` is a `pymodbus` TCP **client**
that stands in for the real compute box from a MacBook.

- **Setup:** `pip install pymodbus`
- **Run:** `python3 computebox_sim.py <PLC_IP>` (default `10.90.11.200`, port 502)
- **Prompt commands:** `alive`, `turnon`, `mcubooted`, `running`, `parkrel`, `ebrakerel`,
  `errreset`, `recrank` (each toggles its HR0 bit and writes the word); `status` reads back
  HR1..HR7 and decodes state/flags/pressures; `cmd` shows the local command word; `clear`
  zeroes all bits; `quit`.

It maintains a local mirror of HR0 and rewrites the whole register on each toggle. A typical
happy-path walk: `alive` → `turnon` → `mcubooted` → (auto ignition/glow) → `running` →
(pressure build) → `ebrakerel` → `parkrel`, checking `status` between steps to watch `State`
climb 0 → 17.

> The compute box's Modbus TCP is generally **not reachable in PLCSIM** — the simulator is a
> **real-hardware** tool. In sim, exercise the same paths by modifying `ModbusData.hold` directly.

---

## 8. Commissioning & Testing

### 8.1 What is sim-testable (standard side)

The entire standard program is validatable in PLCSIM V20 with **no F-hardware**:

- **Sequencer:** open `Seq_DB` → Monitor → modify `MB_*` inputs and `AutoMode`/`Abort`; watch
  `State` walk 0 → 17 and the `Req_*` bits latch/clear per §4. (Verified: `State` walks the full
  chain.)
- **Pressure:** modify the raw `Press_*` inputs to exercise `FC_Pressure` scaling, `PressBuildOK`
  (all-5-≥120), and `FB_PressMon` run-band trips (soft/hard/fault).
- **Modbus glue:** modify `ModbusData.hold[0]` bits to drive commands and read back
  `hold[1..7]`; equivalent to the compute box without a live TCP link.

Because SimView checkbox modifies sometimes don't apply, prefer a **TIA Watch table** (add the
`%M`/DB rows, Monitor all, right-click → Modify → Modify to 1) for reliable stimulus.

### 8.2 What requires real F-hardware (safety side) — PLCSIM limitation

**Standard S7-PLCSIM keeps safety mode PERMANENTLY ACTIVATED.** The "Disable safety mode" button
stays greyed even with offline=online consistency, a safety password set, and the CPU in RUN.
Consequences (a confirmed dead end — do not re-fight):

- You **cannot force or modify F-tags** in the sim ("Debugging of fail-safe tags is not allowed
  in permanent safety mode").
- Passivated F-I/O **cannot be reintegrated** in sim: the `ACK` is itself an F-input that is
  passivated → circular.

Therefore the live F **happy path** — reintegrate → `estop_safe = 1` → outputs follow requests →
e-stop drops → outputs collapse — can only be validated on a **real F-CPU**.

**What the sim *does* prove:** the safety program holds the correct **safe state**. With F-I/O
passivated, `SafeOK = 0` → `Abort = 1`, `ParkBrake_Lock = 1`, and all ignition/MCU outputs OFF.
That is exactly the intended fail-safe behavior.

### 8.3 Hardware bring-up checklist

1. Set/confirm the **safety password** on the project (required for any safety download).
2. Confirm CPU access level = "Full access (no protection)"; disable "Protection of confidential
   PLC configuration data" (else the CPU-common download aborts).
3. Download standard + safety programs.
4. On power-up, F-I/O comes up **passivated** (expect `QBAD`). Press **`Rem_Ack`** → `ACK_GL`
   reintegrates the F-I/O and `ESTOP1.ACK` re-arms the e-stop.
5. Verify `estop_safe = 1`, then `SafeOK = 1` (pressures healthy).
6. Walk the sequence from the compute box / `computebox_sim.py`; verify each `Req_*` produces its
   gated F-output and that the ignition/crank timing matches §4.
7. **E-stop test in multiple states:** press remote e-stop mid-sequence and at OPERATIONAL;
   confirm immediate output collapse, both brakes apply, and the sequencer returns to INIT.
8. **Run-band test:** with the engine running, drive a pressure out of band and confirm the
   soft (3 s) / hard (±5%) / wire-break trips latch `PressTrip` and require `errreset`.

---

## 9. Open Items & Assumptions to Confirm

| # | Item | Current state / assumption | Confirm |
|---|---|---|---|
| 1 | **Ignition dwell times** | IGNACCESSORY 1 s, IGNRUN glow 3 s, MCU/auton settles 5 s each | Validate against the real engine's glow-plug and MCU boot timing; placeholders per earlier notes (0.5/1/2 s) were superseded by the values in `FB_Sequencer`. |
| 2 | **PressBuildOK quorum** | Requires **all 5** sensors ≥ 120 bar | Confirm whether a subset (e.g., shuttle + prop only) is the real intent — e-stop-line sensors may read differently. |
| 3 | **Brake release order** | E-brake (15) then park brake (16) | Confirm this is the desired mechanical sequence. |
| 4 | **"Ignition P1" mapping** | `MainPwr_Sw` (%Q49.7) = ignition "P1" | Verify against machine documentation. |
| 5 | **`FB_PressMon` active gate** | Header says `State >= 13`; code uses `Req_RunMon` (state 14) | Align comment to code; `Req_RunMon` is authoritative. |
| 6 | **OB1 call order** | On-box `Main` shows only `FC_Pressure` + `Seq_DB`; Modbus glue + `FB_PressMon` must be inserted per §2.1 | Confirm the final OB1 wiring on the live project. |
| 7 | **Real Modbus block** | `MB_SERVER` instance + connection params not yet in the reviewed sources | Configure and commission the actual `MB_SERVER` on the CPU. |
| 8 | **`Press_Prop` address** | %IW35 taken from the old tag table (F-AI Pressure probe was truncated) | Re-probe to confirm. |
| 9 | **Legacy blocks** | GRAPH `FB_Startup` (FB2) + `Startup_DB` superseded by the SCL sequencer | Delete to avoid confusion. |
| 10 | **HR2 state range** | Register-map comments say "State (0..16)"; the machine now has 18 states (0..17) | Cosmetic — update the DB/simulator comments to 0..17. |

---

*Source-of-truth files: `volvo_l60h_IO_map.md` (I/O), `FB_Sequencer.scl` (state machine),
`FC_Pressure.scl` + `pressure_trip.scl` (pressure), `modbus.scl` (register map),
`computebox_sim.py` (simulator), and the `tia-plc-learning` build log.*
