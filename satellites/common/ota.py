"""
ota.py — common OTA code-update module for all RS485 satellites.

Reliable Python-code updates over the half-duplex RS485 bus. One shared
file, deployed to every satellite; each main loop calls ota.handle(m)
first for every received message.

Protocol (host -> satellite, NDJSON {"id":N,"d":{...}}):

  {"cmd":"FW_INFO"}
      -> {"res":"OK","cmd":"FW_INFO","proto":1,"files":{"main.py":"<sha256>",...}}
  {"cmd":"FW_BEGIN","file":"main.py","size":12345,"sha256":"<hex>"}
      -> opens "main.py.new" staging file
  {"cmd":"FW_DATA","n":0,"b":"<base64>"}
      -> stop-and-wait: every chunk ACKed {"res":"OK","cmd":"FW_DATA","n":0};
         duplicate n re-ACKed (idempotent), other mismatch ->
         {"err":"SEQ","cmd":"FW_DATA","want":<expected>}
  {"cmd":"FW_END"}
      -> verifies size + sha256 of the staged file; on success keeps it
         staged, on failure deletes it
  {"cmd":"FW_COMMIT"}
      -> atomically renames every verified "<f>.new" -> "<f>" (littlefs
         rename is atomic per file)
  {"cmd":"FW_ABORT"}   -> drops session + all staged files
  {"cmd":"FW_REBOOT"}  -> machine.reset() after the ACK is flushed

Crash safety: power loss mid-transfer leaves only inert "*.new" files;
boot code is untouched until FW_COMMIT. A stale session (no FW_* traffic
for SESSION_TIMEOUT_MS) is cleaned up by tick()/handle().

Main-loop integration:

    ota = OTA(rs485)
    for m in rs485.read():
        if ota.handle(m):
            continue
        ...normal dispatch...
    # optionally: skip heavy rendering while ota.active
"""

import os
import time
import machine
import uhashlib
import ubinascii

PROTO = 1
STAGE_SUFFIX = ".new"
SESSION_TIMEOUT_MS = 30000
MAX_FILE_SIZE = 256 * 1024


def _sha256_file(path):
    h = uhashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(512)
            if not chunk:
                break
            h.update(chunk)
    return ubinascii.hexlify(h.digest()).decode()


def _exists(path):
    try:
        os.stat(path)
        return True
    except OSError:
        return False


