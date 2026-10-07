#!/usr/bin/env python3
"""
avc_dashboard — live view of decoded AVC-LAN state (AVC data only), to
compare against what the car's display shows.

  avc_dashboard.py [--port P] [--http 8765] [--log FILE.ndjson]

Open http://localhost:8765 . Decoding follows captures/2026-10-07/AVC_MAP.md.
Holds the gateway port (stop other gwctl/capture tools first). Forces AVC
polarity "lo" at start.
"""
import argparse
import http.server
import json
import signal
import sys
import threading
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from gwctl import find_port, open_port, send  # noqa: E402

lock = threading.Lock()
state = {
    "climate": {}, "power": {}, "display": {},
    "events": [], "frames": {}, "stats": {"avc": 0, "avc_s": 0.0},
}
stop = False


def event(msg):
    state["events"].insert(0, time.strftime("%H:%M:%S ") + msg)
    del state["events"][40:]


VENT = {0x80: "face + foot", 0x40: "foot", 0x20: "windscreen + foot"}
CLIMATE_BTN = {(0, 0x08): "AUTO", (0, 0x02): "recirc", (1, 0x01): "windscreen+foot",
               (1, 0x02): "foot", (1, 0x04): "face+foot", (1, 0x08): "face",
               (1, 0x20): "A/C", (2, 0x80): "fan 1", (2, 0x40): "fan 2", (2, 0x20): "fan 3",
               (2, 0x10): "fan 4", (4, 0x08): "fan 5", (4, 0x04): "fan 6", (2, 0x08): "fan 7"}
NAV_BTN = {"01": "MENU", "04": "DEST", "02": "MAP"}
SCREEN = {"58": "nav", "5F": "energy flow / trip", "5D": "climate", "5E": "audio", "56": "info", "00": "none"}
SHIFT = {"84": "P", "04": "R/N", "0C": "D"}


def s16(h):
    v = int(h, 16)
    return v - 65536 if v > 32767 else v


