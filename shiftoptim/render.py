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
<link href="https://fonts.googleapis.com/css2?family=Roboto+Flex:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lucide@latest"></script>
<style>
:root {
  /* DARK THEME (Default) */
  --calendar-grid-line: rgba(255, 255, 255, 0.05);
  --md-sys-color-primary: #A5B4FC;
  --md-sys-color-on-primary: #1E1B4B;
  --md-sys-color-primary-container: #312E81;
  --md-sys-color-on-primary-container: #E0E7FF;
  
  --md-sys-color-secondary: #94A3B8;
  --md-sys-color-on-secondary: #0F172A;
  --md-sys-color-secondary-container: #1E293B;
  --md-sys-color-on-secondary-container: #F1F5F9;
  
  --md-sys-color-tertiary: #2DD4BF;
  --md-sys-color-on-tertiary: #00332C;
  --md-sys-color-tertiary-container: #115E59;
  --md-sys-color-on-tertiary-container: #CCFBF1;
  
  --md-sys-color-error: #FCA5A5;
  --md-sys-color-on-error: #7F1D1D;
  --md-sys-color-error-container: #991B1B;
  --md-sys-color-on-error-container: #FEE2E2;
  
  --md-sys-color-surface: #090D16;
  --md-sys-color-on-surface: #F8FAFC;
  --md-sys-color-on-surface-variant: #94A3B8;
  
  --md-sys-color-surface-container-lowest: #05070B;
  --md-sys-color-surface-container-low: #0E1424;
  --md-sys-color-surface-container: #151E33;
  --md-sys-color-surface-container-high: #212C47;
  --md-sys-color-surface-container-highest: #2D3B5C;
  
  --md-sys-color-outline: #475569;
  --md-sys-color-outline-variant: #1E293B;
  
  /* Shapes */
  --md-sys-shape-corner-none: 0px;
  --md-sys-shape-corner-extra-small: 4px;
  --md-sys-shape-corner-small: 8px;
  --md-sys-shape-corner-medium: 12px;
  --md-sys-shape-corner-large: 16px;
  --md-sys-shape-corner-extra-large: 28px;
  --md-sys-shape-corner-full: 9999px;
  
  /* Elevation Shadows */
  --md-sys-elevation-shadow-1: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
  --md-sys-elevation-shadow-2: 0 3px 6px rgba(0,0,0,0.4), 0 2px 4px rgba(0,0,0,0.3);
  --md-sys-elevation-shadow-3: 0 10px 20px rgba(0,0,0,0.5), 0 6px 6px rgba(0,0,0,0.4);
  
  /* Motion & Easing */
  --md-sys-motion-easing-emphasized: cubic-bezier(0.2, 0, 0, 1);
  --md-sys-motion-easing-emphasized-decelerate: cubic-bezier(0.05, 0.7, 0.1, 1);
}

@media (prefers-color-scheme: light) {
  :root {
    /* LIGHT THEME */
    --calendar-grid-line: rgba(0, 0, 0, 0.05);
    --md-sys-color-primary: #4F46E5;
    --md-sys-color-on-primary: #FFFFFF;
    --md-sys-color-primary-container: #E0E7FF;
    --md-sys-color-on-primary-container: #1E1B4B;
    
    --md-sys-color-secondary: #475569;
    --md-sys-color-on-secondary: #FFFFFF;
    --md-sys-color-secondary-container: #F1F5F9;
    --md-sys-color-on-secondary-container: #0F172A;
    
    --md-sys-color-tertiary: #0D9488;
    --md-sys-color-on-tertiary: #FFFFFF;
    --md-sys-color-tertiary-container: #CCFBF1;
    --md-sys-color-on-tertiary-container: #115E59;
    
    --md-sys-color-error: #EF4444;
    --md-sys-color-on-error: #FFFFFF;
    --md-sys-color-error-container: #FEE2E2;
    --md-sys-color-on-error-container: #991B1B;
    
    --md-sys-color-surface: #F8FAFC;
    --md-sys-color-on-surface: #0F172A;
    --md-sys-color-on-surface-variant: #475569;
    
    --md-sys-color-surface-container-lowest: #FFFFFF;
    --md-sys-color-surface-container-low: #F1F5F9;
    --md-sys-color-surface-container: #E2E8F0;
    --md-sys-color-surface-container-high: #CBD5E1;
    --md-sys-color-surface-container-highest: #94A3B8;
    
    --md-sys-color-outline: #94A3B8;
    --md-sys-color-outline-variant: #E2E8F0;
    
    --md-sys-elevation-shadow-1: 0 1px 2px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.1);
    --md-sys-elevation-shadow-2: 0 2px 4px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.08);
    --md-sys-elevation-shadow-3: 0 4px 8px rgba(0,0,0,0.1), 0 8px 24px rgba(0,0,0,0.15);
  }
}

