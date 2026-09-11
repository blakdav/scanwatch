#!/usr/bin/env python3
"""scanwatch: watches the scanner's document feeder and files PDFs."""

import collections
import datetime
import os
import re
import subprocess
import threading
import urllib.request

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

STATE = "/state/duplex"
PEND = "/state/pending"
PAPER = "/state/paper"
PAUSED = "/state/paused"
RESFILE = "/state/resolution"
POLLFILE = "/state/poll"
MODEFILE = "/state/mode"
OUT = "/out"

SCANNER_IP = os.environ.get("SCANNER_IP", "")
DEFAULT_RES = 300
DEFAULT_POLL = 2.0
DEFAULT_MODE = "Gray"

COLOR_MODES = {
    "Gray": "Greyscale",
    "Color": "Colour",
    "Lineart": "Black and white",
}

# Filled in from the scanner itself so the interface can state the real
# ceiling for whatever hardware is attached.
DEVICE = {"model": "", "resolutions": [], "max": None}

PAPER_SIZES = {
    "letter": "Letter, 8.5 by 11 inches",
    "a4": "A4, 210 by 297 mm",
    "legal": "Legal, 8.5 by 14 inches",
    "a5": "A5, 148 by 210 mm",
    "receipt": "Receipt, 80 mm wide",
}

_LOG = collections.deque(maxlen=100)


class Log:
    """Log buffer that stamps every line as it arrives."""

    def append(self, line):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        _LOG.append("%s  %s" % (ts, line))

    def __iter__(self):
        return iter(_LOG)

    def __len__(self):
        return len(_LOG)


LOG = Log()


