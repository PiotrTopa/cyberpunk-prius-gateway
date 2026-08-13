#!/usr/bin/env python3
"""
satellite_ota.py — update satellite Python code over RS485 (via the gateway).

Talks NDJSON to the gateway's USB CDC port; the gateway transparently
forwards frames with id > 5 to the RS485 bus and mirrors satellite replies
back. Implements the FW_* protocol from satellites/common/ota.py:
stop-and-wait chunks, sha256 verification, staged files, atomic commit.

Maintenance-mode usage (backend stopped, satellite rail powered):

    # Show what's on the satellite
    ./satellite_ota.py --port /dev/ttyACM0 --dev 110 info

    # Sync a satellite directory (only changed .py files), commit + reboot
    ./satellite_ota.py --port /dev/ttyACM0 --dev 110 sync satellites/vfd/

    # Push specific files
    ./satellite_ota.py --port /dev/ttyACM0 --dev 102 push satellites/light/main.py

    # Recover / restart
    ./satellite_ota.py --port /dev/ttyACM0 --dev 110 abort
    ./satellite_ota.py --port /dev/ttyACM0 --dev 110 reboot
"""

import argparse
import base64
import hashlib
import json
import os
import sys
import time

import serial

CHUNK_SIZE = 512          # raw bytes per FW_DATA frame (b64 fits rxbuf=2048)
ACK_TIMEOUT_S = 2.0
RETRIES = 3


class OtaError(Exception):
    pass


class SatelliteLink:
    """NDJSON request/response to one satellite through the gateway port."""

    def __init__(self, port, dev_id, baud=115200, verbose=False):
        self.dev_id = dev_id
        self.verbose = verbose
        self.ser = serial.Serial(port, baud, timeout=0.05)

    def send(self, payload):
        frame = json.dumps({"id": self.dev_id, "d": payload},
                           separators=(",", ":")) + "\n"
        if self.verbose:
            print(">>", frame.strip())
        self.ser.write(frame.encode())

    def wait_reply(self, cmd, timeout=ACK_TIMEOUT_S):
        """Wait for a reply from our device carrying "cmd" == cmd."""
        deadline = time.monotonic() + timeout
        buf = b""
        while time.monotonic() < deadline:
            buf += self.ser.read(4096)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except ValueError:
                    continue
                if self.verbose:
                    print("<<", line.decode(errors="replace"))
                if obj.get("id") != self.dev_id:
                    continue
                d = obj.get("d") or {}
                if d.get("cmd") == cmd:
                    return d
        return None

    def request(self, payload, timeout=ACK_TIMEOUT_S, retries=RETRIES):
        """Send + wait for matching reply, with retries (stop-and-wait ARQ)."""
        cmd = payload["cmd"]
        for attempt in range(retries):
            self.send(payload)
            d = self.wait_reply(cmd, timeout)
            if d is not None:
                return d
            print("  .. no reply to %s (attempt %d/%d)" % (cmd, attempt + 1, retries))
        raise OtaError("no reply to %s from device %d" % (cmd, self.dev_id))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def fw_info(link):
    d = link.request({"cmd": "FW_INFO"}, timeout=5.0)
    if d.get("res") != "OK":
        raise OtaError("FW_INFO failed: %s" % d)
    return d


