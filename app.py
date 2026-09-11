#!/usr/bin/env python3
"""scanwatch: watches the scanner's document feeder and files PDFs."""

import collections
import os
import subprocess
import threading

from flask import Flask, jsonify, render_template_string

app = Flask(__name__)

STATE = "/state/duplex"
PEND = "/state/pending"
OUT = "/out"

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
    letter-spacing: 0.01em;
    margin: 0 0 1.5rem;
    color: var(--muted);
  }
  .toggle {
    width: 100%;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--panel);
    color: var(--text);
    padding: 1.75rem 1.5rem;
    text-align: left;
    font: inherit;
    cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  .toggle:hover { border-color: #3b4250; }
  .toggle:focus-visible { outline: 2px solid var(--live); outline-offset: 2px; }
  .toggle.on { border-color: var(--live); background: #1b2a24; }
  .mode {
    font-size: 1.5rem;
    font-weight: 600;
    display: block;
    margin-bottom: 0.35rem;
  }
  .hint { color: var(--muted); font-size: 0.9rem; }
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
  @media (prefers-reduced-motion: reduce) {
    * { transition: none !important; }
  }
</style>
</head>
<body>
<main>
  <h1>scanwatch</h1>

  <button class="toggle" id="toggle" onclick="flip()">
    <span class="mode" id="mode">Loading</span>
    <span class="hint" id="hint"></span>
  </button>

  <p class="status" id="status" hidden></p>

  <h2>Activity</h2>
  <pre id="log">Waiting for the watcher to report in.</pre>
</main>

<script>
async function refresh() {
  let d;
  try {
    d = await (await fetch('/api/state')).json();
  } catch (e) {
    document.getElementById('log').textContent = 'Cannot reach scanwatch.';
    return;
  }

  const btn = document.getElementById('toggle');
  btn.classList.toggle('on', d.duplex);
  document.getElementById('mode').textContent =
    d.duplex ? 'Double-sided scanning' : 'Single-sided scanning';
  document.getElementById('hint').textContent = d.duplex
    ? 'Every stack pairs with the next one. Tap to go back to single-sided.'
    : 'Each stack becomes its own PDF. Tap to scan double-sided pages.';

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

async function flip() {
  await fetch('/api/toggle', { method: 'POST' });
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
        log=list(LOG),
    )


@app.route("/api/toggle", methods=["POST"])
def toggle():
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


@app.route("/healthz")
def healthz():
    return jsonify(ok=True, out_writable=os.access(OUT, os.W_OK))


if __name__ == "__main__":
    threading.Thread(target=runner, daemon=True).start()
    app.run(host="0.0.0.0", port=8080)
