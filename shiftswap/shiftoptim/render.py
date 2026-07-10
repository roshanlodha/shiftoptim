from __future__ import annotations
import json
from datetime import date, timedelta
from .models import Schedule, Resident, Shift
from .optimizer import CycleResult
from .utility import phi_loc, phi_type, utility
from .feasibility import _streaks


def _fmt_time(dt) -> str:
    h = dt.hour % 12 or 12
    return f"{h}:{dt.strftime('%M')} {'AM' if dt.hour < 12 else 'PM'}"


def _shift_dict(s: Shift) -> dict:
    start_hour = s.t_start.hour + s.t_start.minute / 60.0
    end_hour = s.t_end.hour + s.t_end.minute / 60.0
    
    # If the shift ends at midnight on the next calendar day, represent it as 24.0
    # to avoid splitting it across days.
    if s.t_end.hour == 0 and s.t_end.minute == 0 and (s.t_end.date() - s.t_start.date()).days == 1:
        end_hour = 24.0
        
    return {
        "uid": s.uid,
        "summary": s.summary,
        "startFmt": _fmt_time(s.t_start),
        "endFmt": _fmt_time(s.t_end),
        "loc": s.loc,
        "type": s.type,
        "workDate": s.work_date.isoformat(),
        "isJeopardy": s.is_jeopardy,
        "startHour": start_hour,
        "endHour": end_hour,
    }


def get_schedule_bounds(shifts: list[Shift]) -> tuple[date, date]:
    if not shifts:
        today = date.today()
        # Fallback to current week
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end
    
    dates = [s.work_date for s in shifts]
    min_date = min(dates)
    max_date = max(dates)
    
    start = min_date - timedelta(days=min_date.weekday())
    end = max_date + timedelta(days=6 - max_date.weekday())
    return start, end


def _off_streaks(timeline: list[date], worked_dates: set[date]) -> list[int]:
    runs = []
    current_run = 0
    for d in timeline:
        if d not in worked_dates:
            current_run += 1
        else:
            if current_run > 0:
                runs.append(current_run)
                current_run = 0
    if current_run > 0:
        runs.append(current_run)
    return runs


def _total_hours(shifts: list[Shift]) -> float:
    return sum((s.t_end - s.t_start).total_seconds() / 3600 for s in shifts)


def _resident_metrics(r: Resident, orig_shifts: list[Shift], final_shifts: list[Shift], timeline: list[date]) -> dict:
    orig_runs = _off_streaks(timeline, {s.work_date for s in orig_shifts})
    orig_avg_off = sum(orig_runs)/len(orig_runs) if orig_runs else 0.0
    final_runs = _off_streaks(timeline, {s.work_date for s in final_shifts})
    final_avg_off = sum(final_runs)/len(final_runs) if final_runs else 0.0

    return {
        "name": r.name,
        "locPref": r.loc_pref,
        "typePref": r.type_pref,
        "daysPref": r.days_pref,
        "daysWeight": r.days_weight,
        "daysOff": [d.isoformat() for d in sorted(r.days_off)],
        "locWeight": r.loc_weight,
        "typeWeight": r.type_weight,
        "origHours": r.orig_hours,
        "loc": {
            "orig": round(phi_loc(orig_shifts, r) * 100),
            "opt": round(phi_loc(final_shifts, r) * 100),
        },
        "type": {
            "orig": round(phi_type(orig_shifts, r) * 100),
            "opt": round(phi_type(final_shifts, r) * 100),
        },
        "streak": {
            "orig": round(orig_avg_off, 1),
            "opt": round(final_avg_off, 1),
        },
        "hours": {
            "orig": round(_total_hours(orig_shifts), 1),
            "opt": round(_total_hours(final_shifts), 1),
        },
        "happiness": {
            "orig": round(utility(orig_shifts, r) * 100),
            "opt": round(utility(final_shifts, r) * 100),
        }
    }


def build_payload(sched: Schedule, log: list[CycleResult],
                  original_assignment: dict) -> dict:
    orig_shifts_by_name = {n: [sched.shifts[uid] for uid in uids] for n, uids in original_assignment.items()}
    final_shifts_by_name = {n: [sched.shifts[uid] for uid in uids] for n, uids in sched.assignment.items()}

    # Compute timeline for days-off streaks
    all_shifts = list(sched.shifts.values())
    start_date, end_date = get_schedule_bounds(all_shifts)
    timeline = []
    curr = start_date
    while curr <= end_date:
        timeline.append(curr)
        curr += timedelta(days=1)

    swaps: dict = {n: [] for n in sched.residents}
    for cycle_idx, res in enumerate(log):
        # Build recv_uid -> giver map for partner lookup
        recv_to_giver = {v: giver for giver, u, v in res.moves}
        for giver, u, v in res.moves:
            su, sv = sched.shifts[u], sched.shifts[v]
            # The partner is whoever gives away the shift we receive
            partner = recv_to_giver.get(u, "")
            swaps[giver].append({
                "cycleId": cycle_idx,
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
                "swapWith": partner,
                "partnerDelta": round(res.deltas.get(partner, 0), 4) if partner else 0.0,
            })

    for n in swaps:
        swaps[n].sort(key=lambda sw: max(sw["delta"], sw["partnerDelta"]), reverse=True)

    return {
        "residents": {
            n: _resident_metrics(r, orig_shifts_by_name.get(n, []), final_shifts_by_name.get(n, []), timeline)
            for n, r in sched.residents.items()
        },
        "shifts": {uid: _shift_dict(s) for uid, s in sched.shifts.items()},
        "originalAssignment": {n: list(uids) for n, uids in original_assignment.items()},
        "finalAssignment": {n: list(uids) for n, uids in sched.assignment.items()},
        "swaps": swaps,
    }



def render_html(sched: Schedule, log: list[CycleResult],
                original_assignment: dict) -> str:
    payload = build_payload(sched, log, original_assignment)
    from .config import STREAK_BETA, TIME_DIFF_WEIGHT
    payload["config"] = {
        "STREAK_BETA": STREAK_BETA,
        "TIME_DIFF_WEIGHT": TIME_DIFF_WEIGHT,
    }
    data_js = "const DATA = " + json.dumps(payload, indent=2) + ";"
    return _TEMPLATE.replace("/*__INJECT_DATA__*/", data_js)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shift Swap Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=Outfit:wght@400;600;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lucide@latest"></script>
<style>
:root {
  /* DARK THEME (Default) */
  --bg: hsl(224, 25%, 6%);
  --panel: hsl(224, 25%, 9%);
  --panel-high: hsl(224, 25%, 12%);
  --border: hsl(224, 20%, 15%);
  --border-high: hsl(224, 20%, 22%);
  --text: hsl(210, 40%, 98%);
  --text-muted: hsl(215, 20%, 65%);
  
  /* Primary Accent: Indigo/Violet */
  --primary: hsl(250, 95%, 76%);
  --primary-bg: hsl(250, 40%, 16%);
  --on-primary: hsl(250, 100%, 95%);
  
  /* Success: Emerald */
  --success: hsl(150, 80%, 45%);
  --success-bg: hsl(150, 40%, 12%);
  --on-success: hsl(150, 90%, 95%);
  
  /* Warning/Jeopardy: Amber */
  --warning: hsl(35, 90%, 55%);
  --warning-bg: hsl(35, 40%, 12%);
  --on-warning: hsl(35, 90%, 95%);

  /* Danger: Rose */
  --danger: hsl(350, 90%, 68%);
  --danger-bg: hsl(350, 40%, 14%);
  --on-danger: hsl(350, 95%, 95%);

  /* Secondary: Slate */
  --secondary: hsl(215, 25%, 68%);
  --secondary-bg: hsl(215, 20%, 15%);
  --on-secondary: hsl(215, 20%, 95%);
  
  /* Location styles */
  --mgh-bg: hsl(250, 30%, 15%);
  --mgh-border: hsl(250, 70%, 65%);
  --mgh-text: hsl(250, 80%, 90%);
  --bwh-bg: hsl(210, 25%, 14%);
  --bwh-border: hsl(210, 50%, 60%);
  --bwh-text: hsl(210, 70%, 90%);
  
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.4);
  --shadow-md: 0 4px 12px rgba(0, 0, 0, 0.5), 0 2px 4px rgba(0, 0, 0, 0.4);
  --shadow-lg: 0 12px 24px rgba(0, 0, 0, 0.6), 0 4px 8px rgba(0, 0, 0, 0.5);

  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 16px;
  
  --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
  --font-display: 'Outfit', var(--font-sans);

  /* Backward Compatibility Mapping */
  --md-sys-color-primary: var(--primary);
  --md-sys-color-on-primary: var(--on-primary);
  --md-sys-color-primary-container: var(--primary-bg);
  --md-sys-color-on-primary-container: var(--primary);
  
  --md-sys-color-secondary: var(--secondary);
  --md-sys-color-on-secondary: var(--on-secondary);
  --md-sys-color-secondary-container: var(--secondary-bg);
  --md-sys-color-on-secondary-container: var(--secondary);
  
  --md-sys-color-tertiary: var(--success);
  --md-sys-color-on-tertiary: var(--on-success);
  --md-sys-color-tertiary-container: var(--success-bg);
  --md-sys-color-on-tertiary-container: var(--success);
  
  --md-sys-color-error: var(--danger);
  --md-sys-color-on-error: var(--on-danger);
  --md-sys-color-error-container: var(--danger-bg);
  --md-sys-color-on-error-container: var(--danger);
  
  --md-sys-color-surface: var(--bg);
  --md-sys-color-on-surface: var(--text);
  --md-sys-color-on-surface-variant: var(--text-muted);
  
  --md-sys-color-surface-container-lowest: var(--bg);
  --md-sys-color-surface-container-low: var(--panel);
  --md-sys-color-surface-container: var(--panel-high);
  --md-sys-color-surface-container-high: var(--panel-high);
  --md-sys-color-surface-container-highest: var(--panel-high);
  
  --md-sys-color-outline: var(--border-high);
  --md-sys-color-outline-variant: var(--border);
}