*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

body {
  font-family: 'Roboto Flex', system-ui, -apple-system, sans-serif;
  background: var(--md-sys-color-surface);
  color: var(--md-sys-color-on-surface);
  line-height: 1.5;
  font-size: 14px;
  min-height: 100vh;
  transition: background-color 0.3s, color 0.3s;
}

/* Header / App Bar */
.hdr {
  background: var(--md-sys-color-surface-container-low);
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: sticky;
  top: 0;
  z-index: 100;
  backdrop-filter: blur(12px);
  transition: background-color 0.3s, border-color 0.3s;
  height: 72px;
}
.logo-mark {
  width: 40px;
  height: 40px;
  border-radius: var(--md-sys-shape-corner-large);
  background: linear-gradient(135deg, var(--md-sys-color-primary), var(--md-sys-color-tertiary));
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--md-sys-color-on-primary);
  box-shadow: 0 4px 12px rgba(79, 70, 229, 0.2);
  flex-shrink: 0;
}
.logo {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface);
  letter-spacing: -0.2px;
}
.logo-sub {
  color: var(--md-sys-color-on-surface-variant);
  font-size: 0.75rem;
  font-weight: 400;
}

/* Happiness Scorecard Card */
.happiness-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: var(--md-sys-color-surface-container-low);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  padding: 16px;
  box-shadow: var(--md-sys-elevation-shadow-1);
  transition: all 0.3s;
  margin-bottom: 16px;
}
@keyframes happiness-pulse {
  0% { box-shadow: 0 0 0 0 rgba(45, 212, 191, 0.4); }
  70% { box-shadow: 0 0 0 8px rgba(45, 212, 191, 0); }
  100% { box-shadow: 0 0 0 0 rgba(45, 212, 191, 0); }
}
.orb-pulse {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: var(--md-sys-color-tertiary);
  color: var(--md-sys-color-on-tertiary);
  display: flex;
  align-items: center;
  justify-content: center;
  animation: happiness-pulse 2s infinite;
  flex-shrink: 0;
}
.orb-text {
  line-height: 1.2;
}
.orb-label {
  font-size: 0.72rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--md-sys-color-on-surface-variant);
  font-weight: 700;
}
.orb-value {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--md-sys-color-on-surface);
}

/* MD3 Dropdown Selector */
.md3-select-wrapper {
  position: relative;
  display: inline-flex;
  flex-direction: column;
}
.md3-select-label {
  position: absolute;
  top: -6px;
  left: 12px;
  background: var(--md-sys-color-surface-container-low);
  padding: 0 6px;
  font-size: 0.7rem;
  font-weight: 600;
  color: var(--md-sys-color-primary);
  pointer-events: none;
  transition: color 0.2s, background-color 0.3s;
}
.md3-select {
  height: 48px;
  padding: 0 40px 0 16px;
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-small);
  background: transparent;
  color: var(--md-sys-color-on-surface);
  font-size: 0.9rem;
  font-family: inherit;
  font-weight: 500;
  outline: none;
  cursor: pointer;
  appearance: none;
  transition: border-color 0.2s, box-shadow 0.2s;
  min-width: 180px;
}
.md3-select:focus {
  border-color: var(--md-sys-color-primary);
  border-width: 2px;
}
.md3-select-wrapper::after {
  content: '▼';
  font-family: inherit;
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--md-sys-color-on-surface-variant);
  pointer-events: none;
  font-size: 10px;
}

