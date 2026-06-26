#!/usr/bin/env python3
"""
dashboard.py — local-network dashboard for the B-Raspi ground station.

Scans the SatDump output directory, presents each recent pass as a row:
  - left:  decoded imagery (false-colour composite shown first; button cycles channels)
  - right: SNR-vs-elevation analysis graph + pass stats

Newest pass at top. Shows passes from the last N days (default 3).

Run on the Pi:
    pip3 install flask --break-system-packages
    python3 dashboard.py

Then browse from any device on your network to:
    http://<pi-ip>:5000
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, send_file, abort, Response

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_BASE = "/home/brian/satdump_output"
DAYS_BACK = 3
PORT = 5000

# SatNOGS API token — used only for fetching waterfalls server-side.
# Read from an environment variable so the token never lives in this file
# (set it in the systemd unit or export it before running).
API_TOKEN = os.environ.get("SATNOGS_API_TOKEN", "")

# Folder names look like: iq_cs16_2026-06-25T18-02-42
FOLDER_RE = re.compile(r"^iq_cs16_(\d{4})-(\d{2})-(\d{2})T(\d{2})-(\d{2})-(\d{2})$")

app = Flask(__name__)


def parse_folder_time(name):
    """Extract a UTC datetime from a pass folder name, or None if it doesn't match."""
    m = FOLDER_RE.match(name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=timezone.utc)
    except ValueError:
        return None


def classify_image(filename):
    """Order images so the false-colour composite is first, then channels."""
    low = filename.lower()
    if "false_color" in low or "false_colour" in low:
        return (0, filename)
    if "msu-mr-1" in low:
        return (1, filename)
    if "msu-mr-2" in low:
        return (2, filename)
    if "msu-mr-3" in low:
        return (3, filename)
    return (9, filename)


def list_passes():
    """Return a list of pass dicts, newest first, within the DAYS_BACK window."""
    if not os.path.isdir(OUTPUT_BASE):
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=DAYS_BACK)
    passes = []

    for name in os.listdir(OUTPUT_BASE):
        folder = os.path.join(OUTPUT_BASE, name)
        if not os.path.isdir(folder):
            continue
        dt = parse_folder_time(name)
        if dt is None or dt < cutoff:
            continue

        # images live in MSU-MR/
        img_dir = os.path.join(folder, "MSU-MR")
        images = []
        if os.path.isdir(img_dir):
            for f in os.listdir(img_dir):
                if f.lower().endswith(".png"):
                    images.append(f)
        images.sort(key=classify_image)

        # analysis CSV (may be absent)
        has_csv = os.path.isfile(os.path.join(folder, "pass_analysis.csv"))

        # metadata from the API response, if present
        sat_name = "Meteor M2-x"
        sat_key = "unknown"   # used by the front-end to decide flip behaviour
        max_el = None
        obs_id = None
        waterfall_url = None
        obs_json = os.path.join(folder, ".obs_response.json")
        if os.path.isfile(obs_json):
            try:
                with open(obs_json) as fh:
                    data = json.load(fh)
                    obs = data[0] if isinstance(data, list) and data else data
                    norad = obs.get("norad_cat_id")
                    raw_name = (obs.get("tle0") or "").lstrip("0 ").strip()
                    # NORAD ID is the authoritative disambiguator
                    if norad == 59051:
                        sat_name, sat_key = "Meteor M2-4", "m2-4"
                    elif norad == 57166:
                        sat_name, sat_key = "Meteor M2-3", "m2-3"
                    elif raw_name:
                        sat_name = raw_name
                        low = raw_name.lower()
                        if "m2-4" in low or "m2 4" in low:
                            sat_key = "m2-4"
                        elif "m2-3" in low or "m2 3" in low:
                            sat_key = "m2-3"
                    max_el = obs.get("max_altitude")
                    obs_id = obs.get("id")
                    waterfall_url = obs.get("waterfall")
            except Exception:
                pass

        # is the waterfall already cached locally?
        has_waterfall_cached = os.path.isfile(os.path.join(folder, "waterfall.png"))

        passes.append({
            "folder": name,
            "datetime_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "datetime_iso": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sat_name": sat_name,
            "sat_key": sat_key,
            "max_elevation": max_el,
            "obs_id": obs_id,
            "images": images,
            "has_analysis": has_csv,
            "has_waterfall_url": bool(waterfall_url),
            "has_waterfall_cached": has_waterfall_cached,
            "has_obs_id": bool(obs_id),
        })

    passes.sort(key=lambda p: p["datetime_utc"], reverse=True)
    return passes


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.route("/api/passes")
def api_passes():
    return jsonify(list_passes())


