#!/usr/bin/env python3
"""
BLE NUS host tool (Route B): monitor + control + mouse move/click in one process.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import time
import collections



from host_frame_monitor import Monitor

try:
    import pyautogui  # type: ignore
except Exception:
    pyautogui = None
try:
    from bleak import BleakClient, BleakScanner
except Exception:
    BleakClient = None
    BleakScanner = None

NUS_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
NUS_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # write
NUS_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # notify

M_RE = re.compile(r"^M,(\d+),(-?\d+),(-?\d+)$")


async def find_device(name: str, timeout: float):
    assert BleakScanner is not None
    print(f"[scan] looking for '{name}' ({timeout}s)...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in devices:
        if (d.name or "") == name:
            return d
    return None


async def run(args) -> int:
    if BleakClient is None or BleakScanner is None:
        print("ERROR: bleak not installed. Run: pip install bleak", file=sys.stderr)
        return 2

    mon = Monitor(quiet=args.quiet)

    dev = await find_device(args.name, args.scan_timeout)
    if dev is None:
        print(f"ERROR: device '{args.name}' not found", file=sys.stderr)
        return 3

    print(f"[connect] {dev.address} {dev.name}")

    done = asyncio.Event()
    last_click_at = 0.0

    pending_click_side = None
    pending_click_until = 0.0
    click_window = collections.deque(maxlen=8)
    mouse_dev = None
    mouse_button_enum = None
    baseline_count = 0
    baseline_dx_sum = 0.0
    baseline_dy_sum = 0.0
    baseline_dx = 0.0
    baseline_dy = 0.0


    mouse_dev = None
    mouse_button_enum = None

    if args.move_mouse or args.click or args.center_on_start:
        try:
            from pynput.mouse import Button, Controller  # type: ignore
            mouse_dev = Controller()
            mouse_button_enum = Button
        except Exception:
            # print("ERROR: --move-mouse/--click needs pynput. Install with: pip install pynput", file=sys.stderr)
            print("ERROR: --move-mouse/--click needs pynput. Install with: pip install pynput", file=sys.stderr)
            return 5

    def maybe_move_mouse(line: str):
        if not args.move_mouse:
            return
        m = M_RE.match(line.strip())
        if not m:
            return

        dx = int(m.group(2))
        dy = int(m.group(3))

        dx_s = int(dx * args.move_scale)
        dy_s = int(dy * args.move_scale)

        if args.invert_x:
            dx_s = -dx_s
        if args.invert_y:
            dy_s = -dy_s

        if abs(dx_s) < args.move_deadband:
            dx_s = 0
        if abs(dy_s) < args.move_deadband:
            dy_s = 0

        if dx_s == 0 and dy_s == 0:
            return

        print(f"[MOVE] dx={dx_s} dy={dy_s}")
        if mouse_dev is not None:
            mouse_dev.move(dx_s, dy_s)

    def maybe_gesture_click(line: str):
        # nonlocal last_click_at
        nonlocal last_click_at, pending_click_side, pending_click_until
        if not args.gesture_click:
            return

        m = M_RE.match(line.strip())
        if not m:
            return

        dx = int(m.group(2))
        dy = int(m.group(3))
        now = time.time()
        click_window.append((dx, dy))
         
        if now - last_click_at < args.click_cooldown_ms / 1000.0:
            return

        # if dx <= -args.click_threshold:
        #     last_click_at = now
        #     print(f"[GESTURE] LEFT_CLICK dx={dx}")
        #     if args.click and mouse_dev is not None and mouse_button_enum is not None:
        #         mouse_dev.click(mouse_button_enum.left, 1)
        # elif dx >= args.click_threshold:
        #     last_click_at = now
        #     print(f"[GESTURE] RIGHT_CLICK dx={dx}")
        #     if args.click and mouse_dev is not None and mouse_button_enum is not None:
        #         mouse_dev.click(mouse_button_enum.right, 1)
     # flick-then-settle trigger: reduce accidental clicks during continuous movement
        if pending_click_side is None:
            if dx <= -args.click_threshold:
                pending_click_side = "LEFT"
                pending_click_until = now + (args.settle_ms / 1000.0)
            elif dx >= args.click_threshold:
                pending_click_side = "RIGHT"
                pending_click_until = now + (args.settle_ms / 1000.0)
            return

        if now > pending_click_until:
            avg_mag = 0.0
            if click_window:
                avg_mag = sum(abs(a) + abs(b) for a, b in click_window) / float(len(click_window))
            if avg_mag <= args.settle_threshold:
            # if True:
                last_click_at = now
                if pending_click_side == "LEFT":
                    print(f"[GESTURE] LEFT_CLICK settle avg={avg_mag:.2f}")
                    if args.click and mouse_dev is not None and mouse_button_enum is not None:
                        mouse_dev.click(mouse_button_enum.left, 1)
                else:
                    print(f"[GESTURE] RIGHT_CLICK settle avg={avg_mag:.2f}")
                    if args.click and mouse_dev is not None and mouse_button_enum is not None:
                        mouse_dev.click(mouse_button_enum.right, 1)
            pending_click_side = None
            
    def on_tx(_: int, data: bytearray):
        text = bytes(data).decode(errors="ignore")
        for line in text.splitlines():
            mon.feed_line(line)
            maybe_move_mouse(line)
            maybe_gesture_click(line)

    async with BleakClient(dev.address) as client:
        # bleak API compatibility
        if hasattr(client, "get_services"):
            svcs = await client.get_services()
            svc_uuids = {s.uuid.lower() for s in svcs}
        else:
            svc_uuids = {s.uuid.lower() for s in client.services}

        if NUS_SERVICE_UUID.lower() not in svc_uuids:
            print("ERROR: NUS service not found", file=sys.stderr)
            return 4

        await client.start_notify(NUS_TX_UUID, on_tx)
        print("[notify] subscribed NUS TX")

        # if args.center_on_start and mouse_dev is not None:
        #     try:
        #         sw, sh = mouse_dev.screen_size
        #         mouse_dev.position = (sw // 2, sh // 2)
        #         print(f"[MOUSE] centered to ({sw // 2}, {sh // 2})")
        #     except Exception as e:
        #         print(f"[WARN] failed to center mouse: {e}")
        
        if args.center_on_start and mouse_dev is not None:
            try:
                if pyautogui is None:
                    raise RuntimeError("pyautogui not installed")
                sw, sh = pyautogui.size()
                cx, cy = sw // 2, sh // 2
                mouse_dev.position = (cx, cy)
                print(f"[MOUSE] centered to ({cx}, {cy})")
            except Exception as e:
                print(f"[WARN] failed to center mouse: {e}")


        if args.cmd:
            payload = (args.cmd.strip().upper() + "\n").encode("ascii", errors="ignore")
            print(f"[write] {payload!r}")
            await client.write_gatt_char(NUS_RX_UUID, payload, response=True)
            await asyncio.sleep(0.2)

        if args.duration > 0:
            await asyncio.sleep(args.duration)
            done.set()
        else:
            print("[run] press Ctrl+C to stop")
            try:
                while not done.is_set():
                    await asyncio.sleep(0.2)
            except KeyboardInterrupt:
                done.set()

        await client.stop_notify(NUS_TX_UUID)

    print(mon.summary())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="BLE NUS monitor/control for Progress A/B")
    ap.add_argument("--name", default="Limb_Assistant", help="BLE device name")
    ap.add_argument("--scan-timeout", type=float, default=8.0)
    ap.add_argument("--duration", type=float, default=10.0, help="Monitor seconds, 0=until Ctrl+C")
    ap.add_argument("--cmd", choices=["START", "STOP", "STATUS"], help="Optional one-shot command")

    ap.add_argument("--move-mouse", action="store_true", help="Apply M dx/dy to OS mouse movement")
    ap.add_argument("--move-scale", type=float, default=1.0, help="Scale factor for dx/dy -> OS movement")
    ap.add_argument("--move-deadband", type=int, default=0, help="Deadband after scaling")
    ap.add_argument("--invert-x", action="store_true", help="Invert X movement")
    ap.add_argument("--invert-y", action="store_true", help="Invert Y movement")

    ap.add_argument("--gesture-click", action="store_true", help="Map fast left/right rotation to mouse clicks")
    ap.add_argument("--click-threshold", type=int, default=50, help="|dx| threshold for click trigger")
    ap.add_argument("--click-cooldown-ms", type=int, default=300, help="Min interval between clicks")
    ap.add_argument("--settle-ms", type=int, default=120, help="Flick-to-settle window for click confirm")
    ap.add_argument("--settle-threshold", type=float, default=12.0, help="Avg motion magnitude threshold to confirm click")
    ap.add_argument("--click", action="store_true", help="Actually click OS mouse (needs pynput)")
    ap.add_argument("--center-on-start", action="store_true", help="Move OS cursor to screen center on script start")
    ap.add_argument("--calibrate-level", action="store_true", help="Use startup frames as level baseline (keep device level)")
    ap.add_argument("--calibrate-frames", type=int, default=40, help="Frame count used for baseline calibration")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())