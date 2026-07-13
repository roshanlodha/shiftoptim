# PGY-1 ED Scheduler — Complete CSP Specification

## 1. Problem Overview

Schedule **15 EM PGY-1 residents** (on-service + off-service) across **14 shift types** at **2 hospitals** (MGH, BWH). Non-EM interns (IM, surgery, anesthesia, etc.) also rotate through the ED working the same shift types — their count is a **hyperparameter** per block. The scheduler assigns only EM PGY1s; non-EM interns' slots are subtracted from total demand.

---

## 2. Staffing Model

### 2.1 Resident Pool (per block)

| Category | Source | Shift behavior |
|---|---|---|
| **MGH on-service** (2–4) | Block schedule CSV | MGH shifts only, 20–22/month |
| **BWH on-service** (1–3) | Block schedule CSV | BWH shifts only, 20–22/month |
| **Flex** (0–1) | Block schedule CSV | **Either** MGH or BWH, fills gaps |
| **Off-service EM PGY1s** (hyperparameter) | Imputed from prior month / configurable | Some EM shifts alongside their rotation |
| **Non-EM interns** (hyperparameter) | Configurable per block | Same shift types as EM, scheduled separately |

### 2.2 Demand Computation

```
EM_PGY1_demand(shift, day) = total_demand(shift, day) − non_EM_slots(shift, day)
```

Total demand is known from ICS. Non-EM contribution is derived from the hyperparameter count. The scheduler only assigns EM PGY1s to `EM_PGY1_demand`.

### 2.3 Off-Service EM Residents

