"""Hard constraints for the PGY-1 CP-SAT schedule model."""

import datetime as dt
from .config import (
    SHIFTS,
    NIGHT_SHIFT,
    BASE_DEMAND,
    SHIFT_MIN_PER_HALF,
    SHIFT_MAX_PER_HALF,
    MGH_SHIFTS,
    BWH_SHIFTS,
    WED,
)


def add_coverage_constraints(model, works, dates, num_residents):
    """At most demand residents on any shift on any day."""
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
    - Off-service/inactive days are blocked (0 shifts).
    - At most one shift per resident per day.
    """
    num_days = len(dates)
    for r, name in enumerate(residents):
        for d in range(num_days):
            date = dates[d]
            model.AddAtMostOne(works[(r, d, s)] for s in SHIFTS)

            role = role_on.get((name, date))
            if role is None:
                # Inactive / off-service day
                for s in SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "MGH":
                # MGH shifts only
                for s in BWH_SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "BWH":
                # BWH shifts only
                for s in MGH_SHIFTS:
                    model.Add(works[(r, d, s)] == 0)
            elif role == "Flex":
                # Can work both sites, no site restriction
                pass


def add_shift_count_constraints(model, works, dates, residents, role_on,
                                shift_min=SHIFT_MIN_PER_HALF, shift_max=SHIFT_MAX_PER_HALF):
    """Enforce shift counts per half-block:
    - Active half-block: between shift_min and shift_max for EM proper core.
    - Inactive half-block: exactly 0.
    - MGH active half-block: at least 3 overnight shifts (EM proper core only).
    """
    mid = len(dates) // 2
    dates_a = dates[:mid]
    dates_b = dates[mid:]

    EM_PROPER_INTERNS = {
        "Brian", "Ashleigh", "Sara", "Emily", "Isabella", "Wendy",
        "Daem", "Bailey", "JP", "Roshan", "Mauranda", "Justin",
        "Jethel", "Clifford", "Andrea"
    }

    for r, name in enumerate(residents):
        is_em = name in EM_PROPER_INTERNS
        min_limit = shift_min if is_em else 0

        # Half A
        active_a = any((name, d) in role_on for d in dates_a)
        sum_a = sum(works[(r, d, s)] for d in range(mid) for s in SHIFTS)
        if active_a:
            model.Add(sum_a >= min_limit)
            model.Add(sum_a <= shift_max)
            # MGH block night requirement (EM proper only)
            role_a_sample = role_on.get((name, dates_a[0])) if dates_a else None
            if role_a_sample == "MGH" and is_em:
                model.Add(sum(works[(r, d, NIGHT_SHIFT)] for d in range(mid)) >= 3)
        else:
            model.Add(sum_a == 0)

        # Half B
        active_b = any((name, d) in role_on for d in dates_b)
        sum_b = sum(works[(r, d, s)] for d in range(mid, len(dates)) for s in SHIFTS)
        if active_b:
            model.Add(sum_b >= min_limit)
            model.Add(sum_b <= shift_max)
            # MGH block night requirement (EM proper only)
            role_b_sample = role_on.get((name, dates_b[0])) if dates_b else None
            if role_b_sample == "MGH" and is_em:
                model.Add(sum(works[(r, d, NIGHT_SHIFT)] for d in range(mid, len(dates))) >= 3)
        else:
            model.Add(sum_b == 0)


def add_rest_constraints(model, works, num_residents, num_days):
    """Enforce ACGME rest constraints: at least shift_duration (min 8h) rest
    between consecutive shifts.
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


def add_acgme_weekly_constraints(model, works, num_residents, num_days):
    """Enforce ACGME weekly constraints:
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
            # Prev night check
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
    """Protect Wednesday conference (7am - 5pm) and Tuesday night for EM proper residents.
    Off-service residents are exempt from both.
    """
    EM_PROPER_INTERNS = {
        "Brian", "Ashleigh", "Sara", "Emily", "Isabella", "Wendy",
        "Daem", "Bailey", "JP", "Roshan", "Mauranda", "Justin",
        "Jethel", "Clifford", "Andrea"
    }
    
    # Wednesday conference protection
    for d, date in enumerate(dates):
        if date.weekday() == WED:
            for s, info in SHIFTS.items():
                start = info["start"]
                end = info["end"]
                if end < start:
                    end += 24
                # Overlap with [7, 17]
                if max(7, start) < min(17, end):
                    for r, name in enumerate(residents):
                        if name in EM_PROPER_INTERNS:
                            model.Add(works[(r, d, s)] == 0)

    # Tuesday night protection (overnight shift 5 ends Wednesday morning)
    for d, date in enumerate(dates):
        if date.weekday() == WED - 1:  # Tuesday
            for r, name in enumerate(residents):
                if name in EM_PROPER_INTERNS:
                    model.Add(works[(r, d, NIGHT_SHIFT)] == 0)


def add_all_hard_constraints(model, works, dates, residents, role_on,
                              shift_min=SHIFT_MIN_PER_HALF, shift_max=SHIFT_MAX_PER_HALF):
    num_residents = len(residents)
    num_days = len(dates)
    add_coverage_constraints(model, works, dates, num_residents)
    add_site_and_availability_constraints(model, works, dates, residents, role_on)
    add_shift_count_constraints(model, works, dates, residents, role_on, shift_min, shift_max)
    add_rest_constraints(model, works, num_residents, num_days)
    add_acgme_weekly_constraints(model, works, num_residents, num_days)
    add_wednesday_conference_protection(model, works, dates, residents)
