#!/usr/bin/env python3
"""
powerbox_maint.py — maintenance-mode keeper for the Prius powerbox.

While the backend is stopped (satellite OTA, debugging), the powerbox stops
seeing POCO heartbeats: it gates its telemetry TX off and will eventually
start pressing the host's power button ("wake a dead POCO"). This tool
impersonates the backend's heartbeat so the powerbox stays calm and chatty,
and (optionally) holds the OUT2 RS485-satellite rail on.

Run it in the background for the whole maintenance window:

    ./powerbox_maint.py --port /dev/serial/by-id/usb-...699f-if00 --out2 on &
    ...satellite_ota.py work on the gateway port...
    kill %1 && sudo systemctl start prius-backend

Sends {"a":"hb","n":N} every 2 s; prints powerbox STATUS lines so you can
watch out2/pm state.
"""

import argparse
import json
import sys
import time

import serial


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--port", required=True, help="powerbox serial port")
    ap.add_argument("--out2", choices=["on", "off", "keep"], default="keep",
                    help="switch the RS485 satellite rail (default: keep)")
    ap.add_argument("--quiet", action="store_true", help="don't echo STATUS")
    args = ap.parse_args()

    ser = serial.Serial(args.port, 115200, timeout=0.2)
    n = 0
    last_hb = 0.0
    out2_sent = False
    print("powerbox maintenance heartbeat running (Ctrl-C to stop)")
    try:
        while True:
            now = time.time()
            if now - last_hb >= 2.0:
                ser.write((json.dumps(
                    {"id": 0, "d": {"a": "hb", "n": n & 0xFF}}) + "\n").encode())
                n += 1
                last_hb = now
                # Rail command after the second hb: TX/host-present gate is
                # open by then, so we can see the change in STATUS.
                if args.out2 != "keep" and not out2_sent and n >= 2:
                    ser.write((json.dumps(
                        {"id": 0, "d": {"a": "out", "ch": 2,
                                        "on": args.out2 == "on"}}) + "\n").encode())
                    out2_sent = True
            line = ser.readline().strip()
            if line and not args.quiet:
                sys.stdout.write(line.decode(errors="replace") + "\n")
                sys.stdout.flush()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
