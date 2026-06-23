from __future__ import annotations
import json
from .models import Schedule, Resident, Shift
from .optimizer import CycleResult


def _fmt_time(dt) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.strftime('%M')} {'AM' if dt.hour < 12 else 'PM'}"


def _shift_dict(s: Shift) -> dict:
    return {
        "uid": s.uid,
        "summary": s.summary,
        "startFmt": _fmt_time(s.t_start),
        "endFmt": _fmt_time(s.t_end),
        "loc": s.loc,
        "type": s.type,
        "workDate": s.work_date.isoformat(),
        "isJeopardy": s.is_jeopardy,
    }


def _resident_dict(r: Resident) -> dict:
    return {
        "name": r.name,
        "locPref": r.loc_pref,
        "locWeight": round(r.loc_weight * 100),
        "typePref": r.type_pref,
        "typeWeight": round(r.type_weight * 100),
        "daysPref": r.days_pref,
        "daysWeight": round(r.days_weight * 100),
        "daysOff": [d.isoformat() for d in sorted(r.days_off)],
    }


def build_payload(sched: Schedule, log: list[CycleResult],
                  original_assignment: dict) -> dict:
    swaps: dict = {n: [] for n in sched.residents}
    for res in log:
        for giver, u, v in res.moves:
            su, sv = sched.shifts[u], sched.shifts[v]
            swaps[giver].append({
                "giveUid": u,
                "giveSummary": su.summary,
                "giveDate": su.work_date.isoformat(),
                "giveLoc": su.loc,
                "giveType": su.type,
                "giveStart": _fmt_time(su.t_start),
                "giveEnd": _fmt_time(su.t_end),
                "recvUid": v,
                "recvSummary": sv.summary,
                "recvDate": sv.work_date.isoformat(),
                "recvLoc": sv.loc,
                "recvType": sv.type,
                "recvStart": _fmt_time(sv.t_start),
                "recvEnd": _fmt_time(sv.t_end),
                "delta": round(res.deltas.get(giver, 0), 4),
            })

    return {
        "residents": {n: _resident_dict(r) for n, r in sched.residents.items()},
        "shifts": {uid: _shift_dict(s) for uid, s in sched.shifts.items()},
        "originalAssignment": {n: list(uids) for n, uids in original_assignment.items()},
        "finalAssignment": {n: list(uids) for n, uids in sched.assignment.items()},
        "swaps": swaps,
    }


def render_html(sched: Schedule, log: list[CycleResult],
                original_assignment: dict) -> str:
    payload = build_payload(sched, log, original_assignment)
    data_js = "const DATA = " + json.dumps(payload, indent=2) + ";"
    return _TEMPLATE.replace("/*__INJECT_DATA__*/", data_js)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ShiftMaxxer &mdash; Swap Report</title>
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#F1F5F9;--surface:#FFFFFF;--border:#E2E8F0;
  --text:#0F172A;--muted:#64748B;
  --mgh:#2563EB;--mgh-l:#DBEAFE;
  --bwh:#059669;--bwh-l:#D1FAE5;
  --give:#DC2626;--give-l:#FEE2E2;
  --recv:#16A34A;--recv-l:#DCFCE7;
  --jeop:#6B7280;--jeop-l:#F3F4F6;
  --accent:#6366F1;--accent-l:#EEF2FF;
  --r:12px;--sh:0 1px 3px rgba(0,0,0,.08),0 1px 2px rgba(0,0,0,.05);
  --sh-lg:0 10px 25px -5px rgba(0,0,0,.1),0 4px 10px -3px rgba(0,0,0,.05);
}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,sans-serif;background:var(--bg);color:var(--text);line-height:1.5;font-size:14px}