/* MD3 Icon Buttons */
.md3-btn-icon-outlined {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: 1px solid var(--md-sys-color-outline);
  background: transparent;
  color: var(--md-sys-color-on-surface-variant);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 0.2s, border-color 0.2s, color 0.2s;
}
.md3-btn-icon-outlined:hover {
  background-color: var(--md-sys-color-primary-container);
  border-color: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary-container);
}

/* Segmented Buttons */
.md3-segmented-button-container {
  display: inline-flex;
  background: var(--md-sys-color-surface-container-high);
  border: 1px solid var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-full);
  overflow: hidden;
  padding: 4px;
  align-items: center;
}
.md3-segmented-button {
  border: none;
  background: transparent;
  color: var(--md-sys-color-on-surface-variant);
  padding: 6px 16px;
  font-size: 0.8rem;
  font-weight: 700;
  border-radius: var(--md-sys-shape-corner-full);
  cursor: pointer;
  transition: background-color 0.2s, color 0.2s;
  outline: none;
}
.md3-segmented-button:hover {
  background-color: rgba(79, 70, 229, 0.08);
  color: var(--md-sys-color-primary);
}
.md3-segmented-button.selected {
  background-color: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary);
}

/* Main Layout */
.main {
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 32px 48px;
  display: flex;
  flex-direction: column;
  gap: 32px;
}

/* Top Section Grid */
.top-grid {
  display: grid;
  grid-template-columns: 1fr 340px;
  gap: 24px;
  align-items: start;
}
@media (max-width: 1024px) {
  .top-grid {
    grid-template-columns: 1fr;
  }
}

/* Section Header */
.sec-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.section-title {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface);
  display: flex;
  align-items: center;
  gap: 10px;
}
.section-title::before {
  content: '';
  display: block;
  width: 4px;
  height: 18px;
  background: var(--md-sys-color-primary);
  border-radius: 2px;
}

/* Week Navigation & Grid */
.week-nav {
  display: flex;
  align-items: center;
  gap: 12px;
}
.week-label {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface);
  min-width: 200px;
  text-align: center;
}
.week-view-container {
  overflow-x: auto;
  border-radius: var(--md-sys-shape-corner-medium);
  border: 1px solid var(--md-sys-color-outline-variant);
  background: var(--md-sys-color-surface-container-low);
  transition: background-color 0.3s, border-color 0.3s;
}
.week-grid {
  display: grid;
  grid-template-columns: 50px repeat(7, minmax(130px, 1fr));
  column-gap: 8px;
  row-gap: 0;
  padding: 12px;
  min-width: 1000px;
}
.week-col-hdr {
  text-align: center;
  padding: 10px 8px;
  background: var(--md-sys-color-surface-container);
  border-radius: var(--md-sys-shape-corner-small);
  transition: background-color 0.3s;
  margin-bottom: 8px;
}
.week-col-hdr.today {
  background: var(--md-sys-color-primary-container);
  color: var(--md-sys-color-on-primary-container);
}
.wch-dow {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--md-sys-color-on-surface-variant);
}
.week-col-hdr.today .wch-dow {
  color: var(--md-sys-color-primary);
}
.wch-date {
  font-size: 1.25rem;
  font-weight: 800;
  color: var(--md-sys-color-on-surface);
  line-height: 1.1;
  margin-top: 2px;
}
.week-col-hdr.today .wch-date {
  color: var(--md-sys-color-on-primary-container);
}
.week-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

