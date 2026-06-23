# ShiftMaxxer — Implementation Plan

This document is a complete, step-by-step build specification for the HAEMR
shift-swap optimizer. It is written so that an implementer can build the entire
system in one pass without making design decisions. Follow the phases in order.
Every phase has: inputs, outputs, exact data structures, function signatures,
and pseudocode.

If something is ambiguous, the rule is: **do exactly what is written here.**

---

## 0. Project Layout & Dependencies

Create this directory structure:

```
shiftmaxxer/
├── data/
│   ├── ics/                  # 15 resident .ics files go here
│   └── preferences.csv       # resident preference form export
├── shiftmaxxer/
│   ├── __init__.py
│   ├── config.py             # constants / tunables
│   ├── models.py             # dataclasses (Shift, Resident, Schedule)
│   ├── ingest.py             # Phase 1: parse ics + csv
│   ├── feasibility.py        # Phase 2: ACGME + day-off predicate V()
│   ├── utility.py            # Phase 3: preference utility U()
│   ├── graph.py              # Phase 4: trade graph + bounded cycles
│   ├── optimizer.py          # Phase 5: greedy Pareto resolution loop
│   └── report.py             # Phase 6: human-readable swap log
├── main.py                   # CLI entry point wiring all phases
├── requirements.txt
└── tests/
    └── test_smoke.py
```

`requirements.txt`:

```
icalendar>=5.0
pandas>=2.0
networkx>=3.1
python-dateutil>=2.8
pytest>=7.0
```

Install: `pip install -r requirements.txt`.

Python 3.10+ required (uses `match`, `dataclasses`, `|` unions).

---

## 1. Global Configuration (`config.py`)

Hardcode these. They are the single source of truth for tunables.

```python
from datetime import timedelta

# --- ACGME hard constraints ---
MIN_REST = timedelta(hours=12)      # min gap between consecutive shifts
MAX_CONSECUTIVE_DAYS = 6            # max length of a working streak

# --- Time-of-day classification, keyed on LOCAL start hour [0..23] ---
# Morning:   start hour in [4, 11)
# Swing:     start hour in [11, 18)
# Overnight: start hour in [18, 24) or [0, 4)
MORNING_START, SWING_START, OVERNIGHT_START = 4, 11, 18

# --- Streak preference normalization (max possible |len - target|) ---
# target in [3,6], streak length in [1,6]  => max deviation = 5
STREAK_BETA = 5.0

# --- Location parsing: first N chars of ICS LOCATION field ---
LOC_PREFIX_LEN = 3                  # "MGH Junior" -> "MGH"
VALID_LOCATIONS = {"MGH", "BWH"}

# --- Shifts containing any of these keywords (case-insensitive) in the
#     SUMMARY are "jeopardy"/backup shifts. They ARE swappable like any other
#     shift, but they are location-agnostic and time-agnostic: they carry
#     loc=None and type=None, so they neither help nor hurt the location and
#     time-of-day scores. They DO count as a worked day toward the streak. ---
JEOPARDY_KEYWORDS = ("jeopardy", "backup")

# --- Sentinel values for "no preference" ---
NO_PREF = "ANY"

# --- Optimizer defaults (overridable via CLI) ---
DEFAULT_MAX_TOTAL_SWAPS = 20        # K: total shifts allowed to change hands
DEFAULT_MAX_CYCLE_LENGTH = 2        # n_max: 2 = 1:1 trades, 3 = 3-way. CAP AT 3.

# Timezone: all .ics events use TZID=EDT with a fixed -0400 offset.
LOCAL_TZ = "America/New_York"
```

**Hard rule:** `DEFAULT_MAX_CYCLE_LENGTH` must never exceed 3. The trade-graph
edge model is only mathematically valid for cycle length ≤ 3 (see Phase 4 note).

---

## 2. Data Models (`models.py`)

