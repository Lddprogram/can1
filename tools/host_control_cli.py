#!/usr/bin/env python3
"""
Host control CLI for Progress B firmware commands.

Sends START / STOP / STATUS over serial UART and optionally reads response lines.
"""

from __future__ import annotations

import argparse
import sys
import time

try:
    import serial  # type: ignore
except Exception:
    serial = None

VALID_CMDS = {"START", "STOP", "STATUS"}


def run_once(port: str, baud: int, cmd: str, timeout: float, eol: str) -> int:
    if serial is None:
        print("ERROR: pyserial not installed. Run: pip install pyserial", file=sys.stderr)
        return 2

    payload = (cmd + eol).encode("ascii", errors="ignore")

    with serial.Serial(port, baudrate=baud, timeout=0.2) as ser:
        ser.reset_input_buffer()
        ser.write(payload)
        ser.flush()

        end_at = time.time() + timeout
        got = 0
        while time.time() < end_at:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore").strip()
            if not line:
                continue
            print(line)
            got += 1

        if got == 0:
            print("(no response within timeout)")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Send START/STOP/STATUS to firmware over serial")
    ap.add_argument("--serial", required=True, help="Serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200, help="Baud rate")
    ap.add_argument("--cmd", required=True, help="START|STOP|STATUS")
    ap.add_argument("--timeout", type=float, default=1.5, help="Read response timeout in seconds")
    ap.add_argument("--eol", default="\n", help="Line ending, default newline")
    args = ap.parse_args()

    cmd = args.cmd.strip().upper()
    if cmd not in VALID_CMDS:
        print(f"ERROR: invalid cmd={args.cmd}. Must be one of {sorted(VALID_CMDS)}", file=sys.stderr)
        return 2

    return run_once(args.serial, args.baud, cmd, args.timeout, args.eol)


if __name__ == "__main__":
    raise SystemExit(main())
