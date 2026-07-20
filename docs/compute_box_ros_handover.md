# Compute Box ↔ PLC — ROS Node Handover

**Target:** the ROS node on the compute box that owns the Modbus TCP connection to the
Volvo L60H autonomous engine‑start PLC.
**Scope:** this is the complete interface contract — connection, register map, the PLC
state machine, the command handshake you must drive, timing, and safety constraints.
You do **not** need the PLC code; everything required is here.

Reference behaviour lives in `computebox_sim.py` (REPL) and `computebox_gui.py`
(Tkinter dashboard) — both are Modbus clients that already speak this protocol correctly.
Mirror their command‑gating logic.

---

## 1. Roles & topology

- **PLC** — Siemens ET 200SP **CPU 1510SP F‑1 PN** (fail‑safe). Runs the 18‑state
  engine‑start sequencer *and* an F‑safety program that gates every physical output as
  `output = Req_x AND SafeOK`. It is the Modbus **server**.
- **Compute box (you)** — Modbus TCP **client / master**. You initiate *every* transaction;
  the PLC only responds. You issue **requests** (command bits) and read back status; the PLC
  decides what actually happens.
- **You have no safety authority.** The remote E‑stop, the 1oo2 estop evaluation, F‑I/O
  passivation/reintegration, and the `SafeOK` gate are all in hardware + the F‑program.
  Modbus commands are *requests only* — the safety program can and will veto them.
- **Network** — compute box → **Blitzfunk wireless** → PLC. Expect latency, jitter, and
  occasional dropouts. Design for reconnection.

---

## 2. Connection

| Item | Value |
|---|---|
| Protocol | Modbus **TCP** |
| PLC IP | `10.90.11.200` |
| Port | `502` |
| Unit / slave ID | `1` (default; the PLC `MB_SERVER` answers) |
| Data model | **Holding registers only** — no coils, no input registers |
| Function codes | `0x03` Read Holding Registers, `0x06` Write Single Register (optionally `0x10` Write Multiple) |
| Suggested poll rate | 5–10 Hz (100–200 ms). Reference GUI uses 400 ms. Don't hammer it. |

The entire interface is the DB array `ModbusData.hold[0..9]` = holding registers HR0–HR9.

---

## 3. Register map

### HR0 — command word — **you WRITE → PLC reads**
One 16‑bit register, bit‑packed. Write the whole word (`0x06` to address 0) on any change.

| Bit | Name | Meaning |
|---|---|---|
| 0 | `alive` | compute box alive / heartbeat present |
| 1 | `turnon` | operator/mission "turn on" request |
| 2 | `mcubooted` | both MRS MCUs booted & ready |
| 3 | `running` | engine confirmed running (stops the starter) |
| 4 | `parkrel` | release parking brake |
| 5 | `ebrakerel` | release e‑stop brake |
| 6 | `errreset` | reset error / clear latched pressure trip |
| 7 | `recrank` | re‑attempt crank (from CRANKFAIL) |
| 8 | `start` | **deliberate go‑ahead to begin ignition/crank** (momentary; only acted on at State 5) |

### HR1–HR7 — telemetry — **PLC WRITES → you read**

| Reg | Field | Meaning |
|---|---|---|
| HR1.0 | `Error` | sequencer in PRESSFAULT |
| HR1.1 | `CrankFail` | sequencer in CRANKFAIL |
| HR1.2 | `PostPress` | engine running, pressures being posted |
| HR1.3 | `PressTrip` | run‑band pressure trip **latched** |
| HR2 | `State` | current sequencer state, `0..17` (see §5) |
| HR3 | `Shuttle1` | pressure, **bar × 10** (int) |
| HR4 | `Estop1` | pressure, bar × 10 |
| HR5 | `Shuttle2` | pressure, bar × 10 |
| HR6 | `Estop2` | pressure, bar × 10 |
| HR7 | `Prop` | pressure, bar × 10 |
| HR8 | heartbeat | **you WRITE** — increment & write every cycle; `FB_CommWatch` trips `CommLost`→`SafeOK` if it stops changing (see §8) |
| HR9 | — | reserved / unused |

