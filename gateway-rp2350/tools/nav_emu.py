#!/usr/bin/env python3
"""
nav_emu — stand in for the Prius nav ECU (AVC-LAN 178, logical 58) through the gateway.

  nav_emu.py LOG.ndjson [--port P] [--no-burst] [--no-btn-ack] [--announce]

Start it BEFORE the car wakes the bus: the display (110) only talks to a nav that
answers its startup roll call. Replies are replayed from captures/2026-10-07/run1_nav
(see NAV_EMULATION_SPEC.md). Everything received/sent is logged like avc_capture.py.

Limitation: gateway v3 cannot ACK frames addressed to 178 (passive RX), so the
display's unicast requests to 178 will show up NAKed. Watch whether it carries on.
"""
import argparse
import json
import signal
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from gwctl import find_port, open_port, send  # noqa: E402

ME = "178"
DISP = "110"
AUDIO = "1C6"

stop = False


def h(s):
    return s.split()


def bcd(n):
    return "%02X" % ((n // 10) * 16 + n % 10)


class Emu:
    def __init__(self, ser, log, burst=True, btn_ack=True):
        self.ser, self.log = ser, log
        self.burst, self.btn_ack = burst, btn_ack
        self.timers = []          # (due_monotonic, fn)
        self.periodic_on = False
        self.n_tx = 0

    # --- io ---
    def tx(self, slave, data, bcast=False, delay=0.0):
        def go():
            d = {"m": ME, "s": slave, "c": 15, "d": h(data)}
            if bcast:
                d["b"] = True
            line = send(self.ser, {"id": 2, "d": d})
            self.n_tx += 1
            self.write({"tx": d})
            return line
        if delay:
            self.at(delay, go)
        else:
            go()

    def at(self, delay, fn):
        self.timers.append((time.monotonic() + delay, fn))

    def write(self, rec):
        rec["ht"] = time.time()
        self.log.write(json.dumps(rec, separators=(",", ":")) + "\n")

    def say(self, msg):
        print(time.strftime("%H:%M:%S"), msg, flush=True)
        self.write({"note": msg})

    # --- behaviour ---
    def start_periodic(self):
        if self.periodic_on:
            return
        self.periodic_on = True
        self.say("periodic heartbeats on")

        def beat():
            if stop:
                return
            self.tx("1FF", "58 31 F1 02 00", bcast=True)
            self.tx("FFF", "58 01 DB 00 00 00 00 00 00", bcast=True, delay=0.6)
            self.at(5.0, beat)
        self.at(1.0, beat)

    def initial_burst(self):
        if not self.burst:
            return
        self.tx(DISP, "00 58 32 E0")
        self.tx(AUDIO, "00 85 E0 E0", delay=0.003)
        self.tx(DISP, "00 58 56 E0", delay=0.007)
        self.tx(DISP, "00 58 34 E0", delay=0.010)
        self.tx(AUDIO, "00 85 E0 E4", delay=0.016)
        self.tx(AUDIO, "00 85 E0 E6", delay=0.019)
        for k in range(1, 4):                       # repeated 3x at 300 ms in run 1
            self.tx(DISP, "00 58 32 E0", delay=0.3 * k + 0.05)
            self.tx(DISP, "00 58 56 E0", delay=0.3 * k + 0.053)
            self.tx(DISP, "00 58 34 E0", delay=0.3 * k + 0.057)

    def blind(self, duration_fast=20.0):
        """No RX: push the startup answers on a timer, then steady-state traffic."""
        t0 = time.monotonic()
        self.say("BLIND mode: transmitting without listening")

        def fast():
            if stop:
                return
            self.tx(DISP, "00 01 12 10 58 24 85")
            self.tx(DISP, "00 01 12 12 58 28 29 32 60 74 A4 56", delay=0.02)
            self.tx(DISP, "00 58 12 9F 02 F9 D1 3D 0A 58 A6 E4 80 8C", delay=0.04)
            self.tx(DISP, "00 01 12 12 27 58 40 64 62 61 55 6E 6D", delay=0.06)
            self.tx(DISP, "00 01 12 12 34 A2 58 43 63 65 44 45 E0", delay=0.08)
            self.tx(DISP, "00 01 00 17", delay=0.10)
            if time.monotonic() - t0 < duration_fast:
                self.at(1.0, fast)

        def steady():
            if stop:
                return
            self.tx(DISP, "00 01 12 10 58 24 85")
            self.tx(DISP, "00 58 32 F0 C9 00 00 01", delay=0.02)
            self.tx(DISP, "00 58 6E F0 C9 00 00 01", delay=0.04)
            self.tx(DISP, "00 58 56 B7 06", delay=0.06)
            self.tx(DISP, "00 58 56 9E 00 03 01 23 31 %s FF" % bcd(int(time.time()) % 60), delay=0.08)
            self.at(5.0, steady)

        fast()
        self.at(1.2, self.initial_burst)
        self.at(3.0, self.start_periodic)
        self.at(4.0, steady)

    def on_frame(self, d):
        m, s, data = d.get("m"), d.get("s"), " ".join(d.get("d", []))
        if m != DISP:
            return
        # roll call (broadcast)
        if data == "12 01 00":
            self.say("roll call 12 01 00 -> announcing 58 24 85")
            self.tx(DISP, "00 01 12 10 58 24 85")
        elif data == "12 01 01":
            self.tx(DISP, "00 01 12 12 58 28 29 32 60 74 A4 56")
        elif data == "00 01 07":
            self.tx(DISP, "00 01 00 17")
        elif s != ME:
            return
        # unicast to 178
        elif data == "00 12 58 8F":
            self.tx(DISP, "00 58 12 9F 02 F9 D1 3D 0A 58 A6 E4 80 8C")
        elif data.startswith("00 12 01 02 17 80"):
            self.tx(DISP, "00 01 12 12 27 58 40 64 62 61 55 6E 6D")
        elif data.startswith("00 12 01 02 17 81"):
            self.tx(DISP, "00 01 12 12 34 A2 58 43 63 65 44 45 E0")
        elif data.startswith("00 12 01 02 11 00 17 82"):
            self.say("setup done -> initial burst")
            self.initial_burst()
            self.start_periodic()
        elif data == "00 32 58 E0":
            self.tx(DISP, "00 58 32 F0 C9 00 00 01")
        elif data == "00 6E 58 E0":
            self.tx(DISP, "00 58 6E F0 C9 00 00 01")
        elif data == "00 56 58 F0 49 3C 44":
            self.tx(DISP, "00 58 56 B7 06")
        elif data == "00 56 58 8E":
            self.tx(DISP, "00 58 56 9E 00 03 01 23 31 %s FF" % bcd(int(time.time()) % 60))
            self.start_periodic()
        elif data == "00 12 58 42 02 01":
            self.tx(DISP, "00 58 12 52 02 01")
            self.tx("1FF", "58 31 F1 02 00", bcast=True, delay=0.004)
        elif data.startswith("00 25 58 84"):
            key = d["d"][4]
            self.say(f"BUTTON {key}" + ("" if key != "00" else " (release)"))
            if key != "00" and self.btn_ack:
                self.tx(DISP, "00 58 12 50 02 01", delay=0.004)
        elif data.startswith("00 21 24 78"):
            self.say("TOUCH " + " ".join(d["d"][4:]))

    def pump(self):
        now = time.monotonic()
        due = [t for t in self.timers if t[0] <= now]
        self.timers = [t for t in self.timers if t[0] > now]
        for _, fn in sorted(due, key=lambda t: t[0]):
            fn()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--port")
    ap.add_argument("--no-burst", action="store_true", help="skip the 58->display/85->audio burst")
    ap.add_argument("--no-btn-ack", action="store_true", help="do not answer button presses")
    ap.add_argument("--announce", action="store_true",
                    help="bus already awake: send roll-call answers + heartbeats unsolicited")
    ap.add_argument("--blind", action="store_true",
                    help="RX unusable (H1 in TX-correct orientation): transmit on a timer, start once the car is ON")
    args = ap.parse_args()

    def on_term(*_):
        global stop
        stop = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    with open_port(find_port(args.port)) as ser, open(args.log, "a", buffering=1) as log:
        ser.timeout = 0.002
        emu = Emu(ser, log, burst=not args.no_burst, btn_ack=not args.no_btn_ack)
        send(ser, {"id": 0, "d": {"a": "avc_cfg", "pol": "lo"}})
        emu.say("nav_emu up (pol lo); waiting for the display's roll call")
        if args.blind:
            emu.blind()
        elif args.announce:
            emu.tx(DISP, "00 01 12 10 58 24 85")
            emu.tx(DISP, "00 01 12 12 58 28 29 32 60 74 A4 56", delay=0.05)
            emu.start_periodic()
        naks = 0
        buf = b""
        while not stop:
            emu.pump()
            chunk = ser.read(4096)
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                rec = {"hm": time.monotonic(), "raw": raw.decode(errors="replace").rstrip()}
                try:
                    obj = json.loads(raw)
                except ValueError:
                    obj = None
                if obj is not None:
                    rec["obj"] = obj
                emu.write(rec)
                if not obj:
                    continue
                if obj.get("id") == 2:
                    d = obj["d"]
                    if d.get("echo"):
                        if d.get("nak"):
                            emu.say("our TX NAKed: " + " ".join(d.get("d", [])))
                        continue
                    if d.get("s") == ME and d.get("nak"):
                        naks += 1
                    emu.on_frame(d)
                elif obj.get("id") == 0 and "err" in obj.get("d", {}):
                    emu.say("gateway error: " + json.dumps(obj["d"]))
        emu.say(f"stopping; tx={emu.n_tx}, display->178 NAKed={naks}")


if __name__ == "__main__":
    main()