Off-service EM PGY1s (on PICU, Cards, Ultrasound, etc.) still pick up **some** ED shifts. Key differences from on-service:
- Fewer shifts/month (imputed, not 20–22)
- **Can work Wednesday mornings** (don't attend conference)
- Site affiliation TBD per off-service rotation

---

## 3. Residents

**15 EM PGY-1s** from [PGY-1.csv](file:///Users/roshanlodha/Documents/shiftoptim/data/Final%20Intern%20Year%202026-2027%20Block%20Schedules%20-%20PGY-1.csv):

| ID | Name | ID | Name |
|---|---|---|---|
| R1 | Brian | R9 | JP |
| R2 | Ashleigh | R10 | Roshan |
| R3 | Sara | R11 | Mauranda |
| R4 | Emily | R12 | Justin |
| R5 | Isabella | R13 | Jethel |
| R6 | Wendy | R14 | Clifford |
| R7 | Daem | R15 | Andrea |
| R8 | Bailey | | |

---

## 4. Block Schedule

20 half-blocks: Block 4a → Block 13b (Sep 21, 2026 – Jun 27, 2027).

### Role mapping

| CSV value | Role |
|---|---|
| `MGH` | On-service MGH |
| `BWH` | On-service BWH |
| `Flex` | On-service Flex (either site) |
| `OB` | Off-service — auto-assigned Jeopardy (excluded) |
| `Vacation` | Off-service — no shifts |
| Everything else | Off-service — may pick up EM shifts |

### Off-service types (from CSV)

`Anes/MEE`, `BWH MICU`, `CHB`, `Cards`, `MGH MICU`, `OB`, `Ortho`, `PICU`, `Ultrasound`, `Vacation`

### Sample block staffing

| Block | MGH | BWH | Flex | OB | Vacation | Other off-service |
|---|---|---|---|---|---|---|
| 4a | 3 | 2 | 1 (Wendy) | 1 | 2 | 6 |
| 4b | 4 | 2 | 0 | 1 | 2 | 6 |
| 5a | 3 | 2 | 0 | 1 | 1 | 8 |

---

## 5. Shift Catalog (14 types)

### 5.1 MGH Shifts (6 types)

| ID | Name | Time | Duration | Type |
|---|---|---|---|---|
| 0 | AC PGY1 7a-4p | 07:00→16:00 | 9h | Morning |
| 1 | FT 11a-8p | 11:00→20:00 | 9h | Mid |
| 2 | West Jr 10a-8p | 10:00→20:00 | 10h | Mid |
| 3 | AC PGY1 1p-11p | 13:00→23:00 | 10h | Swing |
| 4 | East Jr 1p-11p | 13:00→23:00 | 10h | Swing |
| 5 | East Jr 11p-7a | 23:00→07:00 | 8h | Overnight |

### 5.2 BWH Shifts (8 types)

| ID | Name | Time | Duration | Type | Sched |
|---|---|---|---|---|---|
| 6 | Exe Jr 8a-4p | 08:00→16:00 | 8h | Morning | Weekdays |
| 7 | FF Jr 8a-4p | 08:00→16:00 | 8h | Morning | Weekdays |
| 8 | Exe Jr 12p-12a | 12:00→00:00 | 12h | Mid | Not Wed |
| 9 | Exe Jr 3p-12a | 15:00→00:00 | 9h | Swing | Daily |
| 10 | FF Jr 3p-12a | 15:00→00:00 | 9h | Swing | Weekdays |
| 11 | FF Jr 6p-12a | 18:00→00:00 | 6h | Swing | **Wed only** |
| 12 | FF Jr 7a-4p | 07:00→16:00 | 9h | Morning | **Weekends** |
| 13 | FF Jr 12p-12a | 12:00→00:00 | 12h | Mid | **Weekends** |

> [!NOTE]
> No PGY1 BWH overnight. PGY2 covers BWH nights (10p-8a).

---

## 6. Total Demand Matrix (from ICS, Jul 27 – Aug 23)

These are **total** demand across ALL juniors (EM + non-EM). The variable ranges show week-to-week fluctuation driven by non-EM intern availability.

### 6.1 MGH Total Demand

| Shift | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| AC PGY1 7a-4p | 1–2 | 1–2 | **0** | 1–2 | 1 | 1 | 1 |
| FT 11a-8p | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| West Jr 10a-8p | 1–2 | 1–2 | 1 | 1–3 | 1–2 | 0 | 0 |
| AC PGY1 1p-11p | 2–3 | 2–3 | 1 | 2–4 | 2–3 | 2–3 | 1–3 |
| East Jr 1p-11p | 0–2 | 1–2 | 0 | 1 | 0–2 | 0 | 0–1 |
| East Jr 11p-7a | 2–3 | 2 | 2 | 2 | 2–3 | 2–3 | 2 |

### 6.2 BWH Total Demand

| Shift | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---|---|---|---|---|---|---|
| Exe Jr 8a-4p | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| FF Jr 8a-4p | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| Exe Jr 12p-12a | 1 | 1 | 0 | 1 | 1 | 1–2 | 1 |
| Exe Jr 3p-12a | 1 | 1–2 | 1 | 1–2 | 1–2 | 1 | 1–2 |
| FF Jr 3p-12a | 2–3 | 2 | 0–2 | 2 | 2–3 | 0 | 0 |
| FF Jr 6p-12a | 0 | 0 | 1–2 | 0 | 0 | 0 | 0 |
| FF Jr 7a-4p | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| FF Jr 12p-12a | 0 | 0 | 0 | 0 | 0 | 1–2 | 1 |

### 6.3 Weekly Totals

| | Mon | Tue | Wed | Thu | Fri | Sat | Sun | **Weekly** |
|---|---|---|---|---|---|---|---|---|
| MGH min | 7 | 8 | 5 | 8 | 7 | 6 | 5 | **46** |
| MGH max | 13 | 12 | 5 | 13 | 12 | 8 | 8 | **71** |
| BWH min | 6 | 6 | 4 | 6 | 6 | 4 | 4 | **36** |
| BWH max | 7 | 7 | 7 | 7 | 8 | 6 | 5 | **47** |
| **Total min** | **13** | **14** | **9** | **14** | **13** | **10** | **9** | **82** |
| **Total max** | **20** | **19** | **12** | **20** | **20** | **14** | **13** | **118** |

### 6.4 EM PGY1 Demand Derivation

```
em_demand(shift, weekday) = total_demand(shift, weekday) − non_em_slots(shift, weekday)
```

Non-EM slots are distributed proportionally across shift types based on the non-EM intern hyperparameter and the 20–22 shifts/month per intern constraint. The solver takes EM demand as input after this subtraction.

> [!IMPORTANT]
> **The demand is VARIABLE** — ranges reflect real-world fluctuation in non-EM availability. The solver should use a **fixed demand** (e.g., a configurable baseline derived from the minimum or mode) and treat overflow as non-EM intern territory.

---

## 7. Hard Constraints

### C1: Coverage

For each `(day, shift)` with `em_demand > 0`, assign exactly `em_demand` EM PGY1 residents.

### C2: One Shift Per Day

At most one shift per resident per day.

### C3: Site Exclusivity

- MGH residents → MGH shifts only (IDs 0–5)
- BWH residents → BWH shifts only (IDs 6–13)
- **Flex** → MGH or BWH (either site)
- Off-service EM PGY1s → shifts at their affiliated site (hyperparameter)
- Vacation / OB → 0 EM shifts

### C4: Shift Count

- On-service: 10–11 shifts per 2-week half-block (20–22/month)
- Off-service: configurable per block (imputed from prior month)

### C5: Rest (ACGME, same as PGY4)

Rest ≥ max(8h, shift_duration) between consecutive shifts.

### C6: ACGME Weekly Limits

- ≤60 ED hours in rolling 7-day window
- ≥1 free 24h day per 7-day window

### C7: Wednesday Conference Protection

- `AC PGY1 7a-4p` demand = 0 on Wednesdays (no morning MGH for on-service)
- **Off-service EM PGY1s CAN work BWH morning shifts on Wed** (don't attend conference)
- On-service residents do NOT work any shift starting before ~10am on Wednesday

---

## 8. Soft Constraints / Objective

| Weight | Objective |
|---|---|
| 10,000 | Time-off request violations |
| 200 | Night stretch structure (prefer consecutive runs) |
| 150 | Total shift count evenness |
| 100 | Weekend shift evenness |
| 50 | Night shift evenness (MGH only) |
| 30 | Morning / Swing balance |
| 15 | Site balance (for Flex residents) |

---

## 9. Implementation Blueprint

```
schedulebuilder/
├── pgy4/          # existing — do not modify
└── pgy1/          # new
    ├── __init__.py
    ├── config.py       # shifts, demand, weights, constants
    ├── inputs.py       # parse PGY-1 CSV + SQL roster + hyperparams
    ├── constraints.py  # hard constraints (C1–C7)
    ├── objective.py    # soft constraints / penalties
    ├── solver.py       # CP-SAT model build + solve
    ├── export.py       # grid + summary CSV output
    ├── history.py      # cross-block ledger
    ├── verify.py       # post-solve assertions
    └── schedule.py     # CLI entrypoint
```

### 9.1 `config.py`

```python
MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
WEEKEND_DAYS = frozenset({SAT, SUN})

SHIFTS = {
    0:  {"name": "AC PGY1 7a-4p",   "start": 7,  "end": 16, "duration": 9,  "type": "Morning",   "site": "MGH"},
    1:  {"name": "FT 11a-8p",       "start": 11, "end": 20, "duration": 9,  "type": "Mid",       "site": "MGH"},
    2:  {"name": "West Jr 10a-8p",   "start": 10, "end": 20, "duration": 10, "type": "Mid",       "site": "MGH"},
    3:  {"name": "AC PGY1 1p-11p",   "start": 13, "end": 23, "duration": 10, "type": "Swing",     "site": "MGH"},
    4:  {"name": "East Jr 1p-11p",   "start": 13, "end": 23, "duration": 10, "type": "Swing",     "site": "MGH"},
    5:  {"name": "East Jr 11p-7a",   "start": 23, "end": 7,  "duration": 8,  "type": "Overnight", "site": "MGH"},
    6:  {"name": "Exe Jr 8a-4p",     "start": 8,  "end": 16, "duration": 8,  "type": "Morning",   "site": "BWH"},
    7:  {"name": "FF Jr 8a-4p",      "start": 8,  "end": 16, "duration": 8,  "type": "Morning",   "site": "BWH"},
    8:  {"name": "Exe Jr 12p-12a",   "start": 12, "end": 0,  "duration": 12, "type": "Mid",       "site": "BWH"},
    9:  {"name": "Exe Jr 3p-12a",    "start": 15, "end": 0,  "duration": 9,  "type": "Swing",     "site": "BWH"},
    10: {"name": "FF Jr 3p-12a",     "start": 15, "end": 0,  "duration": 9,  "type": "Swing",     "site": "BWH"},
    11: {"name": "FF Jr 6p-12a",     "start": 18, "end": 0,  "duration": 6,  "type": "Swing",     "site": "BWH"},
    12: {"name": "FF Jr 7a-4p",      "start": 7,  "end": 16, "duration": 9,  "type": "Morning",   "site": "BWH"},
    13: {"name": "FF Jr 12p-12a",    "start": 12, "end": 0,  "duration": 12, "type": "Mid",       "site": "BWH"},
}

NIGHT_SHIFT = 5
MGH_SHIFTS = tuple(s for s in SHIFTS if SHIFTS[s]["site"] == "MGH")
BWH_SHIFTS = tuple(s for s in SHIFTS if SHIFTS[s]["site"] == "BWH")

# Total demand from ICS (MODE values — baseline)
TOTAL_DEMAND = {
    0:  {0: 1, 1: 1, 2: 0, 3: 1, 4: 1, 5: 1, 6: 1},   # AC 7a-4p
    1:  {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1},   # FT
    2:  {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0},   # West Jr
    3:  {0: 2, 1: 2, 2: 1, 3: 2, 4: 2, 5: 2, 6: 1},   # AC 1p-11p
    4:  {0: 1, 1: 1, 2: 0, 3: 1, 4: 1, 5: 0, 6: 0},   # East 1p-11p
    5:  {0: 2, 1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2},   # East 11p-7a (nights)
    6:  {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0},   # Exe 8a-4p
    7:  {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 0, 6: 0},   # FF 8a-4p
    8:  {0: 1, 1: 1, 2: 0, 3: 1, 4: 1, 5: 1, 6: 1},   # Exe 12p-12a
    9:  {0: 1, 1: 1, 2: 1, 3: 1, 4: 1, 5: 1, 6: 1},   # Exe 3p-12a
    10: {0: 2, 1: 2, 2: 1, 3: 2, 4: 2, 5: 0, 6: 0},   # FF 3p-12a
    11: {0: 0, 1: 0, 2: 2, 3: 0, 4: 0, 5: 0, 6: 0},   # FF 6p-12a (Wed)
    12: {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1},   # FF 7a-4p (wknd)
    13: {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 1, 6: 1},   # FF 12p-12a (wknd)
}

SHIFT_MIN_PER_HALF = 10  # on-service
SHIFT_MAX_PER_HALF = 11  # on-service

EM_ROLES = {"MGH", "BWH"}
FLEX_ROLE = "Flex"
NO_SHIFT_ROLES = {"Vacation", "OB"}  # OB = jeopardy only

W_TIMEOFF = 10_000
W_NIGHTS_STRUCTURE = 200
W_TOTAL_SPREAD = 150
BALANCE_WEIGHTS = {
    "Total": 150, "Weekend": 100, "Morning": 30,
    "Swing": 30, "Night": 50, "MGH": 15, "BWH": 15,
}
```

### 9.2 `inputs.py`

```python
def load_block(block_num, non_em_count=0, off_service_shifts_per_half=5):
    """Load one 4-week block.
    
    Args:
        block_num: Block number (4-13)
        non_em_count: Number of non-EM interns available (hyperparameter)
        off_service_shifts_per_half: Shifts per half-block for off-service EM PGY1s
    
    Returns:
        dates, residents, role_on, active_halves, em_demand
    
    Parses PGY-1 CSV for block schedule.
    Loads EM resident list from SQL table.
    Computes em_demand = total_demand − non_EM share.
    """
```

### 9.3 `constraints.py`

```python
def add_coverage_constraints(model, works, dates, residents_by_role, em_demand):
    """Each (day, shift) filled by exactly em_demand residents."""

def add_site_constraints(model, works, dates, residents, role_at):
    """MGH→MGH only, BWH→BWH only, Flex→either, off-service→affiliated site."""

def add_one_shift_per_day(model, works, num_residents, num_days):

def add_rest_constraints(model, works, num_residents, num_days):
    """Rest ≥ max(8h, shift_duration)."""

def add_acgme_weekly_constraints(model, works, num_residents, num_days):
    """≤60h/7d, ≥1 free day/7d."""

def add_shift_count_constraints(model, works, residents, role_at, half_boundaries):
    """On-service: 10-11/half. Off-service: configurable."""

def add_wednesday_protection(model, works, dates, residents, role_at):
    """On-service: no morning shifts Wed. Off-service: CAN work BWH mornings Wed."""
```

### 9.4 Remaining modules

`objective.py`, `solver.py`, `export.py`, `verify.py`, `history.py`, `schedule.py` — same pattern as PGY4 with adjustments for demand-based coverage and multi-role residents.

---

## 10. Key Differences from PGY-4 Scheduler

| Aspect | PGY-4 | PGY-1 |
|---|---|---|
| Residents per block | ~9 | 5–6 on-service + off-service (variable) |
| Shift types | 8 | 14 |
| Sites | MGH + BWH (all work both) | MGH or BWH (site-exclusive) |
| Nights | 1 shift, all residents eligible | 1 shift (East Jr), MGH-only |
| Demand | exactly-1 per required shift | variable demand per shift (1–4) |
| Flex role | ✓ | ✓ (either site) |
| Off-service residents | Not modeled | Modeled (pick up some shifts) |
| Non-EM interns | N/A | Hyperparameter, subtracted from demand |
| Input format | config.ini | CSV + SQL + hyperparams |
| Wednesday protection | No morning except Acute swing | No morning for on-service; off-service CAN |