**Pressure scaling:** value ÷ 10 = bar. Sensors are 4–20 mA, **0–400 bar** full scale
(4 mA = 0 bar). So HR value `1234` = `123.4 bar`. Working band is **120–150 bar**.

---

## 4. Command semantics — level vs pulse

| Type | Bits | How to send |
|---|---|---|
| **Level** (set and hold) | `alive`, `turnon`, `mcubooted`, `running`, `parkrel`, `ebrakerel` | set the bit and leave it set for the rest of the run |
| **Momentary pulse** | `recrank`, `errreset`, `start` | set the bit, write, wait ~300–400 ms, clear the bit, write |

Why pulses matter: `recrank` held would auto‑retry cranking forever (defeats the "no
auto‑retry" design); `errreset` held would prevent a new trip from ever latching; `start`
is pulsed so a held bit can't auto‑crank on the next pass through State 5 (e.g. after an
abort). **Pulse them, don't hold them.**

Maintain a local mirror of HR0, mutate the relevant bit, write the whole word.

---

## 5. The PLC state machine (HR2) & the handshake you drive

The sequencer only leaves certain states when **you** send the right command; the rest
advance on their **own internal timers**. Your job is to drive the command‑gated
transitions and watch the automatic ones.

| State | Name | What the machine is doing | **Your action** |
|---|---|---|---|
| 0 | INIT | idle | **none** — see "AutoMode gate" below |
| 1 | MAINPOWER | main power / P1 on | send **`alive`** |
| 2 | WAITTURNON | alive received | send **`turnon`** |
| 3 | POWERMCU | MCUs powered | send **`mcubooted`** |
| 4 | MCU_SETTLE | MCUs settle (5 s) | *auto* |
| 5 | AUTONRELAYS | autonomous relays on, **powered & ready — HOLDS here** | pulse **`start`** ⚠️ commit point — begins ignition/crank |
| 6 | IGNACCESSORY | ignition pos I (1 s) | *auto* |
| 7 | IGNRUN | ignition pos II + glow (3 s) | *auto* |
| 8 | CRANK | **starter cranking** (≤10 s) | send **`running`** the instant the engine catches |
| 9 | CRANKFAIL | crank timed out, starter off | pulse **`recrank`** to retry — **or** send **`running`** if the engine is actually turning (see reboot note) |
| 10 | ENGINERUN | engine running, posting pressures | *auto* → 11 |
| 11 | PRESSBUILD | waiting for pressure ≥120 bar (≤20 s) | *auto* → 14 on success |
| 12 | PRESSFAULT | pressure didn't build | pulse **`errreset`** (→ engine off → INIT) |
| 13 | ENGINEOFF | ignition off | *auto* → 0 |
| 14 | RUNNING | engine OK, **run‑band monitor active** | send **`ebrakerel`** |
| 15 | EBRAKERELEASED | e‑brake released | send **`parkrel`** |
| 16 | PARKRELEASED | park brake released | *auto* → 17 |
| 17 | OPERATIONAL | fully running, brakes released | done |

