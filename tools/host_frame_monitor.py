#!/usr/bin/env python3
"""
Host-side frame monitor for Progress A/B.

Supports input from:
1) --serial COMx --baud 115200
2) --file path/to/log.txt
3) stdin pipe

Parses frames:
- G,<seq>,<gx>,<gy>,<gz>
- G,<seq>,ERR
- M,<seq>,<dx>,<dy>
- S,<0|1>
- A,START / A,STOP
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Optional, TextIO

try:
    import serial  # type: ignore
except Exception:
    serial = None

G_OK_RE = re.compile(r"^G,(\d+),(-?\d+),(-?\d+),(-?\d+)$")
G_ERR_RE = re.compile(r"^G,(\d+),ERR$")
M_RE = re.compile(r"^M,(\d+),(-?\d+),(-?\d+)$")
S_RE = re.compile(r"^S,([01])$")
A_RE = re.compile(r"^A,(START|STOP)$")


@dataclass
class SeqState:
    last: Optional[int] = None
    jumps: int = 0
    drops: int = 0

    def feed(self, seq: int) -> None:
        if self.last is None:
            self.last = seq
            return
        if seq != self.last + 1:
            self.jumps += 1
            if seq > self.last + 1:
                self.drops += seq - (self.last + 1)
        self.last = seq


@dataclass
class Stats:
    lines: int = 0
    unknown: int = 0
    gyro_ok: int = 0
    gyro_err: int = 0
    mouse: int = 0
    status: int = 0
    ack: int = 0
    gyro_seq: SeqState = field(default_factory=SeqState)
    mouse_seq: SeqState = field(default_factory=SeqState)


class Monitor:
    def __init__(self, quiet: bool = False):
        self.stats = Stats()
        self.quiet = quiet

    def feed_line(self, raw: str) -> None:
        line = raw.strip()
        if not line:
            return
        self.stats.lines += 1

        m = G_OK_RE.match(line)
        if m:
            seq = int(m.group(1))
            gx, gy, gz = int(m.group(2)), int(m.group(3)), int(m.group(4))
            self.stats.gyro_ok += 1
            self.stats.gyro_seq.feed(seq)
            if not self.quiet:
                print(f"[GYRO] seq={seq} gx={gx} gy={gy} gz={gz}")
            return

        m = G_ERR_RE.match(line)
        if m:
            seq = int(m.group(1))
            self.stats.gyro_err += 1
            self.stats.gyro_seq.feed(seq)
            if not self.quiet:
                print(f"[GYRO_ERR] seq={seq}")
            return

        m = M_RE.match(line)
        if m:
            seq = int(m.group(1))
            dx, dy = int(m.group(2)), int(m.group(3))
            self.stats.mouse += 1
            self.stats.mouse_seq.feed(seq)
            if not self.quiet:
                print(f"[MOUSE] seq={seq} dx={dx} dy={dy}")
            return

        m = S_RE.match(line)
        if m:
            self.stats.status += 1
            state = "ON" if m.group(1) == "1" else "OFF"
            if not self.quiet:
                print(f"[STATUS] mouse_output={state}")
            return

        m = A_RE.match(line)
        if m:
            self.stats.ack += 1
            if not self.quiet:
                print(f"[ACK] {m.group(1)}")
            return

        self.stats.unknown += 1
        if not self.quiet:
            print(f"[UNKNOWN] {line}")

    def summary(self) -> str:
        s = self.stats
        return (
            "\n===== SUMMARY =====\n"
            f"lines={s.lines} unknown={s.unknown}\n"
            f"gyro_ok={s.gyro_ok} gyro_err={s.gyro_err} "
            f"gyro_jumps={s.gyro_seq.jumps} gyro_drops={s.gyro_seq.drops}\n"
            f"mouse={s.mouse} mouse_jumps={s.mouse_seq.jumps} mouse_drops={s.mouse_seq.drops}\n"
            f"status={s.status} ack={s.ack}\n"
        )


def monitor_stream(f: TextIO, mon: Monitor, interval: float) -> None:
    last = time.time()
    while True:
        line = f.readline()
        if line == "":
            break
        mon.feed_line(line)
        if interval > 0 and time.time() - last >= interval:
            print(mon.summary())
            last = time.time()


def monitor_serial(port: str, baud: int, mon: Monitor, interval: float) -> None:
    if serial is None:
        raise RuntimeError("pyserial not installed. Run: pip install pyserial")
    with serial.Serial(port, baudrate=baud, timeout=0.5) as ser:
        last = time.time()
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode(errors="ignore")
            mon.feed_line(line)
            if interval > 0 and time.time() - last >= interval:
                print(mon.summary())
                last = time.time()


def main() -> int:
    ap = argparse.ArgumentParser(description="Progress A/B frame monitor")
    ap.add_argument("--serial", help="Serial port, e.g. COM5 or /dev/ttyUSB0")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--file", help="Input log file")
    ap.add_argument("--quiet", action="store_true", help="Only print summaries")
    ap.add_argument("--summary-interval", type=float, default=5.0, help="seconds, 0 disables periodic summary")
    args = ap.parse_args()

    mon = Monitor(quiet=args.quiet)

    try:
        if args.serial:
            monitor_serial(args.serial, args.baud, mon, args.summary_interval)
        elif args.file:
            with open(args.file, "r", encoding="utf-8", errors="ignore") as f:
                monitor_stream(f, mon, args.summary_interval)
        else:
            monitor_stream(sys.stdin, mon, args.summary_interval)
    except KeyboardInterrupt:
        pass

    print(mon.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
