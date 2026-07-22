# ED Block Schedule Builder & Optimizer

Complete resident shift scheduling and post-solve trade optimization system for emergency medicine residents across MGH and BWH.

The system combines:
1. **Phase 1 (Initial Solver):** Google OR-Tools CP-SAT Constraint Satisfaction Programming (CSP) solver that builds legal, ACGME-compliant, coverage-fulfilled block schedules from scratch.
2. **Phase 2 (Block Optimizer):** Directed trade graph Pareto exchange algorithm ([algorithm.MD](file:///Users/roshanlodha/Documents/shiftoptim/algorithm.MD)) that optimizes resident streak preferences ("Frequent Breaks" vs "Longer Breaks") on solved blocks.

---

## Quick start (web app)

```bash
env/bin/python -m webapp.seed          # first time only
env/bin/python -m webapp.wsgi          # http://127.0.0.1:5000
```

Admin (`jaba` / `thehutt`) runs the solver, reviews drafts, optimizes resident streak preferences, and publishes.
Residents view schedules, set break preferences in Settings ("Frequent Breaks" vs "Longer Breaks"), request time off, and manage trade requests.
All data lives in `data/shiftoptim.db` (SQLite).

---

## Architecture & Algorithm

See full mathematical formulation and guarantees in [algorithm.MD](file:///Users/roshanlodha/Documents/shiftoptim/algorithm.MD).

### Phase 1: Initial CP-SAT CSP Solver
- **Engine:** [OR-Tools CP-SAT](https://developers.google.com/optimization/reference/python/sat/python/cp_model)
- **Decision variables:** Boolean `works[r, d, s]` per resident $r$, day $d$, shift $s$.
- **Hard constraints:** Coverage, availability, minimum rest ($\ge 12$h), rolling 7-day ACGME limits ($\le 60$h ED time, $\ge 1$ free 24h day/week), half-block minimum shifts.
- **Soft objectives:** Minimizes weighted penalties for time-off requests, night structure, and cumulative shift-type evenness (Laura's rule across Morning, Swing, Night, MGH, BWH, Weekend).

### Phase 2: Post-Solve Pareto Graph Optimizer (`shiftswap/shiftoptim`)
- Accepts a solved draft schedule $A^{(0)}$.
- Evaluates resident break preferences:
  - **Frequent Breaks:** Target streak length $p_{\text{str}} = 2$.
  - **Longer Breaks:** Target streak length $p_{\text{str}} = 6$ (up to ACGME max 6 days).
- Runs **Complete Mode** trade graph cycle search (`optimize_complete`) within the block date window.
- Guarantees strict total utility gain, weak Pareto improvement ($U_i(A_i') \ge U_i(A_i)$ for all residents), and zero ACGME violations.

---

## Layout

```
algorithm.MD              Full mathematical specification of CSP solver & Pareto trade graph algorithm
webapp/                    Flask web application, SQLite schema, seed script
  app.py                   Web routes (admin solver, draft review, block optimizer, settings, trades)
  bridge.py                DB ↔ CP-SAT solver bridge & shiftswap optimizer bridge
  schema.sql               SQLite schema (users, residents, rotations, runs, assignments, trade_requests, settings)
  seed.py                  Database seed script
schedulebuilder/pgy4/      CP-SAT solver engine
  config.py                Shift catalog, roles, weights, constants
  constraints.py           Hard constraints (coverage, rest, ACGME, minimums)
  objective.py             Soft penalties (time-off, nights structure, evenness)
  solver.py                Model assembly and solve loop
shiftswap/                 Shift trade graph optimizer core (`shiftoptim` library)
  shiftoptim/optimizer.py  Pareto cycle detection & trade execution (`optimize_complete`, `optimize_limited`)
  shiftoptim/models.py     Shift, Resident, and Schedule domain models
  shiftoptim/utility.py    Streak satisfaction $\phi_{\text{str}}$ and utility functions
```

---

## Notes for the paper

- **System Type:** End-to-end multi-site physician scheduling and post-solve preference optimization.
- **Phase 1 (CSP):** OR-Tools CP-SAT formulation solving multi-role, multi-site coverage with rolling ACGME bounds and rate-scaled Chebyshev fairness.
- **Phase 2 (Graph Exchange):** Directed trade graph cycle enumeration and execution guaranteeing Pareto improvements on resident break/streak preferences.