def runner():
    """Run watch.sh forever, capturing its output into the log buffer."""
    while True:
        proc = subprocess.Popen(
            ["/app/watch.sh"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                LOG.append(line)
        LOG.append("watcher exited, restarting")


def probe_device():
    """Read the model name and the feeder's supported resolutions."""
    url = "http://%s/eSCL/ScannerCapabilities" % SCANNER_IP
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            xml = r.read().decode("utf-8", "replace")
    except Exception as e:
        LOG.append("could not read scanner capabilities: %s" % e)
        return

    m = re.search(r"<pwg:MakeAndModel>([^<]+)<", xml)
    if m:
        DEVICE["model"] = m.group(1).strip()

    # Prefer the feeder's block; fall back to the whole document.
    block = xml
    a = re.search(r"<scan:AdfSimplexInputCaps>(.*?)</scan:AdfSimplexInputCaps>", xml, re.S)
    if a:
        block = a.group(1)

    res = sorted({int(v) for v in re.findall(r"<scan:XResolution>(\d+)<", block)})
    if res:
        DEVICE["resolutions"] = res
        DEVICE["max"] = res[-1]
        LOG.append("scanner reports %s, up to %d dpi over the feeder"
                   % (DEVICE["model"] or "an unknown model", DEVICE["max"]))


def current_res():
    if os.path.exists(RESFILE):
        try:
            with open(RESFILE) as fh:
                return int(fh.read().strip())
        except ValueError:
            pass
    return DEFAULT_RES


def current_poll():
    if os.path.exists(POLLFILE):
        try:
            with open(POLLFILE) as fh:
                return float(fh.read().strip())
        except ValueError:
            pass
    return DEFAULT_POLL


def current_mode():
    if os.path.exists(MODEFILE):
        with open(MODEFILE) as fh:
            v = fh.read().strip()
        if v in COLOR_MODES:
            return v
    return DEFAULT_MODE


def current_paper():
    if os.path.exists(PAPER):
        with open(PAPER) as fh:
            v = fh.read().strip()
        if v in PAPER_SIZES:
            return v
    return "letter"


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>scanwatch</title>
<style>
  :root {
    --bg: #16181d;
    --panel: #1e2128;
    --line: #2c313b;
    --text: #e6e8ec;
    --muted: #8b929f;
    --live: #4ea87a;
    --held: #c9a227;
    --off: #b4545a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 2rem 1rem 4rem;
    background: var(--bg);
    color: var(--text);
    font: 16px/1.5 ui-sans-serif, system-ui, sans-serif;
  }
  main { max-width: 34rem; margin: 0 auto; }
  h1 {
    font-size: 1.1rem;
    font-weight: 600;
    margin: 0 0 1.5rem;
    color: var(--muted);
  }
  .toggle {
    display: block;
    width: 100%;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--panel);
    color: var(--text);
    padding: 1.5rem;
    text-align: left;
    font: inherit;
    cursor: pointer;
    margin-bottom: 0.9rem;
    transition: border-color 0.15s, background 0.15s;
  }
  .toggle:hover { border-color: #3b4250; }
  .toggle:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .toggle.on { border-color: var(--live); background: #1b2a24; }
  .toggle.stopped { border-color: var(--off); background: #2a1c1e; }
  .mode {
    font-size: 1.35rem;
    font-weight: 600;
    display: block;
    margin-bottom: 0.35rem;
  }
  .hint { color: var(--muted); font-size: 0.9rem; }
  .field {
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--panel);
    padding: 1.25rem 1.5rem;
    margin-bottom: 0.9rem;
  }
  .field label {
    display: block;
    font-size: 0.9rem;
    color: var(--muted);
    margin-bottom: 0.6rem;
  }
  select {
    width: 100%;
    font: inherit;
    padding: 0.7rem 0.8rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: #14161a;
    color: var(--text);
  }
  select:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .choices { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .choice {
    flex: 1 1 7rem;
    font: inherit;
    padding: 0.7rem 0.6rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: #14161a;
    color: var(--text);
    cursor: pointer;
    text-align: center;
    transition: border-color 0.15s, background 0.15s;
  }
  .choice:hover { border-color: #3b4250; }
  .choice:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .choice.sel { border-color: var(--live); background: #1b2a24; }
  .choice small { display: block; color: var(--muted); font-size: 0.75rem; margin-top: 0.15rem; }
  .row { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
  input[type=number] {
    flex: 1;
    font: inherit;
    padding: 0.7rem 0.8rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: #14161a;
    color: var(--text);
    min-width: 0;
  }
  input[type=number]:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .row button {
    font: inherit;
    padding: 0.7rem 1.1rem;
    border-radius: 7px;
    border: 1px solid var(--line);
    background: var(--panel);
    color: var(--text);
    cursor: pointer;
  }
  .row button:hover { border-color: #3b4250; }
  .note { color: var(--muted); font-size: 0.8rem; margin: 0.6rem 0 0; }
  .status {
    margin: 1.25rem 0 0;
    padding: 0.85rem 1rem;
    border-left: 3px solid var(--held);
    background: var(--panel);
    border-radius: 0 6px 6px 0;
    font-size: 0.92rem;
  }
  .status[hidden] { display: none; }
  h2 {
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--muted);
    margin: 2.5rem 0 0.6rem;
  }
  pre {
    margin: 0;
    padding: 1rem;
    background: #101216;
    border: 1px solid var(--line);
    border-radius: 8px;
    color: #b8c0cc;
    font: 0.8rem/1.6 ui-monospace, monospace;
    max-height: 22rem;
    overflow: auto;
    white-space: pre-wrap;
    word-break: break-word;
  }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>
</head>
<body>
<main>
  <h1>scanwatch</h1>

  <button class="toggle" id="watchBtn" onclick="flip('watch')">
    <span class="mode" id="watchMode">Loading</span>
    <span class="hint" id="watchHint"></span>
  </button>

  <button class="toggle" id="duplexBtn" onclick="flip('duplex')">
    <span class="mode" id="duplexMode"></span>
    <span class="hint" id="duplexHint"></span>
  </button>

  <div class="field">
    <label for="paper">Paper size</label>
    <select id="paper" onchange="setPaper()"></select>
  </div>

  <div class="field">
    <label>Colour</label>
    <div class="choices" id="modes"></div>
  </div>

  <div class="field">
    <label>Scan resolution</label>
    <div class="choices">
      <button class="choice" id="r300" onclick="setRes(300)">300 dpi<small>General documents</small></button>
      <button class="choice" id="r600" onclick="setRes(600)">600 dpi<small>High resolution</small></button>
    </div>
    <div class="row">
      <input type="number" id="customRes" min="50" max="4800" step="10" placeholder="Custom dpi">
      <button onclick="setCustomRes()">Set</button>
    </div>
    <p class="note" id="resNote"></p>
  </div>

  <div class="field">
    <label for="pollSecs">Check the feeder every</label>
    <div class="row">
      <input type="number" id="pollSecs" min="1" max="3600" step="1">
      <button onclick="setPoll()">Set</button>
    </div>
    <p class="note">Seconds between checks. Longer intervals leave the printer alone more of the time.</p>
  </div>

  <p class="status" id="status" hidden></p>

  <h2>Activity</h2>
  <pre id="log">Waiting for the watcher to report in.</pre>
</main>

<script>
let sizes = null;

async function refresh() {
  let d;
  try {
    d = await (await fetch('/api/state')).json();
  } catch (e) {
    document.getElementById('log').textContent = 'Cannot reach scanwatch.';
    return;
  }

  const wb = document.getElementById('watchBtn');
  wb.classList.toggle('on', !d.paused);
  wb.classList.toggle('stopped', d.paused);
  document.getElementById('watchMode').textContent =
    d.paused ? 'Watching paused' : 'Watching the feeder';
  document.getElementById('watchHint').textContent = d.paused
    ? 'The scanner is left alone so it can sleep. Tap before you scan.'
    : 'Load paper and it scans. Tap to stop contacting the scanner.';

  const db = document.getElementById('duplexBtn');
  db.classList.toggle('on', d.duplex);
  document.getElementById('duplexMode').textContent =
    d.duplex ? 'Double-sided scanning' : 'Single-sided scanning';
  document.getElementById('duplexHint').textContent = d.duplex
    ? 'Every stack pairs with the next one. Tap to go back to single-sided.'
    : 'Each stack becomes its own PDF. Tap to scan double-sided pages.';

  const sel = document.getElementById('paper');
  if (!sizes) {
    sizes = d.paper_sizes;
    for (const [k, label] of Object.entries(sizes)) {
      const o = document.createElement('option');
      o.value = k;
      o.textContent = label;
      sel.appendChild(o);
    }
  }
  if (document.activeElement !== sel) sel.value = d.paper;

  const mw = document.getElementById('modes');
  if (!mw.children.length) {
    for (const [k, label] of Object.entries(d.color_modes)) {
      const b = document.createElement('button');
      b.className = 'choice';
      b.dataset.mode = k;
      b.textContent = label;
      b.onclick = () => setMode(k);
      mw.appendChild(b);
    }
  }
  for (const b of mw.children) b.classList.toggle('sel', b.dataset.mode === d.mode);

  document.getElementById('r300').classList.toggle('sel', d.resolution === 300);
  document.getElementById('r600').classList.toggle('sel', d.resolution === 600);
  const cr = document.getElementById('customRes');
  if (document.activeElement !== cr) {
    cr.value = (d.resolution === 300 || d.resolution === 600) ? '' : d.resolution;
  }

  const note = document.getElementById('resNote');
  let txt = 'Currently ' + d.resolution + ' dpi. ';
  if (d.device && d.device.max) {
    txt += d.device.max + ' dpi is the highest the ' + (d.device.model || 'scanner') +
           ' offers over the network. Higher values are accepted but the scanner will fall back to the nearest it supports.';
  } else {
    txt += 'The scanner has not reported its supported resolutions yet.';
  }
  note.textContent = txt;

  const ps = document.getElementById('pollSecs');
  if (document.activeElement !== ps) ps.value = d.poll;

  const s = document.getElementById('status');
  if (d.pending) {
    s.hidden = false;
    s.textContent = 'Front sides are held. Put the stack back in the feeder to scan the reverse.';
  } else {
    s.hidden = true;
  }

  const log = document.getElementById('log');
  if (d.log.length) {
    log.textContent = d.log.join('\\n');
    log.scrollTop = log.scrollHeight;
  }
}

async function flip(what) {
  await fetch('/api/toggle/' + what, { method: 'POST' });
  refresh();
}

async function setMode(m) {
  await fetch('/api/mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: m }),
  });
  refresh();
}

async function setRes(dpi) {
  await fetch('/api/resolution', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ dpi: dpi }),
  });
  document.getElementById('customRes').value = '';
  refresh();
}

async function setCustomRes() {
  const v = parseInt(document.getElementById('customRes').value, 10);
  if (!v) return;
  await setRes(v);
}

async function setPoll() {
  const v = parseFloat(document.getElementById('pollSecs').value);
  if (!v) return;
  await fetch('/api/poll', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ seconds: v }),
  });
  refresh();
}

