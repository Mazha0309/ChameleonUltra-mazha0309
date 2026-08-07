#!/usr/bin/env python3
"""Control auto polling on a Chameleon Ultra over USB serial (6868:8686).

Usage:
    python polling_ctl.py on                    # enable polling (saved to flash)
    python polling_ctl.py off                   # disable polling
    python polling_ctl.py interval <ms>         # set interval 100..5000 (saved)
    python polling_ctl.py status                # read enable + interval
"""

import sys
import time

import serial
import serial.tools.list_ports

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from cu_frame import (
    CMD_GET_POLLING_ENABLE,
    CMD_SET_POLLING_ENABLE,
    CMD_GET_POLLING_INTERVAL,
    CMD_SET_POLLING_INTERVAL,
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


def exchange(ser, cmd, payload=b"", timeout=2.0):
    ser.reset_input_buffer()
    ser.write(encode_frame(cmd, 0, payload))
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk
            try:
                frame = parse_frame(buf)
            except ValueError:
                break
            if frame is not None and frame["cmd"] == cmd:
                return frame
        else:
            time.sleep(0.05)
    return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    port = find_port()
    if port is None:
        print("Chameleon not found (USB VID 6868:8686). Plug it in first.")
        sys.exit(1)

    ser = serial.Serial(port, baudrate=115200, timeout=2)
    ser.dtr = 1
    time.sleep(0.2)

    op = sys.argv[1]
    if op == "on":
        r = exchange(ser, CMD_SET_POLLING_ENABLE, b"\x01")
        print("enabled" if r and r["status"] == STATUS_SUCCESS else f"FAILED {r}")
    elif op == "off":
        r = exchange(ser, CMD_SET_POLLING_ENABLE, b"\x00")
        print("disabled" if r and r["status"] == STATUS_SUCCESS else f"FAILED {r}")
    elif op == "interval":
        ms = int(sys.argv[2])
        if not (100 <= ms <= 5000):
            print("interval must be 100..5000")
            sys.exit(1)
        r = exchange(ser, CMD_SET_POLLING_INTERVAL, ms.to_bytes(2, "big"))
        print(
            f"interval={ms}ms" if r and r["status"] == STATUS_SUCCESS else f"FAILED {r}"
        )
    elif op == "status":
        r1 = exchange(ser, CMD_GET_POLLING_ENABLE)
        r2 = exchange(ser, CMD_GET_POLLING_INTERVAL)
        if r1 and r2:
            enable = r1["data"][0] == 1
            interval = int.from_bytes(r2["data"], "big")
            print(f"polling: {'ON' if enable else 'OFF'}, interval={interval}ms")
        else:
            print("no response")
    else:
        print(__doc__)
        sys.exit(1)

    ser.close()


if __name__ == "__main__":
    main()
