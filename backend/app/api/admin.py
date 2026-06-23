"""Admin / observability endpoints. Read-only (mostly).

GET  /api/admin/calibration         — current weights + last attempt + history
POST /api/admin/calibration/run     — manual one-shot calibration cycle (no auth gate yet)
GET  /api/admin/dashboard           — HTML dashboard
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
_SECTION_LOG = _DATA / "section_score_log.jsonl"
_SECTION_RESULTS = _DATA / "section_calibration_results.json"

_SECTIONS = ("summary", "experience", "projects", "skills")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("admin: failed reading %s: %s", path, e)
        return None


def _section_log_stats() -> dict:
    """Count rows per section in section_score_log.jsonl."""
    counts = {s: 0 for s in _SECTIONS}
    if not _SECTION_LOG.exists():
        return counts
    try:
        with _SECTION_LOG.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    sec = ev.get("section", "")
                    if sec in counts:
                        counts[sec] += 1
                except Exception:
                    continue
    except Exception:
        pass
    return counts


@router.get("/calibration")
async def get_calibration_status():
    """Snapshot: live weights, last attempt result, recent history, watcher state,
    per-section weights, section log stats, section calibration results."""
    from app.core.weights_store import get_weights, history, as_dict

    active = as_dict(get_weights())

    # Build per-section weight table (calibrated vs hand-tuned default)
    from app.api.match_logic.section_scorer import DEFAULT_SECTION_WEIGHTS
    section_w_table: dict = {}
    cal_sw = active.get("section_weights") or {}
    for sec in _SECTIONS:
        if sec in cal_sw and cal_sw[sec]:
            section_w_table[sec] = {**cal_sw[sec], "source": "calibrated"}
        else:
            section_w_table[sec] = {**DEFAULT_SECTION_WEIGHTS.get(sec, {}), "source": "default"}

    from app.core.llm_labeler import count_by_source
    label_sources = count_by_source()

    return {
        "active": active,
        "last_attempt": _read_json(_LAST_ATTEMPT_PATH),
        "watcher_state": _read_json(_STATE_PATH),
        "history": history(limit=10),
        "section_weights_table": section_w_table,
        "section_log_stats": _section_log_stats(),
        "section_calibration_results": _read_json(_SECTION_RESULTS),
        "label_sources": label_sources,
    }


@router.post("/calibration/run")
async def trigger_calibration():
    """Run one calibration cycle synchronously."""
    try:
        from app.core.auto_calibrator import run_calibration_cycle
        import asyncio
        result = await asyncio.to_thread(run_calibration_cycle)
        return result
    except Exception as e:
        logger.exception("admin: manual calibration crashed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/calibration/label-llm")
async def trigger_llm_labeling(limit: int = 20, concurrency: int = 4):
    """Label unlabeled score_log pairs via LLM judge.

    limit caps the number of LLM calls per request for cost control.
    Call this explicitly — it is NOT part of the auto-calibration loop.
    """
    try:
        from app.core.llm_labeler import label_unlabeled_pairs
        result = await label_unlabeled_pairs(limit=limit, concurrency=concurrency)
        return result
    except Exception as e:
        logger.exception("admin: LLM labeling crashed")
        raise HTTPException(status_code=500, detail=str(e))


_DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Calibration Dashboard</title>
<style>
  :root {
    --bg: #f6f8fa; --panel: #ffffff; --border: #d0d7de;
    --fg: #24292f; --muted: #57606a; --accent: #0969da;
    --good: #1a7f37; --warn: #9a6700; --bad: #cf222e;
    --cal: #8250df;
  }
  * { box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 24px; }
  h1 { margin: 0 0 4px; font-size: 20px; }
  h2 { margin: 28px 0 10px; font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.6px; font-weight: 600; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
  .sub { color: var(--muted); font-size: 12px; margin-bottom: 24px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 14px; box-shadow: 0 1px 3px rgba(31,35,40,0.06); }
  .card .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 26px; font-weight: 600; margin-top: 4px; font-variant-numeric: tabular-nums; }
  .card .hint { color: var(--muted); font-size: 11px; margin-top: 6px; line-height: 1.5; }
  table { width: 100%; border-collapse: collapse; background: var(--panel); border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin-bottom: 8px; box-shadow: 0 1px 2px rgba(31,35,40,0.04); }
  th, td { padding: 7px 11px; text-align: left; font-size: 12px; border-bottom: 1px solid var(--border); font-variant-numeric: tabular-nums; }
  th { background: #f6f8fa; color: var(--muted); font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: rgba(31,35,40,0.03); }
  pre { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; color: var(--fg); margin: 0; }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; }
  .pill.swapped { background: rgba(26,127,55,0.1); color: var(--good); }
  .pill.below_threshold { background: rgba(87,96,106,0.1); color: var(--muted); }
  .pill.gate_failed { background: rgba(207,34,46,0.1); color: var(--bad); }
  .pill.tune_insufficient_data,.pill.cosine_insufficient_bad,.pill.cosine_narrow_spread,.pill.weak_signal { background: rgba(154,103,0,0.1); color: var(--warn); }
  .pill.ok { background: rgba(26,127,55,0.1); color: var(--good); }
  .pill.calibrated { background: rgba(130,80,223,0.1); color: var(--cal); }
  .pill.default { background: rgba(87,96,106,0.1); color: var(--muted); }
  .pill.insufficient_data { background: rgba(154,103,0,0.1); color: var(--warn); }
  button { background: var(--accent); color: white; border: 0; padding: 8px 16px; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: 13px; }
  button:hover { opacity: 0.85; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .toolbar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; }
  .toolbar .auto { color: var(--muted); font-size: 12px; }
  .reasons { color: var(--bad); font-size: 12px; margin-top: 8px; padding-left: 0; list-style: none; }
  .reasons li::before { content: "✗ "; }
  .reasons li { margin-bottom: 3px; }
  .signal-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 6px; }
  .signal-chip { background: rgba(9,105,218,0.08); border: 1px solid rgba(9,105,218,0.2); border-radius: 4px; padding: 2px 8px; font-size: 11px; color: var(--accent); }
  .progress-bar { height: 4px; background: var(--border); border-radius: 2px; margin-top: 6px; overflow: hidden; }
  .progress-bar .fill { height: 100%; background: var(--accent); border-radius: 2px; transition: width 0.3s; }
  .section-block { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 10px; }
  .section-card { background: var(--panel); border: 1px solid var(--border); border-radius: 6px; padding: 14px; }
  .section-card .sec-title { font-size: 13px; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; gap: 8px; }
  .section-card .weight-row { display: flex; justify-content: space-between; font-size: 12px; padding: 3px 0; border-bottom: 1px solid var(--border); }
  .section-card .weight-row:last-child { border-bottom: none; }
  .section-card .weight-key { color: var(--muted); }
  .section-card .weight-val { font-variant-numeric: tabular-nums; font-weight: 600; }
  .section-card .weight-val.zero { color: var(--border); }
  .meta-row { display: flex; gap: 16px; margin-top: 10px; font-size: 11px; color: var(--muted); }
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  @media (max-width: 700px) { .two-col { grid-template-columns: 1fr; } }
</style>
</head>
<body>
  <h1>Calibration Dashboard</h1>
  <div class="sub">Hybrid-scorer weights · auto-calibrator state · section diagnostics · dev-only view</div>

  <div class="toolbar">
    <button id="run-btn" onclick="runCycle()">Run cycle now</button>
    <button id="llm-btn" onclick="runLlmLabel()" style="background:var(--cal)">Label via LLM (limit 20)</button>
    <span class="auto">Auto-refresh: <span id="refresh-state">on (5s)</span></span>
    <span class="auto">Last updated: <span id="last-update">—</span></span>
  </div>

  <h2>Global active weights</h2>
  <div class="grid" id="active-grid"></div>

  <h2>Per-section weights</h2>
  <p style="color:var(--muted);font-size:12px;margin:0 0 12px"><span style="color:var(--cal)">■</span> calibrated &nbsp; <span style="color:var(--muted)">■</span> hand-tuned default (auto-calibrated after ≥10 labeled rows per section)</p>
  <div class="section-block" id="section-weights-block"></div>

  <h2>Section score log — data accumulation</h2>
  <p style="color:var(--muted);font-size:12px;margin:0 0 10px">Rows logged per section toward per-section calibration (need ≥10 to calibrate)</p>
  <div id="section-log-stats"></div>

  <h2>Label sources</h2>
  <p style="color:var(--muted);font-size:12px;margin:0 0 10px">Breakdown of labels.jsonl rows by source (human > llm > implicit in calibration priority)</p>
  <div id="label-sources"></div>

  <h2>Last calibration attempt</h2>
  <div id="last-attempt"></div>

  <h2>Section calibration — last run results</h2>
  <div id="section-cal-results"></div>

  <h2>Watcher state</h2>
  <pre id="watcher-state">—</pre>

  <h2>Global weight history (last 10)</h2>
  <div style="overflow-x:auto">
  <table id="history-table">
    <thead><tr>
      <th>When</th><th>w_kw</th><th>w_skill</th><th>w_ngram</th><th>w_edu</th><th>w_sen</th><th>w_cos</th>
      <th>p_low</th><th>p_high</th><th>N</th><th>Spearman</th><th>Kendall τ</th><th>Source</th>
    </tr></thead>
    <tbody id="history-body"></tbody>
  </table>
  </div>

<script>
const MIN_ROWS_CAL = 10;

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
  return typeof v === 'number' ? v.toFixed(digits) : String(v);
}
function pct(v) {
  if (v === null || v === undefined) return '—';
  return (v * 100).toFixed(1) + '%';
}

function weightVal(v) {
  const n = typeof v === 'number' ? v : parseFloat(v);
  if (isNaN(n)) return '<span class="weight-val zero">0.00</span>';
  const cls = n === 0 ? 'weight-val zero' : 'weight-val';
  return `<span class="${cls}">${n.toFixed(2)}</span>`;
}

function renderSectionWeights(swTable) {
  if (!swTable) { document.getElementById('section-weights-block').innerHTML = '<p style="color:var(--muted);font-size:12px">No data.</p>'; return; }
  const sections = ['summary','experience','projects','skills'];
  const labels = { w_kw:'keyword', w_skill:'skill', w_ngram:'n-gram', w_edu:'education', w_sen:'seniority', w_cos:'semantic' };
  document.getElementById('section-weights-block').innerHTML = sections.map(sec => {
    const sw = swTable[sec] || {};
    const src = sw.source || 'default';
    const sp = sw.spearman != null ? `spearman ${fmt(sw.spearman, 3)}` : '';
    const nr = sw.n_rows != null ? `N=${sw.n_rows}` : '';
    return `<div class="section-card">
      <div class="sec-title">
        ${sec.charAt(0).toUpperCase()+sec.slice(1)}
        <span class="pill ${src}">${src}</span>
      </div>
      ${Object.entries(labels).map(([k,lbl]) =>
        `<div class="weight-row"><span class="weight-key">${lbl}</span>${weightVal(sw[k])}</div>`
      ).join('')}
      <div class="meta-row">
        ${sp ? `<span>${sp}</span>` : ''}
        ${nr ? `<span>${nr}</span>` : ''}
      </div>
    </div>`;
  }).join('');
}

function renderSectionLogStats(stats) {
  if (!stats) { document.getElementById('section-log-stats').innerHTML = '<pre>No section_score_log.jsonl yet.</pre>'; return; }
  const sections = ['summary','experience','projects','skills'];
  document.getElementById('section-log-stats').innerHTML = `<table>
    <thead><tr><th>Section</th><th>Rows logged</th><th>Progress to calibration (≥${MIN_ROWS_CAL})</th><th>Status</th></tr></thead>
    <tbody>${sections.map(sec => {
      const n = stats[sec] || 0;
      const pctFill = Math.min(100, Math.round(n / MIN_ROWS_CAL * 100));
      const ready = n >= MIN_ROWS_CAL;
      return `<tr>
        <td style="font-weight:600">${sec}</td>
        <td>${n}</td>
        <td style="min-width:140px">
          <div class="progress-bar"><div class="fill" style="width:${pctFill}%;background:${ready ? 'var(--good)' : 'var(--accent)'}"></div></div>
          <span style="font-size:10px;color:var(--muted)">${pctFill}%</span>
        </td>
        <td>${ready ? '<span class="pill ok">ready</span>' : `<span class="pill below_threshold">${MIN_ROWS_CAL - n} more needed</span>`}</td>
      </tr>`;
    }).join('')}</tbody>
  </table>`;
}

function renderSectionCalResults(res) {
  const el = document.getElementById('section-cal-results');
  if (!res) { el.innerHTML = '<pre>No section_calibration_results.json yet — run a calibration cycle first.</pre>'; return; }
  const sections = ['summary','experience','projects','skills'];
  el.innerHTML = `<div style="overflow-x:auto"><table>
    <thead><tr>
      <th>Section</th><th>Status</th><th>N rows</th>
      <th>w_kw</th><th>w_skill</th><th>w_ngram</th><th>w_edu</th><th>w_sen</th><th>w_cos</th>
      <th>Spearman</th><th>Kendall τ</th>
    </tr></thead>
    <tbody>${sections.map(sec => {
      const r = res[sec];
      if (!r) return `<tr><td>${sec}</td><td colspan="10" style="color:var(--muted)">—</td></tr>`;
      const b = r.best || {};
      return `<tr>
        <td style="font-weight:600">${sec}</td>
        <td><span class="pill ${r.status}">${r.status}</span></td>
        <td>${r.n_rows ?? 0}</td>
        <td>${fmt(b.w_kw, 2)}</td><td>${fmt(b.w_skill, 2)}</td><td>${fmt(b.w_ngram, 2)}</td>
        <td>${fmt(b.w_edu, 2)}</td><td>${fmt(b.w_sen, 2)}</td><td>${fmt(b.w_cos, 2)}</td>
        <td style="color:${(b.spearman||0)>=0.3?'var(--good)':'var(--warn)'}">${fmt(b.spearman, 4)}</td>
        <td>${fmt(b.kendall_tau, 4)}</td>
      </tr>`;
    }).join('')}</tbody>
  </table></div>`;
}

function render(d) {
  const a = d.active || {};

  // Global weights cards
  document.getElementById('active-grid').innerHTML = `
    <div class="card"><div class="label">w_kw — keyword</div><div class="value">${fmt(a.w_kw, 2)}</div><div class="hint">BM25 keyword coverage · req 70% / pref 30% blend</div></div>
    <div class="card"><div class="label">w_skill — skill taxonomy</div><div class="value">${fmt(a.w_skill, 2)}</div><div class="hint">Skill domain alignment · required 60% / preferred 40%</div></div>
    <div class="card"><div class="label">w_ngram — phrase match</div><div class="value">${fmt(a.w_ngram, 2)}</div><div class="hint">Multi-word phrases: "machine learning", "CI/CD"</div></div>
    <div class="card"><div class="label">w_edu — education</div><div class="value">${fmt(a.w_edu, 2)}</div><div class="hint">Degree-level fit to JD requirements</div></div>
    <div class="card"><div class="label">w_sen — seniority</div><div class="value">${fmt(a.w_sen, 2)}</div><div class="hint">Years-of-experience gap penalty</div></div>
    <div class="card"><div class="label">w_cos — semantic</div><div class="value">${fmt(a.w_cos, 2)}</div><div class="hint">Cosine similarity · whole-doc + experience 50/50</div></div>
    <div class="card"><div class="label">Cosine remap p_low → p_high</div><div class="value" style="font-size:18px">${fmt(a.p_low, 4)} → ${fmt(a.p_high, 4)}</div><div class="hint">Raw cosine is rescaled: below p_low → 0, above p_high → 1</div></div>
    <div class="card"><div class="label">Labeled rows (N)</div><div class="value">${a.n_rows ?? 0}</div><div class="hint">Labeled (resume, JD) pairs used in last fit</div></div>
    <div class="card"><div class="label">Spearman ρ</div><div class="value" style="color:${(a.spearman||0)>=0.4?'var(--good)':(a.spearman||0)>=0.2?'var(--warn)':'var(--bad)'}">${fmt(a.spearman, 3)}</div><div class="hint">Kendall τ = ${fmt(a.kendall_tau, 3)} · target ≥ 0.40 at N≥300</div></div>
    <div class="card"><div class="label">Source / calibrated at</div><div class="value" style="font-size:15px">${a.source || '—'}</div><div class="hint">${a.calibrated_at ? a.calibrated_at.slice(0,19).replace('T',' ') + ' UTC' : 'never calibrated — using hard-coded defaults'}</div></div>
  `;

  renderSectionWeights(d.section_weights_table);
  renderSectionLogStats(d.section_log_stats);
  renderLabelSources(d.label_sources);

  // Last attempt
  const la = d.last_attempt;
  const lastEl = document.getElementById('last-attempt');
  if (!la) {
    lastEl.innerHTML = '<pre>No attempts recorded yet.</pre>';
  } else {
    const signals = la.implicit_labels_added?.by_signal || {};
    const signalHtml = Object.keys(signals).length
      ? `<div class="signal-row">${Object.entries(signals).map(([k,v]) => `<span class="signal-chip">${k}: +${v}</span>`).join('')}</div>`
      : '';

    const reasonsHtml = la.reasons?.length
      ? `<ul class="reasons">${la.reasons.map(r => `<li>${r}</li>`).join('')}</ul>`
      : '';

    const swUpdated = la.section_weights_updated?.length
      ? `<div style="margin-top:8px;font-size:12px">Section weights updated: <strong>${la.section_weights_updated.join(', ')}</strong></div>`
      : '';

    lastEl.innerHTML = `<div class="card">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">
        <span class="pill ${la.status}">${la.status}</span>
        ${la.swapped
          ? '<span style="color:var(--good);font-size:13px">✓ weights swapped</span>'
          : '<span style="color:var(--muted);font-size:13px">no swap</span>'}
      </div>

      <div class="two-col">
        <div>
          <div class="hint"><strong>Data</strong></div>
          <div class="hint">uploads: ${la.upload_count ?? '—'}</div>
          <div class="hint">labels total: ${la.label_count ?? '—'}</div>
          <div class="hint">new uploads since last calibration: ${la.new_since_last ?? '—'} / ${la.trigger_threshold ?? '—'} threshold</div>
          <div class="hint">recorded: ${la.recorded_at ? la.recorded_at.slice(0,19).replace('T',' ') + ' UTC' : '—'}</div>
        </div>
        <div>
          <div class="hint"><strong>Implicit labels added this cycle</strong></div>
          <div class="hint">new: +${la.implicit_labels_added?.new_labels ?? 0}</div>
          <div class="hint">skipped (already labeled): ${la.implicit_labels_added?.skipped_existing ?? 0}</div>
          <div class="hint">skipped (too recent): ${la.implicit_labels_added?.skipped_too_recent ?? 0}</div>
          ${signalHtml}
        </div>
      </div>

      ${reasonsHtml}

      ${la.candidate ? `<div class="hint" style="margin-top:10px"><strong>Gate candidate:</strong> kw=${fmt(la.candidate.w_kw,2)} skill=${fmt(la.candidate.w_skill,2)} ngram=${fmt(la.candidate.w_ngram,2)} edu=${fmt(la.candidate.w_edu,2)} sen=${fmt(la.candidate.w_sen,2)} cos=${fmt(la.candidate.w_cos,2)} &nbsp;·&nbsp; spearman=${fmt(la.candidate.spearman,4)} &nbsp;·&nbsp; p_low=${fmt(la.candidate.p_low,4)} p_high=${fmt(la.candidate.p_high,4)}</div>` : ''}
      ${la.spearman_floor != null ? `<div class="hint">Spearman floor (dynamic): ${fmt(la.spearman_floor,3)} &nbsp;·&nbsp; old spearman: ${fmt(la.old_spearman,3)}</div>` : ''}

      ${la.new_weights ? `<div class="hint" style="margin-top:10px"><strong>New global weights applied:</strong> kw=${fmt(la.new_weights.w_kw,2)} skill=${fmt(la.new_weights.w_skill,2)} ngram=${fmt(la.new_weights.w_ngram,2)} edu=${fmt(la.new_weights.w_edu,2)} sen=${fmt(la.new_weights.w_sen,2)} cos=${fmt(la.new_weights.w_cos,2)}<br>remap: ${fmt(la.new_weights.p_low,4)} → ${fmt(la.new_weights.p_high,4)} &nbsp;·&nbsp; N=${la.n_rows ?? '—'} spearman=${fmt(la.spearman,4)}</div>` : ''}

      ${swUpdated}
    </div>`;
  }

  renderSectionCalResults(d.section_calibration_results);

  document.getElementById('watcher-state').textContent = d.watcher_state
    ? JSON.stringify(d.watcher_state, null, 2)
    : '— (no cycles yet)';

  // History table
  const body = document.getElementById('history-body');
  if (!d.history?.length) {
    body.innerHTML = '<tr><td colspan="13" style="color:var(--muted);text-align:center">No history yet.</td></tr>';
  } else {
    body.innerHTML = d.history.map(h => {
      const hasSW = h.section_weights && Object.keys(h.section_weights).length > 0;
      return `<tr>
        <td style="white-space:nowrap">${(h.calibrated_at||'').slice(0,19).replace('T',' ')}</td>
        <td>${fmt(h.w_kw,2)}</td><td>${fmt(h.w_skill,2)}</td><td>${fmt(h.w_ngram,2)}</td>
        <td>${fmt(h.w_edu,2)}</td><td>${fmt(h.w_sen,2)}</td><td>${fmt(h.w_cos,2)}</td>
        <td>${fmt(h.p_low,4)}</td><td>${fmt(h.p_high,4)}</td>
        <td>${h.n_rows ?? 0}</td>
        <td style="color:${(h.spearman||0)>=0.4?'var(--good)':(h.spearman||0)>=0.2?'var(--warn)':'var(--bad)'}">${fmt(h.spearman,3)}</td>
        <td>${fmt(h.kendall_tau,3)}</td>
        <td>${h.source||'—'}${hasSW ? ' <span class="pill calibrated" style="font-size:9px;padding:1px 5px">+sec</span>' : ''}</td>
      </tr>`;
    }).join('');
  }
}

function renderLabelSources(sources) {
  const el = document.getElementById('label-sources');
  if (!sources || !Object.keys(sources).length) {
    el.innerHTML = '<pre>No labels yet.</pre>';
    return;
  }
  const order = ['human', 'llm', 'implicit', 'unknown'];
  const colors = { human: 'var(--good)', llm: 'var(--cal)', implicit: 'var(--accent)', unknown: 'var(--muted)' };
  const total = Object.values(sources).reduce((a, b) => a + b, 0);
  const rows = [...order, ...Object.keys(sources).filter(k => !order.includes(k))].filter(k => sources[k] > 0);
  el.innerHTML = `<table><thead><tr><th>Source</th><th>Count</th><th>%</th></tr></thead><tbody>
    ${rows.map(k => `<tr>
      <td style="color:${colors[k]||'var(--fg)'}; font-weight:600">${k}</td>
      <td>${sources[k]}</td>
      <td>${total > 0 ? (sources[k]/total*100).toFixed(1)+'%' : '—'}</td>
    </tr>`).join('')}
    <tr><td style="color:var(--muted)">total</td><td><strong>${total}</strong></td><td>100%</td></tr>
  </tbody></table>`;
}

async function runLlmLabel() {
  const btn = document.getElementById('llm-btn');
  btn.disabled = true;
  btn.textContent = 'Labeling…';
  try {
    const r = await fetch('/api/admin/calibration/label-llm?limit=20', { method: 'POST' });
    const result = await r.json();
    console.log('llm label result', result);
    alert(`LLM labeling done: good=${result.good} ok=${result.ok} bad=${result.bad} failed=${result.failed}`);
    await fetchStatus();
  } catch (e) {
    alert('LLM label failed: ' + e);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Label via LLM (limit 20)';
  }
}

async function runCycle() {
  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.textContent = 'Running…';
  try {
    const r = await fetch('/api/admin/calibration/run', { method: 'POST' });
    const result = await r.json();
    console.log('cycle result', result);
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