def transfer_file(link, local_path, remote_name):
    """Transfer one file into the satellite's staging area and verify it."""
    with open(local_path, "rb") as f:
        data = f.read()
    sha = hashlib.sha256(data).hexdigest()
    nchunks = (len(data) + CHUNK_SIZE - 1) // CHUNK_SIZE

    print("-> %s (%d bytes, %d chunks, sha %s...)" %
          (remote_name, len(data), nchunks, sha[:12]))

    d = link.request({"cmd": "FW_BEGIN", "file": remote_name,
                      "size": len(data), "sha256": sha})
    if d.get("res") != "OK":
        raise OtaError("FW_BEGIN rejected: %s" % d)

    t0 = time.monotonic()
    n = 0
    while n < nchunks:
        raw = data[n * CHUNK_SIZE:(n + 1) * CHUNK_SIZE]
        b64 = base64.b64encode(raw).decode()
        d = link.request({"cmd": "FW_DATA", "n": n, "b": b64})
        if d.get("res") == "OK" and d.get("n") == n:
            n += 1
            if n % 16 == 0 or n == nchunks:
                pct = 100 * n // nchunks
                sys.stdout.write("\r   %3d%% (%d/%d)" % (pct, n, nchunks))
                sys.stdout.flush()
        elif d.get("err") == "SEQ":
            n = int(d["want"])  # resync to what the satellite expects
        else:
            raise OtaError("FW_DATA failed at chunk %d: %s" % (n, d))
    dt = time.monotonic() - t0
    print("  (%.1fs, %.0f B/s)" % (dt, len(data) / dt if dt else 0))

    d = link.request({"cmd": "FW_END"}, timeout=5.0)
    if d.get("res") != "OK":
        raise OtaError("FW_END verification failed: %s" % d)
    print("   verified: %s" % d["sha256"][:12])


def commit_and_reboot(link, reboot):
    d = link.request({"cmd": "FW_COMMIT"}, timeout=5.0)
    if d.get("res") != "OK":
        raise OtaError("FW_COMMIT failed: %s" % d)
    print("committed: %s" % ", ".join(d.get("files", [])))
    if reboot:
        link.request({"cmd": "FW_REBOOT"})
        print("satellite rebooting")


def cmd_info(link, args):
    d = fw_info(link)
    print("proto v%s, %d .py files:" % (d.get("proto"), len(d.get("files", {}))))
    for name, sha in sorted(d.get("files", {}).items()):
        print("  %-24s %s" % (name, sha))


def cmd_push(link, args):
    for path in args.files:
        transfer_file(link, path, os.path.basename(path))
    commit_and_reboot(link, not args.no_reboot)


def cmd_sync(link, args):
    remote = fw_info(link).get("files", {})
    todo = []
    for name in sorted(os.listdir(args.directory)):
        path = os.path.join(args.directory, name)
        if not name.endswith(".py") or not os.path.isfile(path):
            continue
        local_sha = sha256_file(path)
        if remote.get(name) == local_sha:
            print("== %s (up to date)" % name)
        else:
            todo.append((path, name))
    if not todo:
        print("nothing to update")
        return
    for path, name in todo:
        transfer_file(link, path, name)
    commit_and_reboot(link, not args.no_reboot)
    if not args.no_reboot:
        time.sleep(3.0)
        remote = fw_info(link).get("files", {})
        ok = all(remote.get(n) == sha256_file(p) for p, n in todo)
        print("post-reboot verify:", "OK" if ok else "MISMATCH!")


def cmd_abort(link, args):
    print(link.request({"cmd": "FW_ABORT"}))


def cmd_reboot(link, args):
    print(link.request({"cmd": "FW_REBOOT"}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--port", required=True, help="gateway serial port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--dev", type=int, required=True, help="satellite device id")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("info", help="show remote .py manifest")
    p = sub.add_parser("push", help="push specific files, commit + reboot")
    p.add_argument("files", nargs="+")
    p.add_argument("--no-reboot", action="store_true")
    p = sub.add_parser("sync", help="sync a directory (changed .py only)")
    p.add_argument("directory")
    p.add_argument("--no-reboot", action="store_true")
    sub.add_parser("abort", help="abort transfer, drop staged files")
    sub.add_parser("reboot", help="reboot the satellite")

    args = ap.parse_args()
    link = SatelliteLink(args.port, args.dev, args.baud, args.verbose)
    try:
        {"info": cmd_info, "push": cmd_push, "sync": cmd_sync,
         "abort": cmd_abort, "reboot": cmd_reboot}[args.command](link, args)
    except OtaError as e:
        print("ERROR:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