async function setPaper() {
  const v = document.getElementById('paper').value;
  await fetch('/api/paper', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ size: v }),
  });
  refresh();
}

refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(PAGE)


@app.route("/api/state")
def state():
    return jsonify(
        duplex=os.path.exists(STATE),
        pending=os.path.exists(PEND),
        paused=os.path.exists(PAUSED),
        paper=current_paper(),
        paper_sizes=PAPER_SIZES,
        resolution=current_res(),
        poll=current_poll(),
        mode=current_mode(),
        color_modes=COLOR_MODES,
        device=DEVICE,
        log=list(_LOG),
    )


@app.route("/api/toggle/duplex", methods=["POST"])
def toggle_duplex():
    if os.path.exists(STATE):
        os.remove(STATE)
        # Leaving held fronts behind would silently pair them with an
        # unrelated stack later, so drop them when the mode is turned off.
        if os.path.exists(PEND):
            with open(PEND) as fh:
                held = fh.read().strip()
            os.remove(PEND)
            if held and held.startswith("/tmp/"):
                subprocess.run(["rm", "-rf", held], check=False)
            LOG.append("double-sided turned off, discarded the held fronts")
        else:
            LOG.append("double-sided turned off")
    else:
        open(STATE, "w").close()
        LOG.append("double-sided turned on")
    return jsonify(ok=True)