class OTA:
    def __init__(self, rs485):
        self.rs485 = rs485
        self.active = False      # transfer in progress -> main loop may skip work
        self._f = None           # open staging file handle
        self._name = None        # target file name of current transfer
        self._size = 0
        self._sha = None         # expected sha256 (hex) of current transfer
        self._hash = None        # incremental hasher
        self._next = 0           # next expected chunk index
        self._written = 0
        self._last_rx = 0
        self._staged = []        # verified staged target names

    # -- public ---------------------------------------------------------

    def handle(self, m):
        """Process one received payload. Returns True if it was an FW_* one."""
        cmd = m.get("cmd")
        if not cmd or not cmd.startswith("FW_"):
            return False
        self._last_rx = time.ticks_ms()
        try:
            if cmd == "FW_INFO":
                self._info()
            elif cmd == "FW_BEGIN":
                self._begin(m)
            elif cmd == "FW_DATA":
                self._data(m)
            elif cmd == "FW_END":
                self._end()
            elif cmd == "FW_COMMIT":
                self._commit()
            elif cmd == "FW_ABORT":
                self._abort()
            elif cmd == "FW_REBOOT":
                self.rs485.send({"res": "OK", "cmd": "FW_REBOOT"})
                time.sleep_ms(100)
                machine.reset()
            else:
                self.rs485.send({"err": "UNKNOWN_FW_CMD", "cmd": cmd})
        except Exception as e:
            self._cleanup_session()
            self.rs485.send({"err": "FW_FAIL", "cmd": cmd, "msg": str(e)})
        return True

    def tick(self, now=None):
        """Call periodically: aborts a stale session (host went away)."""
        if self._f is not None:
            if now is None:
                now = time.ticks_ms()
            if time.ticks_diff(now, self._last_rx) > SESSION_TIMEOUT_MS:
                print("OTA: session timeout, dropping", self._name)
                self._cleanup_session()

    # -- handlers -------------------------------------------------------

    def _info(self):
        files = {}
        for name in os.listdir():
            if name.endswith(".py"):
                files[name] = _sha256_file(name)
        self.rs485.send({"res": "OK", "cmd": "FW_INFO", "proto": PROTO,
                         "files": files})

    def _begin(self, m):
        name = m.get("file")
        size = m.get("size")
        sha = m.get("sha256")
        if (not isinstance(name, str) or "/" in name or ".." in name
                or not name or not isinstance(size, int)
                or not (0 < size <= MAX_FILE_SIZE) or not sha):
            self.rs485.send({"err": "BAD_ARGS", "cmd": "FW_BEGIN"})
            return
        self._cleanup_session()  # restart: drop any half transfer
        self._name = name
        self._size = size
        self._sha = sha.lower()
        self._hash = uhashlib.sha256()
        self._next = 0
        self._written = 0
        self._f = open(name + STAGE_SUFFIX, "wb")
        self.active = True
        self.rs485.send({"res": "OK", "cmd": "FW_BEGIN", "file": name})

    def _data(self, m):
        if self._f is None:
            self.rs485.send({"err": "NO_SESSION", "cmd": "FW_DATA"})
            return
        n = m.get("n")
        if n == self._next - 1:
            # Duplicate (our ACK got lost): re-ACK without writing
            self.rs485.send({"res": "OK", "cmd": "FW_DATA", "n": n})
            return
        if n != self._next:
            self.rs485.send({"err": "SEQ", "cmd": "FW_DATA", "want": self._next})
            return
        try:
            raw = ubinascii.a2b_base64(m.get("b", ""))
        except Exception:
            self.rs485.send({"err": "BAD_B64", "cmd": "FW_DATA", "want": n})
            return
        self._f.write(raw)
        self._hash.update(raw)
        self._written += len(raw)
        self._next += 1
        self.rs485.send({"res": "OK", "cmd": "FW_DATA", "n": n})

    def _end(self):
        if self._f is None:
            self.rs485.send({"err": "NO_SESSION", "cmd": "FW_END"})
            return
        name = self._name
        self._f.close()
        self._f = None
        self.active = False
        got = ubinascii.hexlify(self._hash.digest()).decode()
        if self._written != self._size or got != self._sha:
            try:
                os.remove(name + STAGE_SUFFIX)
            except OSError:
                pass
            self.rs485.send({"err": "HASH", "cmd": "FW_END", "file": name,
                             "sha256": got, "size": self._written})
        else:
            if name not in self._staged:
                self._staged.append(name)
            self.rs485.send({"res": "OK", "cmd": "FW_END", "file": name,
                             "sha256": got})
        self._name = None
        self._hash = None

    def _commit(self):
        if not self._staged:
            self.rs485.send({"err": "NOTHING_STAGED", "cmd": "FW_COMMIT"})
            return
        done = []
        for name in self._staged:
            os.rename(name + STAGE_SUFFIX, name)  # atomic on littlefs
            done.append(name)
        self._staged = []
        self.rs485.send({"res": "OK", "cmd": "FW_COMMIT", "files": done})

    def _abort(self):
        self._cleanup_session()
        for name in self._staged:
            try:
                os.remove(name + STAGE_SUFFIX)
            except OSError:
                pass
        self._staged = []
        self.rs485.send({"res": "OK", "cmd": "FW_ABORT"})

    # -- internals ------------------------------------------------------

    def _cleanup_session(self):
        if self._f is not None:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None
            if self._name and _exists(self._name + STAGE_SUFFIX):
                try:
                    os.remove(self._name + STAGE_SUFFIX)
                except OSError:
                    pass
        self._name = None
        self._hash = None
        self.active = False
