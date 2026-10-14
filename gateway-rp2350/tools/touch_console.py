#!/usr/bin/env python3
"""
touch_console — live view of the touch panel / hardware buttons the display sends to the nav.

  touch_console.py LOG.ndjson [--port 8766]

Tails an emulator/recorder log (nav_emu.py / avc_capture.py line format) so it can run next
to the emulator that owns the serial port. Open http://localhost:8766.

Frames (display 110 -> nav 178):
  00 21 24 78 X Y X Y   touch, one byte per axis, streamed while the finger moves
  00 21 24 78 00 00 00 00   release
  00 25 58 84 KK 00     hardware buttons: 01 menu, 04 dest, 02 map, 00 release
"""
import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EVENTS = []          # (seq, dict)
LOCK = threading.Lock()
SEQ = [0]


def push(ev):
    with LOCK:
        SEQ[0] += 1
        EVENTS.append((SEQ[0], ev))
        del EVENTS[:-2000]


def handle_line(raw):
    try:
        rec = json.loads(raw)
    except ValueError:
        return
    obj = rec.get("obj") or rec
    if obj.get("id") != 2:
        return
    d = obj.get("d", {})
    if d.get("m") != "110" or d.get("s") != "178":
        return
    data = d.get("d", [])
    t = rec.get("ht", time.time())
    if data[:4] == ["00", "21", "24", "78"] and len(data) >= 8:
        x, y = int(data[4], 16), int(data[5], 16)
        push({"t": t, "type": "touch", "x": x, "y": y, "raw": " ".join(data),
              "release": x == 0 and y == 0 and data[6] == "00" and data[7] == "00"})
    elif data[:4] == ["00", "25", "58", "84"] and len(data) >= 5:
        push({"t": t, "type": "button", "key": data[4], "raw": " ".join(data)})


def tail(path):
    with open(path) as f:
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.02)
                continue
            handle_line(line)


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>Prius touch console</title>
<style>
body{font-family:system-ui,sans-serif;background:#111;color:#ddd;margin:0;display:flex;height:100vh}
#left{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center}
canvas{background:#000;border:2px solid #444;image-rendering:pixelated}
#right{width:360px;border-left:1px solid #333;padding:12px;overflow:auto;font-size:13px}
#log div{font-family:monospace;white-space:pre}
.btn{display:inline-block;padding:4px 10px;margin:2px;border:1px solid #555;border-radius:4px}
.on{background:#2a6;color:#000}
h3{margin:8px 0 4px}
input{width:60px}
</style></head><body>
<div id="left">
 <canvas id="c" width="1024" height="600"></canvas>
 <div style="margin-top:8px">last: <span id="last">—</span> &nbsp; points: <span id="n">0</span>
 &nbsp; <button onclick="pts=[];draw()">clear</button>
 &nbsp; calib X <input id="x0" value="4">–<input id="x1" value="249"> Y <input id="y0" value="255">–<input id="y1" value="9"> (top–bottom)
 &nbsp; <label><input type="checkbox" id="flipy"> flip Y</label> <span style="color:#888">Y counts upward: 255 = top edge, 9 = bottom edge (measured 2026-10-14)</span></div>
 <div style="margin-top:6px"><span class="btn" id="b01">MENU 01</span><span class="btn" id="b04">DEST 04</span><span class="btn" id="b02">MAP 02</span></div>
</div>
<div id="right"><h3>raw frames</h3><div id="log"></div></div>
<script>
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
let pts=[];let last=null;
function map(p){const x0=+x0i.value,x1=+x1i.value,y0=+y0i.value,y1=+y1i.value;
 let fx=(p.x-x0)/(x1-x0), fy=(p.y-y0)/(y1-y0); if(flipy.checked) fy=1-fy;
 return [fx*cv.width, fy*cv.height];}
const x0i=document.getElementById('x0'),x1i=document.getElementById('x1'),y0i=document.getElementById('y0'),y1i=document.getElementById('y1'),flipy=document.getElementById('flipy');
function draw(){ctx.fillStyle='#000';ctx.fillRect(0,0,cv.width,cv.height);
 ctx.strokeStyle='#333';for(let i=1;i<8;i++){ctx.beginPath();ctx.moveTo(cv.width*i/8,0);ctx.lineTo(cv.width*i/8,cv.height);ctx.stroke();}
 for(let i=1;i<4;i++){ctx.beginPath();ctx.moveTo(0,cv.height*i/4);ctx.lineTo(cv.width,cv.height*i/4);ctx.stroke();}
 pts.forEach((p,i)=>{const [x,y]=map(p);ctx.fillStyle=p.release?'#f44':(i==pts.length-1?'#fff':'#2a6');ctx.beginPath();ctx.arc(x,y,p.release?3:5,0,6.28);ctx.fill();});
 if(last&&!last.release){const [x,y]=map(last);ctx.strokeStyle='#ff0';ctx.beginPath();ctx.arc(x,y,14,0,6.28);ctx.stroke();
  ctx.fillStyle='#ff0';ctx.font='14px monospace';ctx.fillText(`x=${last.x} (0x${last.x.toString(16).padStart(2,'0')})  y=${last.y} (0x${last.y.toString(16).padStart(2,'0')})`,x+18,y-6);}
 document.getElementById('n').textContent=pts.filter(p=>!p.release).length;}
const log=document.getElementById('log');
const es=new EventSource('/events');
es.onmessage=e=>{const ev=JSON.parse(e.data);
 const row=document.createElement('div');row.textContent=new Date(ev.t*1000).toLocaleTimeString()+'  '+ev.raw;log.prepend(row);while(log.childElementCount>200)log.lastChild.remove();
 if(ev.type=='touch'){if(ev.release){pts.push(ev);last=null;document.getElementById('last').textContent='release';}
  else{pts.push(ev);last=ev;document.getElementById('last').textContent=`x=${ev.x} y=${ev.y}`;}draw();}
 else if(ev.type=='button'){['01','04','02'].forEach(k=>document.getElementById('b'+k).classList.toggle('on',ev.key==k));}
};
draw();
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            last = 0
            with LOCK:
                backlog = list(EVENTS)
            try:
                for seq, ev in backlog:
                    self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                    last = seq
                self.wfile.flush()
                while True:
                    with LOCK:
                        new = [(s, e) for s, e in EVENTS if s > last]
                    for seq, ev in new:
                        self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        last = seq
                    if new:
                        self.wfile.flush()
                    else:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(PAGE.encode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--replay", action="store_true", help="load the whole file first instead of tailing from the end")
    args = ap.parse_args()
    if args.replay:
        for line in open(args.log):
            handle_line(line)
    threading.Thread(target=tail, args=(args.log,), daemon=True).start()
    print(f"touch console on http://localhost:{args.port}  (tailing {args.log})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()


if __name__ == "__main__":
    main()