def _safe_folder(folder):
    """Reject any folder name that doesn't match the strict pattern (path-traversal guard)."""
    if not FOLDER_RE.match(folder):
        abort(404)
    path = os.path.join(OUTPUT_BASE, folder)
    if not os.path.isdir(path):
        abort(404)
    return path


@app.route("/api/image/<folder>/<filename>")
def api_image(folder, filename):
    base = _safe_folder(folder)
    if not filename.lower().endswith(".png") or "/" in filename or "\\" in filename:
        abort(404)
    path = os.path.join(base, "MSU-MR", filename)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png")


@app.route("/api/analysis/<folder>")
def api_analysis(folder):
    base = _safe_folder(folder)
    path = os.path.join(base, "pass_analysis.csv")
    if not os.path.isfile(path):
        abort(404)
    with open(path) as fh:
        return Response(fh.read(), mimetype="text/csv")


@app.route("/api/waterfall/<folder>")
def api_waterfall(folder):
    """Serve the locally-cached waterfall; fetch+cache from SatNOGS on first request.

    If the waterfall URL wasn't captured at decode time (SatNOGS often generates
    the waterfall a little after the pass), re-query the observation endpoint live
    by obs_id to get a current URL.
    """
    base = _safe_folder(folder)
    cached = os.path.join(base, "waterfall.png")

    # already cached -> serve it
    if os.path.isfile(cached):
        return send_file(cached, mimetype="image/png")

    obs_json = os.path.join(base, ".obs_response.json")
    if not os.path.isfile(obs_json):
        abort(404, description="No observation metadata for this pass")

    try:
        with open(obs_json) as fh:
            data = json.load(fh)
            obs = data[0] if isinstance(data, list) and data else data
            url = obs.get("waterfall")
            obs_id = obs.get("id")
    except Exception:
        abort(500, description="Could not read observation metadata")

    # If the saved URL is missing, re-query SatNOGS live by obs_id — the
    # waterfall will usually exist by now, well after the pass completed.
    if not url and obs_id:
        try:
            api_url = f"https://network.satnogs.org/api/observations/{obs_id}/"
            headers = {"User-Agent": "BRaspi-Dashboard"}
            if API_TOKEN:
                headers["Authorization"] = f"Token {API_TOKEN}"
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                fresh = json.loads(resp.read())
            url = fresh.get("waterfall")
        except Exception as e:
            abort(502, description=f"Could not re-query observation from SatNOGS: {e}")

    if not url:
        abort(404, description="No waterfall available for this pass yet")

    # fetch the image from SatNOGS and cache it locally
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BRaspi-Dashboard"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
        tmp = cached + ".tmp"
        with open(tmp, "wb") as out:
            out.write(content)
        os.replace(tmp, cached)
    except Exception as e:
        abort(502, description=f"Failed to fetch waterfall from SatNOGS: {e}")

    return send_file(cached, mimetype="image/png")


@app.route("/")
def index():
    return Response(PAGE_HTML, mimetype="text/html")