/* ── Header ── */
.hdr{background:var(--surface);border-bottom:1px solid var(--border);padding:.875rem 2rem;display:flex;align-items:center;gap:1rem;position:sticky;top:0;z-index:50;box-shadow:var(--sh)}
.logo{font-size:1.125rem;font-weight:800;background:linear-gradient(135deg,var(--accent),#8B5CF6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;letter-spacing:-.5px}
.logo-sub{color:var(--muted);font-size:.8rem;font-weight:400;-webkit-text-fill-color:var(--muted)}
.sel-wrap{margin-left:auto;display:flex;align-items:center;gap:.6rem}
.sel-wrap label{font-size:.8rem;color:var(--muted);font-weight:500}
select{padding:.45rem .75rem;border:1px solid var(--border);border-radius:8px;font-size:.85rem;background:var(--bg);color:var(--text);cursor:pointer;outline:none;font-family:inherit}
select:focus{border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-l)}

/* ── Layout ── */
.main{max-width:1400px;margin:0 auto;padding:1.5rem 2rem 3rem}
.top-grid{display:grid;grid-template-columns:1fr 300px;gap:1.25rem;align-items:start}
@media(max-width:900px){.top-grid{grid-template-columns:1fr}}
.sec-label{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:.6rem}
hr.div{border:none;border-top:1px solid var(--border);margin:1.5rem 0}

/* ── Calendar ── */
.months-wrap{display:flex;flex-wrap:wrap;gap:1rem}
.month-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:1rem;box-shadow:var(--sh);min-width:260px;flex:1}
.month-title{font-weight:700;text-align:center;margin-bottom:.75rem;font-size:.875rem}
.cal-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px}
.cal-hdr{font-size:.62rem;font-weight:700;text-align:center;color:var(--muted);padding:3px 0}
.cal-day{min-height:58px;padding:2px;border-radius:6px;vertical-align:top}
.cal-day.blank{opacity:0}
.day-num{font-size:.67rem;color:var(--muted);padding:2px 3px;line-height:1}
.pill{font-size:.58rem;border-radius:3px;padding:2px 4px;margin-bottom:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-weight:600;cursor:default;display:block;line-height:1.4}
.p-mgh{background:var(--mgh-l);color:var(--mgh)}
.p-bwh{background:var(--bwh-l);color:var(--bwh)}
.p-jeop{background:var(--jeop-l);color:var(--jeop)}
.p-give{background:var(--give-l);color:var(--give);text-decoration:line-through;opacity:.75}
.p-recv{background:var(--recv-l);color:var(--recv);font-weight:700}
.legend{display:flex;gap:.75rem;flex-wrap:wrap;margin-top:.875rem}
.leg{display:flex;align-items:center;gap:.3rem;font-size:.68rem;color:var(--muted)}
.leg-dot{width:9px;height:9px;border-radius:2px;flex-shrink:0}

/* ── Preferences ── */
.prefs-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);padding:1.25rem;box-shadow:var(--sh)}
.pref-row{margin-bottom:1rem}
.pref-row:last-child{margin-bottom:0}
.pref-lbl{font-size:.67rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:700;margin-bottom:.2rem}
.pref-val{font-size:.875rem;font-weight:600}
.pref-val.any{color:var(--muted);font-style:italic;font-weight:400}
.wbar-wrap{display:flex;align-items:center;gap:.5rem;margin-top:.3rem}
.wbar{flex:1;height:4px;background:var(--border);border-radius:2px;overflow:hidden}
.wfill{height:100%;background:var(--accent);border-radius:2px;transition:width .4s}
.wlbl{font-size:.65rem;color:var(--muted);min-width:28px;text-align:right}
.doff-list{font-size:.75rem;color:var(--give);margin-top:.2rem}
.doff-none{font-size:.75rem;color:var(--muted);font-style:italic}
.pref-icon{margin-right:.3rem}