```python
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional

@dataclass(frozen=True)
class Shift:
    uid: str                  # ICS UID (unique key)
    owner: str                # resident name (filename stem or mapping)
    t_start: datetime         # tz-aware
    t_end: datetime           # tz-aware
    loc: Optional[str]        # "MGH" | "BWH" | None (None = jeopardy/backup)
    type: Optional[str]       # "Morning" | "Swing" | "Overnight" | None
    work_date: date           # calendar date of t_start (LOCAL) -> streak key
    summary: str              # raw SUMMARY text
    is_jeopardy: bool         # True = location/time-agnostic backup shift

# Jeopardy shifts are fully swappable. loc=None and type=None mean they are
# excluded from the location and time satisfaction scores, but their work_date
# still counts toward the consecutive-days streak and toward feasibility.

@dataclass
class Resident:
    name: str
    loc_pref: str             # "MGH" | "BWH" | "ANY"
    loc_weight: float
    type_pref: str            # "Morning" | "Swing" | "Overnight" | "ANY"
    type_weight: float
    days_pref: int            # ideal consecutive days, 3..6
    days_weight: float
    days_off: frozenset[date] # dates that MUST remain shift-free

# A schedule assignment: resident name -> set of Shift uids they own.
# Keep the authoritative store as: dict[str, set[str]] (name -> {uid}).
# Plus a uid -> Shift lookup table.
```

`Schedule` is just two dicts carried together; define a small container:

```python
@dataclass
class Schedule:
    assignment: dict[str, set[str]]      # resident name -> set of shift uids
    shifts: dict[str, Shift]             # uid -> Shift
    residents: dict[str, Resident]       # name -> Resident

    def shifts_of(self, name: str) -> list[Shift]:
        return [self.shifts[u] for u in self.assignment[name]]
```

---

## 3. Phase 1 — Ingestion (`ingest.py`)

### 3.1 Parse the ICS files

Input: a directory of 15 `.ics` files. Resident name = file stem unless a
mapping file exists; use the file stem for now.

ICS facts (verified against the sample file):
- Each shift is a `VEVENT`.
- `DTSTART;TZID=EDT:20260709T110000` and `DTEND;TZID=EDT:...` give start/end.
- `LOCATION:` looks like `MGH Junior`, `BWH Junior`. Take first 3 chars.
- `SUMMARY:` looks like `MGH Jr. - FT 11a-8p`. Used only for the jeopardy keyword
  check; do NOT parse times out of it (use DTSTART/DTEND).
- Overnight shifts cross midnight: `DTSTART ...T230000`, `DTEND` next day.
- The "Jeopardy" event spans ~24h — it stays swappable, but is tagged
  `is_jeopardy=True` with `loc=None`/`type=None` (counts toward streak only).

```python
from icalendar import Calendar
from dateutil import tz
from datetime import datetime
from pathlib import Path
from .config import (LOC_PREFIX_LEN, VALID_LOCATIONS, JEOPARDY_KEYWORDS,
                     MORNING_START, SWING_START, OVERNIGHT_START, LOCAL_TZ)
from .models import Shift

LOCAL = tz.gettz(LOCAL_TZ)

def classify_type(start: datetime) -> str:
    h = start.hour
    if MORNING_START <= h < SWING_START:
        return "Morning"
    if SWING_START <= h < OVERNIGHT_START:
        return "Swing"
    return "Overnight"   # h >= 18 or h < 4

def parse_location(raw: str) -> str:
    code = (raw or "").strip()[:LOC_PREFIX_LEN].upper()
    if code not in VALID_LOCATIONS:
        raise ValueError(f"Unknown location prefix: {raw!r}")
    return code

def is_jeopardy(summary: str) -> bool:
    s = (summary or "").lower()
    return any(k in s for k in JEOPARDY_KEYWORDS)

def parse_ics_file(path: Path, owner: str) -> list[Shift]:
    cal = Calendar.from_ical(path.read_bytes())
    shifts = []
    for comp in cal.walk("VEVENT"):
        start = comp.decoded("DTSTART")
        end = comp.decoded("DTEND")
        # Ensure tz-aware in LOCAL; ICS uses fixed -0400 (EDT).
        start = start.astimezone(LOCAL) if start.tzinfo else start.replace(tzinfo=LOCAL)
        end = end.astimezone(LOCAL) if end.tzinfo else end.replace(tzinfo=LOCAL)
        summary = str(comp.get("SUMMARY", ""))
        jeop = is_jeopardy(summary)
        shifts.append(Shift(
            uid=str(comp.get("UID")),
            owner=owner,
            t_start=start,
            t_end=end,
            # Jeopardy shifts are location/time-agnostic -> None on both.
            loc=None if jeop else parse_location(str(comp.get("LOCATION", ""))),
            type=None if jeop else classify_type(start),
            work_date=start.date(),
            summary=summary,
            is_jeopardy=jeop,
        ))
    return shifts

def load_all_ics(ics_dir: Path) -> list[Shift]:
    out = []
    for p in sorted(ics_dir.glob("*.ics")):
        out.extend(parse_ics_file(p, owner=p.stem))
    return out
```

