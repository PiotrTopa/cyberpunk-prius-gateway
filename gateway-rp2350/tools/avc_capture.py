#!/usr/bin/env python3
"""
avc_capture — log everything the gateway says, losslessly, for later diffing.

  avc_capture.py OUT.ndjson [--port P] [--seconds N] [--obd [MS]] [--can-sniff [all|chg]]

Each output line is {"ht": <unix time>, "hm": <host monotonic>, "raw": <line>}
plus "obj" when the line parsed as JSON. Stops on Ctrl-C / SIGTERM / --seconds.
Sending SIGUSR1 writes a {"mark": n} line (event markers: ignition on, etc.).

--obd polls engine RPM, speed, coolant temp and engine load (OBD-II mode 01,
0x7E0 -> 0x7E8) through gateway CAN subscriptions every MS ms (default 500).
This switches the gateway CAN controller out of listen-only (it transmits the
requests); on exit the subscriptions are dropped and listen-only is restored.

--can-sniff (firmware >= 3.1.0) streams every CAN frame listen-only alongside AVC
("chg" = only frames whose payload changed). Turned off again on exit.
"""
import argparse
import json
import signal
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from gwctl import find_port, open_port, send  # noqa: E402

stop = False
marks = 0

OBD_PIDS = {0x0C: "rpm", 0x0D: "speed", 0x05: "coolant", 0x04: "load"}


def obd_start(ser, interval):
    for slot, pid in enumerate(OBD_PIDS):
        send(ser, {"id": 1, "d": {"a": "sub", "slot": slot, "i": "0x7E0", "d": [2, 1, pid],
                                  "r": ["0x7E8"], "t": 100, "int": interval}})


def obd_stop(ser):
    send(ser, {"id": 1, "d": {"a": "unsub", "slot": "all"}})
    send(ser, {"id": 1, "d": {"a": "mode", "m": "listen"}})


def main():
    global marks
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--port")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--obd", nargs="?", const=500, type=int, metavar="MS")
    ap.add_argument("--can-sniff", nargs="?", const="all", choices=["all", "chg"])
    args = ap.parse_args()

    def on_term(*_):
        global stop
        stop = True

    pending = []

    def on_mark(*_):
        pending.append(time.time())

    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    signal.signal(signal.SIGUSR1, on_mark)

    port = find_port(args.port)
    t_end = None if args.seconds is None else time.monotonic() + args.seconds
    n = 0
    with open_port(port) as ser, open(args.out, "a", buffering=1) as f:
        f.write(json.dumps({"ht": time.time(), "start": port, "obd": args.obd, "can_sniff": args.can_sniff}) + "\n")
        if args.obd:
            obd_start(ser, args.obd)
        if args.can_sniff:
            send(ser, {"id": 1, "d": {"a": "sniff", "on": True, "chg": args.can_sniff == "chg"}})
        while not stop and (t_end is None or time.monotonic() < t_end):
            while pending:
                marks += 1
                f.write(json.dumps({"ht": pending.pop(0), "mark": marks}) + "\n")
            raw = ser.readline()
            if not raw:
                continue
            rec = {"ht": time.time(), "hm": time.monotonic(),
                   "raw": raw.decode(errors="replace").rstrip()}
            try:
                rec["obj"] = json.loads(raw)
            except ValueError:
                pass
            f.write(json.dumps(rec, separators=(",", ":")) + "\n")
            n += 1
        if args.can_sniff:
            send(ser, {"id": 1, "d": {"a": "sniff", "on": False}})
            time.sleep(0.2)
        if args.obd:
            obd_stop(ser)
            time.sleep(0.2)
        f.write(json.dumps({"ht": time.time(), "stop": n}) + "\n")
    print(f"# {n} lines -> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
