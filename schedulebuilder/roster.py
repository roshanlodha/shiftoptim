"""Hardcoded PGY-4 roster/roles for blocks 4 and 5 (transcribed from data/pgy4.csv).

Blocks are 4 weeks long, split into two 2-week halves ("a" and "b"). A resident's
role (MGB / MGB Nights / Flex) can differ between halves of the same block.
"""

import datetime as dt

# Name in roster -> name used in time-off requests (differs when the roster uses
# a first name / nickname but requests were logged under the last name).
LAST_NAME = {
    "Aaron": "D'Amore",
    "Abby": "Raynor",
    "Xin": "Qi",
    "Jake": "Hurwitz",
    "Abd Al-Rahman": "Traboulsi",
    "Brendan": "Eappen",
    "Nneoma": "Okonkwo",
    "Jackie": "Anyaso",
    "Ash": "Fonjungo",
    "Brittany": "Botticelli",
    "Julia Menzies": "Menzies",
    "Rich": "Tamirian",
    "Kira": "Kira",
    "Muhammad": "Shoaib",
    "Julia Malits": "Malits",
}

# block -> half ("a"/"b") -> (start_date, end_date), inclusive.
BLOCK_HALF_DATES = {
    "4": {
        "a": (dt.date(2026, 9, 21), dt.date(2026, 10, 4)),
        "b": (dt.date(2026, 10, 5), dt.date(2026, 10, 18)),
    },
    "5": {
        "a": (dt.date(2026, 10, 19), dt.date(2026, 11, 1)),
        "b": (dt.date(2026, 11, 2), dt.date(2026, 11, 15)),
    },
}

# block -> half -> {resident: role}. Only residents on MGB / MGB Nights / Flex
# that half are listed; everyone else is off-block (NWH, Vacation, Elective, etc.)
# and excluded entirely.
BLOCK_ROSTER = {
    "4": {
        "a": {
            "Aaron": "MGB",
            "Abby": "MGB",
            "Jake": "MGB",
            "Brendan": "MGB",
            "Jackie": "MGB",
            "Ash": "MGB",
            "Julia Menzies": "MGB Nights",
            "Rich": "Flex",
            "Kira": "MGB",
        },
        "b": {
            "Aaron": "MGB",
            "Brendan": "MGB",
            "Jackie": "MGB",
            "Ash": "MGB Nights",
            "Rich": "MGB",
            "Kira": "MGB",
            "Xin": "MGB",
            "Abd Al-Rahman": "Flex",
            "Muhammad": "MGB",
        },
    },
    "5": {
        "a": {
            "Aaron": "MGB",
            "Jake": "Flex",
            "Abd Al-Rahman": "MGB",
            "Brendan": "MGB Nights",
            "Nneoma": "MGB",
            "Brittany": "MGB",
            "Rich": "MGB",
            "Muhammad": "MGB",
            "Julia Malits": "MGB",
        },
        "b": {
            "Aaron": "MGB Nights",
            "Jake": "MGB",
            "Abd Al-Rahman": "MGB",
            "Nneoma": "MGB",
            "Brittany": "MGB",
            "Rich": "MGB",
            "Julia Malits": "MGB",
            "Abby": "MGB",
            "Ash": "MGB",
        },
    },
}


def load_block(block):
    """Loads one full block (both halves) of hardcoded roster data.

    Returns:
        dates: sorted list of all dates in the block.
        residents: list of resident names active in at least one half.
        role_on: dict (name, date) -> role string ("MGB" / "MGB Nights" / "Flex"),
                 only present for days the resident is active.
        active_halves: dict name -> number of halves (1 or 2) the resident is active in.
    """
    halves = BLOCK_HALF_DATES.get(block)
    if halves is None:
        raise ValueError(f"Block '{block}' has no hardcoded roster data")

    dates = []
    role_on = {}
    active_halves = {}
    residents_seen = []

    for half, (start, end) in sorted(halves.items()):
        half_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
        dates.extend(half_dates)

        roles = BLOCK_ROSTER[block][half]
        for name, role in roles.items():
            if name not in active_halves:
                residents_seen.append(name)
            active_halves[name] = active_halves.get(name, 0) + 1
            for d in half_dates:
                role_on[(name, d)] = role

    dates = sorted(dates)
    return dates, residents_seen, role_on, active_halves