### 3.2 Parse the preferences CSV

CSV columns (exact):
`resident, location_pref, location_weight, time_pref, time_weight, days_pref, days_weight, days_off`

- `location_pref`: `MGH` / `BWH` / anything else → `ANY`.
- `time_pref`: `Morning` / `Swing` / `Overnight` / else → `ANY`.
- `days_pref`: int, clamp to [3,6].
- `days_off`: a string like `"07/04/2026", "07/05/2026"` (quoted, comma-sep).
  Parse to a set of `date`. Empty → empty set.
- **Weight normalization:** after reading raw weights, normalize each resident's
  three weights to sum to 1.0. If all three are 0, set all to 0 (resident is
  indifferent; utility will be constant). Treat a weight as 0 when its pref is `ANY`.

```python
import pandas as pd
import re
from datetime import datetime
from .config import NO_PREF
from .models import Resident

def _parse_days_off(cell: str) -> frozenset:
    if not isinstance(cell, str) or not cell.strip():
        return frozenset()
    dates = re.findall(r"(\d{2}/\d{2}/\d{4})", cell)
    return frozenset(datetime.strptime(d, "%m/%d/%Y").date() for d in dates)

def _norm_pref(value: str, allowed: set[str]) -> str:
    v = str(value).strip().upper()
    table = {a.upper(): a for a in allowed}
    return table.get(v, NO_PREF)

def load_preferences(csv_path) -> dict[str, Resident]:
    df = pd.read_csv(csv_path)
    residents = {}
    for _, row in df.iterrows():
        loc_pref = _norm_pref(row["location_pref"], {"MGH", "BWH"})
        type_pref = _norm_pref(row["time_pref"], {"Morning", "Swing", "Overnight"})

        # Zero-out weights whose preference is ANY.
        w_loc = 0.0 if loc_pref == NO_PREF else float(row["location_weight"])
        w_typ = 0.0 if type_pref == NO_PREF else float(row["time_weight"])
        w_str = float(row["days_weight"])

        total = w_loc + w_typ + w_str
        if total > 0:
            w_loc, w_typ, w_str = w_loc/total, w_typ/total, w_str/total

        residents[str(row["resident"])] = Resident(
            name=str(row["resident"]),
            loc_pref=loc_pref, loc_weight=w_loc,
            type_pref=type_pref, type_weight=w_typ,
            days_pref=int(max(3, min(6, int(row["days_pref"])))),
            days_weight=w_str,
            days_off=_parse_days_off(row["days_off"]),
        )
    return residents
```

### 3.3 Assemble the `Schedule`

```python
def build_schedule(ics_dir, csv_path) -> "Schedule":
    shifts_list = load_all_ics(ics_dir)
    residents = load_preferences(csv_path)
    shifts = {s.uid: s for s in shifts_list}
    assignment = {name: set() for name in residents}
    for s in shifts_list:
        assignment.setdefault(s.owner, set()).add(s.uid)
    # Every ics owner must exist in preferences; if not, create indifferent resident.
    for owner in assignment:
        if owner not in residents:
            residents[owner] = Resident(owner, "ANY",0, "ANY",0, 4,0, frozenset())
    return Schedule(assignment=assignment, shifts=shifts, residents=residents)
```

**Phase 1 output:** a fully populated `Schedule`.

---

## 4. Phase 2 — Feasibility Predicate `V()` (`feasibility.py`)

