"""Soft constraints (weighted objective) for the PGY-4 CP-SAT schedule model."""

from .config import (
    BALANCE_CATEGORIES,
    BALANCE_WEIGHTS,
    EXTRA_SHIFT,
    NIGHT_SHIFT,
    SHIFTS,
    W_EXTRA_SHIFT,
    W_EXTRA_WEEKEND,
    W_FLEX_NIGHT_REWARD,
    W_NIGHTS_STRUCTURE,
    W_NON_FLEX_NIGHT_PENALTY,
    W_TIMEOFF,
    WEEKEND_DAYS,
)
from .history import empty_entry


def add_timeoff_penalties(model, works, dates, residents, timeoff, penalties):
    """Time-off requests are soft (heavily penalized): a shift "touches" a
    requested day if any of its hours fall on it, including a spilled-over
    overnight from the previous day. Returns the list of (name, date, shift, var)
    tuples so callers can report violations after solving."""
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


def add_nights_and_flex_penalties(model, works, dates, residents, role_at, penalties):
    """Nights residents prefer 4 weekday nights/week (penalize weekend nights);
    Flex residents are rewarded for taking weekend overnights; regular MGB
    residents are mildly discouraged from taking any overnight."""
    for r, name in enumerate(residents):
        for d, date in enumerate(dates):
            role = role_at(name, d)
            is_weekend = date.weekday() in WEEKEND_DAYS
            if role == "MGB Nights" and is_weekend:
                penalties.append(works[(r, d, NIGHT_SHIFT)] * W_NIGHTS_STRUCTURE)
            elif role == "Flex" and is_weekend:
                penalties.append(works[(r, d, NIGHT_SHIFT)] * -W_FLEX_NIGHT_REWARD)
            elif role == "MGB":
                penalties.append(works[(r, d, NIGHT_SHIFT)] * W_NON_FLEX_NIGHT_PENALTY)


def add_relief_shift_penalties(model, works, dates, num_residents, penalties):
    """Only lean on the FF/Ex relief shift when needed, preferring Mon/Tue/Thu."""
    for r in range(num_residents):
        for d, date in enumerate(dates):
            penalties.append(works[(r, d, EXTRA_SHIFT)] * W_EXTRA_SHIFT)
            if date.weekday() in WEEKEND_DAYS:
                penalties.append(works[(r, d, EXTRA_SHIFT)] * W_EXTRA_WEEKEND)


def add_evenness_penalties(model, works, dates, residents, role_at, history, active_halves,
                           penalties, balance_weights=None):
    """Laura's rule: spread cumulative counts **per half-block worked** as evenly
    as possible across residents, per wellness category. Residents who worked
    fewer half-blocks should not be penalized for having lower raw totals.

    Comparison uses floor(cum * Hmax / halves) so CP-SAT avoids floating point;
    see rate_scaled() for the same math outside the model.
    """
    if balance_weights is None:
        balance_weights = BALANCE_WEIGHTS

    num_days = len(dates)
    day_eligible = [
        r for r, name in enumerate(residents)
        if {role_at(name, d) for d in range(num_days)} - {None} != {"MGB Nights"}
    ]
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
        penalties.append(spread * balance_weights[category])


def rate_scaled(cum, halves, h_max):
    """Floor(cum * h_max / halves): proportional rate comparison used by the
    evenness objective. Equal per-half rates yield equal scaled values."""
    h = max(1, halves)
    return (cum * h_max) // h
