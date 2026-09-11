#!/usr/bin/env python3
"""scanwatch: watches the scanner's document feeder and files PDFs."""

import collections
import os
import subprocess
import threading

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

STATE = "/state/duplex"
PEND = "/state/pending"
PAPER = "/state/paper"
PAUSED = "/state/paused"
OUT = "/out"

PAPER_SIZES = {
    "letter": "Letter, 8.5 by 11 inches",
    "a4": "A4, 210 by 297 mm",
    "legal": "Legal, 8.5 by 14 inches",
    "a5": "A5, 148 by 210 mm",
    "receipt": "Receipt, 80 mm wide",
}

LOG = collections.deque(maxlen=100)


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
        log=list(LOG),
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


@app.route("/healthz")
def healthz():
    return jsonify(ok=True, out_writable=os.access(OUT, os.W_OK))


if __name__ == "__main__":
    threading.Thread(target=runner, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