A proposed set of shifts for one resident is **valid** iff all three hold.
Operate on a `list[Shift]` (the proposed shifts of one resident) plus that
resident's `days_off`.

```python
from datetime import date
from .config import MIN_REST, MAX_CONSECUTIVE_DAYS
from .models import Shift

def _streaks(work_dates: set[date]) -> list[int]:
    """Return lengths of maximal consecutive-day runs."""
    if not work_dates:
        return []
    ordered = sorted(work_dates)
    lengths, run = [], 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            run += 1
        else:
            lengths.append(run); run = 1
    lengths.append(run)
    return lengths

def is_valid(shifts: list[Shift], days_off: frozenset[date]) -> bool:
    if not shifts:
        return True

    # (c) Day-off: no shift may fall on a declared day off.
    for s in shifts:
        if s.work_date in days_off:
            return False

    ordered = sorted(shifts, key=lambda s: s.t_start)

    # (a) Minimum rest between chronologically adjacent shifts.
    #     (Also forbids overlap, since gap >= 12h > 0.)
    for a, b in zip(ordered, ordered[1:]):
        if b.t_start - a.t_end < MIN_REST:
            return False

    # (b) Maximum consecutive working days.
    if any(L > MAX_CONSECUTIVE_DAYS for L in _streaks({s.work_date for s in shifts})):
        return False

    return True
```

**Phase 2 output:** `is_valid(shifts, days_off) -> bool`.

---

## 5. Phase 3 — Utility Function `U()` (`utility.py`)

All φ are in [0,1]. `U` is the normalized weighted sum (weights already sum to
≤1 from Phase 1). Empty schedule → utility 0 (and φ guards avoid div-by-zero).

```python
from .config import STREAK_BETA
from .feasibility import _streaks
from .models import Shift, Resident

def phi_loc(shifts: list[Shift], r: Resident) -> float:
    # Jeopardy shifts (loc is None) are location-agnostic: excluded from both
    # numerator and denominator so they neither help nor hurt this score.
    located = [s for s in shifts if s.loc is not None]
    if r.loc_pref == "ANY" or not located:
        return 1.0
    return sum(1 for s in located if s.loc == r.loc_pref) / len(located)

def phi_type(shifts: list[Shift], r: Resident) -> float:
    # Jeopardy shifts (type is None) are time-agnostic: excluded from this score.
    typed = [s for s in shifts if s.type is not None]
    if r.type_pref == "ANY" or not typed:
        return 1.0
    return sum(1 for s in typed if s.type == r.type_pref) / len(typed)

def phi_str(shifts: list[Shift], r: Resident) -> float:
    runs = _streaks({s.work_date for s in shifts})
    if not runs:
        return 1.0
    mean_dev = sum(abs(L - r.days_pref) for L in runs) / len(runs)
    return max(0.0, 1.0 - mean_dev / STREAK_BETA)

def utility(shifts: list[Shift], r: Resident) -> float:
    return (r.loc_weight  * phi_loc(shifts, r)
          + r.type_weight * phi_type(shifts, r)
          + r.days_weight * phi_str(shifts, r))
```

**Phase 3 output:** `utility(shifts, resident) -> float`.

---

## 6. Phase 4 — Trade Graph & Bounded Cycles (`graph.py`)

### 6.1 Directed edge definition

Nodes = shift uids. Edge `(u → v)` means: the owner of `u` gives up `u` and
receives `v`. It exists iff, for owner `i` of `u` (where `v` is owned by `j ≠ i`):

1. `v.work_date` is NOT in `i.days_off` (explicit day-off rejection),
2. the post-swap set `A_i' = (A_i \ {u}) ∪ {v}` passes `is_valid`,
3. `utility(A_i') >= utility(A_i)` (resident `i` is not made worse off).

All shifts are swappable, including jeopardy/backup shifts. A jeopardy shift
simply carries `loc=None`/`type=None`, so trading it in or out only affects the
streak score and feasibility, never the location/time scores.

