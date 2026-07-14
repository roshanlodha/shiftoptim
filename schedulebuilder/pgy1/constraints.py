"""Hard constraints for the PGY-1 CP-SAT schedule model."""

from .config import (
    SHIFTS,
    NIGHT_SHIFT,
    BASE_DEMAND,
    SHIFT_MIN_PER_HALF,
    SHIFT_MAX_PER_HALF,
    MGH_SHIFTS,
    BWH_SHIFTS,
    WED,
    is_em_proper,
)


def add_coverage_constraints(model, works, dates, num_residents):
    """Soft coverage: at most demand residents on any shift on any day (underfill OK)."""
    for d, date in enumerate(dates):
        weekday = date.weekday()
        for s in SHIFTS:
            demand = BASE_DEMAND[s][weekday]
            model.Add(sum(works[(r, d, s)] for r in range(num_residents)) <= demand)


def add_site_and_availability_constraints(model, works, dates, residents, role_on):
    """Ensure site exclusivity and block inactive days:
    - MGH residents work MGH shifts only.
    - BWH residents work BWH shifts only.
    - Flex residents work either site.
    - Inactive days are blocked (0 shifts).
    - At most one shift per resident per day.
    """
    num_days = len(dates)
    for r, name in enumerate(residents):
        for d in range(num_days):
            date = dates[d]
            model.AddAtMostOne(works[(r, d, s)] for s in SHIFTS)

            role = role_on.get((name, date))
            if role is None:
                for s in SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "MGH":
                for s in BWH_SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "BWH":
                for s in MGH_SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "Flex":
                pass


def _half_has_role(name, dates_half, role_on, site=None):
    """True if resident is active on any day in the half (optionally at site)."""
    for d in dates_half:
        role = role_on.get((name, d))
        if role is None:
            continue
        if site is None or role == site or role == "Flex":
            return True
    return False


def add_shift_count_constraints(model, works, dates, residents, role_on,
                                shift_min=SHIFT_MIN_PER_HALF, shift_max=SHIFT_MAX_PER_HALF):
    """Enforce shift counts per half-block for EM proper only:
    - Active half: between shift_min and shift_max.
    - Inactive half: exactly 0.
    Off-service placeholders: no min/max (ACGME weekly caps still apply).
    Night count is soft (see objective) — not enforced here.
    """
    mid = len(dates) // 2
    dates_a = dates[:mid]
    dates_b = dates[mid:]

    for r, name in enumerate(residents):
        is_em = is_em_proper(name)

        sum_a = sum(works[(r, d, s)] for d in range(mid) for s in SHIFTS)
        active_a = _half_has_role(name, dates_a, role_on)
        if not active_a:
            model.Add(sum_a == 0)
        elif is_em:
            model.Add(sum_a >= shift_min)
            model.Add(sum_a <= shift_max)

        sum_b = sum(works[(r, d, s)] for d in range(mid, len(dates)) for s in SHIFTS)
        active_b = _half_has_role(name, dates_b, role_on)
        if not active_b:
            model.Add(sum_b == 0)
        elif is_em:
            model.Add(sum_b >= shift_min)
            model.Add(sum_b <= shift_max)


def add_rest_constraints(model, works, num_residents, num_days, prior_last_shifts=None):
    """ACGME rest: at least shift_duration (min 8h) between consecutive shifts.
    Applies to EM proper and off-service placeholders alike.
    """
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

    if prior_last_shifts:
        for r, s1 in prior_last_shifts.items():
            info1 = SHIFTS[s1]
            end1 = info1["end"] + (24 if info1["type"] == "Overnight" else 0)
            for s2, info2 in SHIFTS.items():
                start2 = info2["start"] + 24
                rest_hours = start2 - end1
                required_rest = max(8, info1["duration"])
                if rest_hours < required_rest:
                    model.Add(works[(r, 0, s2)] == 0)


def add_acgme_weekly_constraints(model, works, num_residents, num_days):
    """ACGME weekly caps for everyone (EM + off-service):
    - <= 60 ED hours per rolling 7 days.
    - >= 1 completely free day per rolling 7 days.
    """
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


def add_wednesday_conference_protection(model, works, dates, residents):
    """Protect Wednesday conference (7am-5pm) and Tuesday night for EM proper only.
    Off-service placeholders are exempt.
    """
    for d, date in enumerate(dates):
        if date.weekday() == WED:
            for s, info in SHIFTS.items():
                start = info["start"]
                end = info["end"]
                if end < start:
                    end += 24
                if max(7, start) < min(17, end):
                    for r, name in enumerate(residents):
                        if is_em_proper(name):
                            model.Add(works[(r, d, s)] == 0)

        if date.weekday() == WED - 1:  # Tuesday night → Wed morning
            for r, name in enumerate(residents):
                if is_em_proper(name):
                    model.Add(works[(r, d, NIGHT_SHIFT)] == 0)


def add_all_hard_constraints(model, works, dates, residents, role_on,
                              shift_min=SHIFT_MIN_PER_HALF, shift_max=SHIFT_MAX_PER_HALF,
                              prior_last_shifts=None):
    num_residents = len(residents)
    num_days = len(dates)
    add_coverage_constraints(model, works, dates, num_residents)
    add_site_and_availability_constraints(model, works, dates, residents, role_on)
    add_shift_count_constraints(model, works, dates, residents, role_on, shift_min, shift_max)
    add_rest_constraints(model, works, num_residents, num_days, prior_last_shifts)
    add_acgme_weekly_constraints(model, works, num_residents, num_days)
    add_wednesday_conference_protection(model, works, dates, residents)
