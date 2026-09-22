#!/usr/bin/env python3
"""
gwctl — talk to the gateway over USB-CDC (NDJSON).

  gwctl.py monitor [--avc-only] [--latency]   stream everything the gateway says
  gwctl.py whoami                             IDENT round trip (also measures RTT)
  gwctl.py stats                              counters snapshot
  gwctl.py raw [--seconds N] [--csv FILE]     AVC-LAN raw pulse widths (bring-up)
  gwctl.py avc M S C [D ...]                  transmit an AVC-LAN frame (hex fields)
  gwctl.py req I D... [--resp R ...] [--t MS] [--isotp]   one CAN request
  gwctl.py sub SLOT I D... [--int MS] ...     add a subscription; 'unsub SLOT|all'
  gwctl.py mode normal|listen                 CAN controller mode
  gwctl.py send '<json line>'                 send a raw command line
  gwctl.py bootsel                            reboot into the UF2 bootloader
  gwctl.py reset

Port: --port, or $GW_PORT, or the first /dev/serial/by-id/*Prius_Gateway* match.

The backend holds the port open in the car; stop it first (see
satellites/README.md "Maintenance window").
"""
import argparse
import glob
import json
import os
import sys
import time

try:
    import serial
except ImportError:
    sys.exit("pip install pyserial")


def find_port(explicit):
    if explicit:
        return explicit
    if os.environ.get("GW_PORT"):
        return os.environ["GW_PORT"]
    cands = sorted(glob.glob("/dev/serial/by-id/*Prius_Gateway*"))
    if cands:
        return cands[0]
    cands = sorted(glob.glob("/dev/ttyACM*"))
    if cands:
        return cands[0]
    sys.exit("no gateway port found; use --port")


def open_port(path):
    return serial.Serial(path, 1_000_000, timeout=0.05)


def send(ser, obj):
    line = json.dumps(obj, separators=(",", ":")) + "\n"
    ser.write(line.encode())
    return line


def lines(ser, seconds=None):
    """Yield (host_time, parsed_or_None, raw) until timeout."""
    t_end = None if seconds is None else time.monotonic() + seconds
    while t_end is None or time.monotonic() < t_end:
        raw = ser.readline()
        if not raw:
            continue
        now = time.monotonic()
        try:
            obj = json.loads(raw)
        except ValueError:
            obj = None
        yield now, obj, raw.decode(errors="replace").rstrip()


def fmt_avc(d):
    data = " ".join(d.get("d", []))
    flags = "".join(k for k in ("b", "nak", "echo") if d.get(k))
    return f"{d.get('m')}->{d.get('s')} c={d.get('c'):X} [{data}]" + (f" {{{flags}}}" if flags else "")


def cmd_monitor(args, ser):
    print(f"# monitoring {ser.port} (Ctrl-C to stop)")
    # latency estimate: compare gateway ts deltas against host arrival deltas
    prev = None
    for host_t, obj, raw in lines(ser):
        if obj is None:
            print("?", raw)
            continue
        dev = obj.get("id")
        if args.avc_only and dev != 2:
            continue
        stamp = time.strftime("%H:%M:%S") + f".{int((host_t % 1) * 1000):03d}"
        if dev == 2:
            extra = ""
            if args.latency and prev is not None and obj.get("ts") is not None:
                d_host = (host_t - prev[0]) * 1000.0
                d_gw = obj["ts"] - prev[1]
                extra = f"  dt_host={d_host:7.1f}ms dt_gw={d_gw:5d}ms skew={d_host - d_gw:+6.1f}ms"
            if obj.get("ts") is not None:
                prev = (host_t, obj["ts"])
            print(f"{stamp} AVC  {fmt_avc(obj['d'])}{extra}")
        elif dev == 1:
            print(f"{stamp} CAN  {json.dumps(obj['d'])}")
        elif dev == 0:
            d = obj["d"]
            if d.get("msg") == "GW_HB" and not args.hb:
                continue
            print(f"{stamp} SYS  {json.dumps(d)}")
        else:
            print(f"{stamp} SAT{dev} {json.dumps(obj['d'])}")


def cmd_whoami(args, ser):
    ser.reset_input_buffer()
    t0 = time.monotonic()
    send(ser, {"id": 0, "d": {"a": "whoami"}})
    for host_t, obj, raw in lines(ser, 2.0):
        if obj and obj.get("id") == 0 and obj["d"].get("msg") == "IDENT":
            print(json.dumps(obj["d"]), f"  rtt={1000 * (host_t - t0):.1f} ms")
            return
    sys.exit("no IDENT reply")


def cmd_stats(args, ser):
    ser.reset_input_buffer()
    send(ser, {"id": 0, "d": {"a": "stats"}})
    for _, obj, raw in lines(ser, 2.0):
        if obj and obj.get("id") == 0 and "stats" in obj["d"]:
            print(json.dumps(obj["d"]["stats"], indent=2))
            return
    sys.exit("no stats reply")


def cmd_raw(args, ser):
    send(ser, {"id": 0, "d": {"a": "avc_raw", "on": True}})
    out = open(args.csv, "w") if args.csv else None
    if out:
        out.write("kind,us\n")
    n = 0
    t_end = time.monotonic() + args.seconds
    try:
        for _, obj, raw in lines(ser, args.seconds):
            if not obj or obj.get("id") != 0 or "avc_raw" not in obj["d"]:
                continue
            vals = obj["d"]["avc_raw"]
            if not isinstance(vals, list):
                continue
            n += len(vals)
            if out:
                for v in vals:
                    out.write(("gap,%d\n" % -v) if v < 0 else ("dom,%d\n" % v))
            else:
                print(" ".join(f"{v:+d}" for v in vals))
            if time.monotonic() > t_end:
                break
    finally:
        send(ser, {"id": 0, "d": {"a": "avc_raw", "on": False}})
        if out:
            out.close()
    print(f"# {n} pulses captured", file=sys.stderr)