/* Time labels column styling */
.time-labels-col {
  position: relative;
  height: 360px;
  margin-top: 6px;
  transition: margin-top 0.3s;
}
.week-grid.has-allday .time-labels-col {
  margin-top: 0px;
}
.time-label {
  position: absolute;
  right: 8px;
  font-size: 0.65rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface-variant);
  transform: translateY(-50%);
}

/* Calendar Sections */
.allday-container {
  display: flex;
  flex-direction: column;
  gap: 4px;
  background-color: var(--md-sys-color-surface-container-lowest);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-bottom: none;
  border-top-left-radius: var(--md-sys-shape-corner-small);
  border-top-right-radius: var(--md-sys-shape-corner-small);
  padding: 6px 6px 4px 6px;
  transition: border-color 0.3s, background-color 0.3s;
}
.allday-container.today-allday {
  border-color: var(--md-sys-color-primary);
  border-width: 2px 2px 0 2px;
  background-color: rgba(79, 70, 229, 0.02);
}

.hourly-container {
  position: relative;
  height: 360px;
  background: linear-gradient(var(--calendar-grid-line) 1px, transparent 1px);
  background-size: 100% 15px; /* grid line every 1 hour (15px) */
  background-color: var(--md-sys-color-surface-container-lowest);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-small);
  padding: 6px;
  transition: border-color 0.3s, background-color 0.3s;
}
.hourly-container.today-hourly {
  border-color: var(--md-sys-color-primary);
  border-width: 2px;
  background-color: rgba(79, 70, 229, 0.02);
}
.hourly-container.split-bottom {
  border-top: none;
  border-top-left-radius: 0;
  border-top-right-radius: 0;
  padding-top: 0px;
}
.hourly-container.today-hourly.split-bottom {
  border-width: 0 2px 2px 2px;
}

/* Shift card */
.shift-card {
  border-radius: var(--md-sys-shape-corner-small);
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-left: 4px solid transparent;
  transition: transform 0.2s var(--md-sys-motion-easing-emphasized),
              box-shadow 0.2s var(--md-sys-motion-easing-emphasized),
              background-color 0.3s;
  cursor: default;
  background: var(--md-sys-color-surface-container-low);
  color: var(--md-sys-color-on-surface);
}
.shift-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--md-sys-elevation-shadow-1);
}
.shift-card.sb-mgh {
  background: var(--md-sys-color-primary-container);
  color: var(--md-sys-color-on-primary-container);
  border-left-color: var(--md-sys-color-primary);
}
.shift-card.sb-mgh .sb-loc { color: var(--md-sys-color-primary); }
.shift-card.sb-bwh {
  background: var(--md-sys-color-secondary-container);
  color: var(--md-sys-color-on-secondary-container);
  border-left-color: var(--md-sys-color-secondary);
}
.shift-card.sb-bwh .sb-loc { color: var(--md-sys-color-secondary); }
.shift-card.sb-give {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
  border-left-color: var(--md-sys-color-error);
  opacity: 0.85;
}
.shift-card.sb-give .sb-loc { color: var(--md-sys-color-error); }
.shift-card.sb-recv {
  background: var(--md-sys-color-tertiary-container);
  color: var(--md-sys-color-on-tertiary-container);
  border-left-color: var(--md-sys-color-tertiary);
}
.shift-card.sb-recv .sb-loc { color: var(--md-sys-color-tertiary); }
.allday-card {
  border-radius: var(--md-sys-shape-corner-small);
  padding: 6px 8px;
  background: var(--md-sys-color-surface-container-highest);
  color: var(--md-sys-color-on-surface-variant);
  cursor: default;
  transition: background-color 0.2s, transform 0.2s;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  border: none;
  box-shadow: none;
  margin-bottom: 2px;
}
.allday-card:hover {
  background: var(--md-sys-color-surface-container-high);
  transform: translateY(-1px);
}
.allday-card.sb-give {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
}
.allday-card.sb-recv {
  background: var(--md-sys-color-tertiary-container);
  color: var(--md-sys-color-on-tertiary-container);
}
.allday-card .sb-title {
  text-align: center;
  white-space: normal;
  overflow: visible;
  text-overflow: clip;
  color: inherit;
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1.2;
  word-break: break-word;
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
  color: var(--md-sys-color-on-surface);
  line-height: 1.2;
  word-break: break-word;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-loc {
  font-size: 0.65rem;
  font-weight: 600;
  color: var(--md-sys-color-on-surface-variant);
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-time {
  font-size: 0.65rem;
  color: var(--md-sys-color-on-surface-variant);
  display: flex;
  align-items: center;
  gap: 4px;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sb-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.58rem;
  font-weight: 700;
  border-radius: 4px;
  padding: 1px 4px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-top: 2px;
  width: fit-content;
}
.badge-give {
  background: var(--md-sys-color-error);
  color: var(--md-sys-color-on-error);
}
.badge-recv {
  background: var(--md-sys-color-tertiary);
  color: var(--md-sys-color-on-tertiary);
}

/* Sidebar Preferences / Metrics */
.prefs-card {
  background: var(--md-sys-color-surface-container-low);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  box-shadow: var(--md-sys-elevation-shadow-1);
  transition: background-color 0.3s, border-color 0.3s, box-shadow 0.3s;
}
.pref-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
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
  letter-spacing: 0.06em;
  color: var(--md-sys-color-on-surface-variant);
  display: flex;
  align-items: center;
  gap: 6px;
}
.pref-val {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface);
}
.pref-val.any {
  color: var(--md-sys-color-on-surface-variant);
  font-style: italic;
  font-weight: 400;
}

