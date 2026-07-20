# volvo_l60h — PLC Commissioning Test Plan

Work top‑to‑bottom: each phase is **less risky than the next**, and later phases assume the
earlier ones passed. **Keep the remote E‑stop in hand for every live phase.**

Legend: `[ ]` = to do · **PASS =** the condition that proves it works.

---

## Phase 0 — Pre‑flight (do every session)
- [ ] `Seq_DB.SimMode = FALSE` (watch table). **PASS =** FALSE. *(SimMode bypasses safety + pressure — must be off.)*
- [ ] CPU in **RUN**, no SF/MAINT LED, diagnostic buffer clean.
- [ ] Compute‑box GUI running, **`ModbusData.hold[8]` incrementing** (heartbeat alive).
- [ ] Watch table loaded: `State, SafeOK, estop_safe, AutoMode, Abort, PressTrip, CommLost, ShuttleBuildOK, ShuttleLowErr`, all 5 `Press_*_bar`, all `Req_*`, the outputs (`Ign_*, MCU_Enable, MainPwr_Sw, ParkBrake_*, Sol_Estop*`), `RemEstop_1/2, Rem_Ack, AutoMan_Sw1`.
- [ ] **Machine movement state known & recorded** — is the e‑stop brake release path connected or disconnected right now? (Determines whether Phase 6 can move the machine.)

---

## Phase 1 — Safety chain (no engine)
Goal: prove the E‑stop veto, reintegration, AutoMode gating, and anti‑restart guard.
- [ ] **Reintegrate:** E‑stop released → press `Rem_Ack`. **PASS =** `estop_safe → 1`, `SafeOK → 1`.
- [ ] **AutoMode:** AutoMan switch → Auto. **PASS =** `AutoMode → 1`, `State 0 → 1`.
- [ ] **E‑stop drops everything:** at State 1 (or 3), press E‑stop. **PASS =** `SafeOK → 0`, `Abort → 1`, `State → 0`, and outputs go safe (`MainPwr_Sw/MCU_Enable → 0`, `ParkBrake_Lock → 1`, `Sol_Estop*/Ign_* → 0`).
- [ ] **Recovery:** release E‑stop (`estop_safe` stays 0) → `Rem_Ack`. **PASS =** `estop_safe/SafeOK → 1`.
- [ ] **Anti‑restart guard:** with `turnon` still asserted, clear the E‑stop. **PASS =** machine **holds at State 0** (does NOT auto‑march to crank). Drop `turnon` + re‑send → it starts. *(`turnOnSeenLow` guard.)*

---

## Phase 2 — Comm watchdog (no engine)
- [ ] **Watchdog does NOT arm before RUNNING:** at State 3 (or any state <14), **close the GUI**. **PASS =** **no** `CommLost`, sequence just holds (tolerates a crank‑phase reboot).
- [ ] **Watchdog arms at RUNNING:** get to **State ≥14**, heartbeat running, then **close the GUI**. **PASS =** after **~10 s**, `CommLost → 1`, `SafeOK → 0`, `State → 0`, outputs safe.
- [ ] **Relaunch GUI.** **PASS =** heartbeat resumes → `CommLost → 0` **auto‑recovers**, `SafeOK → 1`. Machine parked at INIT until a fresh `turnon`.
- [ ] Reminder: **change `FB_CommWatch.Timeout` 10 s → 3 s before production.**

---

## Phase 3 — Dry handshake to State 3 (no crank)
Goal: prove power/MCU outputs and F‑RQ readbacks with the engine untouched.
- [ ] `CLEAR ALL`, then `alive` → **State 2**, `turnon` → **State 3**.
- [ ] **PASS =** `MainPwr_Sw` (%Q49.7) and `MCU_Enable` (%Q49.6) both TRUE; measure ~24 V at the F‑DQ terminals; **F‑RQ MAIN SWITCH + MCU PWR relays close** (continuity / MCU rail live now that the 24 V source is fixed).
- [ ] **F‑RQ readback:** confirm **no passivation / discrepancy** on slots 7–14 in the diagnostic buffer.
- [ ] **Hold here** — do NOT send `mcubooted`.

---

## Phase 4 — Ignition + crank (⚠️ LIVE ENGINE)
Safety gate: area clear of people/moving parts, exhaust ventilated, fire extinguisher near, E‑stop in hand.
- [ ] Send `mcubooted` → State 4 (settle) → **State 5 AUTONRELAYS** → `Aux_Relays` (%Q0.3).
- [ ] **START gate:** confirm it **HOLDS at State 5** — does NOT auto‑advance to ignition. **PASS =** State stays 5 until you send **`start`**. *(No auto‑crank on MCU‑boot alone.)*
- [ ] Send **`start`** → ignition cascade begins:
  - [ ] State 6 IGNACCESSORY → `Ign_30` (%Q0.2) + `Ign_R` (%Q49.0)
  - [ ] State 7 IGNRUN → `Ign_15_54` (%Q49.1) + `Ign_DR` (%Q49.2) glow
  - [ ] State 8 CRANK → `Ign_50` (%Q49.3) fires the starter; `Ign_R`/`Ign_15_54` drop