@media (prefers-color-scheme: light) {
  :root {
    --bg: hsl(220, 20%, 97%);
    --panel: hsl(0, 0%, 100%);
    --panel-high: hsl(220, 20%, 94%);
    --border: hsl(220, 15%, 89%);
    --border-high: hsl(220, 15%, 82%);
    --text: hsl(224, 25%, 12%);
    --text-muted: hsl(220, 15%, 45%);
    
    --primary: hsl(250, 85%, 55%);
    --primary-bg: hsl(250, 90%, 96%);
    --on-primary: hsl(250, 90%, 20%);
    
    --success: hsl(150, 80%, 32%);
    --success-bg: hsl(150, 80%, 95%);
    --on-success: hsl(150, 80%, 15%);
    
    --warning: hsl(35, 90%, 40%);
    --warning-bg: hsl(35, 90%, 95%);
    --on-warning: hsl(35, 90%, 15%);
    
    --danger: hsl(350, 80%, 48%);
    --danger-bg: hsl(350, 90%, 96%);
    --on-danger: hsl(350, 80%, 15%);

    --secondary: hsl(215, 20%, 40%);
    --secondary-bg: hsl(215, 20%, 94%);
    --on-secondary: hsl(215, 20%, 15%);

    --mgh-bg: hsl(250, 90%, 96%);
    --mgh-border: hsl(250, 60%, 75%);
    --mgh-text: hsl(250, 80%, 25%);
    --bwh-bg: hsl(210, 90%, 96%);
    --bwh-border: hsl(210, 50%, 70%);
    --bwh-text: hsl(210, 80%, 25%);
    
    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
    --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
    --shadow-lg: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
  }
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: var(--font-sans);
  background: var(--bg);
  color: var(--text);
  line-height: 1.5;
  font-size: 14px;
  min-height: 100vh;
  transition: background-color 0.2s, color 0.2s;
}

/* Header / App Bar */
.hdr {
  background: rgba(14, 20, 36, 0.3);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 16px 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  transition: background-color 0.2s, border-color 0.2s;
  height: 72px;
}
@media (prefers-color-scheme: light) {
  .hdr {
    background: rgba(255, 255, 255, 0.7);
  }
}

.logo {
  font-family: var(--font-display);
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--text);
  letter-spacing: -0.4px;
  background: linear-gradient(135deg, var(--text) 50%, var(--primary));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}

/* Happiness Card */
.happiness-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 16px;
  box-shadow: var(--shadow-sm);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  margin-bottom: 16px;
}
.happiness-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

@keyframes happiness-pulse {
  0% { box-shadow: 0 0 0 0 rgba(250, 95, 76, 0.2); }
  70% { box-shadow: 0 0 0 8px rgba(250, 95, 76, 0); }
  100% { box-shadow: 0 0 0 0 rgba(250, 95, 76, 0); }
}

.orb-pulse {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  background: var(--primary-bg);
  color: var(--primary);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background-color 0.2s, color 0.2s;
}

.orb-text {
  line-height: 1.2;
}
.orb-label {
  font-size: 0.75rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  font-weight: 600;
}
.orb-value {
  font-family: var(--font-display);
  font-size: 1.6rem;
  font-weight: 800;
  color: var(--text);
  margin-top: 2px;
}

/* Dropdown Selector */
.md3-select-wrapper {
  position: relative;
  display: inline-flex;
  flex-direction: column;
}
.md3-select-label {
  position: absolute;
  top: -7px;
  left: 10px;
  background: var(--bg);
  padding: 0 6px;
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--primary);
  pointer-events: none;
  transition: color 0.2s;
}
.md3-select {
  height: 40px;
  padding: 0 36px 0 12px;
  border: 1px solid var(--border-high);
  border-radius: var(--radius-sm);
  background: var(--panel);
  color: var(--text);
  font-size: 0.85rem;
  font-family: var(--font-sans);
  font-weight: 600;
  outline: none;
  cursor: pointer;
  appearance: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  min-width: 180px;
  box-shadow: var(--shadow-sm);
}
.md3-select:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-bg);
}
.md3-select-wrapper::after {
  content: ' ';
  position: absolute;
  right: 14px;
  top: 50%;
  transform: translateY(-50%);
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 4px solid var(--text-muted);
  pointer-events: none;
}

/* Icon Buttons */
.md3-btn-icon-outlined {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--border-high);
  background: var(--panel);
  color: var(--text);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: all 0.2s;
  box-shadow: var(--shadow-sm);
}
.md3-btn-icon-outlined:hover {
  background-color: var(--primary-bg);
  border-color: var(--primary);
  color: var(--primary);
}

/* Segmented Buttons */
.md3-segmented-button-container {
  display: inline-flex;
  background: var(--panel-high);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 3px;
  align-items: center;
}
.md3-segmented-button {
  border: none;
  background: transparent;
  color: var(--text-muted);
  padding: 6px 14px;
  font-size: 0.78rem;
  font-weight: 700;
  border-radius: calc(var(--radius-lg) - 3px);
  cursor: pointer;
  transition: all 0.2s;
  outline: none;
}
.md3-segmented-button:hover {
  color: var(--text);
}
.md3-segmented-button.selected {
  background-color: var(--primary-bg);
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}

/* Main Layout */
.main {
  max-width: 1440px;
  margin: 0 auto;
  padding: 32px 32px 64px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* Grid Layout */
.top-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 32px;
  align-items: start;
}
@media (max-width: 1024px) {
  .top-grid {
    grid-template-columns: 1fr;
    gap: 24px;
  }
}

/* Section Header */
.sec-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 20px;
}
.section-title {
  font-family: var(--font-display);
  font-size: 1.2rem;
  font-weight: 800;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 10px;
  letter-spacing: -0.3px;
}
.section-title::before {
  content: '';
  display: block;
  width: 4px;
  height: 18px;
  background: var(--primary);
  border-radius: 99px;
}

/* Week Navigation & Grid */
.week-nav {
  display: flex;
  align-items: center;
  gap: 12px;
}
.week-label {
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text);
  min-width: 180px;
  text-align: center;
  font-family: var(--font-display);
}
.week-view-container {
  overflow-x: auto;
  border-radius: var(--radius-lg);
  border: 1px solid var(--border);
  background: var(--panel);
  box-shadow: var(--shadow-sm);
}
.week-grid {
  display: grid;
  grid-template-columns: 50px repeat(7, minmax(130px, 1fr));
  column-gap: 8px;
  row-gap: 0;
  padding: 16px;
  min-width: 1000px;
}
.week-col-hdr {
  text-align: center;
  padding: 10px 8px;
  background: var(--panel-high);
  border-radius: var(--radius-md);
  margin-bottom: 12px;
}
.week-col-hdr.today {
  background: var(--primary-bg);
  border: 1px solid var(--primary);
}
.wch-dow {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
}
.week-col-hdr.today .wch-dow {
  color: var(--primary);
}
.wch-date {
  font-family: var(--font-display);
  font-size: 1.3rem;
  font-weight: 800;
  color: var(--text);
  line-height: 1.1;
  margin-top: 2px;
}
.week-col-hdr.today .wch-date {
  color: var(--text);
}

