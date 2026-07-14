"""Soft constraints (weighted objective) for the PGY-1 CP-SAT schedule model."""

from .config import (
    BALANCE_CATEGORIES,
    BALANCE_WEIGHTS,
    NIGHT_SHIFT,
    NIGHT_TARGET_PER_MGH_HALF,
    OS_BALANCE_WEIGHTS,
    SHIFTS,
    W_NIGHT_TARGET,
    W_NIGHTS_STRUCTURE,
    W_TIMEOFF,
    WEEKEND_DAYS,
    is_em_proper,
    is_off_service,
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
                for s in SHIFTS:
                    v = model.NewBoolVar(f"timeoff_violation_r{r}_d{d}_s{s}")
                    model.Add(v == works[(r, d, s)])
                    penalties.append(v * W_TIMEOFF)
                    violations.append((name, date, s, v))
                if d > 0:
                    v = model.NewBoolVar(f"timeoff_violation_prevnight_r{r}_d{d}")
                    model.Add(v == works[(r, d - 1, NIGHT_SHIFT)])
                    penalties.append(v * W_TIMEOFF)
                    violations.append((name, date, NIGHT_SHIFT, v))
    return violations


def add_night_structure_penalties(model, works, dates, residents, penalties):
    """Prefer consecutive night runs for EM proper only. OS placeholders exempt."""
    num_days = len(dates)
    for r, name in enumerate(residents):
        if not is_em_proper(name):
            continue
        for d in range(num_days):
            isolated = model.NewBoolVar(f"isolated_night_r{r}_d{d}")
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


def add_night_target_penalties(model, works, dates, residents, role_on, penalties):
    """Soft: MGH EM proper prefer ~NIGHT_TARGET_PER_MGH_HALF nights per active half."""
    mid = len(dates) // 2
    halves = [(0, mid, dates[:mid]), (mid, len(dates), dates[mid:])]
    target = NIGHT_TARGET_PER_MGH_HALF
    for r, name in enumerate(residents):
        if not is_em_proper(name):
            continue
        for hi, (d0, d1, dates_h) in enumerate(halves):
            if not any(role_on.get((name, d)) in ("MGH", "Flex") for d in dates_h):
                continue
            nights = sum(works[(r, d, NIGHT_SHIFT)] for d in range(d0, d1))
            # |nights - target| via positive + negative deviation
            pos = model.NewIntVar(0, len(dates), f"night_over_r{r}_h{hi}")
            neg = model.NewIntVar(0, target, f"night_under_r{r}_h{hi}")
            model.Add(nights - pos + neg == target)
            penalties.append(pos * W_NIGHT_TARGET)
            penalties.append(neg * W_NIGHT_TARGET)


def _evenness_for_pool(model, works, dates, residents, history, active_halves,
                       pool, categories, balance_weights, penalties, tag):
    """Laura-style per-half-block-worked evenness within one resident pool."""
    if len(pool) < 2:
        return

    num_days = len(dates)
    halves_by_r = {
        r: max(1, history.get(residents[r], empty_entry())["half_blocks_worked"]
               + active_halves.get(residents[r], 0))
        for r in pool
    }
    h_max = max(halves_by_r.values())
    cum_cap = 500
    adj_cap = cum_cap * h_max

    counts_by_category = {cat: {} for cat in categories}

    for r in pool:
        name = residents[r]
        entry = history.get(name, empty_entry())
        carry = entry["shifts"]
        h_r = halves_by_r[r]

        for category in categories:
            if category == "Total":
                this_block = sum(works[(r, d, s)] for d in range(num_days) for s in SHIFTS)
                carry_count = sum(carry.get(SHIFTS[s]["name"], 0) for s in SHIFTS)
            elif category == "Weekend":
                weekend_days = [d for d, date in enumerate(dates) if date.weekday() in WEEKEND_DAYS]
                this_block = sum(works[(r, d, s)] for d in weekend_days for s in SHIFTS)
                carry_count = entry.get("weekend", 0)
            else:
                shift_ids = BALANCE_CATEGORIES[category]
                this_block = sum(works[(r, d, s)] for d in range(num_days) for s in shift_ids)
                carry_count = sum(carry.get(SHIFTS[s]["name"], 0) for s in shift_ids)

            cum = model.NewIntVar(0, cum_cap, f"cum_{tag}_{category}_r{r}")
            model.Add(cum == this_block + carry_count)
            num = model.NewIntVar(0, adj_cap, f"num_{tag}_{category}_r{r}")
            model.Add(num == cum * h_max)
            adj = model.NewIntVar(0, adj_cap, f"adj_{tag}_{category}_r{r}")
            model.AddDivisionEquality(adj, num, h_r)
            counts_by_category[category][r] = adj

    for category, values_map in counts_by_category.items():
        if len(values_map) < 2:
            continue
        values = list(values_map.values())
        max_v = model.NewIntVar(0, adj_cap, f"max_{tag}_{category}")
        min_v = model.NewIntVar(0, adj_cap, f"min_{tag}_{category}")
        model.AddMaxEquality(max_v, values)
        model.AddMinEquality(min_v, values)
        spread = model.NewIntVar(0, adj_cap, f"spread_{tag}_{category}")
        model.Add(spread == max_v - min_v)
        penalties.append(spread * balance_weights.get(category, 15))


def add_evenness_penalties(model, works, dates, residents, role_on, history, active_halves,
                           penalties, balance_weights=None):
    """EM proper wellness evenness among themselves; OS balanced among themselves.

    Off-service: Total, Night, Weekend only (count > nights > weekends).
    EM: full BALANCE_CATEGORIES + Total + Weekend.
    """
    if balance_weights is None:
        balance_weights = BALANCE_WEIGHTS

    em_pool = [r for r, name in enumerate(residents) if is_em_proper(name)]
    os_pool = [r for r, name in enumerate(residents) if is_off_service(name)]

    em_categories = list(BALANCE_CATEGORIES) + ["Total", "Weekend"]
    _evenness_for_pool(
        model, works, dates, residents, history, active_halves,
        em_pool, em_categories, balance_weights, penalties, "em",
    )
    _evenness_for_pool(
        model, works, dates, residents, history, active_halves,
        os_pool, ["Total", "Night", "Weekend"], OS_BALANCE_WEIGHTS, penalties, "os",
    )


def rate_scaled(cum, halves, h_max):
    h = max(1, halves)
    return (cum * h_max) // h
