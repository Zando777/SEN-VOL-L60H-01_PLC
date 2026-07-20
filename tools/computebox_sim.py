#!/usr/bin/env python3
"""
Fake compute box for the volvo_l60h autonomous PLC — a Modbus TCP *client*
that stands in for the real compute box. It writes command bits to the PLC's
holding registers and reads back status/pressures.

Register map (matches the PLC's ModbusData DB):
  HR0 command (we WRITE): bit0 Alive, 1 TurnOn, 2 McuBooted, 3 EngineRunning,
                          4 ParkRelease, 5 EbrakeRelease, 6 ErrorReset, 7 ReCrank
  HR1 status  (we READ):  bit0 Error, 1 CrankFail, 2 PostPress, 3 PressTrip
  HR2 State (0..16)
  HR3..HR7 pressures x10 bar (Shuttle1, Estop1, Shuttle2, Estop2, Prop)

Setup:  pip install pymodbus
Run:    python3 computebox_sim.py <PLC_IP>      (default 10.90.11.200)
Type 'help' at the prompt.
"""
import sys
from pymodbus.client import ModbusTcpClient

CMD_BITS = {
    "alive": 0, "turnon": 1, "mcubooted": 2, "running": 3,
    "parkrel": 4, "ebrakerel": 5, "errreset": 6, "recrank": 7,
}
STATE_NAMES = {
    0: "INIT", 1: "MAINPOWER", 2: "WAITTURNON", 3: "POWERMCU", 4: "MCU_SETTLE",
    5: "AUTONRELAYS", 6: "IGNACCESSORY", 7: "IGNRUN", 8: "CRANK", 9: "CRANKFAIL",
    10: "ENGINERUN", 11: "PRESSBUILD", 12: "PRESSFAULT", 13: "ENGINEOFF",
    14: "RUNNING", 15: "EBRAKERELEASED", 16: "PARKRELEASED", 17: "OPERATIONAL",
}
PRESS_NAMES = ["Shuttle1", "Estop1", "Shuttle2", "Estop2", "Prop"]


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else "10.90.11.200"
    cli = ModbusTcpClient(ip, port=502)
    if not cli.connect():
        print(f"Could not connect to {ip}:502.")
        print("(In PLCSIM the CPU's Modbus TCP usually isn't reachable — this works against real hardware.)")
        return
    print(f"Connected to PLC at {ip}:502.  Type 'help'.")
    cmd = 0  # local mirror of HR0

    def write():
        cli.write_register(0, cmd)

    def show_status():
        rr = cli.read_holding_registers(1, count=7)
        if rr.isError():
            print("read error:", rr); return
        st, state = rr.registers[0], rr.registers[1]
        press = rr.registers[2:7]
        print(f"  State = {state} ({STATE_NAMES.get(state, '?')})")
        flags = [n for n, b in [("Error", 0), ("CrankFail", 1), ("PostPress", 2), ("PressTrip", 3)] if st & (1 << b)]
        print(f"  Status flags: {', '.join(flags) if flags else '(none)'}")
        for name, raw in zip(PRESS_NAMES, press):
            print(f"    {name:9s} {raw/10.0:6.1f} bar")

    HELP = ("commands: " + ", ".join(CMD_BITS) +
            "\n  each toggles its command bit and writes HR0"
            "\n  'status' read back | 'cmd' show command word | 'clear' all bits 0 | 'quit'")
    print(HELP)
    while True:
        try:
            line = input(f"[cmd={cmd:08b}] > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue
        if line in ("quit", "exit", "q"):
            break
        if line in ("help", "h", "?"):
            print(HELP); continue
        if line == "status":
            show_status(); continue
        if line == "cmd":
            print(f"  HR0 = {cmd:08b}"); continue
        if line == "clear":
            cmd = 0; write(); print("  all command bits cleared"); continue
        if line in CMD_BITS:
            cmd ^= (1 << CMD_BITS[line])
            write()
            print(f"  {line} -> {'1' if cmd & (1 << CMD_BITS[line]) else '0'}  (HR0={cmd:08b})")
            continue
        print("unknown; type 'help'")
    cli.close()
    print("bye")


if __name__ == "__main__":
    main()
