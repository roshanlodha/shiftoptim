"""Soft constraints (weighted objective) for the PGY-1 CP-SAT schedule model."""

from .config import (
    BALANCE_CATEGORIES,
    BALANCE_WEIGHTS,
    NIGHT_SHIFT,
    SHIFTS,
    W_NIGHTS_STRUCTURE,
    W_TIMEOFF,
    WEEKEND_DAYS,
)
from .history import empty_entry


def add_timeoff_penalties(model, works, dates, residents, timeoff, penalties):
    """Time-off requests are soft (heavily penalized).
    A shift touches a requested day if it starts on it or if a previous day's
    overnight shift spills into it.
    """
    violations = []
    for r, name in enumerate(residents):
        for start, end in timeoff.get(name, []):
            for d, date in enumerate(dates):
                if not (start <= date <= end):
                    continue
                # Resident scheduled on the requested day
                for s in SHIFTS:
                    v = model.NewBoolVar(f"timeoff_violation_r{r}_d{d}_s{s}")
                    model.Add(v == works[(r, d, s)])
                    penalties.append(v * W_TIMEOFF)
                    violations.append((name, date, s, v))
                # Spilled over overnight from previous day
                if d > 0:
                    v = model.NewBoolVar(f"timeoff_violation_prevnight_r{r}_d{d}")
                    model.Add(v == works[(r, d - 1, NIGHT_SHIFT)])
                    penalties.append(v * W_TIMEOFF)
                    violations.append((name, date, NIGHT_SHIFT, v))
    return violations


def add_night_structure_penalties(model, works, dates, residents, penalties):
    """Prefer nights in runs. Penalize isolated single night shifts."""
    num_days = len(dates)
    for r in range(len(residents)):
        for d in range(num_days):
            # Check if d is isolated
            isolated = model.NewBoolVar(f"isolated_night_r{r}_d{d}")
            
            # Conditions for isolation: works tonight AND didn't work last night AND won't work tomorrow night
            conditions = [works[(r, d, NIGHT_SHIFT)]]
            if d > 0:
                conditions.append(works[(r, d - 1, NIGHT_SHIFT)].Not())
            if d < num_days - 1:
                conditions.append(works[(r, d + 1, NIGHT_SHIFT)].Not())
                
            model.AddBoolAnd(conditions).OnlyEnforceIf(isolated)
            model.Add(isolated == 0).OnlyEnforceIf(works[(r, d, NIGHT_SHIFT)].Not())
            if d > 0:
                model.Add(isolated == 0).OnlyEnforceIf(works[(r, d - 1, NIGHT_SHIFT)])
            if d < num_days - 1:
                model.Add(isolated == 0).OnlyEnforceIf(works[(r, d + 1, NIGHT_SHIFT)])
                
            penalties.append(isolated * W_NIGHTS_STRUCTURE)


def add_evenness_penalties(model, works, dates, residents, role_on, history, active_halves,
                           penalties, balance_weights=None):
    """Laura's rule: spread cumulative counts per half-block worked as evenly
    as possible across residents per wellness category.
    """
    if balance_weights is None:
        balance_weights = BALANCE_WEIGHTS

    num_days = len(dates)
    # Include all active residents for evenness
    day_eligible = list(range(len(residents)))
    if len(day_eligible) < 2:
        return

    halves_by_r = {
        r: max(1, history.get(residents[r], empty_entry())["half_blocks_worked"]
               + active_halves.get(residents[r], 0))
        for r in day_eligible
    }
    h_max = max(halves_by_r.values())
    cum_cap = 500
    adj_cap = cum_cap * h_max

    counts_by_category = {cat: {} for cat in BALANCE_CATEGORIES}
    counts_by_category["Total"] = {}
    counts_by_category["Weekend"] = {}

    for r in day_eligible:
        name = residents[r]
        entry = history.get(name, empty_entry())
        carry = entry["shifts"]
        h_r = halves_by_r[r]

        for category, shift_ids in BALANCE_CATEGORIES.items():
            count_this_block = sum(
                works[(r, d, s)] for d in range(num_days) for s in shift_ids
            )
            carry_count = sum(carry.get(SHIFTS[s]["name"], 0) for s in shift_ids)
            cum = model.NewIntVar(0, cum_cap, f"cum_{category}_r{r}")
            model.Add(cum == count_this_block + carry_count)
            num = model.NewIntVar(0, adj_cap, f"num_{category}_r{r}")
            model.Add(num == cum * h_max)
            adj = model.NewIntVar(0, adj_cap, f"adj_{category}_r{r}")
            model.AddDivisionEquality(adj, num, h_r)
            counts_by_category[category][r] = adj

        # Weekend shifts
        weekend_days = [d for d, date in enumerate(dates) if date.weekday() in WEEKEND_DAYS]
        weekend_this_block = sum(
            works[(r, d, s)] for d in weekend_days for s in SHIFTS
        )
        cum_weekend = model.NewIntVar(0, cum_cap, f"cum_Weekend_r{r}")
        model.Add(cum_weekend == weekend_this_block + entry.get("weekend", 0))
        num_w = model.NewIntVar(0, adj_cap, f"num_Weekend_r{r}")
        model.Add(num_w == cum_weekend * h_max)
        adj_w = model.NewIntVar(0, adj_cap, f"adj_Weekend_r{r}")
        model.AddDivisionEquality(adj_w, num_w, h_r)
        counts_by_category["Weekend"][r] = adj_w

        # Total shifts
        total_this_block = sum(works[(r, d, s)] for d in range(num_days) for s in SHIFTS)
        carry_total = sum(carry.get(SHIFTS[s]["name"], 0) for s in SHIFTS)
        cum_total = model.NewIntVar(0, cum_cap, f"cum_Total_r{r}")
        model.Add(cum_total == total_this_block + carry_total)
        num_total = model.NewIntVar(0, adj_cap, f"num_Total_r{r}")
        model.Add(num_total == cum_total * h_max)
        adj_total = model.NewIntVar(0, adj_cap, f"adj_Total_r{r}")
        model.AddDivisionEquality(adj_total, num_total, h_r)
        counts_by_category["Total"][r] = adj_total

    for category, values in counts_by_category.items():
        if len(values) < 2:
            continue
        values = list(values.values())
        max_v = model.NewIntVar(0, adj_cap, f"max_{category}")
        min_v = model.NewIntVar(0, adj_cap, f"min_{category}")
        model.AddMaxEquality(max_v, values)
        model.AddMinEquality(min_v, values)
        spread = model.NewIntVar(0, adj_cap, f"spread_{category}")
        model.Add(spread == max_v - min_v)
        penalties.append(spread * balance_weights.get(category, 15))


def rate_scaled(cum, halves, h_max):
    h = max(1, halves)
    return (cum * h_max) // h