/* MD3 Dual-color Progress Indicators */
.wbar-wrap {
  display: flex;
  align-items: center;
  gap: 12px;
}
.wbar {
  flex: 1;
  height: 6px;
  background: var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-full);
  overflow: hidden;
  display: flex;
}
.wfill-orig {
  height: 100%;
  background: var(--md-sys-color-outline); /* grey */
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}
.wfill-gain {
  height: 100%;
  background: var(--md-sys-color-tertiary); /* green */
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}
.wlbl {
  font-size: 0.68rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface-variant);
  min-width: 60px;
  text-align: right;
}

/* Days Off Chips */
.doff-container {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}
.doff-chip {
  background: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
  border-radius: var(--md-sys-shape-corner-small);
  padding: 4px 8px;
  font-size: 0.72rem;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.doff-none {
  font-size: 0.75rem;
  color: var(--md-sys-color-on-surface-variant);
  font-style: italic;
}
.divider {
  border: none;
  border-top: 1px solid var(--md-sys-color-outline-variant);
  margin: 4px 0;
}

/* Proposed Swaps Section */
.swaps-section {
  margin-top: 16px;
}
.count-badge {
  background: var(--md-sys-color-primary);
  color: var(--md-sys-color-on-primary);
  border-radius: var(--md-sys-shape-corner-full);
  padding: 2px 10px;
  font-size: 0.8rem;
  font-weight: 700;
  margin-left: 8px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.swaps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 16px;
}
@media (max-width: 480px) {
  .swaps-grid {
    grid-template-columns: 1fr;
  }
}

/* Swap Card styling */
.swap-card {
  background: var(--md-sys-color-surface-container-low);
  border: 1px solid var(--md-sys-color-outline-variant);
  border-radius: var(--md-sys-shape-corner-medium);
  position: relative;
  transition: transform 0.2s var(--md-sys-motion-easing-emphasized),
              box-shadow 0.2s var(--md-sys-motion-easing-emphasized),
              border-color 0.2s;
  display: flex;
  flex-direction: column;
}
.swap-card:hover {
  transform: translateY(-4px);
  box-shadow: var(--md-sys-elevation-shadow-2);
  border-color: var(--md-sys-color-outline);
}
.swap-card.pos-card { border-top: 4px solid var(--md-sys-color-tertiary); }
.swap-card.neg-card { border-top: 4px solid var(--md-sys-color-error); }
.swap-card.neu-card { border-top: 4px solid var(--md-sys-color-outline); }

/* Rejected/Excluded Swaps Styling */
.swap-card.rejected-card {
  opacity: 0.45;
  filter: grayscale(60%);
  border-top-color: var(--md-sys-color-outline-variant) !important;
  transform: none !important;
  box-shadow: none !important;
}
.swap-card.rejected-card .delta-pill {
  background: var(--md-sys-color-surface-container-high) !important;
  color: var(--md-sys-color-on-surface-variant) !important;
  border-color: var(--md-sys-color-outline-variant) !important;
}
.reject-swap-btn {
  position: absolute;
  top: -10px;
  right: -10px;
  width: 32px;
  height: 32px;
  background: var(--md-sys-color-surface-container-high);
  border: 1px solid var(--md-sys-color-outline-variant);
  color: var(--md-sys-color-on-surface-variant);
  cursor: pointer;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: var(--md-sys-elevation-shadow-1);
  transition: background-color 0.2s, color 0.2s, transform 0.2s, box-shadow 0.2s;
  z-index: 10;
}
.reject-swap-btn:hover {
  background-color: var(--md-sys-color-error-container);
  color: var(--md-sys-color-on-error-container);
  transform: scale(1.1);
  box-shadow: var(--md-sys-elevation-shadow-2);
}
.reject-swap-btn.restore:hover {
  background-color: var(--md-sys-color-tertiary-container);
  color: var(--md-sys-color-on-tertiary-container);
  transform: scale(1.1);
  box-shadow: var(--md-sys-elevation-shadow-2);
}

.swap-card-hdr {
  padding: 12px 16px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--md-sys-color-outline-variant);
  border-top-left-radius: calc(var(--md-sys-shape-corner-medium) - 1px);
  border-top-right-radius: calc(var(--md-sys-shape-corner-medium) - 1px);
}
.swap-card-hdr.pos { background: linear-gradient(90deg, rgba(45, 212, 191, 0.08), transparent); }
.swap-card-hdr.neg { background: linear-gradient(90deg, rgba(239, 68, 68, 0.08), transparent); }
.swap-card-hdr.neu { background: var(--md-sys-color-surface-container-high); }