/* ── Swap Cards ── */
.swaps-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:1rem}
.no-swaps{background:var(--surface);border:1px dashed var(--border);border-radius:var(--r);padding:2rem;text-align:center;color:var(--muted);font-size:.875rem}
.swap-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--sh);overflow:hidden;transition:box-shadow .15s}
.swap-card:hover{box-shadow:var(--sh-lg)}
.card-hdr{padding:.6rem 1rem;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--border)}
.card-hdr.pos{background:#F0FDF4;border-color:#BBF7D0}
.card-hdr.neu{background:var(--bg)}
.card-hdr-title{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.07em;color:var(--muted)}
.card-hdr.pos .card-hdr-title{color:var(--recv)}
.delta-pill{background:rgba(255,255,255,.9);border:1px solid currentColor;border-radius:999px;padding:1px 8px;font-size:.67rem;font-weight:700}
.card-hdr.pos .delta-pill{color:var(--recv)}
.card-hdr.neu .delta-pill{color:var(--muted)}
.card-body{display:grid;grid-template-columns:1fr 28px 1fr;align-items:center;gap:.4rem;padding:.875rem}
.shift-blk{padding:.65rem .75rem;border-radius:8px}
.shift-blk.give{background:var(--give-l);border:1px solid #FECACA}
.shift-blk.recv{background:var(--recv-l);border:1px solid #BBF7D0}
.blk-lbl{font-size:.6rem;font-weight:800;text-transform:uppercase;letter-spacing:.08em;margin-bottom:.3rem}
.shift-blk.give .blk-lbl{color:var(--give)}
.shift-blk.recv .blk-lbl{color:var(--recv)}
.blk-summary{font-size:.78rem;font-weight:700;line-height:1.35;margin-bottom:.3rem}
.blk-meta{font-size:.65rem;color:var(--muted);line-height:1.7}
.loc-tag{display:inline-block;border-radius:3px;padding:1px 6px;font-size:.62rem;font-weight:700;margin-top:.3rem}
.lt-mgh{background:var(--mgh-l);color:var(--mgh)}
.lt-bwh{background:var(--bwh-l);color:var(--bwh)}
.lt-none{background:var(--jeop-l);color:var(--jeop)}
.arrow{text-align:center;font-size:1.1rem;color:var(--muted)}
</style>
</head>
<body>
<header class="hdr">
  <div>
    <span class="logo">ShiftMaxxer</span>
    <span class="logo-sub">&nbsp;Swap Report</span>
  </div>
  <div class="sel-wrap">
    <label for="rsel">Viewing</label>
    <select id="rsel"></select>
  </div>
</header>

<main class="main">
  <div class="top-grid">
    <section>
      <div class="sec-label">Schedule</div>
      <div id="months-wrap" class="months-wrap"></div>
      <div class="legend" id="legend">
        <div class="leg"><div class="leg-dot" style="background:var(--mgh-l);border:1px solid var(--mgh)"></div>MGH (kept)</div>
        <div class="leg"><div class="leg-dot" style="background:var(--bwh-l);border:1px solid var(--bwh)"></div>BWH (kept)</div>
        <div class="leg"><div class="leg-dot" style="background:var(--give-l);border:1px solid var(--give)"></div>Given away</div>
        <div class="leg"><div class="leg-dot" style="background:var(--recv-l);border:1px solid var(--recv)"></div>Received</div>
        <div class="leg"><div class="leg-dot" style="background:var(--jeop-l);border:1px solid var(--jeop)"></div>Jeopardy</div>
      </div>
    </section>
    <aside>
      <div class="sec-label">Preferences</div>
      <div class="prefs-card" id="prefs"></div>
    </aside>
  </div>

  <hr class="div">

  <section>
    <div class="sec-label">Proposed Swaps</div>
    <div id="swaps-grid" class="swaps-grid"></div>
  </section>
</main>

<script>
/*__INJECT_DATA__*/

const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
const DNAMES = ['Su','Mo','Tu','We','Th','Fr','Sa'];

let cur = null;

function init() {
  const names = Object.keys(DATA.residents).sort();
  const sel = document.getElementById('rsel');
  names.forEach(n => {
    const o = document.createElement('option');
    o.value = n;
    o.textContent = n.charAt(0).toUpperCase() + n.slice(1);
    sel.appendChild(o);
  });
  cur = names[0];
  sel.value = cur;
  render();
  sel.addEventListener('change', e => { cur = e.target.value; render(); });
}

function render() {
  renderPrefs();
  renderCalendar();
  renderSwaps();
}

/* ── Preferences ── */
function renderPrefs() {
  const r = DATA.residents[cur];
  const fmtDate = iso => {
    const [y, m, d] = iso.split('-').map(Number);
    return MONTHS[m-1].slice(0,3) + ' ' + d + ', ' + y;
  };
  const row = (icon, label, val, isAny, weight) => {
    const bar = weight != null
      ? '<div class="wbar-wrap"><div class="wbar"><div class="wfill" style="width:' + weight + '%"></div></div><div class="wlbl">' + weight + '%</div></div>'
      : '';
    return '<div class="pref-row">'
      + '<div class="pref-lbl">' + icon + ' ' + label + '</div>'
      + '<div class="pref-val' + (isAny ? ' any' : '') + '">' + (isAny ? 'No preference' : val) + '</div>'
      + bar + '</div>';
  };
  const doff = r.daysOff.length
    ? '<div class="doff-list">' + r.daysOff.map(fmtDate).join(', ') + '</div>'
    : '<div class="doff-none">None declared</div>';
  document.getElementById('prefs').innerHTML =
    row('&#128205;', 'Location', r.locPref, r.locPref === 'ANY', r.locWeight)
    + row('&#128336;', 'Time of Day', r.typePref, r.typePref === 'ANY', r.typeWeight)
    + row('&#128197;', 'Preferred Streak', r.daysPref + ' consecutive days', false, r.daysWeight)
    + '<div class="pref-row"><div class="pref-lbl">&#128683; Days Off</div>' + doff + '</div>';
}

/* ── Calendar ── */
function renderCalendar() {
  const orig = new Set(DATA.originalAssignment[cur] || []);
  const final = new Set(DATA.finalAssignment[cur] || []);
  const gives = new Set((DATA.swaps[cur] || []).map(s => s.giveUid));
  const recvs = new Set((DATA.swaps[cur] || []).map(s => s.recvUid));
  const all = new Set([...orig, ...final]);

  // Build date -> [{shift, status}] map
  const dm = {};
  all.forEach(uid => {
    const s = DATA.shifts[uid];
    if (!s) return;
    const k = s.workDate;
    if (!dm[k]) dm[k] = [];
    let st = 'keep';
    if (gives.has(uid)) st = 'give';
    else if (recvs.has(uid)) st = 'recv';
    dm[k].push({ s, st });
  });

  if (!Object.keys(dm).length) {
    document.getElementById('months-wrap').innerHTML = '<p style="color:var(--muted);font-size:.875rem">No shifts found.</p>';
    return;
  }

  const dates = Object.keys(dm).sort();
  const [minY, minM] = dates[0].split('-').map(Number);
  const [maxY, maxM] = dates[dates.length - 1].split('-').map(Number);

  const html = [];
  let y = minY, m = minM;
  while (y < maxY || (y === maxY && m <= maxM)) {
    html.push(buildMonth(y, m, dm));
    m++;
    if (m > 12) { m = 1; y++; }
  }
  document.getElementById('months-wrap').innerHTML = html.join('');
}

function buildMonth(y, m, dm) {
  const firstDow = new Date(y, m - 1, 1).getDay();
  const days = new Date(y, m, 0).getDate();
  const today = new Date().toISOString().slice(0, 10);

  let cells = DNAMES.map(d => '<div class="cal-hdr">' + d + '</div>').join('');
  for (let i = 0; i < firstDow; i++) cells += '<div class="cal-day blank"></div>';

  for (let d = 1; d <= days; d++) {
    const iso = y + '-' + String(m).padStart(2,'0') + '-' + String(d).padStart(2,'0');
    const entries = dm[iso] || [];
    const pills = entries.map(({ s, st }) => {
      let cls = s.isJeopardy ? 'p-jeop' : st === 'give' ? 'p-give' : st === 'recv' ? 'p-recv' : s.loc === 'MGH' ? 'p-mgh' : 'p-bwh';
      const label = s.isJeopardy ? 'Jeopardy' : (s.loc || '') + (s.type ? ' ' + s.type[0] : '');
      return '<span class="pill ' + cls + '" title="' + s.summary + ' (' + s.startFmt + '-' + s.endFmt + ')">' + label + '</span>';
    }).join('');
    const todayCls = iso === today ? ' style="background:var(--accent-l)"' : '';
    cells += '<div class="cal-day"' + todayCls + '>'
      + '<div class="day-num"' + (iso === today ? ' style="color:var(--accent);font-weight:700"' : '') + '>' + d + '</div>'
      + pills + '</div>';
  }

  return '<div class="month-card"><div class="month-title">' + MONTHS[m-1] + ' ' + y + '</div>'
    + '<div class="cal-grid">' + cells + '</div></div>';
}

/* ── Swap Cards ── */
function renderSwaps() {
  const list = DATA.swaps[cur] || [];
  const grid = document.getElementById('swaps-grid');
  if (!list.length) {
    grid.innerHTML = '<div class="no-swaps">No proposed swaps for this resident.</div>';
    return;
  }

  const fmtDate = iso => {
    const [y, m, d] = iso.split('-').map(Number);
    return MONTHS[m-1].slice(0,3) + ' ' + d;
  };

  grid.innerHTML = list.map((sw, i) => {
    const pct = (sw.delta * 100).toFixed(1);
    const isPos = sw.delta >= 0;
    const deltaLabel = sw.delta > 0.0001 ? '+' + pct + '% happiness'
                     : sw.delta < -0.0001 ? pct + '% happiness'
                     : 'Neutral';
    return '<div class="swap-card">'
      + '<div class="card-hdr ' + (isPos ? 'pos' : 'neu') + '">'
      + '<span class="card-hdr-title">Swap ' + (i+1) + '</span>'
      + '<span class="delta-pill">' + deltaLabel + '</span></div>'
      + '<div class="card-body">'
      + blk(sw, 'give', fmtDate)
      + '<div class="arrow">&#8594;</div>'
      + blk(sw, 'recv', fmtDate)
      + '</div></div>';
  }).join('');
}

function blk(sw, side, fmtDate) {
  const p = side === 'give' ? 'give' : 'recv';
  const label = side === 'give' ? 'Giving Away' : 'Receiving';
  const loc = sw[p + 'Loc'];
  const type = sw[p + 'Type'];
  const lcls = loc === 'MGH' ? 'lt-mgh' : loc === 'BWH' ? 'lt-bwh' : 'lt-none';
  const lbl = loc || 'Jeopardy';
  return '<div class="shift-blk ' + side + '">'
    + '<div class="blk-lbl">' + label + '</div>'
    + '<div class="blk-summary">' + sw[p + 'Summary'] + '</div>'
    + '<div class="blk-meta">'
    + fmtDate(sw[p + 'Date']) + '<br>'
    + sw[p + 'Start'] + ' &ndash; ' + sw[p + 'End']
    + '</div>'
    + '<span class="loc-tag ' + lcls + '">' + lbl + (type ? ' &middot; ' + type : '') + '</span>'
    + '</div>';
}

init();
</script>
</body>
</html>
"""
