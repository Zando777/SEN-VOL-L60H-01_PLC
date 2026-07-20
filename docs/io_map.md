# volvo_l60h — Verified I/O Map

**Source:** Device overview + PLC tag export (`tags16_07v1.xlsx`), cross‑checked 2026‑07‑16.
This is the **ground truth** — verified tag ↔ address ↔ module ↔ real‑world function.
The program refers to everything **by tag name**, so the tag table (below) is the single
source of truth for addresses; change a module's address and the tag must follow.

---

## Rack layout (ET 200SP, Rack 0)

| Slot | Module | Type | I addr | Q addr |
|---|---|---|---|---|
| 1 | CPU 1510SP F‑1 PN | — | — | — |
| 2 | **F‑AI Pressures** | F‑AI 4xI 0(4)..20mA HF | 35…48 | 35…39 |
| 3 | **F‑AI Pressure Prop** | F‑AI 4xI 0(4)..20mA HF | 7…20 | 7…11 |
| 4 | **F‑DQ 2A** | F‑DQ 4x24VDC/2A PM HF | 0…4 | 0…4 |
| 5 | **F‑DI Switches** | F‑DI 8x24VDC HF | 21…27 | 21…25 |
| 6 | **F‑DQ 8x Relays** | F‑DQ 8x24VDC/0.5A PP HF | 49…54 | 49…54 |
| 7 | F‑RQ Ign 1 | F‑RQ 1x…/5A | 5 | — |
| 8 | F‑RQ Ign 2 | F‑RQ 1x…/5A | 6 | — |
| 9 | F‑RQ Ign 3 | F‑RQ 1x…/5A | 55 | — |
| 10 | F‑RQ Ign 4 | F‑RQ 1x…/5A | 56 | — |
| 11 | F‑RQ Park Lock | F‑RQ 1x…/5A | 57 | — |
| 12 | F‑RQ Park Unlk | F‑RQ 1x…/5A | 58 | — |
| 13 | F‑RQ MCU PWR | F‑RQ 1x…/5A | 59 | — |
| 14 | F‑RQ MAIN SWITCH | F‑RQ 1x…/5A | 60 | — |
| 15 | Server module | — | — | — |
| — | RemoteEStop (remote station) | F‑DI 8x24VDC HF | 28 | — |

The F‑RQ modules have **input (readback) addresses only** — they are *commanded* by the
F‑DQ 8x Relays channels (see architecture note).

---

## Two‑stage output architecture (important)

Fail‑safe outputs are two stages:
- **Stage 1 — `F-DQ 8x Relays` (0.5 A, %Q49):** the CPU's fail‑safe *command* bits.
- **Stage 2 — `F-RQ` modules (5 A / ≤230 VAC):** each is a heavy relay driven by **one
  F‑DQ channel**, with a **readback** contact wired to its own input address so the
  F‑system can confirm the relay actually switched. The F‑DQ + F‑RQ pair = one fail‑safe
  high‑power output.

Channel → F‑RQ slot rule: F‑RQ slot = **6 + channel + 1**. (e.g. `%Q49.6` → slot 13.)

---

## OUTPUTS

### F‑DQ 8x Relays (slot 6, %Q49) → F‑RQ relays
| Address | Tag | drives → F‑RQ (slot) | Readback | Real‑world |
|---|---|---|---|---|
| %Q49.0 | `Ign_R` | F‑RQ Ign 1 (7) | %I5 | ignition pos I / accessory (R) |
| %Q49.1 | `Ign_15_54` | F‑RQ Ign 2 (8) | %I6 | ignition 15/54 (run) |
| %Q49.2 | `Ign_DR` | F‑RQ Ign 3 (9) | %I55 | glow / DR |
| %Q49.3 | `Ign_50` | F‑RQ Ign 4 (10) | %I56 | **starter (terminal 50)** |
| %Q49.4 | `ParkBrake_Lock` | F‑RQ Park Lock (11) | %I57 | park brake engage |
| %Q49.5 | `ParkBrake_Unlock` | F‑RQ Park Unlk (12) | %I58 | park brake release |
| %Q49.6 | `MCU_Enable` | F‑RQ MCU PWR (13) | %I59 | **MRS MCU power** |
| %Q49.7 | `MainPwr_Sw` | F‑RQ MAIN SWITCH (14) | %I60 | main power / P1 |

### F‑DQ 2A (slot 4, %Q0) — direct 2 A push‑pull
| Address | Tag | Real‑world |
|---|---|---|
| %Q0.0 | `Sol_Estop` | e‑stop brake solenoid (front) |
| %Q0.1 | `Sol_Estop_2` | e‑stop brake solenoid (rear) |
| %Q0.2 | — | unused |
| %Q0.3 | `AM_Relays` | A/M relays |

---

## INPUTS

### Digital
| Address | Tag | Module (slot) | Real‑world |
|---|---|---|---|
| %I21.0 | `AutoMan_Sw1` | F‑DI Switches (5) | Auto/Manual switch (ch A) |
| %I21.4 | `AutoMan_Sw2` | F‑DI Switches (5) | Auto/Manual (ch B, 1oo2 pair) |
| %I28.0 | `RemEstop_1` | RemoteEStop F‑DI | remote E‑stop ch A |
| %I28.1 | `Rem_Ack` | RemoteEStop F‑DI | acknowledge / reintegrate button |
| %I28.2 | `Rem_Start` | RemoteEStop F‑DI | start button |
| %I28.3 | — | RemoteEStop F‑DI | unused |
| %I28.4 | `RemEstop_2` | RemoteEStop F‑DI | remote E‑stop ch B |

### Analog (4–20 mA, 0–400 bar; raw 0–27648 → bar via `raw*400/27648`)
| Address | Tag | Module (slot) | Real‑world |
|---|---|---|---|
| %IW35 | `Press_Shuttle_1` | F‑AI Pressures (2) | shuttle pressure A |
| %IW37 | `Press_Estop_1` | F‑AI Pressures (2) | e‑stop hyd line A |
| %IW39 | `Press_Shuttle_2` | F‑AI Pressures (2) | shuttle pressure B |
| %IW41 | `Press_Estop_2` | F‑AI Pressures (2) | e‑stop hyd line B |
| %IW7 | `Press_Prop` | F‑AI Pressure Prop (3) | proportional valve pressure |

⚠️ **Gotcha:** `%IW9 / %IW11 / %IW13` are the **unused channels 1–3 of the F‑AI Pressure
Prop module** — not shuttle/estop. Any code reading those raw addresses for pressure would
get dead channels (zeros). The shuttle/estop sensors live on the **separate F‑AI Pressures
module at %IW35–41.** This is almost certainly what caused the early "all pressures read 0"
confusion. Because the program reads by **tag name**, it uses the correct addresses.

---

## Orphan / scratch tags (not real machine I/O)
| Tag | Address | Note |
|---|---|---|
| `Tag_1…Tag_9` | %M100/%M101.x | internal memory scratch bits, unused |

Safe to delete for cleanliness.

---

## How to verify any tag yourself
1. **Tag export** → tag's `%` address (e.g. `MCU_Enable %Q49.6`).
2. **Device overview** → module whose I/Q range covers that byte (`49` → F‑DQ 8x Relays, ch 6).
3. Relay function → F‑RQ in slot `6 + channel + 1` (`6+6+1 = 13` → F‑RQ MCU PWR).
4. The remaining physical check (which software can't confirm): the **wiring schematic** —
   that the actual sensor/relay wire lands on the channel the tag assumes.
