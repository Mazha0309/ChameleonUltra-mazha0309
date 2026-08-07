#!/usr/bin/env python3
"""Set the active slot on a Chameleon Ultra over USB serial (6868:8686).

Usage:
    python set_active_slot.py <slot>      # slot 0..15
    python set_active_slot.py             # no arg: read back current slot (via mode cmd)

Requires: pyserial. Frame codec reused from cu_frame (official protocol).
"""

import sys
import time

import serial
import serial.tools.list_ports

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from cu_frame import (
    CMD_SET_ACTIVE_SLOT,
    STATUS_SUCCESS,
    encode_frame,
    parse_frame,
)

VID_CHAMELEON = 0x6868
PID_CHAMELEON = 0x8686


def find_port():
    for p in serial.tools.list_ports.comports():
        if p.vid == VID_CHAMELEON and p.pid == PID_CHAMELEON:
            return p.device
    return None


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    slot = int(sys.argv[1])
    if not (0 <= slot < 16):
        print(f"slot must be 0..15, got {slot}")
        sys.exit(1)

    port = find_port()
    if port is None:
        print("Chameleon not found (USB VID 6868:8686). Plug it in first.")
        sys.exit(1)

    ser = serial.Serial(port, baudrate=115200, timeout=2)
    ser.dtr = 1  # must enable DTR like enter_dfu.py
    time.sleep(0.2)
    ser.reset_input_buffer()

    req = encode_frame(CMD_SET_ACTIVE_SLOT, 0, bytes([slot]))
    print(f"TX SET_ACTIVE_SLOT({slot}): {req.hex()}")
    ser.write(req)

    buf = b""
    deadline = time.time() + 3
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            try:
                frame = parse_frame(buf)
            except ValueError as e:
                print(f"corrupt frame: {e}")
                break
            if frame is not None:
                status = frame["status"]
                if frame["cmd"] == CMD_SET_ACTIVE_SLOT and status == STATUS_SUCCESS:
                    print(
                        f"OK: switched to slot {slot} (LED {slot % 8 + 1}, "
                        f"{'blinking' if slot >= 8 else 'steady'})"
                    )
                else:
                    print(f"response: cmd={frame['cmd']} status=0x{status:04x}")
                ser.close()
                return
        else:
            time.sleep(0.05)
    ser.close()
    print("no response (device sleeping? press button to wake)")


if __name__ == "__main__":
    main()