/* Time labels column styling */
.time-labels-col {
  position: relative;
  height: 360px;
  margin-top: 6px;
}
.week-grid.has-allday .time-labels-col {
  margin-top: 0px;
}
.time-label {
  position: absolute;
  right: 8px;
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--text-muted);
  transform: translateY(-50%);
}

/* Calendar Containers */
.allday-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background-color: rgba(0,0,0,0.05);
  border: 1px solid var(--border);
  border-bottom: none;
  border-top-left-radius: var(--radius-sm);
  border-top-right-radius: var(--radius-sm);
  padding: 6px;
}
@media (prefers-color-scheme: light) {
  .allday-container {
    background-color: rgba(0,0,0,0.02);
  }
}
.allday-container.today-allday {
  border-color: var(--primary);
  border-width: 2px 2px 0 2px;
}

.hourly-container {
  position: relative;
  height: 360px;
  background: linear-gradient(rgba(255,255,255,0.03) 1px, transparent 1px);
  background-size: 100% 15px;
  background-color: rgba(0,0,0,0.1);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 6px;
}
@media (prefers-color-scheme: light) {
  .hourly-container {
    background: linear-gradient(rgba(0,0,0,0.03) 1px, transparent 1px);
    background-size: 100% 15px;
    background-color: rgba(0,0,0,0.01);
  }
}
.hourly-container.today-hourly {
  border-color: var(--primary);
  border-width: 2px;
}
.hourly-container.split-bottom {
  border-top: none;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
}
.hourly-container.today-hourly.split-bottom {
  border-width: 0 2px 2px 2px;
}

/* Shift card */
.shift-card {
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  border: 1px solid var(--border);
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: default;
  background: var(--panel-high);
  color: var(--text);
  box-shadow: var(--shadow-sm);
}
.shift-card:hover {
  transform: translateY(-1px) scale(1.02);
  box-shadow: var(--shadow-md);
  border-color: var(--border-high);
}

/* Colors for shifts based on location or state */
.shift-card.sb-mgh {
  background: var(--mgh-bg);
  border-left: 3px solid var(--mgh-border);
  color: var(--text);
}
.shift-card.sb-mgh .sb-loc { color: var(--mgh-border); }

.shift-card.sb-bwh {
  background: var(--bwh-bg);
  border-left: 3px solid var(--bwh-border);
  color: var(--text);
}
.shift-card.sb-bwh .sb-loc { color: var(--bwh-border); }

.shift-card.sb-give {
  background: var(--danger-bg);
  border-left: 3px solid var(--danger);
  color: var(--text);
}
.shift-card.sb-give .sb-loc { color: var(--danger); }

.shift-card.sb-recv {
  background: var(--success-bg);
  border-left: 3px solid var(--success);
  color: var(--text);
}
.shift-card.sb-recv .sb-loc { color: var(--success); }

/* All day (Jeopardy) card styling */
.allday-card {
  border-radius: var(--radius-sm);
  padding: 6px;
  background: var(--panel-high);
  color: var(--text-muted);
  cursor: default;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: 1px solid var(--border);
}
.allday-card:hover {
  background: var(--border);
  color: var(--text);
}
.allday-card.sb-give {
  background: var(--danger-bg);
  color: var(--text);
  border-color: var(--danger);
}
.allday-card.sb-recv {
  background: var(--success-bg);
  color: var(--text);
  border-color: var(--success);
}
.allday-card .sb-title {
  text-align: center;
  font-size: 0.72rem;
  font-weight: 700;
  line-height: 1.2;
}

.shift-card.absolute-card {
  position: absolute;
  left: 2px;
  right: 2px;
  box-sizing: border-box;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding: 6px 8px;
}

/* Hourly part 1 tiny slice styling */
.shift-card.part-1 {
  height: 15px !important;
  padding: 0 4px !important;
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  line-height: 1 !important;
}
.shift-card.part-1 * {
  display: none;
}

.sb-title {
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1.2;
  word-break: break-all;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-loc {
  font-size: 0.65rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 4px;
}
.sb-time {
  font-size: 0.62rem;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 4px;
}
.sb-badge {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  font-size: 0.58rem;
  font-weight: 800;
  border-radius: 4px;
  padding: 1px 4px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  margin-top: 2px;
  width: fit-content;
}
.badge-give {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid var(--danger);
}
.badge-recv {
  background: var(--success-bg);
  color: var(--success);
  border: 1px solid var(--success);
}

/* Sidebar Preferences / Metrics */
.prefs-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  box-shadow: var(--shadow-sm);
}
.pref-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.pref-lbl-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.pref-lbl {
  font-size: 0.68rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  gap: 6px;
}
.pref-val {
  font-size: 0.82rem;
  font-weight: 700;
  color: var(--text);
}
.pref-val.any {
  color: var(--text-muted);
  font-style: italic;
  font-weight: 400;
}

/* Dual-color Progress Indicators */
.wbar-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}
.wbar {
  flex: 1;
  height: 6px;
  background: var(--panel-high);
  border-radius: 99px;
  overflow: hidden;
  display: flex;
}
.wfill-orig {
  height: 100%;
  background: var(--text-muted);
  opacity: 0.4;
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}
.wfill-gain {
  height: 100%;
  background: var(--success);
  transition: width 0.6s cubic-bezier(0.4, 0, 0.2, 1);
}
.wlbl {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--text-muted);
  min-width: 60px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* Days Off Chips */
.doff-container {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.doff-chip {
  background: var(--danger-bg);
  color: var(--danger);
  border: 1px solid rgba(239, 68, 68, 0.2);
  border-radius: 4px;
  padding: 3px 6px;
  font-size: 0.7rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.doff-none {
  font-size: 0.75rem;
  color: var(--text-muted);
  font-style: italic;
}
.divider {
  border: none;
  border-top: 1px solid var(--border);
  margin: 4px 0;
}

/* Proposed Swaps Section */
.swaps-section {
  margin-top: 16px;
}
.count-badge {
  background: var(--primary-bg);
  color: var(--primary);
  border: 1px solid var(--primary);
  border-radius: 99px;
  padding: 2px 8px;
  font-size: 0.75rem;
  font-weight: 800;
  margin-left: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.swaps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: 20px;
}
@media (max-width: 480px) {
  .swaps-grid {
    grid-template-columns: 1fr;
  }
}

/* Swap Card styling */
.swap-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  position: relative;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}
.swap-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--shadow-lg);
  border-color: var(--border-high);
}
.swap-card.pos-card { border-top: 4px solid var(--success); }
.swap-card.neg-card { border-top: 4px solid var(--danger); }
.swap-card.neu-card { border-top: 4px solid var(--secondary); }

/* Rejected/Excluded Swaps Styling */
.swap-card.rejected-card {
  opacity: 0.35;
  filter: grayscale(80%);
  border-top-color: var(--border) !important;
  transform: none !important;
  box-shadow: none !important;
}
.swap-card.rejected-card .delta-pill {
  background: var(--panel-high) !important;
  color: var(--text-muted) !important;
  border-color: var(--border) !important;
}
.reject-swap-btn {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 28px;
  height: 28px;
  background: var(--panel-high);
  border: 1px solid var(--border);
  color: var(--text-muted);
  cursor: pointer;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--shadow-sm);
  transition: all 0.2s;
  z-index: 10;
}
.reject-swap-btn:hover {
  background-color: var(--danger-bg);
  color: var(--danger);
  border-color: var(--danger);
  transform: scale(1.08);
}
.reject-swap-btn.restore:hover {
  background-color: var(--success-bg);
  color: var(--success);
  border-color: var(--success);
}

.swap-card-hdr {
  padding: 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border);
}
.swap-card-hdr.pos { background: linear-gradient(90deg, var(--success-bg), transparent); }
.swap-card-hdr.neg { background: linear-gradient(90deg, var(--danger-bg), transparent); }
.swap-card-hdr.neu { background: var(--panel-high); }

.swap-with-badge {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text);
  display: flex;
  align-items: center;
  gap: 6px;
}
.partner-chip {
  background: var(--primary-bg);
  color: var(--primary);
  border: 1px solid rgba(250, 95, 76, 0.2);
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 0.72rem;
  font-weight: 700;
}
.delta-pill {
  border-radius: 99px;
  padding: 3px 8px;
  font-size: 0.7rem;
  font-weight: 800;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
  border: 1px solid transparent;
}
.delta-pill.pos { background: var(--success-bg); color: var(--success); border-color: rgba(16, 185, 129, 0.2); }
.delta-pill.neg { background: var(--danger-bg); color: var(--danger); border-color: rgba(239, 68, 68, 0.2); }
.delta-pill.neu { background: var(--secondary-bg); color: var(--secondary); border-color: var(--border); }

