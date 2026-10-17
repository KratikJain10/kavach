# Web alert screen for Kavach: big, projector-friendly, served only to this laptop.
# kavach.py --web starts it on http://localhost:8000
#   GET  /state  current call state (the page polls it twice a second)
#   POST /start  start a new call (listen to the mic, or play the demo file)
#   POST /end    end the call, which triggers the after-call report
#   POST /ask    {"q": "..."} -> chat answer about the call

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kavach</title>
<style>
  :root { --bg:#0d1015; --card:#151a21; --text:#e9ecef; --dim:#8b939e; --line:#252b35;
          --safe:#178a4c; --warn:#d69e2e; --scam:#d93636; --accent:#7aa7ff; }
  * { box-sizing:border-box; margin:0 }
  body { background:var(--bg); color:var(--text); font:18px/1.55 system-ui, "Noto Sans Devanagari", sans-serif;
         padding:24px; max-width:1180px; margin:auto }
  header { display:flex; align-items:center; gap:14px; margin-bottom:18px; flex-wrap:wrap }
  h1 { font-size:30px; letter-spacing:-.01em } .sub { color:var(--dim) }
  .pills { margin-left:auto; display:flex; gap:8px }
  .pill { font-size:13px; padding:4px 12px; border-radius:99px; border:1px solid var(--line); color:var(--dim) }
  .pill .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; background:var(--dim) }
  .pill.on .dot { background:#3ddc84 } .pill.live .dot { background:#ff5a5a; animation:blink 1.2s infinite }
  @keyframes blink { 50% { opacity:.25 } }
  #banner { border-radius:16px; padding:30px 32px; font-size:36px; font-weight:800; background:var(--safe);
            transition:background .3s; line-height:1.2 }
  #banner small { display:block; font-size:18px; font-weight:500; margin-top:8px; opacity:.9 }
  #banner.idle { background:var(--line) }
  #banner.warn { background:var(--warn); color:#141414 }
  #banner.scam { background:var(--scam); animation:pulse 1s infinite }
  @keyframes pulse { 50% { filter:brightness(1.3) } }
  .controls { display:flex; gap:12px; margin-top:14px }
  .controls button { padding:14px 28px; font-size:20px; border-radius:12px }
  #start { background:#3ddc84; color:#0b2416 } #stop { background:#ff5a5a; color:#2a0909 }
  .meter { height:14px; background:var(--line); border-radius:7px; margin:16px 0 6px; overflow:hidden }
  .meter div { height:100%; width:0; background:var(--text); transition:width .5s }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-top:18px }
  .wide { grid-column:1/-1 }
  @media (max-width:820px) { .grid { grid-template-columns:1fr } body { padding:16px } #banner { font-size:26px } }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 20px }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.09em; color:var(--dim); margin-bottom:10px;
             display:flex; justify-content:space-between }
  .hit { padding:7px 0; border-bottom:1px solid var(--line); display:flex; gap:10px; justify-content:space-between }
  .hit:last-child { border:0 } .hit span { color:var(--dim) } .hit b { color:#ff8f8f; font-weight:600 }
  #transcript { max-height:260px; overflow:auto } #transcript p { margin-bottom:8px }
  #transcript .partial { color:var(--dim) }
  #report { white-space:pre-wrap } .who { color:var(--dim); font-size:13px; margin-bottom:6px }
  .empty { color:var(--dim) }
  button { font:inherit; padding:10px 22px; border-radius:10px; border:0; background:var(--text); color:var(--bg);
           font-weight:700; cursor:pointer } button:disabled { opacity:.35; cursor:default }
  #msgs { display:flex; flex-direction:column; gap:10px; max-height:340px; overflow:auto; margin-bottom:12px }
  .msg { padding:10px 14px; border-radius:12px; max-width:85%; white-space:pre-wrap }
  .msg.q { align-self:flex-end; background:#24324a } .msg.a { align-self:flex-start; background:var(--line) }
  .msg .who { margin:4px 0 0 }
  form { display:flex; gap:10px } input { flex:1; font:inherit; padding:10px 14px; border-radius:10px;
         border:1px solid var(--line); background:var(--bg); color:var(--text) }
  .chips { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px }
  .chip { font-size:14px; padding:5px 12px; border-radius:99px; background:var(--line); cursor:pointer; border:0;
          color:var(--text); font-weight:500 }
</style></head><body>
<header>
  <h1>🛡 Kavach</h1><span class="sub">offline scam-call guard</span>
  <div class="pills"><span id="live" class="pill live"><span class="dot"></span><span id="livetxt">listening</span></span>
    <span id="net" class="pill"><span class="dot"></span><span id="nettxt">offline</span></span></div>
</header>
<div id="banner" class="idle">Ready<small>Press Start when the call begins.</small></div>
<div class="controls"><button id="start" onclick="startCall()">▶ Start call</button>
  <button id="stop" onclick="endCall()" disabled>■ End call</button></div>
<div class="meter"><div id="bar"></div></div><div class="sub">risk <b id="risk">0</b> / 100</div>
<div class="grid">
  <div class="card"><h2>Signals heard</h2><div id="hits" class="empty">none yet</div></div>
  <div class="card"><h2>Local AI <span id="aims"></span></h2><div id="ai" class="empty">waiting for enough speech…</div></div>
  <div class="card wide"><h2>Live transcript</h2><div id="transcript" class="empty">…</div></div>
  <div class="card wide"><h2>After-call report</h2>
    <div id="report" class="empty">Appears when you end a suspicious call.</div></div>
  <div class="card wide"><h2>Ask about this call</h2>
    <div class="chips">
      <button class="chip" onclick="ask(this.textContent)">Was this really the police?</button>
      <button class="chip" onclick="ask(this.textContent)">I already sent money. What now?</button>
      <button class="chip" onclick="ask(this.textContent)">क्या यह धोखाधड़ी है?</button></div>
    <div id="msgs"></div>
    <form onsubmit="ask($('q').value); $('q').value=''; return false">
      <input id="q" placeholder="Ask in Hindi, English or Hinglish…" autocomplete="off"><button id="send">Ask</button></form></div>
</div>
<script>
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const LABEL = {
  safe: ["✓ No scam signs", "Kavach is listening to the call."],
  warn: ["! Suspicious call", "Be careful. Don't send money or share any code yet."],
  scam: ["⚠ SCAM LIKELY: hang up", "Don't share OTP. Don't send money. Real police never call like this."] };
let lastLines = 0, callId = null;
async function tick() {
  try {
    const s = await (await fetch('/state')).json();
    if (s.id !== callId) { callId = s.id; $('msgs').innerHTML = ''; resetCards(); }
    const [t, sub] = s.idle ? ["Ready", "Press Start when the call begins."] : LABEL[s.level];
    $('banner').className = s.idle ? 'idle' : s.level; $('banner').innerHTML = `${t}<small>${sub}</small>`;
    const busy = !s.ended || (s.reporting && !s.report);
    $('start').disabled = busy; $('stop').disabled = s.ended;
    $('start').textContent = s.idle ? '▶ Start call' : '▶ New call';
    $('risk').textContent = s.risk; $('bar').style.width = s.risk + '%';
    $('live').className = 'pill' + (s.ended ? '' : ' live');
    $('livetxt').textContent = s.idle ? 'ready' : s.ended ? 'call ended' : 'listening';
    $('net').className = 'pill' + (s.online ? ' on' : ''); $('nettxt').textContent = s.online ? 'Gemma 4 online' : 'offline · local AI';
    const hits = Object.entries(s.hits);
    $('hits').className = hits.length ? '' : 'empty';
    $('hits').innerHTML = hits.length ? hits.map(([p, w]) =>
      `<div class="hit"><span>${esc(p.replace(/_/g,' '))}</span><b>“${esc(w)}”</b></div>`).join('') : 'none yet';
    if (s.ai) { $('ai').className = ''; $('aims').textContent = s.ai.ms + ' ms';
      $('ai').innerHTML = `<b>${esc(s.ai.verdict)}</b> · ${esc(s.ai.pattern.replace(/_/g,' '))}<br>${esc(s.ai.reason || '')}`; }
    const tr = $('transcript');
    tr.className = s.lines.length || s.partial ? '' : 'empty';
    tr.innerHTML = (s.lines.map(l => `<p>${esc(l)}</p>`).join('') +
      (s.partial ? `<p class="partial">${esc(s.partial)}…</p>` : '')) || '…';
    if (s.lines.length !== lastLines) { tr.scrollTop = tr.scrollHeight; lastLines = s.lines.length; }
    if (s.report) { $('report').className = '';
      $('report').innerHTML = `<div class="who">${esc(s.report.who)} · ${s.report.secs}s</div>${esc(s.report.text)}`; }
    else if (s.reporting) $('report').textContent = 'Writing the report…';
    else if (s.ended && !s.idle) $('report').textContent = 'No report needed: this call looked safe.';
  } catch (e) {}
}
function resetCards() {
  $('ai').className = 'empty'; $('ai').textContent = 'waiting for enough speech…'; $('aims').textContent = '';
  $('report').className = 'empty'; $('report').textContent = 'Appears when you end a suspicious call.';
}
function startCall() { $('start').disabled = true; fetch('/start', {method:'POST'}); }
function endCall() { $('stop').disabled = true; fetch('/end', {method:'POST'}); }
async function ask(q) {
  q = q.trim(); if (!q) return;
  const box = $('msgs');
  box.insertAdjacentHTML('beforeend', `<div class="msg q">${esc(q)}</div>`);
  const a = document.createElement('div'); a.className = 'msg a'; a.textContent = 'Thinking…';
  box.appendChild(a); box.scrollTop = box.scrollHeight; $('send').disabled = true;
  try {
    const r = await (await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'},
                                           body: JSON.stringify({q})})).json();
    a.innerHTML = `${esc(r.text)}<div class="who">${esc(r.who)} · ${r.secs}s</div>`;
  } catch (e) { a.textContent = 'Could not get an answer.'; }
  $('send').disabled = false; box.scrollTop = box.scrollHeight;
}
setInterval(tick, 500); tick();
</script></body></html>"""


def serve(snapshot, start, end, ask, port=8000):
    """Serve the page in a background thread. snapshot() -> state dict, start() / end() control the
    call, ask(question) -> {"who", "text", "secs"}."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/state":
                self._send(200, "application/json", json.dumps(snapshot(), ensure_ascii=False))
            else:
                self._send(200, "text/html; charset=utf-8", PAGE)

        def do_POST(self):
            if self.path in ("/start", "/end"):
                (start if self.path == "/start" else end)()
                self._send(204, "text/plain", "")
            elif self.path == "/ask":
                length = int(self.headers.get("Content-Length", 0))
                q = json.loads(self.rfile.read(length) or b"{}").get("q", "")
                self._send(200, "application/json", json.dumps(ask(q), ensure_ascii=False))
            else:
                self._send(404, "text/plain", "")

        def _send(self, code, ctype, body):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):  # keep the terminal clean
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)  # 127.0.0.1: only this laptop can open it
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
