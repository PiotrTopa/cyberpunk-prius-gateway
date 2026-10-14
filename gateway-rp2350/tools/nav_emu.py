#!/usr/bin/env python3
"""
nav_emu — stand in for the Prius nav ECU (AVC-LAN 178, logical 58) through the gateway.

  nav_emu.py LOG.ndjson [--port P] [--pol lo|hi] [--no-burst] [--no-btn-ack] [--announce]

Start it BEFORE the car wakes the bus: the display (110) only talks to a nav that
answers its startup roll call. Replies are replayed from captures/2026-10-07/run1_nav
(see NAV_EMULATION_SPEC.md). Everything received/sent is logged like avc_capture.py.

fw 3.2.0: --fw-ack makes the gateway stretch the ACK slots of frames addressed to
178 and --fw-auto lets it answer the roll call itself (<1 ms, before the climate ECU).
Without --fw-ack the display's requests to 178 die unACKed at the address field and
never reach the host (2026-10-14: 464 aborted 110->178 headers in 40 s).
"""
import argparse
import json
import signal
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from gwctl import find_port, open_port, send  # noqa: E402

ME = "178"
# reply to 00 12 58 8F. Real nav 2026-10-07 (display UI came up Dutch when replayed) vs 2026-10-14 after
# English was selected in the nav's language menu: bytes 4, 8 and 10 differ.
IDENT_NL = "02 F9 D1 3D 0A 58 A6 E4 80 8C"
IDENT_EN = "02 F9 D1 13 0A 58 A6 9A 80 80"
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
        self.screen = None        # display's active screen from 110->FFF 12 01 60 XX
        self.ack_release = True
        self.ident = IDENT_EN
        self.time_fmt = "new"
        self.lang = "02"
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
    def time_reply(self):
        """run1 (2026-10-07) nav: 00 03 01 23 29 25 FF (hh mm ss BCD, clock running);
        2026-10-14 nav: 00 01 01 00 00 17 FF (clock counting from 00:00:00 since the nav page opened).
        --time-fmt old|new selects the two leading bytes (00 03 vs 00 01)."""
        lt = time.localtime()
        hh, mm, ss = bcd(lt.tm_hour), bcd(lt.tm_min), bcd(lt.tm_sec)
        return ("00 03 01 " if self.time_fmt == "old" else "00 01 01 ") + f"{hh} {mm} {ss} FF"

    def start_periodic(self):
        if self.periodic_on:
            return
        self.periodic_on = True
        self.say("periodic heartbeats on")

        def beat():
            if stop:
                return
            # run1_nav (2026-10-07): the real nav broadcasts these only while the display is on
            # the nav screen (12 01 60 58 ..). Sending 58 31 F1 02 00 while another screen is
            # up makes the display ask 00 12 58 43 02 00 every second (emu6, 2026-10-14).
            if self.screen == "58":
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
            self.tx(DISP, "00 58 12 9F " + self.ident, delay=0.04)
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
            self.tx(DISP, "00 58 56 B7 %s" % self.lang, delay=0.06)
            self.tx(DISP, "00 58 56 9E " + self.time_reply(), delay=0.08)
            self.at(5.0, steady)

        fast()
        self.at(1.2, self.initial_burst)
        self.at(3.0, self.start_periodic)
        self.at(4.0, steady)

    def on_frame(self, d):
        m, s, data = d.get("m"), d.get("s"), " ".join(d.get("d", []))
        if m != DISP:
            return
        if data.startswith("12 01 60 ") and len(d["d"]) >= 4:
            if d["d"][3] != self.screen:
                self.screen = d["d"][3]
                self.say(f"display screen -> {self.screen}")
        # 60 s re-registration ping 12 01 20 XX: every device answers 00 01 12 30 XX (run1: nav FF, 1C6 00)
        if data.startswith("12 01 20 ") and len(d["d"]) == 4:
            self.tx(DISP, "00 01 12 30 %s FF" % d["d"][3])
            return
        # roll call (broadcast)
        if data == "12 01 00":
            if self.fw_auto:
                self.say("roll call 12 01 00 (gateway auto-reply slot 0 answers)")
            else:
                self.say("roll call 12 01 00 -> announcing 58 24 85 (delay %.0f ms)" % (self.rc_delay * 1000))
                self.tx(DISP, "00 01 12 10 58 24 85", delay=self.rc_delay)
        elif data == "12 01 01":
            if not self.fw_auto:
                self.tx(DISP, "00 01 12 12 58 28 29 32 60 74 A4 56")
        elif data == "00 01 07":
            self.tx(DISP, "00 01 00 17")
        elif s != ME:
            return
        # unicast to 178
        elif data == "00 12 58 8F":               # identification / settings, polled every 30 s
            self.tx(DISP, "00 58 12 9F " + self.ident)
        elif data.startswith("00 12 01 02 17 80"):
            self.tx(DISP, "00 01 12 12 27 58 40 64 62 61 55 6E 6D")
        elif data.startswith("00 12 01 02 17 81"):
            self.tx(DISP, "00 01 12 12 34 A2 58 43 63 65 44 45 E0")
        elif data.startswith("00 12 01 02 11 00 17 82"):
            self.say("setup done -> initial burst")
            self.initial_burst()
        elif data == "00 32 58 E0":
            self.tx(DISP, "00 58 32 F0 C9 00 00 01")
        elif data == "00 6E 58 E0":
            self.tx(DISP, "00 58 6E F0 C9 00 00 01")
        elif data.startswith("00 56 58 F0"):       # display settings query; reply B7 LL = UI language (06 Dutch, 02 English)
            self.tx(DISP, "00 58 56 B7 %s" % self.lang)
        elif data == "00 32 58 F0 00 00 00 02":     # run1 nav answered this with B7 06 as well
            self.tx(DISP, "00 58 56 B7 %s" % self.lang)
        elif data == "00 56 58 8E":                # time/status request every 5 s on the nav screen
            self.tx(DISP, "00 58 56 9E " + self.time_reply())
        elif data == "00 12 58 42 02 01":          # screen request granted
            self.tx(DISP, "00 58 12 52 02 01")
            self.tx("1FF", "58 31 F1 02 00", bcast=True, delay=0.004)
            self.screen = "58"
            self.start_periodic()
        elif data == "00 12 58 43 02 00":          # screen release request (sent when leaving the nav screen;
            # the display retries 1/s for ~3 s then switches anyway - emu7). Reply by analogy with 42->52.
            if self.ack_release:
                self.tx(DISP, "00 58 12 53 02 00")
                self.tx("1FF", "58 31 F1 00 00", bcast=True, delay=0.002)   # real nav: "my screen is off"
            else:
                self.say("display asks 12 58 43 02 00 (screen release) - not answered (--no-release-ack)")
            self.screen = None
        elif data.startswith("00 25 58 80"):      # info-screen soft buttons: 01 maintenance, 08 calendar, 40 language
            key = d["d"][4]
            self.say(f"SOFT BUTTON {key} ({ {'01': 'maintenance', '08': 'calendar', '40': 'language'}.get(key, '?') })")
            if self.btn_ack:
                self.tx(DISP, "00 58 12 50 02 01")
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
    ap.add_argument("--pol", choices=["lo", "hi"], default="lo",
                    help="AVC RX polarity (PHY board fixed 2026-10-08 needs hi)")
    ap.add_argument("--lang", default="02",
                    help="display UI language code sent in 00 58 56 B7 LL: 02 English (real nav 2026-10-14), 06 Dutch (run1)")
    ap.add_argument("--time-fmt", choices=["old", "new"], default="new",
                    help="time reply header: old = 00 03 01 (run1 2026-10-07), new = 00 01 01 (real nav 2026-10-14)")
    ap.add_argument("--ident", default=IDENT_EN,
                    help="bytes after 00 58 12 9F in the identification reply (default: the 2026-10-14 English set)")
    ap.add_argument("--no-release-ack", action="store_true",
                    help="do not answer 00 12 58 43 02 00 with 00 58 12 53 02 00 (inferred reply, 2026-10-14)")
    ap.add_argument("--can-sniff", action="store_true",
                    help="fw>=3.1.0: also stream every CAN frame into the log (sniff on; off again at exit)")
    ap.add_argument("--raw", action="store_true",
                    help="also stream raw pulse widths into the log (avc_raw on) to see aborted/unACKed frames")
    ap.add_argument("--fw-ack", action="store_true",
                    help="fw>=3.2.0: gateway stretches the ACK slots of frames addressed to 178 (avc_cfg ack)")
    ap.add_argument("--fw-auto", action="store_true",
                    help="fw>=3.2.0: let the gateway answer 12 01 00 / 12 01 01 itself (~0.3 ms, before the climate ECU)")
    ap.add_argument("--rc-delay", type=float, default=0.0,
                    help="ms to wait before answering 12 01 00 (2026-10-14: our USB-latency answer at ~2.5 ms "
                         "collides with the climate ECU's; the real nav answers within 0.5 ms)")
    ap.add_argument("--rc-retries", type=int, default=3,
                    help="resend the roll-call answer this many times if the display NAKs it")
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
        emu.rc_retries = 0
        emu.rc_delay = args.rc_delay / 1000.0
        emu.fw_auto = args.fw_auto
        emu.ack_release = not args.no_release_ack
        emu.ident = args.ident
        emu.time_fmt = args.time_fmt
        emu.lang = args.lang
        if args.fw_auto:
            for slot, match, reply in (
                (0, ["12", "01", "00"], h("00 01 12 10 58 24 85")),
                (1, ["12", "01", "01"], h("00 01 12 12 58 28 29 32 60 74 A4 56")),
            ):
                line = send(ser, {"id": 2, "d": {"a": "auto", "slot": slot, "on": True, "m": DISP, "s": "FFF", "d": match,
                                                 "tx": {"m": ME, "s": DISP, "c": 15, "d": reply}}})
                emu.say(f"auto slot {slot} set")
        send(ser, {"id": 0, "d": {"a": "avc_cfg", "pol": args.pol}})
        if args.raw:
            send(ser, {"id": 0, "d": {"a": "avc_raw", "on": True}})
        if args.fw_ack:
            send(ser, {"id": 0, "d": {"a": "avc_cfg", "ack": ME}})
        if args.can_sniff:
            send(ser, {"id": 1, "d": {"a": "sniff", "on": True}})
        emu.say(f"nav_emu up (pol {args.pol}); waiting for the display's roll call")
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
                        emu.n_echo = getattr(emu, "n_echo", 0) + 1
                        if emu.n_echo <= 3:
                            emu.say("our TX echoed OK" + (" (NAK)" if d.get("nak") else "") + ": " + " ".join(d.get("d", [])))
                        elif d.get("nak"):
                            emu.say("our TX NAKed: " + " ".join(d.get("d", [])))
                        # roll-call answer not acknowledged by the display: resend at once (2026-10-14 cold start: first answer NAKed, never retried)
                        if d.get("nak") and " ".join(d.get("d", [])) == "00 01 12 10 58 24 85" and emu.rc_retries < args.rc_retries:
                            emu.rc_retries += 1
                            emu.say(f"roll-call answer NAKed -> retry {emu.rc_retries}")
                            emu.tx(DISP, "00 01 12 10 58 24 85")
                        continue
                    if d.get("s") == ME and d.get("nak"):
                        naks += 1
                    emu.on_frame(d)
                elif obj.get("id") == 0 and "err" in obj.get("d", {}):
                    emu.say("gateway error: " + json.dumps(obj["d"]))
        if args.raw:
            send(ser, {"id": 0, "d": {"a": "avc_raw", "on": False}})
        if args.fw_ack:
            send(ser, {"id": 0, "d": {"a": "avc_cfg", "ack": "000"}})
        if args.can_sniff:
            send(ser, {"id": 1, "d": {"a": "sniff", "on": False}})
        if args.fw_auto:
            for slot in (0, 1):
                send(ser, {"id": 2, "d": {"a": "auto", "slot": slot, "on": False}})
        emu.say(f"stopping; tx={emu.n_tx}, echoes={getattr(emu, 'n_echo', 0)}, display->178 NAKed={naks}")


if __name__ == "__main__":
    main()