.card-body {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  padding: 16px;
  background: var(--panel);
}
.shift-blk {
  padding: 12px;
  border-radius: var(--radius-md);
  background: var(--panel-high);
  border: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
  height: 100%;
}
.shift-blk.give { border-left: 3px solid var(--danger); }
.shift-blk.recv { border-left: 3px solid var(--success); }

.blk-lbl {
  font-size: 0.65rem;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  display: flex;
  align-items: center;
  gap: 4px;
}
.shift-blk.give .blk-lbl { color: var(--danger); }
.shift-blk.recv .blk-lbl { color: var(--success); }

.blk-summary {
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.35;
  color: var(--text);
}
.blk-meta {
  font-size: 0.7rem;
  color: var(--text-muted);
  line-height: 1.4;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.loc-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 0.65rem;
  font-weight: 700;
  margin-top: auto;
  width: fit-content;
}
.loc-tag.lt-mgh { background: var(--mgh-bg); color: var(--mgh-border); border: 1px solid rgba(250, 95, 76, 0.2); }
.loc-tag.lt-bwh { background: var(--bwh-bg); color: var(--bwh-border); border: 1px solid rgba(210, 50, 70, 0.2); }
.loc-tag.lt-none { background: var(--secondary-bg); color: var(--text-muted); }

.arrow-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.arrow-btn {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--panel-high);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--primary);
  box-shadow: var(--shadow-sm);
}