**AutoMode gate (why you can't start from INIT):** State `0 → 1` is *not* a Modbus
transition. It requires the hardware **AutoMan switch in Auto** *and* **`SafeOK = 1`**
(remote E‑stop released **and** acknowledged via the hardware `Rem_Ack` button). Until an
operator arms the machine, State stays `0` and `alive` does nothing. Your node should
**wait for `State ≥ 1`** before beginning the handshake, and surface "waiting for operator
to arm (Auto + E‑stop ack)" while it's stuck at 0.

**⚠️ The `start` commit point:** `mcubooted` only powers the MCUs and advances to **State 5**,
where the machine **holds** — everything is powered and ready but the engine is *not* started.
Nothing happens until you pulse **`start`**. Once you do, states 6→7 run on internal timers
(~**4 s**) and then **the starter fires (State 8) with no further pause** — the engine
physically cranks and starts. Only pulse `start` when it is genuinely safe to start the engine.
`start` is momentary, so it must be freshly pulsed each time the sequence reaches State 5
(it will never auto‑crank on a stale bit after an abort).

---

## 6. Mapping command bits to real compute‑box signals

These are *requests reflecting real conditions* — don't just fire them blindly:

| Bit | Should reflect |
|---|---|
| `alive` | your node is up and healthy (set once, keep set; it's your presence signal) |
| `turnon` | mission/operator "start the machine" command |
| `mcubooted` | both MRS MCUs have actually booted & report ready (you monitor them; they boot when powered at State 3) |
| `start` | **deliberate decision to start the engine** — mission/operator confirms it's safe to crank. This is the commit point; gate it behind whatever go/no‑go logic the mission requires. |
| `running` | **real engine‑running detection** — RPM above threshold from the engine ECU / CAN / tach. This is the signal that stops cranking; sourcing it correctly is critical. |
| `ebrakerel` / `parkrel` | mission logic decides the machine may be released to drive |
| `errreset` | operator/auto acknowledge to clear a fault |
| `recrank` | operator/auto decision to retry a failed crank |

---

## 7. Timing & timeouts (the PLC enforces these)

| Phase | Limit | On expiry |
|---|---|---|
| MCU settle → State 5 | ~5 s fixed | then **HOLDS at State 5 for `start`** (no timeout) |
| `start` → crank cascade | ~4 s fixed | proceeds to CRANK automatically once `start` is pulsed |
| CRANK | 10 s | → CRANKFAIL (9) if no `running` |
| PRESSBUILD | 20 s | → PRESSFAULT (12) if pressures don't reach 120 bar |
| Run‑band soft out‑of‑band | 3 s | trip (only while State ≥14) |
| Run‑band hard (>5% out) / wire‑break | immediate | trip |

Send `running` **promptly** when the engine catches — if you're slower than the 10 s crank
window the PLC drops to CRANKFAIL even though the engine is actually running.

---

## 8. Safety — read this section

- **You have no safety authority.** Every output is gated by the F‑program's `SafeOK`. A
  remote E‑stop, a pressure trip, or an F‑I/O fault sets `SafeOK = 0`, which **snaps State
  to 0 and drives all outputs safe** (brakes engage, ignition/starter cut) regardless of
  what you're commanding.
- **You will observe trips, not cause or clear the hardware side.** When `SafeOK` drops you
  see `State → 0` and status bits change. React by resetting your command sequence back to
  the start; don't keep asserting stale bits.
- **Reintegration is a hardware action.** After an E‑stop or F‑I/O passivation, an operator
  must press the hardware `Rem_Ack` button to reintegrate. You cannot do this over Modbus.
- **`errreset` (Modbus) clears *latched software faults*** — PRESSFAULT and the latched
  `PressTrip` — but only if the underlying condition is gone. It does **not** reintegrate
  passivated F‑I/O.
- **The engine physically starts.** Treat **`start`** (not `mcubooted`) as the commit to cranking — `mcubooted` only powers the MCUs and parks at State 5; `start` is what fires the ignition/crank cascade.

### Heartbeat watchdog — IMPLEMENTED (`FB_CommWatch`)
The PLC runs a comms watchdog. **You MUST increment `HR8` and write it every cycle.**
`FB_CommWatch` watches `HR8`: if the counter stops changing for longer than the timeout it
sets `CommLost`, folded into `SafeOK` (`SafeOK = estop_safe AND NOT PressTrip AND NOT
CommLost`). So a dead node / dropped link during operation **brings the machine to a safe
stop** (engine cut, brakes engaged, State→0).

- **Armed ONLY during RUNNING (State ≥14).** During startup/crank (States 0–13) a heartbeat
  gap does **not** trip — this deliberately tolerates a **compute‑box brown‑out reboot during
  cranking** (voltage sag). It's safe because without you the sequence just stalls or
  crank‑fails; there's no runaway. The watchdog guards *autonomous operation*, which is the
  only place a dead brain is dangerous.
- **Timeout:** currently **10 s** (commissioning). Scheduled to drop to **3 s** for production.
  Once at State ≥14, don't stop heartbeating longer than this or you'll trip a safe stop.
- **Auto‑recover:** `CommLost` clears the instant the heartbeat resumes — no `errreset` needed.
  Afterwards the machine is parked at INIT (anti‑auto‑restart guard), so a deliberate `turnon`
  re‑issue is required to start again.
- **Consequence for your loop:** keep the `HR8` write on a reliable periodic path (it only
  *matters* once RUNNING). Also still **fail safe** on loss of your own engine‑running / MCU
  inputs.

*Note: like `PressTrip`, this is a standard‑program safe stop folded into `SafeOK` — a
functional safe stop, not a SIL‑rated safety function. The certified safety remains the
hardwired remote E‑stop.*

---

## 9. Error & recovery flows

| Situation | HR indication | Your response |
|---|---|---|
| Crank timed out | State 9, HR1.1 `CrankFail` | pulse `recrank` to retry — **but first check engine RPM: if it's actually running (you rebooted during crank and missed the `running` window), send `running` instead** → State 9→10, avoiding re‑cranking a live engine |
| Pressure didn't build | State 12, HR1.0 `Error` | pulse `errreset` → engine off → INIT |
| Run‑band trip while running | HR1.3 `PressTrip` (+ State → 0) | fix the pressure condition, pulse `errreset`; operator `Rem_Ack` if F‑I/O passivated |
| Modbus timeout / link drop | read fails | transactions are stateless — on reconnect **re‑read HR2 and resume from the *actual* PLC state**, never assume; hold your command word meanwhile |

---

## 10. Suggested ROS node design

- **Modbus client** — `pymodbus` `ModbusTcpClient("10.90.11.200", port=502)`. Wrap read/write
  with reconnect + timeout handling.
- **Periodic loop (5–10 Hz):**
  1. Read HR0–HR7 (`read_holding_registers(0, count=8)`).
  2. Publish telemetry topics.
  3. **Increment and write the heartbeat** (`self.hb = (self.hb+1) & 0xFFFF; write_register(8, self.hb)`) — every cycle, mandatory (see §8).
  4. Compute the command word from current PLC state + your mission/engine inputs.
  5. Write HR0 (`write_register(0, cmd)`) if changed.
- **State‑aware command layer** — mirror `cmd_valid(state)` from the reference clients:
  only assert a command in the state where it's valid, so you never send a nonsensical bit.
- **Suggested topics:**
  - publish `~/plc/state` (int + name), `~/plc/status` (Error/CrankFail/PostPress/PressTrip),
    `~/plc/pressures` (5 × bar), `~/plc/connected` (bool)
  - subscribe / services: `turnon`, `start` (begin ignition/crank), `release` (ebrake+park), `error_reset`, `recrank`
  - inputs the node consumes: engine RPM (→ `running`), MCU ready (→ `mcubooted`), go/no‑go to crank (→ `start`)
- **Bootstrap rule:** don't send `alive` until `State ≥ 1`; surface the "waiting for operator
  to arm" condition when stuck at State 0.
- **Pulse helper:** for `recrank`/`errreset`/`start`, set bit → write → schedule clear ~400 ms later.

---

## 11. Open items / caveats to confirm with the PLC owner

1. **Heartbeat watchdog — DONE** (see §8). `FB_CommWatch` trips `CommLost`→`SafeOK` if `HR8`
   stalls. Timeout is **10 s** for commissioning, **→ change to 3 s for production.** Your node
   must write `HR8` every cycle.
2. **Pressbuild timeout is an *error*, not a *trip*** — currently PRESSFAULT waits for
   `errreset` and idles the engine; a change to make it a hard trip is under discussion.
3. **Pressure gating** — all 5 sensors must be ≥120 bar to pass PRESSBUILD. Whether the
   e‑stop‑brake‑line sensors (`Estop1`/`Estop2`) can physically reach 120 bar *before* the
   brakes are released is still being confirmed; the build check may get narrowed to the
   shuttle/system sensors.
4. **Pressure scaling** assumes 0–400 bar = 4–20 mA. Confirm the transmitter range.
5. **HR8 = heartbeat** (now in use, see §8); **HR9 reserved** — coordinate before using.
6. **Reference clients** (`computebox_sim.py`, `computebox_gui.py`) are the ground truth for
   command gating and register handling — read them.

---

*Interface owner: PLC project `volvo_l60h_alex_pressuresremoved` (TIA V20). Register map =
`ModbusData` DB + `FC_ModbusIn`/`FC_ModbusOut`. This doc reflects the PLC as deployed at
handover; verify HR2 state names and the open items above against the live project.*