```python
import networkx as nx
from .feasibility import is_valid
from .utility import utility
from .models import Schedule

def build_trade_graph(sched: Schedule) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(sched.shifts.keys())

    # Precompute each resident's current shifts and baseline utility.
    base_shifts = {n: sched.shifts_of(n) for n in sched.assignment}
    base_util   = {n: utility(base_shifts[n], sched.residents[n])
                   for n in sched.assignment}

    shifts = sched.shifts
    for u, su in shifts.items():
        i = su.owner; ri = sched.residents[i]
        for v, sv in shifts.items():
            if sv.owner == i:                      # can't trade with yourself
                continue
            if sv.work_date in ri.days_off:        # explicit day-off rejection
                continue
            proposed = [s for s in base_shifts[i] if s.uid != u] + [sv]
            if not is_valid(proposed, ri.days_off):
                continue
            if utility(proposed, ri) >= base_util[i]:
                G.add_edge(u, v)
    return G
```

### 6.2 Bounded cycle enumeration

```python
def find_cycles(G: nx.DiGraph, n_max: int) -> list[list[str]]:
    assert n_max <= 3, "edge model only valid for cycle length <= 3"
    if n_max == 2:
        # Fast path: mutual edges only.
        seen, out = set(), []
        for u, v in G.edges():
            if G.has_edge(v, u) and (v, u) not in seen:
                seen.add((u, v))
                out.append([u, v])
        return out
    return [c for c in nx.simple_cycles(G, length_bound=n_max) if len(c) >= 2]
```

**Phase 4 note (do not remove):** For cycle length ≤ 3 every node has a distinct
owner, so the per-edge checks above fully capture feasibility and utility. For
length ≥ 4 a resident can appear twice and the per-edge checks are insufficient —
that is why `n_max` is capped at 3.

**Phase 4 output:** `build_trade_graph(sched)` and `find_cycles(G, n_max)`.

---

## 7. Phase 5 — Greedy Pareto Resolution (`optimizer.py`)

For each candidate cycle, recompute the full post-trade schedule for every
involved resident (defensive — exact for n_max ≤ 3), verify strict Pareto
improvement, score it, then greedily apply the best within the swap budget `K`.

```python
from dataclasses import dataclass
from .graph import build_trade_graph, find_cycles
from .utility import utility
from .feasibility import is_valid
from .models import Schedule

@dataclass
class CycleResult:
    cycle: list[str]                 # ordered shift uids
    deltas: dict[str, float]         # resident -> delta utility
    total_delta: float
    moves: list[tuple[str, str, str]]  # (giver, shift_given, shift_received)

def _apply_map(cycle: list[str], sched: Schedule):
    """Cycle [u0,u1,...,uk]: owner of u_t gives u_t, receives u_{t+1 mod k}."""
    k = len(cycle)
    moves = []
    for t in range(k):
        u = cycle[t]; v = cycle[(t + 1) % k]
        giver = sched.shifts[u].owner
        moves.append((giver, u, v))
    return moves

def evaluate_cycle(cycle: list[str], sched: Schedule) -> CycleResult | None:
    moves = _apply_map(cycle, sched)
    # Build proposed shift lists per involved resident.
    involved = {}
    for giver, u, v in moves:
        cur = involved.setdefault(giver, set(s.uid for s in sched.shifts_of(giver)))
        cur.discard(u); cur.add(v)

    deltas = {}
    for name, uids in involved.items():
        r = sched.residents[name]
        proposed = [sched.shifts[x] for x in uids]
        if not is_valid(proposed, r.days_off):
            return None
        before = utility(sched.shifts_of(name), r)
        after = utility(proposed, r)
        if after < before - 1e-9:                  # Pareto: nobody worse
            return None
        deltas[name] = after - before

    if not any(d > 1e-9 for d in deltas.values()):  # at least one strictly better
        return None
    return CycleResult(cycle, deltas, sum(deltas.values()), moves)

def apply_cycle(result: CycleResult, sched: Schedule):
    for giver, u, v in result.moves:
        sched.assignment[giver].discard(u)
    for giver, u, v in result.moves:
        sched.assignment[giver].add(v)
        sched.shifts[v] = sched.shifts[v].__class__(  # reassign owner
            **{**sched.shifts[v].__dict__, "owner": giver})

def optimize(sched: Schedule, K: int, n_max: int) -> list[CycleResult]:
    executed, log = 0, []
    while executed < K:
        G = build_trade_graph(sched)
        candidates = []
        for cyc in find_cycles(G, n_max):
            res = evaluate_cycle(cyc, sched)
            if res and (executed + len(res.cycle)) <= K:
                candidates.append(res)
        if not candidates:
            break
        candidates.sort(key=lambda r: r.total_delta, reverse=True)
        best = candidates[0]
        apply_cycle(best, sched)
        executed += len(best.cycle)
        log.append(best)
    return log
```