/* Empty State */
.no-swaps {
  background: var(--panel);
  border: 2px dashed var(--border);
  border-radius: var(--radius-lg);
  padding: 48px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  grid-column: 1 / -1;
  box-shadow: var(--shadow-sm);
}
.no-swaps-icon {
  width: 48px;
  height: 48px;
  color: var(--success);
  animation: bounce 2s infinite;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.no-swaps-msg {
  font-family: var(--font-display);
  font-size: 1.15rem;
  font-weight: 800;
  color: var(--text);
}
.no-swaps-sub {
  font-size: 0.85rem;
  color: var(--text-muted);
  max-width: 340px;
}

/* Standardize Icons */
svg.lucide {
  stroke-width: 2px;
  stroke: currentColor;
  fill: none;
  display: inline-flex !important;
  align-items: center;
  justify-content: center;
  vertical-align: middle;
  line-height: 1;
}

/* Mobile responsive styles */
@media (max-width: 768px) {
  .hdr {
    flex-direction: column;
    align-items: stretch;
    height: auto;
    padding: 16px;
    gap: 12px;
  }
  .hdr > div {
    justify-content: space-between;
  }
  .md3-select-wrapper {
    width: 100%;
  }
  .md3-select {
    width: 100%;
    flex-grow: 1;
  }
  .main {
    padding: 16px 12px 32px;
    gap: 24px;
  }
  .sec-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .sec-header > div {
    flex-direction: column;
    align-items: stretch;
    width: 100%;
    gap: 12px;
  }
  .md3-segmented-button-container {
    width: 100%;
  }
  .md3-segmented-button {
    flex: 1;
    text-align: center;
  }
  .week-nav {
    width: 100%;
    justify-content: space-between;
  }
  .week-label {
    flex-grow: 1;
    min-width: 0;
  }
  .swaps-grid {
    grid-template-columns: 1fr;
  }

  .top-grid section {
    display: none !important;
  }

  .week-view-container {
    border: none !important;
    background: transparent !important;
    box-shadow: none !important;
  }
  .week-grid {
    display: flex !important;
    flex-direction: column !important;
    gap: 12px !important;
    min-width: 0 !important;
    padding: 0 !important;
  }
  .time-labels-col, 
  .week-col-hdr-spacer, 
  .time-labels-allday-spacer {
    display: none !important;
  }
  .week-col-hdr {
    display: flex !important;
    align-items: center !important;
    justify-content: space-between !important;
    padding: 12px 16px !important;
    margin-top: 16px !important;
    margin-bottom: 4px !important;
    border-radius: var(--radius-md) !important;
    background: var(--panel-high) !important;
  }
  .week-col-hdr.today {
    background: var(--primary-bg) !important;
  }
  .week-col-hdr:first-of-type {
    margin-top: 0 !important;
  }
  .wch-dow {
    font-size: 0.85rem !important;
  }
  .wch-date {
    font-size: 1.1rem !important;
    margin-top: 0 !important;
  }

  .allday-container {
    border-bottom: 1px solid var(--border) !important;
    border-radius: var(--radius-sm) !important;
    margin-bottom: 8px !important;
    background: var(--panel) !important;
  }
  .hourly-container {
    position: static !important;
    height: auto !important;
    background: none !important;
    border: none !important;
    padding: 0 !important;
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
  }
  .allday-container:empty,
  .hourly-container:empty {
    display: none !important;
  }
  .shift-card.absolute-card {
    position: static !important;
    height: auto !important;
    width: 100% !important;
    box-sizing: border-box !important;
    margin-bottom: 8px !important;
    padding: 12px 16px !important;
    border-radius: var(--radius-md) !important;
    box-shadow: var(--shadow-sm) !important;
  }
  .shift-card.absolute-card:last-child {
    margin-bottom: 0 !important;
  }
  
  .shift-card.part-1 {
    height: auto !important;
    padding: 12px 16px !important;
    display: flex !important;
  }
  .shift-card.part-1 * {
    display: block !important;
  }

  .sb-title {
    font-size: 0.9rem !important;
  }
  .sb-loc, .sb-time {
    font-size: 0.8rem !important;
  }

  .card-body {
    grid-template-columns: 1fr !important;
    gap: 8px !important;
    padding: 12px !important;
  }
  .arrow-col {
    transform: rotate(90deg) !important;
    margin: 8px 0 !important;
  }
}

@media (max-width: 480px) {
  .logo {
    font-size: 1.1rem;
  }
}
</style>
</head>
<body>
<header class="hdr">
  <div style="display: flex; align-items: center; gap: 16px;">
    <div>
      <div class="logo">Shift Optimizer</div>
    </div>
  </div>

  <div style="display: flex; align-items: center; gap: 12px;">
    <div class="md3-select-wrapper">
      <span class="md3-select-label">Resident</span>
      <select id="rsel" class="md3-select"></select>
    </div>
  </div>
</header>

<main class="main">
  <div class="top-grid">
    <section>
      <div class="sec-header">
        <h2 class="section-title">Schedule View</h2>
        <div style="display: flex; align-items: center; gap: 12px; flex-wrap: wrap;">
          <div class="md3-segmented-button-container">
            <button class="md3-segmented-button" id="toggle-original">Original</button>
            <button class="md3-segmented-button selected" id="toggle-optimal">Optimal</button>
            <button class="md3-segmented-button" id="toggle-all">All</button>
          </div>
          <div class="week-nav">
            <button class="md3-btn-icon-outlined" id="prev-week" title="Previous week">
              <i data-lucide="chevron-left" style="width: 20px; height: 20px;"></i>
            </button>
            <div class="week-label" id="week-label"></div>
            <button class="md3-btn-icon-outlined" id="next-week" title="Next week">
              <i data-lucide="chevron-right" style="width: 20px; height: 20px;"></i>
            </button>
          </div>
        </div>
      </div>
      
      <div class="week-view-container">
        <div id="week-view"></div>
      </div>
    </section>
    
    <aside>
      <div class="sec-header">
        <h2 class="section-title">Metrics</h2>
      </div>
      
      <!-- Standalone Happiness Conserved Card -->
      <div class="happiness-card" id="happiness-card">
        <div class="orb-pulse">
          <i data-lucide="party-popper" style="width: 22px; height: 22px;"></i>
        </div>
        <div class="orb-text">
          <div class="orb-label">Total Happiness Conserved</div>
          <div class="orb-value" id="happiness-value">+0.0%</div>
        </div>
      </div>
      
      <div class="prefs-card" id="prefs"></div>
    </aside>
  </div>

  <div class="swaps-section">
    <div class="sec-header">
      <h2 class="section-title">Proposed Swaps <span class="count-badge" id="swap-count">0</span></h2>
    </div>
    
    <div class="swaps-rows-container" style="display: flex; flex-direction: column; gap: 24px;">
      <div class="swaps-row">
        <h3 class="swaps-row-title" style="margin-bottom: 12px; font-size: 0.95rem; display: flex; align-items: center; gap: 8px;">
          <i data-lucide="heart-handshake" style="color: var(--md-sys-color-tertiary); width: 20px; height: 20px;"></i>
          Swaps for You <span style="font-weight: normal; font-size: 0.8rem; color: var(--md-sys-color-on-surface-variant)">(you should propose these)</span>
          <span class="count-badge" id="swaps-for-you-count">0</span>
        </h3>
        <div id="swaps-for-you-grid" class="swaps-grid"></div>
      </div>

      <div class="swaps-row">
        <h3 class="swaps-row-title" style="margin-bottom: 12px; font-size: 0.95rem; display: flex; align-items: center; gap: 8px;">
          <i data-lucide="arrow-left-right" style="color: var(--md-sys-color-primary); width: 20px; height: 20px;"></i>
          Swaps with You <span style="font-weight: normal; font-size: 0.8rem; color: var(--md-sys-color-on-surface-variant)">(others may propose these)</span>
          <span class="count-badge" id="swaps-with-you-count">0</span>
        </h3>
        <div id="swaps-with-you-grid" class="swaps-grid"></div>
      </div>
    </div>

    <!-- Unified empty state container -->
    <div id="swaps-empty-state" style="display: none;"></div>
  </div>
</main>

<script>
/*__INJECT_DATA__*/

const MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
const DOWS = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'];
const DOWS_SHORT = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'];

let cur = null;
let weekOffset = 0; // weeks from the "anchor" week (first week with any shift)
let anchorMonday = null; // Date object for Monday of anchor week
let viewMode = 'optimal'; // 'optimal' or 'original'

const rejectedCycleIds = new Set();

function getTimeline() {
  const dates = Object.values(DATA.shifts).map(s => s.workDate).sort();
  if (dates.length === 0) return [];
  const start = new Date(dates[0] + 'T00:00:00');
  const end = new Date(dates[dates.length - 1] + 'T00:00:00');
  const timeline = [];
  let curr = new Date(start);
  while (curr <= end) {
    timeline.push(dateToIso(curr));
    curr.setDate(curr.getDate() + 1);
  }
  return timeline;
}

function getOffStreaks(timeline, workedDates) {
  const runs = [];
  let currentRun = 0;
  for (const d of timeline) {
    if (!workedDates.has(d)) {
      currentRun++;
    } else {
      if (currentRun > 0) {
        runs.push(currentRun);
        currentRun = 0;
      }
    }
  }
  if (currentRun > 0) {
    runs.push(currentRun);
  }
  return runs;
}

function getWorkStreaks(workDates) {
  if (workDates.size === 0) return [];
  const ordered = Array.from(workDates).sort();
  const lengths = [];
  let run = 1;
  for (let i = 0; i < ordered.length - 1; i++) {
    const prev = new Date(ordered[i] + 'T00:00:00');
    const cur = new Date(ordered[i+1] + 'T00:00:00');
    const diffDays = Math.round((cur - prev) / (1000 * 60 * 60 * 24));
    if (diffDays === 1) {
      run++;
    } else {
      lengths.push(run);
      run = 1;
    }
  }
  lengths.push(run);
  return lengths;
}

function recomputeAllMetrics() {
  const currentAssignment = {};
  for (const name in DATA.residents) {
    currentAssignment[name] = new Set(DATA.originalAssignment[name] || []);
  }
  for (const name in DATA.swaps) {
    DATA.swaps[name].forEach(sw => {
      if (!rejectedCycleIds.has(sw.cycleId)) {
        currentAssignment[name].delete(sw.giveUid);
        currentAssignment[name].add(sw.recvUid);
      }
    });
  }
  window.currentAssignment = currentAssignment;

  const timeline = getTimeline();

  for (const name in DATA.residents) {
    const r = DATA.residents[name];
    const uids = currentAssignment[name];
    const shiftsList = Array.from(uids).map(uid => DATA.shifts[uid]).filter(Boolean);

    const located = shiftsList.filter(s => s.loc !== null && s.loc !== undefined);
    let locOpt = 1.0;
    if (r.locPref !== "ANY" && located.length > 0) {
      locOpt = located.filter(s => s.loc === r.locPref).length / located.length;
    }
    r.loc.opt = Math.round(locOpt * 100);

    const typed = shiftsList.filter(s => s.type !== null && s.type !== undefined);
    let typeOpt = 1.0;
    if (r.typePref !== "ANY" && typed.length > 0) {
      typeOpt = typed.filter(s => s.type === r.typePref).length / typed.length;
    }
    r.type.opt = Math.round(typeOpt * 100);

    const workedDates = new Set(shiftsList.map(s => s.workDate));
    const runs = getOffStreaks(timeline, workedDates);
    const avgOff = runs.length ? runs.reduce((a, b) => a + b, 0) / runs.length : 0.0;
    r.streak.opt = Math.round(avgOff * 10) / 10;

    let hoursOpt = 0;
    shiftsList.forEach(s => {
      let duration = 0;
      if (s.endHour >= s.startHour) {
        duration = s.endHour - s.startHour;
      } else {
        duration = (s.endHour + 24) - s.startHour;
      }
      hoursOpt += duration;
    });
    r.hours.opt = Math.round(hoursOpt * 10) / 10;

    const workRuns = getWorkStreaks(workedDates);
    let phiStrVal = 1.0;
    if (workRuns.length > 0) {
      let sumDev = 0;
      workRuns.forEach(L => {
        sumDev += Math.abs(L - r.daysPref);
      });
      const meanDev = sumDev / workRuns.length;
      const streakBeta = DATA.config.STREAK_BETA;
      phiStrVal = Math.max(0.0, 1.0 - meanDev / streakBeta);
    }

    const baseUtility = r.locWeight * locOpt + r.typeWeight * typeOpt + r.daysWeight * phiStrVal;
    let finalUtility = baseUtility;
    if (DATA.config.TIME_DIFF_WEIGHT !== 0.0) {
      const additionalShiftTime = hoursOpt - r.origHours;
      finalUtility = baseUtility - (DATA.config.TIME_DIFF_WEIGHT * additionalShiftTime);
    }
    r.happiness.opt = Math.round(finalUtility * 100);
  }
}

function toggleRejectSwap(cycleId) {
  if (rejectedCycleIds.has(cycleId)) {
    rejectedCycleIds.delete(cycleId);
  } else {
    rejectedCycleIds.add(cycleId);
  }
  render();
}

function isoToDate(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, m - 1, d);
}
function dateToIso(dt) {
  return dt.getFullYear() + '-' + String(dt.getMonth()+1).padStart(2,'0') + '-' + String(dt.getDate()).padStart(2,'0');
}
function getMonday(dt) {
  const d = new Date(dt);
  const day = d.getDay(); // 0=Sun
  const diff = day === 0 ? -6 : 1 - day;
  d.setDate(d.getDate() + diff);
  return d;
}
function addDays(dt, n) {
  const d = new Date(dt);
  d.setDate(d.getDate() + n);
  return d;
}
function fmtShort(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return MONTHS[m-1].slice(0,3) + ' ' + d;
}
function cap(s) {
  if (!s) return s;
  return s.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function updateAnchorMonday() {
  const orig = DATA.originalAssignment[cur] || [];
  const current = window.currentAssignment ? (window.currentAssignment[cur] || new Set()) : new Set(DATA.finalAssignment[cur] || []);
  const uids = new Set([...orig, ...current]);
  const dates = Array.from(uids).map(uid => DATA.shifts[uid]).filter(Boolean).map(s => s.workDate).sort();
  if (dates.length) {
    anchorMonday = getMonday(isoToDate(dates[0]));
  } else {
    anchorMonday = getMonday(new Date());
  }
}

function init() {
  const names = Object.keys(DATA.residents).sort();
  const sel = document.getElementById('rsel');
  names.forEach(n => {
    const o = document.createElement('option');
    o.value = n;
    o.textContent = cap(n);
    sel.appendChild(o);
  });
  cur = names[0];
  sel.value = cur;
  updateAnchorMonday();

  document.getElementById('prev-week').addEventListener('click', () => { weekOffset--; renderWeek(); });
  document.getElementById('next-week').addEventListener('click', () => { weekOffset++; renderWeek(); });
  sel.addEventListener('change', e => { cur = e.target.value; weekOffset = 0; updateAnchorMonday(); render(); });

  const optBtn = document.getElementById('toggle-optimal');
  const origBtn = document.getElementById('toggle-original');
  const allBtn = document.getElementById('toggle-all');
  
  const setViewMode = (mode) => {
    viewMode = mode;
    [origBtn, optBtn, allBtn].forEach(btn => btn.classList.remove('selected'));
    if (mode === 'original') origBtn.classList.add('selected');
    else if (mode === 'optimal') optBtn.classList.add('selected');
    else if (mode === 'all') allBtn.classList.add('selected');
    renderWeek();
  };

  origBtn.addEventListener('click', () => setViewMode('original'));
  optBtn.addEventListener('click', () => setViewMode('optimal'));
  allBtn.addEventListener('click', () => setViewMode('all'));

  render();
}

function render() {
  recomputeAllMetrics();
  renderHappiness();
  renderPrefs();
  renderWeek();
  renderSwaps();
}

function updateLucide() {
  if (typeof lucide !== 'undefined') {
    lucide.createIcons();
  }
}

function layoutHourlyEntries(entries) {
  const items = entries.map(e => {
    let start = 0, end = 0;
    if (e.part === 1) {
      start = e.s.startHour;
      end = e.s.startHour + 1.0;
    } else if (e.part === 2) {
      start = 0.0;
      end = e.s.endHour;
    } else {
      start = e.s.startHour;
      end = e.s.endHour;
    }
    return { ...e, start, end };
  });

  items.sort((a, b) => a.start - b.start || b.end - a.end);

  const clusters = [];
  let currentCluster = null;

  items.forEach(item => {
    if (!currentCluster || item.start >= currentCluster.maxEnd) {
      currentCluster = {
        items: [item],
        maxEnd: item.end
      };
      clusters.push(currentCluster);
    } else {
      currentCluster.items.push(item);
      currentCluster.maxEnd = Math.max(currentCluster.maxEnd, item.end);
    }
  });

  clusters.forEach(cluster => {
    const columns = [];
    cluster.items.forEach(item => {
      let colIdx = -1;
      for (let c = 0; c < columns.length; c++) {
        if (columns[c] <= item.start) {
          colIdx = c;
          break;
        }
      }
      if (colIdx === -1) {
        colIdx = columns.length;
        columns.push(item.end);
      } else {
        columns[colIdx] = item.end;
      }
      item.colIdx = colIdx;
    });
    cluster.items.forEach(item => {
      item.numCols = columns.length;
    });
  });

  return items;
}

/* ── Happiness Card ── */
function renderHappiness() {
  const r = DATA.residents[cur];
  const total = (r.happiness.opt - r.happiness.orig) / 100;
  const pct = (total * 100).toFixed(1);
  const el = document.getElementById('happiness-value');
  const card = document.getElementById('happiness-card');
  const pulse = card.querySelector('.orb-pulse');
  el.textContent = (total >= 0 ? '+' : '') + pct + '%';
  
  if (total > 0.001) {
    card.style.background = 'var(--md-sys-color-tertiary-container)';
    card.style.color = 'var(--md-sys-color-on-tertiary-container)';
    card.style.borderColor = 'transparent';
    el.style.color = 'var(--md-sys-color-on-tertiary-container)';
    pulse.style.background = 'var(--md-sys-color-tertiary)';
    pulse.style.color = 'var(--md-sys-color-on-tertiary)';
    pulse.innerHTML = '<i data-lucide="party-popper" style="width:22px; height:22px;"></i>';
  } else if (total < -0.001) {
    card.style.background = 'var(--md-sys-color-error-container)';
    card.style.color = 'var(--md-sys-color-on-error-container)';
    card.style.borderColor = 'transparent';
    el.style.color = 'var(--md-sys-color-on-error-container)';
    pulse.style.background = 'var(--md-sys-color-error)';
    pulse.style.color = 'var(--md-sys-color-on-error)';
    pulse.innerHTML = '<i data-lucide="trending-down" style="width:22px; height:22px;"></i>';
  } else {
    card.style.background = 'var(--md-sys-color-surface-container-low)';
    card.style.color = 'var(--md-sys-color-on-surface)';
    card.style.borderColor = 'var(--md-sys-color-outline-variant)';
    el.style.color = 'var(--md-sys-color-on-surface)';
    pulse.style.background = 'var(--md-sys-color-outline)';
    pulse.style.color = 'var(--md-sys-color-surface)';
    pulse.innerHTML = '<i data-lucide="meh" style="width:22px; height:22px;"></i>';
  }
  updateLucide();
}

/* ── Metrics ── */
function renderPrefs() {
  const r = DATA.residents[cur];
  
  const bar = (origVal, optVal, hideLabel = false) => {
    const origPct = Math.min(100, Math.max(0, origVal));
    const optPct = Math.min(100, Math.max(0, optVal));
    const gainPct = Math.max(0, optPct - origPct);
    
    return '<div class="wbar-wrap">'
      + '<div class="wbar">'
      + '<div class="wfill-orig" style="width:' + origPct + '%"></div>'
      + '<div class="wfill-gain" style="width:' + gainPct + '%"></div>'
      + '</div>'
      + (hideLabel ? '' : '<div class="wlbl">' + origPct + '% &rarr; ' + optPct + '%</div>')
      + '</div>';
  };

  const row = (icon, label, prefVal, isAny, origVal, optVal) => {
    const displayVal = isAny ? 'ANY' : prefVal;
    const barHtml = isAny
      ? '<div style="font-size:0.75rem; color:var(--md-sys-color-on-surface-variant); font-style:italic;">No preference declared</div>'
      : bar(origVal, optVal);
    
    return '<div class="pref-row">'
      + '<div class="pref-lbl-row">'
      + '<span class="pref-lbl"><i data-lucide="' + icon + '" style="width:16px; height:16px;"></i>' + label + '</span>'
      + '<span class="pref-val' + (isAny ? ' any' : '') + '">' + displayVal + '</span>'
      + '</div>'
      + barHtml + '</div>';
  };

  const streakRow = (icon, label, orig, opt, target, weight) => {
    const isAny = weight === 0.0;
    const streakLabel = target <= 4 ? 'Frequent Breaks' : 'Longer Breaks';
    const body = isAny 
      ? '<div style="font-size:0.75rem; color:var(--md-sys-color-on-surface-variant); font-style:italic;">No preference declared</div>'
      : '<div style="font-size:0.75rem; color:var(--md-sys-color-on-surface-variant); margin-top:2px;">Target Work Streak: ' + streakLabel + '</div>';
    const improved = !isAny && (Math.abs(opt - target) < Math.abs(orig - target));
    const colorStyle = improved ? ' style="color: var(--md-sys-color-tertiary); font-weight: 700;"' : '';
    return '<div class="pref-row">'
      + '<div class="pref-lbl-row">'
      + '<span class="pref-lbl"><i data-lucide="' + icon + '" style="width:16px; height:16px;"></i>' + label + '</span>'
      + '<span class="pref-val"' + colorStyle + '>' + orig.toFixed(1) + ' &rarr; ' + opt.toFixed(1) + ' days</span>'
      + '</div>'
      + body
      + '</div>';
  };

  const hoursRow = (orig, opt) => {
    const delta = Math.round((opt - orig) * 10) / 10;
    const deltaStr = delta > 0 ? '+' + delta.toFixed(1) : delta.toFixed(1);
    const color = delta > 0.05
      ? 'var(--md-sys-color-error)'
      : delta < -0.05
        ? 'var(--md-sys-color-tertiary)'
        : 'var(--md-sys-color-on-surface-variant)';
    return '<div class="pref-row">'
      + '<div class="pref-lbl-row">'
      + '<span class="pref-lbl"><i data-lucide="timer" style="width:16px; height:16px;"></i>Hours Worked</span>'
      + '<span class="pref-val">' + orig.toFixed(1) + ' &rarr; <span style="color:' + color + '; font-weight:800;">' + opt.toFixed(1) + ' hrs</span>'
      + '</span>'
      + '</div>'
      + '</div>';
  };

  const happinessRow = (origVal, optVal) => {
    return '<div class="pref-row">'
      + '<div class="pref-lbl-row">'
      + '<span class="pref-lbl" style="color:var(--md-sys-color-tertiary)"><i data-lucide="party-popper" style="width:16px; height:16px;"></i>Total Happiness</span>'
      + '<span class="pref-val" style="color:var(--md-sys-color-tertiary)">' + origVal + '% &rarr; ' + optVal + '%</span>'
      + '</div>'
      + bar(origVal, optVal, true)
      + '</div>';
  };
  
  document.getElementById('prefs').innerHTML =
    row('map-pin', 'Location Preference', r.locPref, r.locPref === 'ANY', r.loc.orig, r.loc.opt)
    + '<hr class="divider">'
    + row('clock', 'Time Preference', r.typePref, r.typePref === 'ANY', r.type.orig, r.type.opt)
    + '<hr class="divider">'
    + streakRow('repeat', 'Avg Days Off Streak', r.streak.orig, r.streak.opt, r.daysPref, r.daysWeight)
    + '<hr class="divider">'
    + hoursRow(r.hours.orig, r.hours.opt)
    + '<hr class="divider">'
    + happinessRow(r.happiness.orig, r.happiness.opt);
  updateLucide();
}

/* ── Week View ── */
function renderWeek() {
  const orig = new Set(DATA.originalAssignment[cur] || []);
  const current = window.currentAssignment ? (window.currentAssignment[cur] || new Set()) : new Set(DATA.finalAssignment[cur] || []);
  const activeSwaps = (DATA.swaps[cur] || []).filter(s => !rejectedCycleIds.has(s.cycleId));
  const gives = new Set(activeSwaps.map(s => s.giveUid));
  const recvs = new Set(activeSwaps.map(s => s.recvUid));
  
  const visibleUids = viewMode === 'optimal' ? current : (viewMode === 'original' ? orig : new Set([...orig, ...current]));

  const dm = {};
  visibleUids.forEach(uid => {
    const s = DATA.shifts[uid];
    if (!s) return;
    
    let st = 'keep';
    if (gives.has(uid)) st = 'give';
    else if (recvs.has(uid)) st = 'recv';

    if (s.isJeopardy) {
      const k = s.workDate;
      if (!dm[k]) dm[k] = [];
      dm[k].push({ s, st, part: 'all-day' });
    } else if (s.endHour < s.startHour) {
      // Overnight shift!
      // Part 1: on start day (workDate)
      const k1 = s.workDate;
      if (!dm[k1]) dm[k1] = [];
      dm[k1].push({ s, st, part: 1 });

      // Part 2: on start day + 1
      const d1 = isoToDate(s.workDate);
      const d2 = addDays(d1, 1);
      const k2 = dateToIso(d2);
      if (!dm[k2]) dm[k2] = [];
      dm[k2].push({ s, st, part: 2 });
    } else {
      // Normal timed shift
      const k = s.workDate;
      if (!dm[k]) dm[k] = [];
      dm[k].push({ s, st, part: 0 });
    }
  });

  const monday = addDays(anchorMonday, weekOffset * 7);
  const sunday = addDays(monday, 6);
  const todayIso = new Date().toISOString().slice(0,10);

  // Update week label
  const moIso = dateToIso(monday);
  const suIso = dateToIso(sunday);
  const [my, mm, md] = moIso.split('-').map(Number);
  const [sy, sm, sd] = suIso.split('-').map(Number);
  const weekLbl = MONTHS[mm-1].slice(0,3) + ' ' + md
    + (mm !== sm ? ' – ' + MONTHS[sm-1].slice(0,3) + ' ' + sd : ' – ' + sd)
    + ', ' + my;
  document.getElementById('week-label').textContent = weekLbl;

  // Check if there are any all-day shifts in the current week
  let weekHasAllday = false;
  for (let i = 0; i < 7; i++) {
    const day = addDays(monday, i);
    const iso = dateToIso(day);
    const entries = dm[iso] || [];
    if (entries.some(e => e.part === 'all-day')) {
      weekHasAllday = true;
      break;
    }
  }

  let gridHtml = '';

  // 1. Time labels column elements
  gridHtml += '<div class="week-col-hdr-spacer" style="grid-column: 1; grid-row: 1; visibility: hidden; height: 52px; padding: 0; margin-bottom: 8px;"></div>';
  if (weekHasAllday) {
    gridHtml += '<div class="time-labels-allday-spacer" style="grid-column: 1; grid-row: 2; height: 0;"></div>';
  }
  const timeLabelsRow = weekHasAllday ? 3 : 2;
  gridHtml += '<div class="time-labels-col" style="grid-column: 1; grid-row: ' + timeLabelsRow + ';">'
    + '<div class="time-label" style="top: 0px;">12 AM</div>'
    + '<div class="time-label" style="top: 105px;">7 AM</div>'
    + '<div class="time-label" style="top: 180px;">12 PM</div>'
    + '<div class="time-label" style="top: 255px;">5 PM</div>'
    + '<div class="time-label" style="top: 345px;">11 PM</div>'
    + '</div>';

  // 2. Day columns elements
  for (let i = 0; i < 7; i++) {
    const day = addDays(monday, i);
    const iso = dateToIso(day);
    const isToday = iso === todayIso;
    const dow = DOWS_SHORT[day.getDay()];
    const dateNum = day.getDate();

    const entries = dm[iso] || [];
    const alldayEntries = entries.filter(e => e.part === 'all-day');
    const hourlyEntries = entries.filter(e => e.part !== 'all-day');

    const colIdx = i + 2;

    // Header
    gridHtml += '<div class="week-col-hdr' + (isToday ? ' today' : '') + '" style="grid-column: ' + colIdx + '; grid-row: 1;">'
      + '<div class="wch-dow">' + dow + '</div>'
      + '<div class="wch-date">' + dateNum + '</div>'
      + '</div>';

    if (weekHasAllday) {
      // All-day container
      let alldayCardsHtml = alldayEntries.map(({ s, st }) => {
        let cls = '';
        let badge = '';
        if (st === 'give') {
          cls = ' sb-give';
          badge = '<span class="sb-badge badge-give"><i data-lucide="arrow-up" style="width:10px; height:10px; stroke-width:3;"></i>Give</span>';
        } else if (st === 'recv') {
          cls = ' sb-recv';
          badge = '<span class="sb-badge badge-recv"><i data-lucide="arrow-down" style="width:10px; height:10px; stroke-width:3;"></i>Recv</span>';
        }
        return '<div class="allday-card' + cls + '" title="' + s.summary + '">'
          + '<div class="sb-title">' + s.summary + '</div>'
          + badge
          + '</div>';
      }).join('');

      gridHtml += '<div class="allday-container' + (isToday ? ' today-allday' : '') + '" style="grid-column: ' + colIdx + '; grid-row: 2;">'
        + alldayCardsHtml
        + '</div>';
    }

    // Hourly container
    let cards = '';
    const positionedEntries = layoutHourlyEntries(hourlyEntries);
    positionedEntries.forEach(({ s, st, part, colIdx, numCols }) => {
      let cls = st === 'give' ? 'sb-give' : st === 'recv' ? 'sb-recv' : s.loc === 'MGH' ? 'sb-mgh' : 'sb-bwh';
      const locLabel = s.loc || 'Unknown';
      
      let badge = '';
      if (st === 'give') {
        badge = '<span class="sb-badge badge-give"><i data-lucide="arrow-up" style="width:10px; height:10px; stroke-width:3;"></i>Give</span>';
      } else if (st === 'recv') {
        badge = '<span class="sb-badge badge-recv"><i data-lucide="arrow-down" style="width:10px; height:10px; stroke-width:3;"></i>Recv</span>';
      }

      // Calculate width and left percentages
      const widthPct = 98 / numCols;
      const leftPct = colIdx * (100 / numCols) + 1;

      if (part === 1) {
        cards += '<div class="shift-card absolute-card part-1 ' + cls + '" style="top: ' + (s.startHour * 15) + 'px; height: 15px; left: ' + leftPct + '%; width: ' + widthPct + '%; right: auto;" title="' + s.summary + '">'
          + '<div style="font-size:0.6rem; font-weight:700; white-space:nowrap; text-overflow:ellipsis; overflow:hidden;">' + s.summary + ' (P1)</div>'
          + '</div>';
      } else if (part === 2) {
        const height = s.endHour * 15;
        cards += '<div class="shift-card absolute-card ' + cls + '" style="top: 0px; height: ' + height + 'px; left: ' + leftPct + '%; width: ' + widthPct + '%; right: auto;" title="' + s.summary + '">'
          + '<div class="sb-title">' + s.summary + ' (P2)</div>'
          + '<div class="sb-loc"><i data-lucide="building" style="width:12px; height:12px;"></i>' + locLabel + (s.type ? ' · ' + s.type : '') + '</div>'
          + '<div class="sb-time"><i data-lucide="clock" style="width:12px; height:12px;"></i>' + s.startFmt + ' - ' + s.endFmt + '</div>'
          + badge
          + '</div>';
      } else {
        const top = s.startHour * 15;
        const height = (s.endHour - s.startHour) * 15;
        cards += '<div class="shift-card absolute-card ' + cls + '" style="top: ' + top + 'px; height: ' + height + 'px; left: ' + leftPct + '%; width: ' + widthPct + '%; right: auto;" title="' + s.summary + '">'
          + '<div class="sb-title">' + s.summary + '</div>'
          + '<div class="sb-loc"><i data-lucide="building" style="width:12px; height:12px;"></i>' + locLabel + (s.type ? ' · ' + s.type : '') + '</div>'
          + '<div class="sb-time"><i data-lucide="clock" style="width:12px; height:12px;"></i>' + s.startFmt + ' - ' + s.endFmt + '</div>'
          + badge
          + '</div>';
      }
    });

    const hourlyRow = weekHasAllday ? 3 : 2;
    gridHtml += '<div class="hourly-container' + (isToday ? ' today-hourly' : '') + (weekHasAllday ? ' split-bottom' : '') + '" style="grid-column: ' + colIdx + '; grid-row: ' + hourlyRow + ';">'
      + cards
      + '</div>';
  }

  document.getElementById('week-view').innerHTML =
    '<div class="week-grid' + (weekHasAllday ? ' has-allday' : '') + '">' + gridHtml + '</div>';
  updateLucide();
}

/* ── Swap Cards ── */
function renderSwaps() {
  const list = DATA.swaps[cur] || [];
  document.getElementById('swap-count').textContent = list.length;

  const rowsContainer = document.querySelector('.swaps-rows-container');
  const emptyState = document.getElementById('swaps-empty-state');

  if (!list.length) {
    rowsContainer.style.display = 'none';
    emptyState.style.display = 'block';
    emptyState.innerHTML = '<div class="no-swaps">'
      + '<i data-lucide="party-popper" class="no-swaps-icon"></i>'
      + '<div class="no-swaps-msg">Already optimized!</div>'
      + '<div class="no-swaps-sub">No swaps proposed for ' + cap(cur) + ' — schedule is already great.</div>'
      + '</div>';
    updateLucide();
    return;
  }

  rowsContainer.style.display = 'flex';
  emptyState.style.display = 'none';

  // Partition the list: swaps for you vs swaps with you
  const swapsForYou = list.filter(sw => sw.delta >= sw.partnerDelta);
  const swapsWithYou = list.filter(sw => sw.delta < sw.partnerDelta);

  document.getElementById('swaps-for-you-count').textContent = swapsForYou.length;
  document.getElementById('swaps-with-you-count').textContent = swapsWithYou.length;

  const renderGrid = (gridEl, subList) => {
    if (!subList.length) {
      gridEl.innerHTML = '<div style="color: var(--md-sys-color-on-surface-variant); font-style: italic; padding: 16px; background: var(--md-sys-color-surface-container-low); border-radius: var(--md-sys-shape-corner-medium); border: 1px dashed var(--md-sys-color-outline-variant); grid-column: 1 / -1; text-align: center;">No swaps in this category.</div>';
      return;
    }

    gridEl.innerHTML = subList.map((sw, i) => {
      const pct = (sw.delta * 100).toFixed(1);
      const partnerPct = (sw.partnerDelta * 100).toFixed(1);
      
      const isPos = sw.delta > 0.0001;
      const isNeg = sw.delta < -0.0001;
      const deltaLabel = isPos ? '+' + pct + '% (You)' : isNeg ? pct + '% (You)' : 'Neutral (You)';
      const dpClass = isPos ? 'pos' : isNeg ? 'neg' : 'neu';

      const isPartnerPos = sw.partnerDelta > 0.0001;
      const isPartnerNeg = sw.partnerDelta < -0.0001;
      const partnerDeltaLabel = isPartnerPos ? '+' + partnerPct + '% (' + cap(sw.swapWith) + ')' : isPartnerNeg ? partnerPct + '% (' + cap(sw.swapWith) + ')' : 'Neutral (' + cap(sw.swapWith) + ')';
      const partnerDpClass = isPartnerPos ? 'pos' : isPartnerNeg ? 'neg' : 'neu';

      const isRejected = rejectedCycleIds.has(sw.cycleId);
      const cardClass = isRejected ? 'rejected-card' : (isPos ? 'pos-card' : isNeg ? 'neg-card' : 'neu-card');
      const hdrClass = isRejected ? 'neu' : (isPos ? 'pos' : isNeg ? 'neg' : 'neu');
      const partnerName = sw.swapWith ? cap(sw.swapWith) : 'Partner';

      const btnIcon = isRejected ? 'rotate-ccw' : 'x';
      const btnTitle = isRejected ? 'Restore Swap' : 'Reject Swap';
      const btnClass = isRejected ? 'reject-swap-btn restore' : 'reject-swap-btn';

      return '<div class="swap-card ' + cardClass + '">'
        + '<div class="swap-card-hdr ' + hdrClass + '">'
        + '<div class="card-hdr-left" style="display:flex; flex-direction:column; gap:4px;">'
        + '<div style="display: flex; align-items: center; gap: 8px;">'
        + '<div style="font-size:0.75rem; font-weight:700; text-transform:uppercase; color:var(--md-sys-color-on-surface-variant)">Swap ' + (i+1) + '</div>'
        + (isRejected ? '<span class="sb-badge badge-recv" style="background:var(--md-sys-color-error-container); color:var(--md-sys-color-on-error-container); font-size:0.65rem; padding: 1px 6px;">Rejected</span>' : '')
        + '</div>'
        + '<div class="swap-with-badge"><i data-lucide="arrow-left-right" style="width:14px; height:14px;"></i>with <span class="partner-name partner-chip">' + partnerName + '</span></div>'
        + '</div>'
        + '<div style="display: flex; align-items: center; gap: 12px;">'
        + '<div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">'
        + '<span class="delta-pill ' + dpClass + '">' 
        + (isPos ? '<i data-lucide="trending-up" style="width:14px; height:14px;"></i>' : isNeg ? '<i data-lucide="trending-down" style="width:14px; height:14px;"></i>' : '')
        + deltaLabel + '</span>'
        + '<span class="delta-pill ' + partnerDpClass + '">' 
        + (isPartnerPos ? '<i data-lucide="trending-up" style="width:14px; height:14px;"></i>' : isPartnerNeg ? '<i data-lucide="trending-down" style="width:14px; height:14px;"></i>' : '')
        + partnerDeltaLabel + '</span>'
        + '</div>'
        + '<button class="' + btnClass + '" title="' + btnTitle + '" onclick="toggleRejectSwap(' + sw.cycleId + ')">'
        + '<i data-lucide="' + btnIcon + '" style="width:18px; height:18px;"></i>'
        + '</button>'
        + '</div>'
        + '</div>'
        + '<div class="card-body">'
        + blk(sw, 'give')
        + '<div class="arrow-col"><div class="arrow-btn"><i data-lucide="arrow-right" style="width:20px; height:20px;"></i></div></div>'
        + blk(sw, 'recv')
        + '</div></div>';
    }).join('');
  };

  renderGrid(document.getElementById('swaps-for-you-grid'), swapsForYou);
  renderGrid(document.getElementById('swaps-with-you-grid'), swapsWithYou);
  updateLucide();
}

function blk(sw, side) {
  const p = side === 'give' ? 'give' : 'recv';
  const label = side === 'give' ? 'Giving Away' : 'Receiving';
  const icon = side === 'give' ? 'arrow-up' : 'arrow-down';
  const loc = sw[p + 'Loc'];
  const type = sw[p + 'Type'];
  
  const isMgh = loc === 'MGH';
  const isBwh = loc === 'BWH';
  const lcls = isMgh ? 'lt-mgh' : isBwh ? 'lt-bwh' : 'lt-none';
  const lbl = loc || 'Jeopardy';
  
  return '<div class="shift-blk ' + side + '">'
    + '<div class="blk-lbl"><i data-lucide="' + icon + '" style="width:12px; height:12px;"></i>' + label + '</div>'
    + '<div class="blk-summary">' + sw[p + 'Summary'] + '</div>'
    + '<div class="blk-meta">'
    + '<div><i data-lucide="calendar" style="width:12px; height:12px; vertical-align:middle; margin-right:4px;"></i>' + fmtShort(sw[p + 'Date']) + '</div>'
    + '<div><i data-lucide="clock" style="width:12px; height:12px; vertical-align:middle; margin-right:4px;"></i>' + sw[p + 'Start'] + ' &ndash; ' + sw[p + 'End'] + '</div>'
    + '</div>'
    + '<span class="loc-tag ' + lcls + '">' + lbl + (type ? ' &middot; ' + type : '') + '</span>'
    + '</div>';
}

init();
</script>
</body>
</html>
"""
