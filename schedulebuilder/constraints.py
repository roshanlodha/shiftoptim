"""Hard constraints for the PGY-4 CP-SAT schedule model."""

from .config import EXTRA_SHIFT, NIGHT_SHIFT, SHIFT_MIN_PER_HALF, SHIFTS


def add_coverage_constraints(model, works, dates, num_residents):
    """Exactly one resident on required-weekday shifts; at most one on the relief
    shift; force everything else unstaffed (this is what protects Wednesday
    didactics, since only the Acute swing/overnight require Wednesday coverage)."""
    for d in range(len(dates)):
        weekday = dates[d].weekday()
        for s, info in SHIFTS.items():
            if weekday in info["required_weekdays"]:
                model.AddExactlyOne(works[(r, d, s)] for r in range(num_residents))
            elif s == EXTRA_SHIFT:
                model.AddAtMostOne(works[(r, d, s)] for r in range(num_residents))
            else:
                for r in range(num_residents):
                    model.Add(works[(r, d, s)] == 0)


def add_availability_constraints(model, works, dates, residents, role_at):
    """At most one shift per resident per day; block inactive days entirely;
    restrict "MGB Nights" residents to the overnight shift only."""
    num_days = len(dates)
    for r, name in enumerate(residents):
        for d in range(num_days):
            model.AddAtMostOne(works[(r, d, s)] for s in SHIFTS)
            role = role_at(name, d)
            if role is None:
                for s in SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "MGB Nights":
                for s in SHIFTS:
                    if s != NIGHT_SHIFT:
                        model.Add(works[(r, d, s)] == 0)


def add_rest_constraints(model, works, num_residents, num_days):
    """Time off after a shift must be >= that shift's duration (minimum 8h)."""
    for r in range(num_residents):
        for d in range(num_days - 1):
            for s1, info1 in SHIFTS.items():
                end1 = info1["end"] + (24 if info1["type"] == "Overnight" else 0)
                for s2, info2 in SHIFTS.items():
                    start2 = info2["start"] + 24
                    rest_hours = start2 - end1
                    required_rest = max(8, info1["duration"])
                    if rest_hours < required_rest:
                        model.AddImplication(works[(r, d, s1)], works[(r, d + 1, s2)].Not())


def add_acgme_weekly_constraints(model, works, num_residents, num_days):
    """<=60 ED hours in any rolling 7-day window, and >=1 free 24h day per window."""
    worked_day = {}
    for r in range(num_residents):
        for d in range(num_days):
            wd = model.NewBoolVar(f"worked_r{r}_d{d}")
            model.AddMaxEquality(wd, [works[(r, d, s)] for s in SHIFTS])
            worked_day[(r, d)] = wd

    free_day = {}
    for r in range(num_residents):
        for d in range(num_days):
            fd = model.NewBoolVar(f"free_r{r}_d{d}")
            night_prev = works[(r, d - 1, NIGHT_SHIFT)] if d > 0 else model.NewConstant(0)
            model.Add(fd == 0).OnlyEnforceIf(worked_day[(r, d)])
            model.Add(fd == 0).OnlyEnforceIf(night_prev)
            model.AddBoolAnd(
                [worked_day[(r, d)].Not(), night_prev.Not() if d > 0 else model.NewConstant(1)]
            ).OnlyEnforceIf(fd)
            free_day[(r, d)] = fd

    for r in range(num_residents):
        for d in range(max(0, num_days - 6)):
            window = range(d, min(d + 7, num_days))
            ed_hours = sum(works[(r, i, s)] * SHIFTS[s]["duration"] for i in window for s in SHIFTS)
            model.Add(ed_hours <= 60)
            if len(list(window)) == 7:
                model.Add(sum(free_day[(r, i)] for i in window) >= 1)


def add_minimum_shift_constraints(model, works, residents, active_halves, num_days,
                                   shift_min_per_half=SHIFT_MIN_PER_HALF):
    """Each resident must work >= 8 shifts per active 2-week half (16 for a full block)."""
    for r, name in enumerate(residents):
        total = sum(works[(r, d, s)] for d in range(num_days) for s in SHIFTS)
        model.Add(total >= shift_min_per_half * active_halves[name])


def add_all_hard_constraints(model, works, dates, residents, role_at, active_halves,
                              shift_min_per_half=SHIFT_MIN_PER_HALF):
    num_residents = len(residents)
    num_days = len(dates)
    add_coverage_constraints(model, works, dates, num_residents)
    add_availability_constraints(model, works, dates, residents, role_at)
    add_rest_constraints(model, works, num_residents, num_days)
    add_acgme_weekly_constraints(model, works, num_residents, num_days)
    add_minimum_shift_constraints(model, works, residents, active_halves, num_days,
                                   shift_min_per_half)
