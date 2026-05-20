#!/usr/bin/env python3
"""
BLE NUS host tool (Route B): monitor + control in one process.

Features:
- Scan/connect by name (default: Limb_Assistant)
- Subscribe NUS TX notify and parse frames (G/M/S/A)
- Optionally send START/STOP/STATUS to NUS RX
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import ctypes
import datetime
import math
import re
import sys
import time

from host_frame_monitor import Monitor

try:
    from bleak import BleakClient, BleakScanner
except Exception:
    BleakClient = None
    BleakScanner = None

try:
    import pyautogui  # type: ignore
except Exception:
    pyautogui = None

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
    click_armed_side = None
    click_armed_at = 0.0
    click_anchor_pos = None
    move_lock_until = 0.0
    mouse_dev = None
    mouse_button_enum = None
    baseline_count = 0
    baseline_dx_sum = 0.0
    baseline_dy_sum = 0.0
    baseline_dx = 0.0
    baseline_dy = 0.0
    calibration_started = False
    still_count = 0
    waiting_still_printed = False
    calibration_wait_started_at = 0.0
    smooth_dx = 0.0
    smooth_dy = 0.0
    drift_bias_x = 0.0
    drift_bias_y = 0.0
    level_still_count = 0
    center_x = None
    center_y = None
    last_level_center_at = 0.0
    level_center_latched = False
    log_fp = None

    def log(msg: str):
        nonlocal log_fp
        ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        print(line)
        if log_fp is not None:
            log_fp.write(line + "\n")
            log_fp.flush()

    if args.log_file:
        log_fp = open(args.log_file, "a", encoding="utf-8")
        log(f"[LOG] append file: {args.log_file}")
    saw_mouse_frame = False

    if args.move_mouse or args.click or args.center_on_start:
        try:
            from pynput.mouse import Button, Controller  # type: ignore
            mouse_dev = Controller()
            mouse_button_enum = Button
        except Exception:
            print("ERROR: --move-mouse/--click/--center-on-start needs pynput. Install with: pip install pynput", file=sys.stderr)
            return 5

    def get_screen_center():
        if pyautogui is not None:
            sw, sh = pyautogui.size()
            return sw // 2, sh // 2, "pyautogui"
        if sys.platform.startswith("win"):
            user32 = ctypes.windll.user32
            sw = int(user32.GetSystemMetrics(0))
            sh = int(user32.GetSystemMetrics(1))
            return sw // 2, sh // 2, "win32"
        raise RuntimeError("no supported screen-size provider (install pyautogui)")

    def parse_mouse_frame(line: str):
        m = M_RE.match(line.strip())
        if not m:
            return None
        return float(int(m.group(2))), float(int(m.group(3)))

    def update_calibration(dx: float, dy: float):
        nonlocal baseline_count, baseline_dx_sum, baseline_dy_sum, baseline_dx, baseline_dy
        nonlocal calibration_started, still_count, waiting_still_printed, calibration_wait_started_at
        if not args.calibrate_level:
            return True
        if baseline_count >= args.calibrate_frames:
            return True
        if args.zero_mode == "still":
            now = time.time()
            if calibration_wait_started_at == 0.0:
                calibration_wait_started_at = now
            motion_mag = abs(dx) + abs(dy)
            if motion_mag <= args.still_threshold:
                still_count += 1
            else:
                still_count = 0
            wait_elapsed_ms = (now - calibration_wait_started_at) * 1000.0
            if args.still_wait_timeout_ms > 0 and wait_elapsed_ms >= args.still_wait_timeout_ms:
                if not calibration_started:
                    print(f"[CALIB] still-wait timeout {args.still_wait_timeout_ms}ms, force start zero capture")
                still_count = args.still_frames
            if still_count < args.still_frames:
                if not waiting_still_printed:
                    waiting_still_printed = True
                    log(f"[CALIB] waiting still frames: need {args.still_frames}, threshold={args.still_threshold}")
                return False
            if waiting_still_printed and not calibration_started:
                log("[CALIB] still condition reached, start zero capture")
        if not calibration_started:
            calibration_started = True
            log(f"[CALIB] start collecting {args.calibrate_frames} frames (keep device level)")
        baseline_dx_sum += dx
        baseline_dy_sum += dy
        baseline_count += 1
        if baseline_count % 10 == 0 and baseline_count < args.calibrate_frames:
            log(f"[CALIB] collecting {baseline_count}/{args.calibrate_frames}")
        if baseline_count == args.calibrate_frames:
            baseline_dx = baseline_dx_sum / float(args.calibrate_frames)
            baseline_dy = baseline_dy_sum / float(args.calibrate_frames)
            log(f"[CALIB] done baseline_dx={baseline_dx:.2f} baseline_dy={baseline_dy:.2f}")
            return True
        return False

    def maybe_move_mouse(line: str):
        nonlocal move_lock_until, saw_mouse_frame, smooth_dx, smooth_dy, drift_bias_x, drift_bias_y
        nonlocal level_still_count, center_x, center_y, last_level_center_at, level_center_latched
        if not args.move_mouse:
            return
        parsed = parse_mouse_frame(line)
        if parsed is None:
            return
        saw_mouse_frame = True
        dx, dy = parsed

        if not update_calibration(dx, dy):
            return

        dx -= baseline_dx
        dy -= baseline_dy

        # Online drift trim: when near-still, slowly learn bias to suppress one-side creep.
        if abs(dx) + abs(dy) <= args.drift_trim_threshold:
            drift_bias_x = (1.0 - args.drift_trim_alpha) * drift_bias_x + args.drift_trim_alpha * dx
            drift_bias_y = (1.0 - args.drift_trim_alpha) * drift_bias_y + args.drift_trim_alpha * dy
        dx -= drift_bias_x
        dy -= drift_bias_y

        # Suppress near-level drift when device returns to horizontal.
        motion_mag = abs(dx) + abs(dy)
        if motion_mag <= args.level_hold_threshold:
            level_still_count += 1
            # Decay filter state quickly to avoid residual wander.
            smooth_dx *= 0.6
            smooth_dy *= 0.6
            if level_still_count >= args.level_hold_frames:
                if args.auto_center_on_level and mouse_dev is not None:
                    now = time.time()
                    if level_center_latched and (now - last_level_center_at) * 1000.0 < args.level_recenter_cooldown_ms:
                        return
                    if center_x is None or center_y is None:
                        try:
                            cx, cy, _ = get_screen_center()
                            center_x, center_y = cx, cy
                        except Exception:
                            center_x, center_y = None, None
                    if center_x is not None and center_y is not None:
                        mouse_dev.position = (center_x, center_y)
                        last_level_center_at = now
                        level_center_latched = True
                return
        else:
            level_still_count = 0
            level_center_latched = False

        # Simple EMA smoothing for cursor stability.
        smooth_dx = (args.smooth_alpha * dx) + ((1.0 - args.smooth_alpha) * smooth_dx)
        smooth_dy = (args.smooth_alpha * dy) + ((1.0 - args.smooth_alpha) * smooth_dy)

        if args.omnidirectional:
            # Isotropic 2D mapping (continuous all-direction movement).
            mag = math.hypot(smooth_dx, smooth_dy)
            if mag < args.move_deadband:
                dx_s = 0
                dy_s = 0
            else:
                unit_x = smooth_dx / mag
                unit_y = smooth_dy / mag
                mapped_mag = ((mag - args.move_deadband) ** args.response_gamma) * args.move_scale
                dx_s = int(unit_x * mapped_mag)
                dy_s = int(unit_y * mapped_mag)
        else:
            dx_s = int(smooth_dx * args.move_scale)
            dy_s = int(smooth_dy * args.move_scale)

        # Per-frame clamp to avoid large spikes causing jumpy cursor movement.
        if dx_s > args.max_step:
            dx_s = args.max_step
        elif dx_s < -args.max_step:
            dx_s = -args.max_step
        if dy_s > args.max_step:
            dy_s = args.max_step
        elif dy_s < -args.max_step:
            dy_s = -args.max_step

        if args.invert_x:
            dx_s = -dx_s
        if args.invert_y:
            dy_s = -dy_s

        if not args.omnidirectional:
            if abs(dx_s) < args.move_deadband:
                dx_s = 0
            if abs(dy_s) < args.move_deadband:
                dy_s = 0

        if dx_s == 0 and dy_s == 0:
            return

        if args.debug_motion:
            log(f"[DBG] raw=({dx:.2f},{dy:.2f}) drift=({drift_bias_x:.2f},{drift_bias_y:.2f}) smooth=({smooth_dx:.2f},{smooth_dy:.2f}) out=({dx_s},{dy_s})")

        if time.time() < move_lock_until:
            return

        log(f"[MOVE] dx={dx_s} dy={dy_s}")
        if mouse_dev is not None:
            mouse_dev.move(dx_s, dy_s)

    def maybe_gesture_click(line: str):
        nonlocal last_click_at, pending_click_side, pending_click_until, click_armed_side, click_armed_at, click_anchor_pos, move_lock_until, saw_mouse_frame
        if not args.gesture_click:
            return
        parsed = parse_mouse_frame(line)
        if parsed is None:
            return
        saw_mouse_frame = True

        dx = int(parsed[0] - baseline_dx)
        dy = int(parsed[1] - baseline_dy)
        now = time.time()
        click_window.append((dx, dy))

        if args.calibrate_level and baseline_count < args.calibrate_frames:
            return

        if now - last_click_at < args.click_cooldown_ms / 1000.0:
            return

        if args.click_mode == "hysteresis":
            if click_armed_side is None:
                # Require horizontal dominance to reduce accidental triggers during diagonal motions.
                if abs(dx) < abs(dy) * args.click_axis_ratio:
                    return
                if dx <= -args.click_threshold:
                    click_armed_side = "LEFT"
                    click_armed_at = now
                    log(f"[GESTURE] armed LEFT dx={dx}")
                    move_lock_until = now + (args.move_lock_ms / 1000.0)
                    if mouse_dev is not None and args.click_anchor_restore:
                        click_anchor_pos = mouse_dev.position
                elif dx >= args.click_threshold:
                    click_armed_side = "RIGHT"
                    click_armed_at = now
                    log(f"[GESTURE] armed RIGHT dx={dx}")
                    move_lock_until = now + (args.move_lock_ms / 1000.0)
                    if mouse_dev is not None and args.click_anchor_restore:
                        click_anchor_pos = mouse_dev.position
                return

            arm_timeout = (now - click_armed_at) * 1000.0 >= args.click_arm_timeout_ms
            if abs(dx) <= args.release_threshold or arm_timeout:
                last_click_at = now
                if click_armed_side == "LEFT":
                    if arm_timeout:
                        log("[GESTURE] LEFT_CLICK timeout")
                    else:
                        log("[GESTURE] LEFT_CLICK hysteresis")
                    if args.click and mouse_dev is not None and mouse_button_enum is not None:
                        mouse_dev.click(mouse_button_enum.left, 1)
                else:
                    if arm_timeout:
                        log("[GESTURE] RIGHT_CLICK timeout")
                    else:
                        log("[GESTURE] RIGHT_CLICK hysteresis")
                    if args.click and mouse_dev is not None and mouse_button_enum is not None:
                        mouse_dev.click(mouse_button_enum.right, 1)
                if args.click_anchor_restore and mouse_dev is not None and click_anchor_pos is not None:
                    mouse_dev.position = click_anchor_pos
                click_armed_side = None
                click_anchor_pos = None
            return

        # flick-then-settle trigger
        if pending_click_side is None:
            if dx <= -args.click_threshold:
                pending_click_side = "LEFT"
                pending_click_until = now + (args.settle_ms / 1000.0)
                move_lock_until = pending_click_until + (args.move_lock_ms / 1000.0)
            elif dx >= args.click_threshold:
                pending_click_side = "RIGHT"
                pending_click_until = now + (args.settle_ms / 1000.0)
                move_lock_until = pending_click_until + (args.move_lock_ms / 1000.0)
            return

        if now > pending_click_until:
            avg_mag = 0.0
            if click_window:
                avg_mag = sum(abs(a) + abs(b) for a, b in click_window) / float(len(click_window))
            if avg_mag <= args.settle_threshold:
                last_click_at = now
                if pending_click_side == "LEFT":
                    log(f"[GESTURE] LEFT_CLICK settle avg={avg_mag:.2f}")
                    if args.click and mouse_dev is not None and mouse_button_enum is not None:
                        mouse_dev.click(mouse_button_enum.left, 1)
                else:
                    log(f"[GESTURE] RIGHT_CLICK settle avg={avg_mag:.2f}")
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
        # Bleak compatibility:
        # - old versions: await client.get_services()
        # - newer versions: services available via client.services after connect
        if hasattr(client, "get_services"):
            svcs = await client.get_services()
            svc_uuids = {s.uuid.lower() for s in svcs}
        else:
            svc_uuids = {s.uuid.lower() for s in client.services}

        if NUS_SERVICE_UUID.lower() not in svc_uuids:
            print("ERROR: NUS service not found", file=sys.stderr)
            return 4

        await client.start_notify(NUS_TX_UUID, on_tx)
        log("[notify] subscribed NUS TX")

        if args.center_on_start and mouse_dev is not None:
            try:
                cx, cy, provider = get_screen_center()
                center_x, center_y = cx, cy
                mouse_dev.position = (cx, cy)
                log(f"[MOUSE] centered to ({cx}, {cy}) via {provider}")
            except Exception as e:
                log(f"[WARN] failed to center mouse: {e}")

        if args.recenter_after_calib and args.center_on_start and mouse_dev is not None:
            # Recenter once after startup hold so late startup motion won't leave pointer offset.
            await asyncio.sleep(0.05)
            try:
                cx, cy, provider = get_screen_center()
                center_x, center_y = cx, cy
                mouse_dev.position = (cx, cy)
                log(f"[MOUSE] re-centered to ({cx}, {cy}) via {provider}")
            except Exception as e:
                log(f"[WARN] failed to re-center mouse: {e}")

        if args.startup_hold_ms > 0:
            log(f"[STARTUP] hold {args.startup_hold_ms}ms for level placement")
            await asyncio.sleep(args.startup_hold_ms / 1000.0)

        if args.cmd:
            payload = (args.cmd.strip().upper() + "\n").encode("ascii", errors="ignore")
            log(f"[write] {payload!r}")
            await client.write_gatt_char(NUS_RX_UUID, payload, response=True)
            # Give firmware a brief window to enqueue ACK/STATUS before heavy stream dominates output.
            await asyncio.sleep(0.2)

        if args.duration > 0:
            await asyncio.sleep(args.duration)
            done.set()
        else:
            log("[run] press Ctrl+C to stop")
            try:
                while not done.is_set():
                    await asyncio.sleep(0.2)
            except KeyboardInterrupt:
                done.set()

        await client.stop_notify(NUS_TX_UUID)

    if args.calibrate_level:
        if not saw_mouse_frame:
            log("[WARN] calibration did not run: no M frames received")
        elif baseline_count < args.calibrate_frames:
            log(f"[WARN] calibration incomplete: {baseline_count}/{args.calibrate_frames} frames")

    log(mon.summary().strip())
    if log_fp is not None:
        log_fp.close()
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
    ap.add_argument("--omnidirectional", action="store_true", default=True, help="Use isotropic 2D vector mapping instead of axis-quantized mapping")
    ap.add_argument("--response-gamma", type=float, default=1.1, help="2D response curve gamma for omnidirectional mapping")
    ap.add_argument("--smooth-alpha", type=float, default=0.35, help="EMA smoothing alpha (0<alpha<=1)")
    ap.add_argument("--max-step", type=int, default=30, help="Max absolute move step per frame after scaling")
    ap.add_argument("--drift-trim-alpha", type=float, default=0.03, help="Online bias trim learning rate when near still")
    ap.add_argument("--drift-trim-threshold", type=float, default=4.0, help="Near-still threshold for drift trim")
    ap.add_argument("--invert-x", action="store_true", help="Invert X movement")
    ap.add_argument("--invert-y", action="store_true", help="Invert Y movement")
    ap.add_argument("--gesture-click", action="store_true", help="Map fast left/right rotation to mouse clicks")
    ap.add_argument("--click-mode", choices=["settle", "hysteresis"], default="hysteresis", help="Gesture click detector mode")
    ap.add_argument("--click-threshold", type=int, default=50, help="|dx| threshold for click trigger")
    ap.add_argument("--release-threshold", type=int, default=15, help="Release threshold for hysteresis click mode")
    ap.add_argument("--click-axis-ratio", type=float, default=1.0, help="Require |dx| >= ratio*|dy| for click arming")
    ap.add_argument("--click-arm-timeout-ms", type=int, default=220, help="Auto-fire armed click if release condition is not met in time")
    ap.add_argument("--click-cooldown-ms", type=int, default=300, help="Min interval between clicks")
    ap.add_argument("--settle-ms", type=int, default=120, help="Flick-to-settle window for click confirm")
    ap.add_argument("--settle-threshold", type=float, default=12.0, help="Avg motion magnitude threshold to confirm click")
    ap.add_argument("--move-lock-ms", type=int, default=120, help="Freeze move around click trigger window")
    ap.add_argument("--click-anchor-restore", action="store_true", help="Restore cursor to armed position after click to reduce trigger drift")
    ap.add_argument("--click", action="store_true", help="Actually click OS mouse (needs pynput)")
    ap.add_argument("--center-on-start", action="store_true", help="Move OS cursor to screen center on script start")
    ap.add_argument("--recenter-after-calib", action="store_true", help="Recenter cursor once after startup hold/calibration phase")
    ap.add_argument("--calibrate-level", action="store_true", help="Use startup frames as level baseline (keep device level)")
    ap.add_argument("--calibrate-frames", type=int, default=40, help="Frame count used for baseline calibration")
    ap.add_argument("--zero-mode", choices=["immediate", "still"], default="still", help="How to start zero capture when calibrate-level is enabled")
    ap.add_argument("--still-threshold", "--still--threshold", type=float, default=3.0, help="Stillness threshold on |dx|+|dy| for zero capture")
    ap.add_argument("--still-frames", type=int, default=20, help="Consecutive still frames required before zero capture starts")
    ap.add_argument("--still-wait-timeout-ms", type=int, default=3000, help="Timeout for still waiting; then force zero capture start")
    ap.add_argument("--auto-center-on-level", action="store_true", help="When device returns level, lock cursor back to center to suppress drift")
    ap.add_argument("--level-hold-threshold", type=float, default=3.0, help="Level-hold threshold on |dx|+|dy|")
    ap.add_argument("--level-hold-frames", type=int, default=10, help="Consecutive level frames before level-hold lock")
    ap.add_argument("--level-recenter-cooldown-ms", type=int, default=1200, help="Cooldown to prevent repeated rapid level re-centering")
    ap.add_argument("--startup-hold-ms", type=int, default=0, help="Hold time before processing movement/clicks")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--log-file", default="host_ble_nus_cli.log", help="Save runtime logs to file (append mode)")
    ap.add_argument("--debug-motion", action="store_true", help="Print detailed motion pipeline debug info")
    args = ap.parse_args()

    if not (0.0 < args.smooth_alpha <= 1.0):
        print("ERROR: --smooth-alpha must be in (0, 1].", file=sys.stderr)
        return 2
    if args.max_step < 1:
        print("ERROR: --max-step must be >= 1.", file=sys.stderr)
        return 2
    if args.response_gamma <= 0.0:
        print("ERROR: --response-gamma must be > 0.", file=sys.stderr)
        return 2
    if not (0.0 <= args.drift_trim_alpha <= 1.0):
        print("ERROR: --drift-trim-alpha must be in [0, 1].", file=sys.stderr)
        return 2
    if args.drift_trim_threshold < 0.0:
        print("ERROR: --drift-trim-threshold must be >= 0.", file=sys.stderr)
        return 2
    if args.click_axis_ratio < 0.0:
        print("ERROR: --click-axis-ratio must be >= 0.", file=sys.stderr)
        return 2
    if args.click_arm_timeout_ms < 0:
        print("ERROR: --click-arm-timeout-ms must be >= 0.", file=sys.stderr)
        return 2
    if args.still_threshold < 0.0:
        print("ERROR: --still-threshold must be >= 0.", file=sys.stderr)
        return 2
    if args.still_wait_timeout_ms < 0:
        print("ERROR: --still-wait-timeout-ms must be >= 0.", file=sys.stderr)
        return 2
    if args.level_hold_threshold < 0.0:
        print("ERROR: --level-hold-threshold must be >= 0.", file=sys.stderr)
        return 2
    if args.level_hold_frames < 1:
        print("ERROR: --level-hold-frames must be >= 1.", file=sys.stderr)
        return 2
    if args.level_recenter_cooldown_ms < 0:
        print("ERROR: --level-recenter-cooldown-ms must be >= 0.", file=sys.stderr)
        return 2

    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