def cmd_avc(args, ser):
    d = {"m": args.master, "s": args.slave, "c": int(args.control, 16), "d": [x.upper() for x in args.data]}
    if args.broadcast:
        d["b"] = True
    print(send(ser, {"id": 2, "d": d}).strip())
    for _, obj, raw in lines(ser, 1.0):
        if obj and (obj.get("id") == 2 and obj["d"].get("echo") or obj.get("id") == 0 and "err" in obj["d"]):
            print(raw)
            return


def build_query(args):
    d = {"i": args.i, "d": [int(x, 0) for x in args.data]}
    if args.resp:
        d["r"] = args.resp
    if args.t:
        d["t"] = args.t
    if args.isotp:
        d["isotp"] = True
    return d


def cmd_req(args, ser):
    d = build_query(args)
    d["a"] = "req"
    ser.reset_input_buffer()
    t0 = time.monotonic()
    print(send(ser, {"id": 1, "d": d}).strip())
    for host_t, obj, raw in lines(ser, (args.t or 100) / 1000.0 + 2.0):
        if obj and obj.get("id") == 1 and obj["d"].get("a") == "resp":
            print(raw, f"  ({1000 * (host_t - t0):.0f} ms)")
            return
        if obj and obj.get("id") == 0 and "err" in obj["d"]:
            print(raw)
            return
    print("no response")


def cmd_sub(args, ser):
    d = build_query(args)
    d.update({"a": "sub", "slot": args.slot, "int": args.interval})
    print(send(ser, {"id": 1, "d": d}).strip())
    for _, obj, raw in lines(ser, 1.0):
        if obj and obj.get("id") == 0 and (obj["d"].get("msg") in ("SUB_OK",) or "err" in obj["d"]):
            print(raw)
            return


def cmd_unsub(args, ser):
    slot = "all" if args.slot == "all" else int(args.slot)
    print(send(ser, {"id": 1, "d": {"a": "unsub", "slot": slot}}).strip())
    for _, obj, raw in lines(ser, 1.0):
        if obj and obj.get("id") == 0 and (str(obj["d"].get("msg", "")).startswith("UNSUB") or "err" in obj["d"]):
            print(raw)
            return


def cmd_mode(args, ser):
    print(send(ser, {"id": 1, "d": {"a": "mode", "m": args.mode}}).strip())
    for _, obj, raw in lines(ser, 1.0):
        if obj and obj.get("id") == 0 and (obj["d"].get("msg") == "CAN_MODE" or "err" in obj["d"]):
            print(raw)
            return


def cmd_send(args, ser):
    ser.write((args.line.strip() + "\n").encode())
    for _, obj, raw in lines(ser, args.wait):
        print(raw)


def cmd_simple(action):
    def run(args, ser):
        print(send(ser, {"id": 0, "d": {"a": action}}).strip())
        for _, obj, raw in lines(ser, 0.5):
            print(raw)
    return run


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("monitor"); p.add_argument("--avc-only", action="store_true")
    p.add_argument("--latency", action="store_true", help="show gateway-vs-host inter-frame timing skew")
    p.add_argument("--hb", action="store_true", help="also show heartbeats"); p.set_defaults(fn=cmd_monitor)
    sp.add_parser("whoami").set_defaults(fn=cmd_whoami)
    sp.add_parser("stats").set_defaults(fn=cmd_stats)
    p = sp.add_parser("raw"); p.add_argument("--seconds", type=float, default=5.0); p.add_argument("--csv")
    p.set_defaults(fn=cmd_raw)
    p = sp.add_parser("avc"); p.add_argument("master"); p.add_argument("slave"); p.add_argument("control")
    p.add_argument("data", nargs="*"); p.add_argument("--broadcast", action="store_true"); p.set_defaults(fn=cmd_avc)
    for name, fn in (("req", cmd_req), ("sub", cmd_sub)):
        p = sp.add_parser(name)
        if name == "sub":
            p.add_argument("slot", type=int)
        p.add_argument("i", help="request CAN id, e.g. 0x7E2")
        p.add_argument("data", nargs="+", help="request bytes, e.g. 0x02 0x21 0xC3")
        p.add_argument("--resp", nargs="*", help="expected response ids, e.g. 0x7EA")
        p.add_argument("--t", type=int, help="timeout ms")
        p.add_argument("--isotp", action="store_true")
        if name == "sub":
            p.add_argument("--int", dest="interval", type=int, default=1000)
        p.set_defaults(fn=fn)
    p = sp.add_parser("unsub"); p.add_argument("slot"); p.set_defaults(fn=cmd_unsub)
    p = sp.add_parser("mode"); p.add_argument("mode", choices=["normal", "listen"]); p.set_defaults(fn=cmd_mode)
    p = sp.add_parser("send"); p.add_argument("line"); p.add_argument("--wait", type=float, default=1.0)
    p.set_defaults(fn=cmd_send)
    sp.add_parser("bootsel").set_defaults(fn=cmd_simple("bootsel"))
    sp.add_parser("reset").set_defaults(fn=cmd_simple("reset"))

    args = ap.parse_args()
    with open_port(find_port(args.port)) as ser:
        try:
            args.fn(args, ser)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
