import os

# PGY-4 block scheduler paths (repo root is three levels up from this file).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

BASE_YEAR = 2026  # academic year 2026-2027; block 4/5 fall entirely in 2026

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
ALL_DAYS = frozenset(range(7))
WEEKEND_DAYS = frozenset({SAT, SUN})

# --- Shift catalog -----------------------------------------------------
# start/end in 24h clock; an "Overnight" shift's end < start means it spans midnight.
# required_weekdays: weekdays (0=Mon..6=Sun) this shift MUST be staffed by exactly one
# resident. On all other weekdays it is forced unstaffed, EXCEPT the relief shift below,
# which is merely optional (at most one resident) rather than forbidden.
SHIFTS = {
    0: {"name": "Acute 7a-4p (MGH)", "start": 7, "end": 16, "duration": 9, "type": "Morning",
        "site": "MGH", "required_weekdays": ALL_DAYS - {WED}},
    1: {"name": "FF 7a-4p (BWH)", "start": 7, "end": 16, "duration": 9, "type": "Morning",
        "site": "BWH", "required_weekdays": ALL_DAYS - {WED}},
    2: {"name": "Fast Track 2p-11p (MGH)", "start": 14, "end": 23, "duration": 9, "type": "Swing",
        "site": "MGH", "required_weekdays": frozenset({THU})},
    3: {"name": "FF 3p-12a (BWH)", "start": 15, "end": 24, "duration": 9, "type": "Swing",
        "site": "BWH", "required_weekdays": ALL_DAYS - {WED}},
    4: {"name": "Peds Snr 3p-11p (MGH)", "start": 15, "end": 23, "duration": 8, "type": "Swing",
        "site": "MGH", "required_weekdays": frozenset({MON, TUE, FRI})},
    # Wednesday this is de facto 6p-12a (didactics run 8a-5p); kept encoded as 3p-12a
    # with the informal understanding the resident skips the first 3 hours.
    5: {"name": "Acute 3p-12a (MGH)", "start": 15, "end": 24, "duration": 9, "type": "Swing",
        "site": "MGH", "required_weekdays": ALL_DAYS},
    6: {"name": "Acute 11p-8a (MGH)", "start": 23, "end": 8, "duration": 9, "type": "Overnight",
        "site": "MGH", "required_weekdays": ALL_DAYS},
    # Relief shift: only used when required coverage can't absorb everyone's minimum.
    7: {"name": "FF/Ex Swing 3p-12a (BWH)", "start": 15, "end": 24, "duration": 9, "type": "Swing",
        "site": "BWH", "required_weekdays": frozenset()},
}
NIGHT_SHIFT = 6
EXTRA_SHIFT = 7
SHIFT_TYPES = ("Morning", "Swing", "Overnight")
SITES = ("MGH", "BWH")
# Day shifts eligible for the cross-resident evenness objective (excludes the
# overnight, which is governed by nights/flex priority instead, and the relief
# shift, which should stay rare rather than "even").
DAY_SHIFTS = tuple(s for s in SHIFTS if s not in (NIGHT_SHIFT, EXTRA_SHIFT))

# Balancing categories for Laura's wellness rule: each maps a category name to
# the set of shift ids it aggregates over. Weekend is handled separately in
# objective.py since it's day-based rather than shift-based. Pedi/FT are
# single-shift categories called out because they're the two specialty day
# shifts that are otherwise easy to let drift unevenly.
BALANCE_CATEGORIES = {
    "Morning": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["type"] == "Morning"),
    "Swing": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["type"] == "Swing"),
    "MGH": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["site"] == "MGH"),
    "BWH": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["site"] == "BWH"),
    "Pedi": (4,),
    "FT": (2,),
}

ACTIVE_ROLES = ("MGB", "MGB Nights", "Flex")

# Minimum shifts owed per active 2-week half (16/full block, 8/single half).
SHIFT_MIN_PER_HALF = 8

# Objective weights (largest first).
W_TIMEOFF = 10_000
W_NIGHTS_STRUCTURE = 200
W_FLEX_NIGHT_REWARD = 100
W_NON_FLEX_NIGHT_PENALTY = 30
# Evenness spread weights (per category); higher = optimized first among balance goals.
BALANCE_WEIGHTS = {
    "Weekend": 100,
    "Morning": 30,
    "Swing": 30,
    "MGH": 15,
    "BWH": 15,
    "Pedi": 8,
    "FT": 8,
}
W_EXTRA_SHIFT = 50
W_EXTRA_WEEKEND = 20