# ---------------------------------------------------------------------------
# Front-end (single self-contained page)
# ---------------------------------------------------------------------------
PAGE_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B-Raspi Ground Station</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<style>
  :root {
    --bg: #0f1419; --panel: #1a2129; --border: #2a333d;
    --text: #e6edf3; --text-dim: #8b97a3; --accent: #4a9eff; --good: #3fb950;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 24px; }
  header { max-width: 1200px; margin: 0 auto 24px; }
  h1 { font-size: 22px; font-weight: 600; }
  .sub { color: var(--text-dim); font-size: 14px; margin-top: 4px; }
  .pass { max-width: 1200px; margin: 0 auto 20px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .pass-head { padding: 12px 18px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 8px; }
  .pass-title { font-size: 16px; font-weight: 600; }
  .pass-meta { color: var(--text-dim); font-size: 13px; }
  .pass-body { display: grid; grid-template-columns: 1fr 1fr; gap: 0; }
  @media (max-width: 800px) { .pass-body { grid-template-columns: 1fr; } }
  .img-panel { padding: 16px; border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; }
  @media (max-width: 800px) { .img-panel { border-right: none; border-bottom: 1px solid var(--border); } }
  .img-frame { width: 100%; aspect-ratio: 1 / 1; background: #000; border-radius: 8px; overflow: hidden; display: flex; align-items: center; justify-content: center; }
  .img-frame img { max-width: 100%; max-height: 100%; object-fit: contain; }
  .img-controls { display: flex; align-items: center; gap: 10px; margin-top: 12px; }
  .img-controls button { background: var(--border); color: var(--text); border: none; border-radius: 6px; padding: 6px 14px; cursor: pointer; font-size: 13px; }
  .img-controls button:hover { background: #34404c; }
  .img-label { color: var(--text-dim); font-size: 13px; min-width: 130px; text-align: center; }
  .analysis-panel { padding: 16px; display: flex; flex-direction: column; }
  .stats { display: flex; gap: 18px; margin-bottom: 12px; flex-wrap: wrap; }
  .stat { background: var(--bg); border-radius: 8px; padding: 8px 14px; }
  .stat-label { color: var(--text-dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
  .stat-val { font-size: 18px; font-weight: 600; margin-top: 2px; }
  .chart-wrap { position: relative; flex: 1; min-height: 240px; }
  .view-wrap { position: relative; flex: 1; min-height: 240px; display: flex; flex-direction: column; }
  .waterfall-wrap { flex: 1; min-height: 240px; align-items: center; justify-content: center; flex-direction: column; gap: 10px; overflow: auto; }
  .wf-img { max-width: 100%; max-height: 520px; height: auto; object-fit: contain; border-radius: 6px; }
  .wf-btn { background: var(--accent); color: #fff; border: none; border-radius: 6px; padding: 8px 18px; cursor: pointer; font-size: 14px; }
  .wf-btn:hover { background: #3a8ae0; }
  .wf-hint { color: var(--text-dim); font-size: 12px; text-align: center; max-width: 320px; }
  .view-controls { margin-top: 12px; }
  .no-analysis { color: var(--text-dim); font-size: 14px; display: flex; align-items: center; justify-content: center; height: 100%; min-height: 200px; text-align: center; }
  .loading, .empty { max-width: 1200px; margin: 40px auto; text-align: center; color: var(--text-dim); }
  /* settings panel */
  .settings { max-width: 1200px; margin: 0 auto 20px; background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 18px; }
  .settings-title { font-size: 13px; font-weight: 600; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 12px; }
  .settings-row { display: flex; flex-wrap: wrap; gap: 22px; align-items: center; }
  .toggle { display: flex; align-items: center; gap: 8px; cursor: pointer; user-select: none; font-size: 14px; }
  .toggle input { display: none; }
  .toggle .track { width: 38px; height: 22px; background: var(--border); border-radius: 11px; position: relative; transition: background 0.15s; flex-shrink: 0; }
  .toggle .track::after { content: ''; position: absolute; top: 2px; left: 2px; width: 18px; height: 18px; background: #fff; border-radius: 50%; transition: transform 0.15s; }
  .toggle input:checked + .track { background: var(--accent); }
  .toggle input:checked + .track::after { transform: translateX(16px); }
  .settings-sep { width: 1px; align-self: stretch; background: var(--border); }
  .settings-group-label { font-size: 12px; color: var(--text-dim); margin-right: 4px; }
</style>
</head>
<body>
<header>
  <h1>B-Raspi Ground Station</h1>
  <div class="sub">Recent Meteor M2-x observations &middot; station 4621</div>
</header>

<div class="settings">
  <div class="settings-title">Settings</div>
  <div class="settings-row">
    <label class="toggle">
      <input type="checkbox" id="set-hide-noimg" checked>
      <span class="track"></span>
      <span>Hide passes with no decoded image</span>
    </label>
    <div class="settings-sep"></div>
    <label class="toggle">
      <input type="checkbox" id="set-irish-time">
      <span class="track"></span>
      <span>Irish local time</span>
    </label>
    <div class="settings-sep"></div>
    <span class="settings-group-label">Flip 180&deg;:</span>
    <label class="toggle">
      <input type="checkbox" id="set-flip-m2-4">
      <span class="track"></span>
      <span>M2-4</span>
    </label>
    <label class="toggle">
      <input type="checkbox" id="set-flip-m2-3" checked>
      <span class="track"></span>
      <span>M2-3</span>
    </label>
  </div>
</div>

<div id="root"><div class="loading">Loading passes&hellip;</div></div>

<script>
const charts = {};
let allPasses = [];

// ---- settings (persisted in localStorage) ----
const SETTINGS_KEY = 'braspi_dashboard_settings';
const defaultSettings = { hideNoImage: true, irishTime: false, flip: { 'm2-4': false, 'm2-3': true } };

function loadSettings() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    if (saved && saved.flip) {
      // merge with defaults so new keys appear for existing users
      return Object.assign({}, JSON.parse(JSON.stringify(defaultSettings)), saved,
        { flip: Object.assign({}, defaultSettings.flip, saved.flip) });
    }
  } catch (e) {}
  return JSON.parse(JSON.stringify(defaultSettings));
}
function saveSettings(s) {
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(s)); } catch (e) {}
}
let settings = loadSettings();

// format a UTC ISO string as either UTC or Europe/Dublin local time
function formatTime(isoUtc) {
  const d = new Date(isoUtc);
  if (settings.irishTime) {
    // Europe/Dublin handles IST/GMT DST automatically
    const s = d.toLocaleString('en-IE', {
      timeZone: 'Europe/Dublin', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
    });
    // detect whether DST (IST) is in effect for the label
    const jan = new Date(d.getFullYear(), 0, 1).getTimezoneOffset();
    const offsetNow = -(new Date(d).getTimezoneOffset());
    // simpler: ask Intl for the zone name
    let tzLabel = 'IST';
    try {
      const parts = new Intl.DateTimeFormat('en-IE', { timeZone: 'Europe/Dublin', timeZoneName: 'short' })
        .formatToParts(d);
      const tzPart = parts.find(p => p.type === 'timeZoneName');
      if (tzPart) tzLabel = tzPart.value;
    } catch (e) {}
    return `${s} ${tzLabel}`;
  }
  // UTC
  const pad = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth()+1)}-${pad(d.getUTCDate())} ` +
         `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`;
}

function applySettingsToControls() {
  document.getElementById('set-hide-noimg').checked = settings.hideNoImage;
  document.getElementById('set-irish-time').checked = settings.irishTime;
  document.getElementById('set-flip-m2-4').checked = !!settings.flip['m2-4'];
  document.getElementById('set-flip-m2-3').checked = !!settings.flip['m2-3'];
}

function wireSettings() {
  document.getElementById('set-hide-noimg').addEventListener('change', e => {
    settings.hideNoImage = e.target.checked; saveSettings(settings); render();
  });
  document.getElementById('set-irish-time').addEventListener('change', e => {
    settings.irishTime = e.target.checked; saveSettings(settings); render();
  });
  document.getElementById('set-flip-m2-4').addEventListener('change', e => {
    settings.flip['m2-4'] = e.target.checked; saveSettings(settings); render();
  });
  document.getElementById('set-flip-m2-3').addEventListener('change', e => {
    settings.flip['m2-3'] = e.target.checked; saveSettings(settings); render();
  });
}

function shouldFlip(satKey) {
  return !!settings.flip[satKey];
}

async function loadPasses() {
  try {
    const res = await fetch('/api/passes');
    allPasses = await res.json();
  } catch (e) {
    document.getElementById('root').innerHTML =
      '<div class="empty">Could not reach the dashboard server.</div>';
    return;
  }
  applySettingsToControls();
  wireSettings();
  render();
}

function render() {
  const root = document.getElementById('root');

  // visibility filter
  let visible = allPasses;
  if (settings.hideNoImage) {
    visible = visible.filter(p => p.images && p.images.length > 0);
  }

  if (!visible.length) {
    root.innerHTML = '<div class="empty">No passes to show with current settings.</div>';
    return;
  }

  // destroy old charts before re-rendering
  Object.values(charts).forEach(c => { try { c.destroy(); } catch(e){} });
  for (const k in charts) delete charts[k];

  root.innerHTML = '';
  visible.forEach((p, idx) => root.appendChild(renderPass(p, idx)));
  visible.forEach((p, idx) => initAnalysisPanel(p, idx));
}

function renderPass(p, idx) {
  const el = document.createElement('div');
  el.className = 'pass';

  const maxEl = (p.max_elevation != null) ? `${p.max_elevation}\u00b0 max` : '';
  const obsLink = p.obs_id
    ? ` &middot; <a href="https://network.satnogs.org/observations/${p.obs_id}/" target="_blank" style="color:var(--accent);text-decoration:none;">obs #${p.obs_id}</a>`
    : '';

  const hasImages = p.images && p.images.length > 0;
  const flipStyle = shouldFlip(p.sat_key) ? ' style="transform: rotate(180deg);"' : '';
  const imgPanel = hasImages ? `
    <div class="img-frame">
      <img id="img-${idx}" src="/api/image/${p.folder}/${encodeURIComponent(p.images[0])}" alt="decoded image"${flipStyle}>
    </div>
    <div class="img-controls">
      <button onclick="cycleImg(${idx}, -1)">&#8592;</button>
      <span class="img-label" id="imglabel-${idx}"></span>
      <button onclick="cycleImg(${idx}, 1)">&#8594;</button>
    </div>` : `<div class="no-analysis">No imagery decoded for this pass</div>`;

  // right panel: a cycler over available views (SNR/elev, SNR/time, waterfall)
  const analysisPanel = `
    <div class="stats" id="stats-${idx}"></div>
    <div class="view-wrap" id="viewwrap-${idx}">
      <div class="chart-wrap" id="chartwrap-${idx}" style="display:none;">
        <canvas id="chart-${idx}"></canvas>
      </div>
      <div class="waterfall-wrap" id="wfwrap-${idx}" style="display:none;"></div>
      <div class="no-analysis" id="noview-${idx}" style="display:none;"></div>
    </div>
    <div class="img-controls view-controls" id="viewctrl-${idx}" style="display:none;">
      <button onclick="cycleView(${idx}, -1)">&#8592;</button>
      <span class="img-label" id="viewlabel-${idx}"></span>
      <button onclick="cycleView(${idx}, 1)">&#8594;</button>
    </div>`;

  el.innerHTML = `
    <div class="pass-head">
      <span class="pass-title">${p.sat_name}</span>
      <span class="pass-meta">${formatTime(p.datetime_iso)}${maxEl ? ' &middot; ' + maxEl : ''}${obsLink}</span>
    </div>
    <div class="pass-body">
      <div class="img-panel">${imgPanel}</div>
      <div class="analysis-panel">${analysisPanel}</div>
    </div>`;

  if (hasImages) {
    el.dataset.images = JSON.stringify(p.images);
    el.dataset.folder = p.folder;
  }
  setTimeout(() => { if (hasImages) updateImgLabel(idx, 0, p.images); }, 0);
  return el;
}

const imgState = {};
function updateImgLabel(idx, pos, images) {
  imgState[idx] = { pos, images };
  const label = document.getElementById(`imglabel-${idx}`);
  if (label) label.textContent = prettyName(images[pos]) + ` (${pos+1}/${images.length})`;
}

function prettyName(fn) {
  const l = fn.toLowerCase();
  if (l.includes('false_color') || l.includes('false_colour')) return 'False Colour';
  if (l.includes('msu-mr-1')) return 'Channel 1';
  if (l.includes('msu-mr-2')) return 'Channel 2';
  if (l.includes('msu-mr-3')) return 'Channel 3';
  return fn.replace(/\.png$/i, '');
}

function cycleImg(idx, dir) {
  const st = imgState[idx];
  if (!st) return;
  let pos = (st.pos + dir + st.images.length) % st.images.length;
  const passEl = document.querySelectorAll('.pass')[idx];
  const folder = passEl.dataset.folder;
  document.getElementById(`img-${idx}`).src =
    `/api/image/${folder}/${encodeURIComponent(st.images[pos])}`;
  updateImgLabel(idx, pos, st.images);
}

// ---- analysis panel: build the list of available views and wire the cycler ----
const viewState = {};   // idx -> { views: [...], pos, data }

async function initAnalysisPanel(p, idx) {
  // determine which views are available for this pass
  const views = [];
  if (p.has_analysis) { views.push('snr_elev'); views.push('snr_time'); }
  // waterfall: available if cached, OR if a URL was saved, OR if we have an
  // obs_id (the backend can re-query SatNOGS live for the URL on demand)
  if (p.has_waterfall_cached || p.has_waterfall_url || p.has_obs_id) views.push('waterfall');

  viewState[idx] = { views, pos: 0, data: null, folder: p.folder,
                     cached: p.has_waterfall_cached };

  if (!views.length) {
    const nv = document.getElementById(`noview-${idx}`);
    if (nv) { nv.style.display = 'flex'; nv.innerHTML = 'No analysis available<br>for this pass yet'; }
    return;
  }

  // show the cycler controls only if more than one view
  const ctrl = document.getElementById(`viewctrl-${idx}`);
  if (ctrl && views.length > 1) ctrl.style.display = 'flex';

  // preload analysis CSV once (used by both chart views + stats)
  if (p.has_analysis) {
    try {
      const res = await fetch(`/api/analysis/${p.folder}`);
      const csv = await res.text();
      const rows = csv.trim().split('\n').slice(1).map(line => {
        const c = line.split(',');
        return { t: parseFloat(c[0]), el: parseFloat(c[2]), snr: parseFloat(c[4]) };
      }).filter(r => !isNaN(r.el) && !isNaN(r.snr));
      viewState[idx].data = rows;
      renderStats(idx, rows);
    } catch (e) {}
  }

  showView(idx, 0);
}

function renderStats(idx, rows) {
  if (!rows || !rows.length) return;
  const snrs = rows.map(r => r.snr), els = rows.map(r => r.el);
  const peakSnr = Math.max(...snrs).toFixed(1);
  const meanSnr = (snrs.reduce((a,b)=>a+b,0)/snrs.length).toFixed(1);
  const maxElev = Math.max(...els).toFixed(1);
  const statsEl = document.getElementById(`stats-${idx}`);
  if (statsEl) statsEl.innerHTML = `
    <div class="stat"><div class="stat-label">Peak SNR</div><div class="stat-val">${peakSnr} dB</div></div>
    <div class="stat"><div class="stat-label">Mean SNR</div><div class="stat-val">${meanSnr} dB</div></div>
    <div class="stat"><div class="stat-label">Max Elev.</div><div class="stat-val">${maxElev}\u00b0</div></div>`;
}

const VIEW_LABELS = { snr_elev: 'SNR vs Elevation', snr_time: 'SNR vs Time', waterfall: 'Waterfall' };

function cycleView(idx, dir) {
  const st = viewState[idx];
  if (!st || !st.views.length) return;
  st.pos = (st.pos + dir + st.views.length) % st.views.length;
  showView(idx, st.pos);
}

function showView(idx, pos) {
  const st = viewState[idx];
  if (!st) return;
  const view = st.views[pos];
  st.pos = pos;

  const chartWrap = document.getElementById(`chartwrap-${idx}`);
  const wfWrap = document.getElementById(`wfwrap-${idx}`);
  const noView = document.getElementById(`noview-${idx}`);
  const label = document.getElementById(`viewlabel-${idx}`);
  [chartWrap, wfWrap, noView].forEach(e => { if (e) e.style.display = 'none'; });
  if (label) label.textContent = `${VIEW_LABELS[view]} (${pos+1}/${st.views.length})`;

  if (view === 'snr_elev' || view === 'snr_time') {
    if (chartWrap) chartWrap.style.display = 'block';
    drawChart(idx, view);
  } else if (view === 'waterfall') {
    if (wfWrap) wfWrap.style.display = 'flex';
    showWaterfall(idx);
  }
}

function drawChart(idx, view) {
  const st = viewState[idx];
  if (!st || !st.data) return;
  const rows = st.data;

  let pts, xLabel, xKey;
  if (view === 'snr_time') {
    xKey = 't'; xLabel = 'Time into pass (s)';
    pts = rows.map(r => ({ x: r.t, y: r.snr }));   // time order, as recorded
  } else {
    xKey = 'el'; xLabel = 'Elevation (deg)';
    pts = rows.map(r => ({ x: r.el, y: r.snr })).sort((a,b) => a.x - b.x);
  }

  // destroy any existing chart on this canvas before redrawing
  if (charts[idx]) { try { charts[idx].destroy(); } catch(e){} }

  const ctx = document.getElementById(`chart-${idx}`);
  if (!ctx) return;
  charts[idx] = new Chart(ctx, {
    type: 'scatter',
    data: { datasets: [{
      label: 'Measured SNR', data: pts,
      pointRadius: 2, pointBackgroundColor: '#4a9eff', showLine: false,
    }]},
    options: {
      responsive: true, maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: i => view === 'snr_time'
          ? `${i.parsed.y.toFixed(1)} dB at ${i.parsed.x.toFixed(0)}s`
          : `${i.parsed.y.toFixed(1)} dB at ${i.parsed.x.toFixed(1)}\u00b0` } } },
      scales: {
        x: { title: { display: true, text: xLabel, color: '#8b97a3' },
             ticks: { color: '#8b97a3' }, grid: { color: 'rgba(255,255,255,0.06)' } },
        y: { title: { display: true, text: 'SNR (dB)', color: '#8b97a3' },
             ticks: { color: '#8b97a3' }, grid: { color: 'rgba(255,255,255,0.06)' } }
      }
    }
  });
}