@app.route("/api/toggle/watch", methods=["POST"])
def toggle_watch():
    if os.path.exists(PAUSED):
        os.remove(PAUSED)
    else:
        open(PAUSED, "w").close()
    return jsonify(ok=True)


@app.route("/api/paper", methods=["POST"])
def set_paper():
    size = (request.get_json(silent=True) or {}).get("size", "")
    if size not in PAPER_SIZES:
        return jsonify(ok=False, error="unknown paper size"), 400
    with open(PAPER, "w") as fh:
        fh.write(size)
    LOG.append("paper size set to " + PAPER_SIZES[size])
    return jsonify(ok=True)


@app.route("/api/resolution", methods=["POST"])
def set_resolution():
    try:
        dpi = int((request.get_json(silent=True) or {}).get("dpi"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="resolution must be a whole number"), 400
    if not 50 <= dpi <= 4800:
        return jsonify(ok=False, error="resolution out of range"), 400
    with open(RESFILE, "w") as fh:
        fh.write(str(dpi))
    note = ""
    if DEVICE["resolutions"] and dpi not in DEVICE["resolutions"]:
        note = " (not one of the values the scanner advertises, it will pick the nearest)"
    LOG.append("resolution set to %d dpi%s" % (dpi, note))
    return jsonify(ok=True)


@app.route("/api/poll", methods=["POST"])
def set_poll():
    try:
        secs = float((request.get_json(silent=True) or {}).get("seconds"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="interval must be a number"), 400
    if not 1 <= secs <= 3600:
        return jsonify(ok=False, error="interval must be between 1 and 3600 seconds"), 400
    with open(POLLFILE, "w") as fh:
        fh.write("%g" % secs)
    LOG.append("checking the feeder every %g seconds" % secs)
    return jsonify(ok=True)


@app.route("/api/mode", methods=["POST"])
def set_mode():
    mode = (request.get_json(silent=True) or {}).get("mode", "")
    if mode not in COLOR_MODES:
        return jsonify(ok=False, error="unknown colour mode"), 400
    with open(MODEFILE, "w") as fh:
        fh.write(mode)
    LOG.append("scanning in " + COLOR_MODES[mode].lower())
    return jsonify(ok=True)


@app.route("/healthz")
def healthz():
    return jsonify(ok=True, out_writable=os.access(OUT, os.W_OK))


if __name__ == "__main__":
    threading.Thread(target=probe_device, daemon=True).start()
    threading.Thread(target=runner, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