**Note on `apply_cycle`:** `Shift` is frozen, so owner reassignment rebuilds the
dataclass. If you prefer, make `Shift.owner` non-frozen instead; either is fine.
Make sure the `uid → Shift` table and the `assignment` sets stay consistent.

**Phase 5 output:** `optimize(sched, K, n_max) -> list[CycleResult]`.

---

## 8. Phase 6 — Reporting (`report.py`)

```python
def format_log(log) -> str:
    if not log:
        return "No beneficial, ACGME-valid, Pareto-improving swaps found."
    lines = []
    for i, res in enumerate(log, 1):
        lines.append(f"=== Swap {i} (total happiness +{res.total_delta:.3f}) ===")
        for giver, u, v in res.moves:
            lines.append(f"  {giver}: gives {u} -> receives {v} "
                         f"(Δ happiness {res.deltas.get(giver, 0):+.3f})")
    return "\n".join(lines)
```

For a richer log, look up `sched.shifts[uid].summary` to print human shift names
instead of uids.

---

## 9. Entry Point (`main.py`)

```python
import argparse
from pathlib import Path
from shiftmaxxer.ingest import build_schedule
from shiftmaxxer.optimizer import optimize
from shiftmaxxer.report import format_log
from shiftmaxxer.config import DEFAULT_MAX_TOTAL_SWAPS, DEFAULT_MAX_CYCLE_LENGTH

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ics", default="data/ics")
    ap.add_argument("--prefs", default="data/preferences.csv")
    ap.add_argument("-K", "--max-swaps", type=int, default=DEFAULT_MAX_TOTAL_SWAPS)
    ap.add_argument("-n", "--max-cycle", type=int, default=DEFAULT_MAX_CYCLE_LENGTH)
    args = ap.parse_args()
    assert args.max_cycle <= 3, "max cycle length capped at 3"

    sched = build_schedule(Path(args.ics), Path(args.prefs))
    log = optimize(sched, K=args.max_swaps, n_max=args.max_cycle)
    print(format_log(log))

if __name__ == "__main__":
    main()
```

Run: `python main.py --ics data/ics --prefs data/preferences.csv -K 20 -n 2`

---

## 10. Smoke Test (`tests/test_smoke.py`)

```python
from shiftmaxxer.feasibility import is_valid, _streaks
from datetime import date

def test_streaks():
    assert _streaks({date(2026,7,1), date(2026,7,2), date(2026,7,4)}) == [2, 1]

def test_max_consecutive():
    # 7 consecutive days must be invalid; build dummy shifts accordingly.
    ...  # implementer fills using Shift fixtures
```

At minimum, assert: (a) a 7-day streak fails `is_valid`; (b) a shift on a
declared day-off fails; (c) two shifts 6h apart fail rest; (d) `optimize` on
a tiny 2-resident fixture produces a mutually beneficial 1:1 swap.

---

## 11. Implementation Checklist (do in this order)

1. [ ] `config.py` — paste constants.
2. [ ] `models.py` — dataclasses.
3. [ ] `ingest.py` — ICS + CSV parsing → `Schedule`. Verify against sample ics.
4. [ ] `feasibility.py` — `is_valid` + `_streaks`.
5. [ ] `utility.py` — φ functions + `utility`.
6. [ ] `graph.py` — `build_trade_graph` + `find_cycles`.
7. [ ] `optimizer.py` — `evaluate_cycle`, `apply_cycle`, `optimize`.
8. [ ] `report.py` + `main.py`.
9. [ ] `tests/test_smoke.py` — run `pytest`.
10. [ ] Drop the 15 ics files in `data/ics/`, the CSV in `data/`, run `main.py`.

Done.
