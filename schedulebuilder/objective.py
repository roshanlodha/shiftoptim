"""Soft constraints (weighted objective) for the PGY-4 CP-SAT schedule model."""

from .config import (
    DAY_SHIFTS,
    EXTRA_SHIFT,
    NIGHT_SHIFT,
    SHIFTS,
    W_BALANCE,
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


def add_evenness_penalties(model, works, dates, residents, role_at, history, penalties):
    """Laura's rule, simplified: for each day-shift kind (everything except the
    overnight and the relief shift), spread cumulative (history + this block)
    counts as evenly as possible across residents. Residents who are "MGB
    Nights" for every active day this block can't work any day shift, so
    they're excluded rather than dragging the minimum down to zero.

    Overnights are intentionally left out here: they're governed by the
    nights/flex priority in add_nights_and_flex_penalties instead of evenness.
    """
    num_days = len(dates)
    day_eligible = [
        r for r, name in enumerate(residents)
        if {role_at(name, d) for d in range(num_days)} - {None} != {"MGB Nights"}
    ]

    counts_by_shift = {s: {} for s in DAY_SHIFTS}
    for r in day_eligible:
        name = residents[r]
        carry = history.get(name, empty_entry())["shifts"]
        for s in DAY_SHIFTS:
            count_this_block = sum(works[(r, d, s)] for d in range(num_days))
            cum = model.NewIntVar(0, 500, f"cum_s{s}_r{r}")
            model.Add(cum == count_this_block + carry.get(SHIFTS[s]["name"], 0))
            counts_by_shift[s][r] = cum

    for s, values in counts_by_shift.items():
        if len(values) < 2:
            continue
        values = list(values.values())
        max_v = model.NewIntVar(0, 500, f"max_s{s}")
        min_v = model.NewIntVar(0, 500, f"min_s{s}")
        model.AddMaxEquality(max_v, values)
        model.AddMinEquality(min_v, values)
        spread = model.NewIntVar(0, 500, f"spread_s{s}")
        model.Add(spread == max_v - min_v)
        penalties.append(spread * W_BALANCE)