def on_avc(d):
    m, s, b = d.get("m"), d.get("s"), d.get("d", [])
    key = f"{m}->{s} " + " ".join(b[:4])
    state["frames"][key] = {"t": time.strftime("%H:%M:%S"), "x": " ".join(b[4:])}
    c, p, disp = state["climate"], state["power"], state["display"]
    if b[1:4] == ["E0", "5D", "F3"] and len(b) >= 10:
        b1, b2, b6 = int(b[4], 16), int(b[5], 16), int(b[9], 16)
        if b1 == 0x41 and b6 == 0:
            c.update(system="OFF", auto=False, ac=False, fan=0)
        else:
            c.update(system="on", auto=bool(b1 & 0x80), ac=bool(b1 & 0x02), fan=b6 >> 5,
                     rear_heat=bool(b1 & 0x08),
                     air="recirc" if b1 & 0x20 else "fresh" if b1 & 0x40 else "?",
                     vent=VENT.get(b2, "face" if (b2 == 0 and b1 & 0x01) else f"0x{b2:02X}"))
        c["raw"] = " ".join(b[4:])
    elif b[1:4] == ["E0", "5D", "F5"] and len(b) >= 5:
        nn = int(b[4], 16)
        c["setpoint"] = "--" if nn == 0x39 else f"{15.5 + 0.5 * nn:.1f} °C"
    elif b[1:4] == ["25", "E0", "84"] and len(b) >= 10:
        hits = [n for (i, bit), n in CLIMATE_BTN.items() if int(b[4 + i], 16) & bit]
        if hits:
            event("climate touch: " + ", ".join(hits))
    elif b[1:4] == ["E4", "5F", "B9"] and len(b) >= 6:
        eng = b[4] == "6C"
        if p.get("engine") is not None and p["engine"] != eng:
            event("ENGINE " + ("ON" if eng else "OFF (stops delivering power)"))
        f1, f2 = int(b[4], 16), int(b[5], 16)
        p.update(engine=eng, flow=f"{b[4]} {b[5]}", arrows={
            "eng": f1 != 0,                      # engine -> power split
            # directions corrected live by the user (2026-10-07 drive home):
            # 00 74 = battery -> wheels on the car's screen
            "bat_out": bool(f2 & 0x40),          # battery -> motor
            "bat_in": bool(f2 & 0x80),           # motor -> battery (charging / regen)
            "whl_out": bool(f2 & 0x10),          # -> wheels
            "whl_in": bool(f2 & 0x08),           # wheels -> (regen)
        })
    elif b[1:4] == ["E4", "5F", "B4"] and len(b) >= 5:
        sh = SHIFT.get(b[4], b[4])
        if p.get("shift") not in (None, sh):
            event("shift " + sh)
        p["shift"] = sh
    elif b[1:4] == ["E4", "5F", "B8"] and len(b) >= 7:
        bars = (int(b[6], 16) & 0x07) + 1          # confirmed 3<->4 bars, drive home
        if p.get("bars") not in (None, bars):
            event(f"battery {bars} bars")
        p["bars"] = bars
        ev = bool(int(b[7], 16) & 0x40) if len(b) >= 8 else False   # EV mode (drive home)
        if p.get("ev") is not None and p["ev"] != ev:
            event("EV mode " + ("ON" if ev else "off"))
        p["ev"] = ev
        evx = bool(int(b[7], 16) & 0x80) if len(b) >= 8 else False  # EV cancel notice
        if evx and not p.get("ev_cancel"):
            event("EV mode CANCELLED")
        p["ev_cancel"] = evx
    elif b[1:4] == ["E4", "5F", "97"] and len(b) >= 6:
        p["v97"] = int(b[4] + b[5], 16)
    elif b[1:4] == ["E5", "5F", "D8"] and len(b) >= 6:
        p["vD8"] = s16(b[4] + b[5])
    elif b[1:4] == ["E5", "5F", "DC"] and len(b) >= 6:
        p["dist"] = b[4] + b[5]
    elif b[1:4] == ["E4", "5F", "96"] and len(b) >= 5:
        p["v96"] = int(b[4], 16)
    elif b[:3] == ["12", "01", "60"] and len(b) >= 4:
        disp["screen"] = SCREEN.get(b[3], b[3])
    elif b[:4] == ["01", "01", "5B", "40"]:
        disp["lights"] = "ON (dimmed)"
        event("lights ON")
    elif b[:4] == ["01", "01", "5A", "80"]:
        disp["lights"] = "off"
        event("lights off")
    elif b[1:4] == ["25", "58", "84"] and len(b) >= 5 and b[4] != "00":
        event("nav button " + NAV_BTN.get(b[4], b[4]))
    elif b[1:4] == ["21", "24", "78"] and len(b) >= 8 and b[4:8] != ["00"] * 4:
        event("touch x=%d y=%d" % (int(b[4], 16), int(b[5], 16)))
    elif b[1:4] == ["E0", "5D", "F7"] and len(b) >= 5:
        disp["outside"] = f"{int(b[4], 16) - 48} °C"
    if m == "178":
        disp["nav"] = "present"


