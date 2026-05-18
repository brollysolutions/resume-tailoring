"""Admin / observability endpoints. Read-only (mostly).

GET  /api/admin/calibration         — current weights + last attempt + history
POST /api/admin/calibration/run     — manual one-shot calibration cycle (no auth gate yet)
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

router = APIRouter()

_BACKEND = Path(__file__).resolve().parents[2]
_DATA = _BACKEND / "data"
_LAST_ATTEMPT_PATH = _DATA / "auto_calibrator_last_attempt.json"
_STATE_PATH = _DATA / "auto_calibrator_state.json"


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("admin: failed reading %s: %s", path, e)
        return None


@router.get("/calibration")
async def get_calibration_status():
    """Snapshot: live weights, last attempt result, recent history, watcher state."""
    from app.core.weights_store import get_weights, history, as_dict
    return {
        "active": as_dict(get_weights()),
        "last_attempt": _read_json(_LAST_ATTEMPT_PATH),
        "watcher_state": _read_json(_STATE_PATH),
        "history": history(limit=10),
    }


@router.post("/calibration/run")
async def trigger_calibration():
    """Run one calibration cycle synchronously. Returns the same dict the
    background watcher would have produced."""
    try:
        from app.core.auto_calibrator import run_calibration_cycle
        import asyncio
        result = await asyncio.to_thread(run_calibration_cycle)
        return result
    except Exception as e:
        logger.exception("admin: manual calibration crashed")
        raise HTTPException(status_code=500, detail=str(e))


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Calibration Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d;
    --fg: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --good: #3fb950; --warn: #d29922; --bad: #f85149;
  }
  body { background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", monospace; margin: 0; padding: 24px; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  h2 { margin: 24px 0 8px; font-size: 14px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 16px; }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 28px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .card .hint { color: var(--muted); font-size: 11px; margin-top: 6px; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
  th, td { padding: 8px 12px; text-align: left; font-size: 13px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  th { background: #1f242c; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  tr:last-child td { border-bottom: none; }
  pre { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; color: var(--fg); margin: 0; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }
  .pill.swapped { background: rgba(63,185,80,0.15); color: var(--good); }
  .pill.below_threshold { background: rgba(139,148,158,0.15); color: var(--muted); }
  .pill.gate_failed { background: rgba(248,81,73,0.15); color: var(--bad); }
  .pill.tune_insufficient_data, .pill.cosine_insufficient_bad, .pill.cosine_narrow_spread { background: rgba(210,153,34,0.15); color: var(--warn); }
  button { background: var(--accent); color: white; border: 0; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 13px; }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
  .toolbar .auto { color: var(--muted); font-size: 12px; }
  .reasons { color: var(--bad); font-size: 12px; margin-top: 8px; }
  .reasons li { margin-left: 16px; }
</style>
</head>
<body>
  <h1>Calibration Dashboard</h1>
  <div class="sub">Live hybrid-scorer weights + auto-calibrator state. Dev view — not for users.</div>

  <div class="toolbar">
    <button id="run-btn" onclick="runCycle()">Run cycle now</button>
    <span class="auto">Auto-refresh: <span id="refresh-state">on (5s)</span></span>
    <span class="auto">Last updated: <span id="last-update">—</span></span>
  </div>

  <h2>Active weights</h2>
  <div class="grid" id="active-grid"></div>

  <h2>Last calibration attempt</h2>
  <div id="last-attempt"></div>

  <h2>Watcher state <span style="color:var(--muted);font-size:11px;font-weight:400">(trigger: every 10 uploads)</span></h2>
  <pre id="watcher-state">—</pre>

  <h2>History (last 10)</h2>
  <table id="history-table">
    <thead><tr><th>When</th><th>w_kw</th><th>w_skill</th><th>w_ngram</th><th>w_edu</th><th>w_sen</th><th>w_cos</th><th>p_low</th><th>p_high</th><th>N</th><th>Spearman</th><th>Source</th></tr></thead>
    <tbody id="history-body"></tbody>
  </table>

<script>
async function fetchStatus() {
  try {
    const r = await fetch('/api/admin/calibration');
    const d = await r.json();
    render(d);
    document.getElementById('last-update').textContent = new Date().toLocaleTimeString();
  } catch (e) {
    console.error('fetch failed', e);
  }
}

function fmt(v, digits=4) {
  if (v === null || v === undefined) return '—';
  return typeof v === 'number' ? v.toFixed(digits) : v;
}

function render(d) {
  const a = d.active || {};
  document.getElementById('active-grid').innerHTML = `
    <div class="card"><div class="label">w_kw</div><div class="value">${fmt(a.w_kw, 2)}</div><div class="hint">keyword coverage · req 70% / pref 30%</div></div>
    <div class="card"><div class="label">w_skill</div><div class="value">${fmt(a.w_skill, 2)}</div><div class="hint">skill taxonomy · domain align 60/40</div></div>
    <div class="card"><div class="label">w_ngram</div><div class="value">${fmt(a.w_ngram, 2)}</div><div class="hint">multi-word skills (ML, CI/CD, etc.)</div></div>
    <div class="card"><div class="label">w_edu</div><div class="value">${fmt(a.w_edu, 2)}</div><div class="hint">degree level fit</div></div>
    <div class="card"><div class="label">w_sen</div><div class="value">${fmt(a.w_sen, 2)}</div><div class="hint">seniority · years-of-experience gap</div></div>
    <div class="card"><div class="label">w_cos</div><div class="value">${fmt(a.w_cos, 2)}</div><div class="hint">cosine · whole-doc + exp section 50/50</div></div>
    <div class="card"><div class="label">p_low / p_high</div><div class="value">${fmt(a.p_low)}<span style="color:var(--muted);font-size:18px"> → </span>${fmt(a.p_high)}</div><div class="hint">cosine remap anchors</div></div>
    <div class="card"><div class="label">N rows</div><div class="value">${a.n_rows ?? 0}</div><div class="hint">labeled pairs fit on</div></div>
    <div class="card"><div class="label">Spearman</div><div class="value">${fmt(a.spearman, 3)}</div><div class="hint">τ=${fmt(a.kendall_tau, 3)}</div></div>
    <div class="card"><div class="label">Source</div><div class="value" style="font-size:16px">${a.source || '—'}</div><div class="hint">${a.calibrated_at || 'never calibrated'}</div></div>
  `;

  const la = d.last_attempt;
  const lastEl = document.getElementById('last-attempt');
  if (!la) {
    lastEl.innerHTML = '<pre>No attempts recorded yet.</pre>';
  } else {
    const reasonsHtml = la.reasons && la.reasons.length
      ? `<ul class="reasons">${la.reasons.map(r => `<li>${r}</li>`).join('')}</ul>`
      : '';
    lastEl.innerHTML = `
      <div class="card">
        <div><span class="pill ${la.status}">${la.status}</span> &nbsp; ${la.swapped ? '<span style="color:var(--good)">✓ weights swapped</span>' : '<span style="color:var(--muted)">no swap</span>'}</div>
        <div class="hint" style="margin-top:8px">uploads=${la.upload_count ?? '—'} · labels=${la.label_count} · new_uploads_since_last=${la.new_since_last} · trigger=${la.trigger_threshold} · recorded ${la.recorded_at || ''}</div>
        ${reasonsHtml}
        ${la.candidate ? `<div class="hint" style="margin-top:8px">candidate: kw=${fmt(la.candidate.w_kw,2)} skill=${fmt(la.candidate.w_skill,2)} cos=${fmt(la.candidate.w_cos,2)} · spearman=${fmt(la.candidate.spearman,3)}</div>` : ''}
        ${la.new_weights ? `<div class="hint" style="margin-top:8px">new: kw=${fmt(la.new_weights.w_kw,2)} skill=${fmt(la.new_weights.w_skill,2)} ngram=${fmt(la.new_weights.w_ngram,2)} edu=${fmt(la.new_weights.w_edu,2)} sen=${fmt(la.new_weights.w_sen,2)} cos=${fmt(la.new_weights.w_cos,2)} · p_low=${fmt(la.new_weights.p_low)} p_high=${fmt(la.new_weights.p_high)}</div>` : ''}
        ${la.spearman ? `<div class="hint">spearman: new=${fmt(la.spearman,3)} old=${fmt(la.old_spearman,3)}</div>` : ''}
        ${la.implicit_labels_added ? `<div class="hint">implicit labels: +${la.implicit_labels_added.new_labels} new · ${la.implicit_labels_added.skipped_existing} dedup · ${la.implicit_labels_added.skipped_too_recent} too-recent${la.implicit_labels_added.by_signal ? ` · tailor_click=${la.implicit_labels_added.by_signal.tailor_clicked} bad_timeout=${la.implicit_labels_added.by_signal.no_tailor_2h} ceiling=${la.implicit_labels_added.by_signal.ceiling_hit} session=${la.implicit_labels_added.by_signal.session_pairwise}` : ''}</div>` : ''}
      </div>`;
  }

  document.getElementById('watcher-state').textContent = d.watcher_state
    ? JSON.stringify(d.watcher_state, null, 2)
    : '— (no cycles yet)';

  const body = document.getElementById('history-body');
  if (!d.history || d.history.length === 0) {
    body.innerHTML = '<tr><td colspan="9" style="color:var(--muted);text-align:center">No history yet.</td></tr>';
  } else {
    body.innerHTML = d.history.map(h => `
      <tr>
        <td>${(h.calibrated_at || '').slice(0,19)}</td>
        <td>${fmt(h.w_kw,2)}</td>
        <td>${fmt(h.w_skill,2)}</td>
        <td>${fmt(h.w_ngram,2)}</td>
        <td>${fmt(h.w_edu,2)}</td>
        <td>${fmt(h.w_sen,2)}</td>
        <td>${fmt(h.w_cos,2)}</td>
        <td>${fmt(h.p_low)}</td>
        <td>${fmt(h.p_high)}</td>
        <td>${h.n_rows ?? 0}</td>
        <td>${fmt(h.spearman,3)}</td>
        <td>${h.source || '—'}</td>
      </tr>`).join('');
  }
}

async function runCycle() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.textContent = 'Running...';
  try {
    await fetch('/api/admin/calibration/run', { method: 'POST' });
    await fetchStatus();
  } catch (e) {
    alert('Run failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Run cycle now';
  }
}

fetchStatus();
setInterval(fetchStatus, 5000);
</script>
</body>
</html>
"""


@router.get("/dashboard", response_class=HTMLResponse)
async def calibration_dashboard():
    """Dev-only dashboard. Plain HTML, polls /api/admin/calibration every 5s."""
    return HTMLResponse(content=_DASHBOARD_HTML)