.swap-with-badge {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--md-sys-color-on-surface);
  display: flex;
  align-items: center;
  gap: 4px;
}
.partner-chip {
  background: var(--md-sys-color-primary-container);
  color: var(--md-sys-color-on-primary-container);
  border-radius: var(--md-sys-shape-corner-small);
  padding: 2px 8px;
  font-size: 0.72rem;
  font-weight: 700;
}
.delta-pill {
  border-radius: var(--md-sys-shape-corner-full);
  padding: 4px 10px;
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 4px;
}
.delta-pill.pos { background: var(--md-sys-color-tertiary-container); color: var(--md-sys-color-on-tertiary-container); }
.delta-pill.neg { background: var(--md-sys-color-error-container); color: var(--md-sys-color-on-error-container); }
.delta-pill.neu { background: var(--md-sys-color-surface-container-highest); color: var(--md-sys-color-on-surface-variant); }

.card-body {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 12px;
  padding: 16px;
}
.shift-blk {
  padding: 12px;
  border-radius: var(--md-sys-shape-corner-medium);
  background: var(--md-sys-color-surface-container-lowest);
  border: 1px solid var(--md-sys-color-outline-variant);
  display: flex;
  flex-direction: column;
  gap: 6px;
  height: 100%;
}
.shift-blk.give { border-left: 4px solid var(--md-sys-color-error); }
.shift-blk.recv { border-left: 4px solid var(--md-sys-color-tertiary); }