PAGE = r"""<!doctype html><html><head><meta charset=utf-8><title>AVC live</title>
<meta name=viewport content="width=device-width,initial-scale=1"><style>
:root{--bg:#0b1014;--card:#121a20;--fg:#d6f5f2;--dim:#6f8f8c;--acc:#33e0d0;--warn:#ffb340;--on:#4cff9a}
body{background:var(--bg);color:var(--fg);font:15px/1.35 ui-monospace,Menlo,monospace;margin:0;padding:12px}
h1{font-size:16px;margin:0 0 10px;color:var(--acc)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:10px}
.c{background:var(--card);border-radius:8px;padding:10px 12px}.c h2{font-size:13px;margin:0 0 8px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em}
.big{font-size:30px;color:var(--acc)}.row{display:flex;justify-content:space-between;border-bottom:1px solid #1d2a31;padding:2px 0}
.on{color:var(--on)}.off{color:var(--dim)}.warn{color:var(--warn)}#ev div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fan span{display:inline-block;width:14px;height:14px;margin-right:3px;background:#22323a;border-radius:3px}.fan span.l{background:var(--acc)}
table{width:100%;font-size:12px;border-collapse:collapse}td{padding:1px 4px;white-space:nowrap}td.x{color:var(--acc)}tr.n td{background:#163a36}
</style></head><body><h1>AVC-LAN live <span id=st class=off></span></h1><div class=grid>
<div class=c><h2>Climate</h2><div class=big id=sp>–</div><div id=cl></div><div class=fan id=fan></div></div>
<div class=c><h2>Energy monitor (AVC B9, provisional)</h2><svg id=em viewBox="0 0 300 190" width=100%>
<defs><marker id=ah viewBox="0 0 10 10" refX=8 refY=5 markerWidth=5 markerHeight=5 orient=auto-start-reverse><path d="M0 0L10 5L0 10z" fill="currentColor"/></marker></defs>
<g font-size=12 fill="var(--fg)" text-anchor=middle>
<rect x=20 y=12 width=80 height=34 rx=6 fill="#1b262d"/><text x=60 y=34>ENGINE</text>
<rect x=20 y=140 width=80 height=34 rx=6 fill="#1b262d"/><text x=60 y=162>WHEELS</text>
<rect x=200 y=140 width=80 height=34 rx=6 fill="#1b262d"/><text x=240 y=162>BATTERY</text>
<circle cx=150 cy=95 r=22 fill="#1b262d"/><text x=150 y=99>MG</text></g>
<g stroke-width=5 fill=none stroke="#22323a"><path d="M75 46 L135 78"/><path d="M75 140 L133 110"/><path d="M167 110 L225 140"/></g>
<g stroke-width=5 fill=none>
<path id=a_eng d="M75 46 L135 78" marker-end="url(#ah)"/>
<path id=a_bout d="M225 140 L167 110" marker-end="url(#ah)"/>
<path id=a_bin d="M167 110 L225 140" marker-end="url(#ah)"/>
<path id=a_wout d="M133 110 L75 140" marker-end="url(#ah)"/>
<path id=a_win d="M75 140 L133 110" marker-end="url(#ah)"/></g></svg>
<div id=emtxt class=off></div></div>
<div class=c><h2>Powertrain / energy</h2><div class=big id=eng>–</div><div id=pw></div></div>
<div class=c><h2>Display</h2><div id=dp></div></div>
<div class=c><h2>Events</h2><div id=ev></div></div>
<div class=c style="grid-column:1/-1"><h2>Last frame per header</h2><table id=fr></table></div></div>
<script>
const row=(k,v,c='')=>`<div class=row><span>${k}</span><span class="${c}">${v??'–'}</span></div>`;
const yn=v=>v===undefined?['–','off']:v?['ON','on']:['off','off'];
let seen={};
const es=new EventSource('/events');
es.onmessage=e=>{const s=JSON.parse(e.data),c=s.climate,p=s.power,d=s.display;
document.getElementById('st').textContent=`${s.stats.avc} frames · ${s.stats.avc_s.toFixed(0)} AVC/s`;
document.getElementById('sp').textContent=c.system==='OFF'?'A/C OFF':(c.setpoint??'–');
let [a,ac]=yn(c.auto),[b,bc]=yn(c.ac);
document.getElementById('cl').innerHTML=row('AUTO',a,ac)+row('A/C',b,bc)+row('rear window heater',c.rear_heat===undefined?'–':c.rear_heat?'ON':'off',c.rear_heat?'on':'off')+row('air',c.air)+row('vent',c.vent)+row('fan',c.fan)+row('raw F3',c.raw,'off');
document.getElementById('fan').innerHTML=[1,2,3,4,5,6,7].map(i=>`<span class="${i<=(c.fan||0)?'l':''}"></span>`).join('');
const A=p.arrows||{},lit=(id,on,col)=>{const el=document.getElementById(id);el.setAttribute('stroke',col);el.style.color=col;el.style.display=on?'':'none'};
lit('a_eng',A.eng,'#ffb340');lit('a_bout',A.bat_out,'#33e0d0');lit('a_bin',A.bat_in,'#4cff9a');lit('a_wout',A.whl_out,'#33e0d0');lit('a_win',A.whl_in,'#4cff9a');
document.getElementById('emtxt').textContent=[A.eng&&'engine',A.bat_out&&'battery→',A.bat_in&&'→battery',A.whl_out&&'→wheels',A.whl_in&&'wheels→(regen)'].filter(Boolean).join(' · ')||'no flow';
const eg=document.getElementById('eng');eg.textContent=p.engine===undefined?'–':p.engine?'ENGINE ON':'engine off';eg.className='big '+(p.engine?'on':'off');
document.getElementById('pw').innerHTML=row('battery',p.bars?('▮'.repeat(p.bars)+'▯'.repeat(8-p.bars)+' '+p.bars+'/8'):'–')+row('EV mode',p.ev===undefined?'–':p.ev_cancel?'CANCELLED':p.ev?'ON':'off',p.ev_cancel?'warn':p.ev?'on':'off')+row('shift',p.shift)+row('flow arrows (B9)',p.flow)+row('97 (engine-related)',p.v97)+row('D8 (signed)',p.vD8)+row('distance counter DC',p.dist)+row('96 (unknown, rising)',p.v96);
document.getElementById('dp').innerHTML=row('active screen',d.screen)+row('lights',d.lights)+row('outside temp',d.outside)+row('nav ECU',d.nav??'not heard');
document.getElementById('ev').innerHTML=s.events.map(x=>`<div>${x}</div>`).join('');
const ks=Object.keys(s.frames).sort();document.getElementById('fr').innerHTML=ks.map(k=>{const f=s.frames[k],n=seen[k]!==undefined&&seen[k]!==f.x;seen[k]=f.x;
return `<tr class="${n?'n':''}"><td>${f.t}</td><td>${k}</td><td class=x>${f.x}</td></tr>`}).join('')};
</script></body></html>"""


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                while not stop:
                    with lock:
                        data = json.dumps(state)
                    self.wfile.write(f"data: {data}\n\n".encode())
                    self.wfile.flush()
                    time.sleep(0.2)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    global stop
    ap = argparse.ArgumentParser()
    ap.add_argument("--port")
    ap.add_argument("--http", type=int, default=8765)
    ap.add_argument("--log")
    args = ap.parse_args()

    def on_term(*_):
        global stop
        stop = True
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", args.http), H)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"dashboard on http://localhost:{args.http}", flush=True)

    log = open(args.log, "a", buffering=1) if args.log else None
    with open_port(find_port(args.port)) as ser:
        send(ser, {"id": 0, "d": {"a": "avc_cfg", "pol": "lo"}})
        n_avc = 0
        t_rate = time.monotonic()
        while not stop:
            raw = ser.readline()
            now = time.monotonic()
            if now - t_rate >= 2:
                with lock:
                    state["stats"]["avc_s"] = n_avc / (now - t_rate)
                n_avc = 0
                t_rate = now
            if not raw:
                continue
            if log:
                log.write(json.dumps({"ht": time.time(), "raw": raw.decode(errors="replace").rstrip()}) + "\n")
            try:
                o = json.loads(raw)
            except ValueError:
                continue
            with lock:
                if o.get("id") == 2 and not o["d"].get("echo"):
                    n_avc += 1
                    state["stats"]["avc"] += 1
                    on_avc(o["d"])
    srv.shutdown()


if __name__ == "__main__":
    main()
