#!/usr/bin/env python3
"""Small write/read validation for the GUI's background CSV session logger."""

import csv
import time

from io_test_gui import SessionCsvLogger


logger = SessionCsvLogger("selftest")
logger.telemetry({"elapsed_seconds": "0.001", "plc_ip": "selftest", "connection_ok": True, "hr0": 1})
logger.command({
    "elapsed_seconds": "0.002", "plc_ip": "selftest", "source": "selftest",
    "command_name": "TEST", "register": 0, "value_decimal": 1,
    "value_hex": "0x0001", "write_result": "SUCCESS",
})
logger.event({
    "elapsed_seconds": "0.003", "plc_ip": "selftest", "severity": "INFO",
    "event_type": "SELFTEST", "message": "logger validation",
})
logger.plc_event({
    "elapsed_seconds": "0.004", "plc_ip": "selftest", "event_sequence": 1,
    "boot_session": 1, "plc_timestamp": "2026-07-23T00:00:00.000000000Z",
    "time_status": 0, "event_id": "0x0001", "event_name": "PLC_BOOT",
    "severity": 1,
})
time.sleep(0.3)
logger.close()

if logger.error:
    raise RuntimeError(logger.error)

for kind, path in logger.paths.items():
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if len(rows) != 2:
        raise RuntimeError(f"{kind}: expected header + one data row, got {len(rows)}")
    print(f"{kind}: OK ({path})")
    path.unlink()

try:
    logger.log_dir.rmdir()
except OSError:
    pass
