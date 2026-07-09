"""Soft constraints (weighted objective) for the PGY-4 CP-SAT schedule model."""

from .config import (
    EXTRA_SHIFT,
    NIGHT_SHIFT,
    SHIFT_TYPES,
    SHIFTS,
    W_BALANCE,
    W_EXTRA_SHIFT,
    W_EXTRA_WEEKEND,
    W_FLEX_NIGHT_REWARD,
    W_MORNING_SWING_SPREAD,
    W_NIGHTS_STRUCTURE,
    W_NON_FLEX_NIGHT_PENALTY,
    W_TIMEOFF,
    WEEKEND_DAYS,
)
from .history import empty_entry, history_type_totals


def add_timeoff_penalties(model, works, dates, residents, last_name, timeoff, penalties):
    """Time-off requests are soft (heavily penalized): a shift "touches" a
    requested day if any of its hours fall on it, including a spilled-over
    overnight from the previous day. Returns the list of (name, date, shift, var)
    tuples so callers can report violations after solving."""
    violations = []
    for r, name in enumerate(residents):
        for start, end in timeoff.get(last_name[name], []):
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


def add_balance_penalties(model, works, dates, residents, last_name, history, penalties):
    """Laura's rule: spread cumulative (history + this block) Morning/Swing/Overnight
    counts evenly across residents, and keep each resident's Morning vs Swing roughly
    even within the block. Returns per-resident cumulative IntVars for history update."""
    num_days = len(dates)
    cumulative = {}
    for r, name in enumerate(residents):
        carry = history_type_totals(history.get(last_name[name], empty_entry()))
        by_type = {
            t: sum(works[(r, d, s)] for d in range(num_days) for s in SHIFTS if SHIFTS[s]["type"] == t)
            for t in SHIFT_TYPES
        }
        cumulative[r] = {}
        for t in SHIFT_TYPES:
            cum = model.NewIntVar(0, 500, f"cum_{t}_r{r}")
            model.Add(cum == by_type[t] + carry[t])
            cumulative[r][t] = cum

        diff = model.NewIntVar(-100, 100, f"morning_swing_diff_r{r}")
        model.Add(diff == by_type["Morning"] - by_type["Swing"])
        abs_diff = model.NewIntVar(0, 100, f"morning_swing_absdiff_r{r}")
        model.AddAbsEquality(abs_diff, diff)
        penalties.append(abs_diff * W_MORNING_SWING_SPREAD)

    if len(residents) > 1:
        for shift_type in SHIFT_TYPES:
            values = [cumulative[r][shift_type] for r in range(len(residents))]
            max_v = model.NewIntVar(0, 500, f"max_{shift_type}")
            min_v = model.NewIntVar(0, 500, f"min_{shift_type}")
            model.AddMaxEquality(max_v, values)
            model.AddMinEquality(min_v, values)
            spread = model.NewIntVar(0, 500, f"spread_{shift_type}")
            model.Add(spread == max_v - min_v)
            penalties.append(spread * W_BALANCE)

    return cumulative