- [ ] **PASS =** engine cranks; the instant it catches, send `running` → **State 10**.
- [ ] **Crank‑fail path:** if no catch in 10 s → **State 9 CRANKFAIL** (`Ign_50` off). Send `recrank` → back to State 8. **PASS =** it retries only on command (no auto‑retry).
- [ ] **Reboot‑recovery path:** at State 9, send **`running`** (simulating a box that rebooted mid‑crank with the engine already turning). **PASS =** jumps to **State 10** (no re‑crank).
- [ ] Confirm **no F‑DQ 2A brownout / passivation** during crank (the earlier failure mode).

---

## Phase 5 — Pressure build + run monitor (⚠️ LIVE)
Use a **loop calibrator (mA)** on a sensor channel for controllable tests.
- [ ] **Build OK:** shuttles reach ≥40 bar within 10 s, Estop/Prop ≥120 within 20 s. **PASS =** `PressBuildOK → 1`, **State 11 → 14**.
- [ ] **Shuttle build fail:** hold a shuttle < 40 past 10 s. **PASS =** **State → 12 PRESSFAULT** at 10 s, `Req_Error`. `errreset` → ENGINEOFF → INIT.
- [ ] **Shuttle > 90 (running):** inject > 90 bar. **PASS =** **instant** `PressTrip`, `SafeOK → 0`, `State → 0`.
- [ ] **Shuttle < 30 for 5 s (running):** inject < 30. **PASS =** after 5 s → **State 12**, **brakes re‑engage** (`Req_EbrakeRel → 0`, `ParkBrake_Lock → 1`).
- [ ] **Estop/Prop band:** out of 120–150 held 3 s → trip; **> 5 %** (<112.5 / >157.5) → immediate trip; **wire‑break** → immediate trip.
- [ ] **Lost sensor while running:** disconnect a sensor. **PASS =** immediate trip (fault or 0‑bar hard‑out), latched until `errreset`.

---

## Phase 6 — Brake release + operational (⚠️ MACHINE CAN MOVE)
Safety gate: **wheels chocked / clear roll path**, drive path safe — releasing brakes can let it move.
- [ ] State 14 → `ebrakerel` → **State 15**. **PASS =** `Sol_Estop` + `Sol_Estop_2` energize (both e‑brake solenoids release).
- [ ] State 15 → `parkrel` → **State 16 → 17 OPERATIONAL**. **PASS =** `ParkBrake_Unlock`, park released.
- [ ] **E‑stop while OPERATIONAL:** press it. **PASS =** all brakes **re‑engage** (`Sol_Estop*` de‑energize, `ParkBrake_Lock`), `State → 0`.

---

## Phase 7 — Modbus interface
- [ ] Command bits `HR0.0–.7` each drive the right `Seq_DB.MB_*`.
- [ ] Telemetry: `HR1` status bits, `HR2` State, `HR3–7` pressures = watch‑table values.
- [ ] **Pressure clamp:** at rest, no sensor shows the 6553.5 wrap (all ≥ 0).
- [ ] Heartbeat `HR8` increments continuously.

---

## Phase 8 — Production readiness
- [ ] `SimMode = FALSE` (baked into DB start value, survives power‑cycle).
- [ ] `FB_CommWatch.Timeout` → **3 s**.
- [ ] `ModbusData.hold[0]` start value = 0 (no phantom command bits).
- [ ] Orphan tags removed (`LED_1/2`, `Tag_1…9`) — optional.
- [ ] F‑collective signature recorded; safety program **consistent**; final download done.

---

## Known pending / open decisions
- [x] **Compute‑box‑power‑first change** — DONE. Compute box is powered by **`Ign_DR`** (control‑power rail, %Q49.2); `Req_IgnDR` now energizes at **State 1** so the box boots before the `alive` gate. *(Verify in Phase 3: `Ign_DR` on at State 1.)*
- [x] **Crank‑reboot provisions** — DONE: comm watchdog armed only at State ≥14; CRANKFAIL accepts `running`. *(Verify in Phases 2 & 4.)*
- [ ] **`Ign_DR` E‑stop gating** — left gated by `SafeOK` (the 1‑hour hold‑up relay means the box won't reboot on E‑stop anyway). Ungate only if you want the DR line physically on through an E‑stop.
- [ ] **Pressbuild timeout = error vs trip** — currently a soft PRESSFAULT; decide whether it should be a hard trip (paused decision).
- [ ] **F‑RQ readback full pass** — one clean sequence run with zero passivation on slots 7–14.
- [ ] **Wiring cross‑check** — sensor/relay channel assignment vs schematic (per `io_map.md`).