.blk-lbl {
  font-size: 0.65rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  display: flex;
  align-items: center;
  gap: 4px;
}
.shift-blk.give .blk-lbl { color: var(--md-sys-color-error); }
.shift-blk.recv .blk-lbl { color: var(--md-sys-color-tertiary); }

.blk-summary {
  font-size: 0.8rem;
  font-weight: 700;
  line-height: 1.35;
  color: var(--md-sys-color-on-surface);
}
.blk-meta {
  font-size: 0.72rem;
  color: var(--md-sys-color-on-surface-variant);
  line-height: 1.4;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.loc-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: var(--md-sys-shape-corner-small);
  padding: 2px 8px;
  font-size: 0.65rem;
  font-weight: 700;
  margin-top: auto;
  width: fit-content;
}
.loc-tag.lt-mgh { background: var(--md-sys-color-primary-container); color: var(--md-sys-color-on-primary-container); }
.loc-tag.lt-bwh { background: var(--md-sys-color-secondary-container); color: var(--md-sys-color-on-secondary-container); }
.loc-tag.lt-none { background: var(--md-sys-color-surface-container-highest); color: var(--md-sys-color-on-surface-variant); }

.arrow-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.arrow-btn {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: var(--md-sys-color-surface-container-high);
  border: 1px solid var(--md-sys-color-outline-variant);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--md-sys-color-primary);
}

/* Empty State */
.no-swaps {
  background: var(--md-sys-color-surface-container-low);
  border: 1.5px dashed var(--md-sys-color-outline);
  border-radius: var(--md-sys-shape-corner-large);
  padding: 48px;
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  grid-column: 1 / -1;
}
.no-swaps-icon {
  width: 48px;
  height: 48px;
  color: var(--md-sys-color-tertiary);
  animation: bounce 2s infinite;
}
@keyframes bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-6px); }
}
.no-swaps-msg {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--md-sys-color-on-surface);
}
.no-swaps-sub {
  font-size: 0.85rem;
  color: var(--md-sys-color-on-surface-variant);
  max-width: 340px;
}

/* Standardize Material Symbols for symmetric, uniform design */
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

  /* Hide schedule calendar section on mobile completely */
  .top-grid section {
    display: none !important;
  }

  /* Calendar mobile vertical view override */
  .week-view-container {
    border: none !important;
    background: transparent !important;
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
    border-radius: var(--md-sys-shape-corner-medium) !important;
    background: var(--md-sys-color-surface-container-high) !important;
  }
  .week-col-hdr.today {
    background: var(--md-sys-color-primary-container) !important;
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

  /* Card and container layout overrides */
  .allday-container {
    border-bottom: 1px solid var(--md-sys-color-outline-variant) !important;
    border-radius: var(--md-sys-shape-corner-small) !important;
    margin-bottom: 8px !important;
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
    border-radius: var(--md-sys-shape-corner-medium) !important;
    box-shadow: var(--md-sys-elevation-1) !important;
  }
  .shift-card.absolute-card:last-child {
    margin-bottom: 0 !important;
  }
  
  /* Overnights (P1) on mobile should be fully legible */
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

  /* Swap Cards mobile override */
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
    font-size: 1rem;
  }
  .logo-sub {
    font-size: 0.7rem;
  }
  .logo-mark {
    width: 32px;
    height: 32px;
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

  // Anchor week = Monday of first shift date across all residents
  const allDates = Object.values(DATA.shifts).map(s => s.workDate).sort();
  if (allDates.length) {
    anchorMonday = getMonday(isoToDate(allDates[0]));
  } else {
    anchorMonday = getMonday(new Date());
  }

  document.getElementById('prev-week').addEventListener('click', () => { weekOffset--; renderWeek(); });
  document.getElementById('next-week').addEventListener('click', () => { weekOffset++; renderWeek(); });
  sel.addEventListener('change', e => { cur = e.target.value; weekOffset = 0; render(); });

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
