# ED Block Schedule Builder

CP-SAT schedule optimizer for **PGY-4** emergency medicine residents across MGH and BWH.

## Quick start (web app)

```bash
env/bin/python -m webapp.seed          # first time only
env/bin/python -m webapp.wsgi          # http://127.0.0.1:5000
```

Admin (`jaba` / `thehutt`) runs the solver, reviews drafts, and publishes.
Residents view schedules, request time off, and see cumulative shift history.
All data lives in `data/shiftoptim.db` (SQLite).

## CLI (legacy)

Edit `config.ini` (block dates, rosters, time off), then:

```bash
env/bin/python -m schedulebuilder.pgy4.schedule 4 5
```

Outputs land in `output/`. Cross-block balance carries in-memory when multiple
blocks are solved in one invocation.

---

## Solver overview

**Engine:** [OR-Tools CP-SAT](https://developers.google.com/optimization/reference/python/sat/python/cp_model)
(Google constraint-programming / SAT hybrid).
Time limit: 60 s, 2 worker threads.

### Decision variables

One Boolean variable `works[r, d, s]` per (resident `r`, day `d`, shift `s`).
A solution is a 0/1 assignment over this tensor.

### Shift catalog

| ID | Name | Hours | Type | Site | Required days |
|----|------|-------|------|------|---------------|
| 0 | Acute 7a–4p | 9 h | Morning | MGH | Mon–Tue, Thu–Sun |
| 1 | FF 7a–4p | 9 h | Morning | BWH | Mon–Tue, Thu–Sun |
| 2 | Fast Track 2p–11p | 9 h | Swing | MGH | Thu only |
| 3 | FF 3p–12a | 9 h | Swing | BWH | Mon–Tue, Thu–Sun |
| 4 | Peds Snr 3p–11p | 8 h | Swing | MGH | Mon, Tue, Fri |
| 5 | Acute 3p–12a | 9 h | Swing | MGH | Every day |
| 6 | Acute 11p–8a | 9 h | Overnight | MGH | Every day |
| 7 | FF/Ex Swing 3p–12a *(relief)* | 9 h | Swing | BWH | Optional |

Wednesday shifts 0, 1, 3 are **not staffed** (didactics). Shift 5 on Wednesday
is encoded as 3p–12a but the first 3 hours are informally skipped.

### Resident roles

| Role | Meaning |
|------|---------|
| `MGB` | Standard day/swing eligible |
| `MGB Nights` | Restricted to overnight (shift 6) only |
| `Flex` | Day/swing eligible; rewarded for covering weekend overnights |

Residents not assigned any active role on a given day are blocked from all shifts.

### Hard constraints (`constraints.py`)

1. **Coverage** — required shifts get *exactly one* resident; relief shift gets *at most one*; all other (shift, day) combos forced to zero.
2. **Availability** — at most one shift per resident per day; inactive days fully blocked; `MGB Nights` residents locked to overnight.
3. **Rest** — gap between consecutive shifts ≥ max(8 h, shift duration). Overnight shifts accounted for midnight-crossing.
4. **ACGME weekly** — rolling 7-day windows: ≤ 60 ED hours; ≥ 1 completely free 24 h day (night-recovery days excluded).
5. **Minimum shifts** — each resident works ≥ 8 shifts per active 2-week half-block (≥ 16 for a full block).

### Soft constraints / objective (`objective.py`)

The solver **minimizes a weighted sum of penalties**:

| Penalty | Weight | Purpose |
|---------|--------|---------|
| Time-off violation | 10 000 | Near-hard: respect requested days off |
| Nights structure | 200 | `MGB Nights` residents avoid weekend overnights |
| Flex night reward | −100 | `Flex` residents incentivized onto weekend overnights |
| Non-Flex overnight | 30 | Mild deterrent for `MGB` residents taking overnights |
| Relief shift use | 50 | Suppress the FF/Ex relief shift |
| Relief shift on weekends | +20 extra | Extra deterrent for weekend relief |
| Evenness spread (per category) | see below | "Laura's rule" — spread cumulative load evenly |

#### Evenness objective (Laura's rule)

For each *balance category* (Morning, Swing, Night, MGH, BWH, Pedi, FT, Weekend),
the solver minimizes `max_adjusted − min_adjusted` across day-eligible residents,
where:

```
adjusted[r] = floor(cumulative_count[r] * H_max / halves_worked[r])
```

This normalizes by half-blocks worked so residents who joined mid-year are not
penalized for lower raw totals. Integer arithmetic avoids floating-point in the
CP model (`AddDivisionEquality`).

**Category weights** (higher = optimized first):

| Category | Weight |
|----------|--------|
| Weekend | 100 |
| Morning | 30 |
| Swing | 30 |
| Night | 20 |
| MGH | 15 |
| BWH | 15 |
| Pedi | 8 |
| FT | 8 |

Weights are admin-configurable at runtime via the web settings page and stored
in the `settings` table; the solver reads them fresh each run.

### Cross-block history

Published runs accumulate shift counts and half-blocks worked per resident in
the `assignments` table. The bridge layer (`webapp/bridge.py`) queries this
history and feeds it as carry-forward into the next block's evenness objective,
so fairness is maintained across the academic year, not just within a single block.

### Post-solve trade validation (`bridge.py`)

After publishing, residents may request shift swaps. Each candidate swap is
validated against the same ACGME hard constraints (rest, 60 h/week, 1 free
day/week) before being offered to the target resident and escalated to admin.

---

## Layout

```
webapp/                    Flask app, SQLite schema, seed data
  app.py                   Routes: admin run→review→publish; resident views; trade requests
  bridge.py                DB ↔ solver bridge; post-publish ACGME swap validation
  schema.sql               SQLite schema (users, residents, rotations, runs, assignments, …)
  seed.py                  Dev seed data
schedulebuilder/pgy4/      CP-SAT solver
  config.py                Shift catalog, roles, weights, constants
  constraints.py           Hard constraints (coverage, rest, ACGME, minimums)
  objective.py             Soft penalties (time-off, nights structure, evenness)
  solver.py                Model assembly and solve loop
  inputs.py                CLI config.ini loader
  export.py                CSV/Excel output (CLI)
  history.py               Cross-block carry-forward helpers
  verify.py                Post-solve constraint checks
shiftswap/                 Archived shift-trade optimizer (legacy)
config.ini                 CLI input (block dates, rosters, time off)
```

---

## Notes for the paper

- **Problem class:** Multi-shift, multi-site, multi-role physician rostering
  with hard regulatory constraints (ACGME) and soft fairness objectives.
- **Model size:** ~`num_residents × num_days × num_shifts` Boolean variables
  (typically ~8 residents × 28 days × 8 shifts ≈ 1 800 Booleans per block).
- **Feasibility vs. optimality:** Time-off violations are soft (weight 10 000)
  rather than hard, ensuring the model always returns a feasible schedule even
  under tight constraints; violations are surfaced as warnings.
- **Fairness metric:** Rate-scaled spread (max − min of adjusted counts) is a
  linear proxy for Chebyshev fairness that CP-SAT handles natively via
  `AddMaxEquality` / `AddMinEquality`.
- **Practical deployment:** Flask + SQLite; admin review gate before publish;
  resident-facing trade workflow with re-validation against ACGME constraints.