function showWaterfall(idx) {
  const st = viewState[idx];
  const wf = document.getElementById(`wfwrap-${idx}`);
  if (!wf) return;

  // already loaded into the DOM?
  if (wf.dataset.loaded === '1') return;

  if (st.cached) {
    // cached server-side: load directly
    wf.innerHTML = `<img class="wf-img" src="/api/waterfall/${st.folder}" alt="waterfall">`;
    wf.dataset.loaded = '1';
  } else {
    // not cached: show a button that triggers the fetch+cache
    wf.innerHTML = `
      <button class="wf-btn" onclick="fetchWaterfall(${idx})">Get Waterfall</button>
      <div class="wf-hint">Fetches the waterfall image from SatNOGS and caches it locally.</div>`;
  }
}

async function fetchWaterfall(idx) {
  const st = viewState[idx];
  const wf = document.getElementById(`wfwrap-${idx}`);
  if (!wf) return;
  wf.innerHTML = `<div class="wf-hint">Fetching waterfall&hellip;</div>`;
  try {
    const res = await fetch(`/api/waterfall/${st.folder}`);
    if (!res.ok) {
      const txt = await res.text();
      wf.innerHTML = `<div class="wf-hint">Could not fetch waterfall (${res.status}).</div>
        <button class="wf-btn" onclick="fetchWaterfall(${idx})">Retry</button>`;
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    wf.innerHTML = `<img class="wf-img" src="${url}" alt="waterfall">`;
    wf.dataset.loaded = '1';
    st.cached = true;
  } catch (e) {
    wf.innerHTML = `<div class="wf-hint">Network error fetching waterfall.</div>
      <button class="wf-btn" onclick="fetchWaterfall(${idx})">Retry</button>`;
  }
}

loadPasses();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print(f"B-Raspi dashboard starting on port {PORT}")
    print(f"Scanning: {OUTPUT_BASE}")
    print(f"Browse from your network to: http://<pi-ip>:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
