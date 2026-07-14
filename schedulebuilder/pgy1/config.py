import os

# PGY-1 block scheduler paths
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUTPUT_DIR = os.path.join(REPO_ROOT, "output")

BASE_YEAR = 2026

MON, TUE, WED, THU, FRI, SAT, SUN = range(7)
ALL_DAYS = frozenset(range(7))
WEEKEND_DAYS = frozenset({SAT, SUN})

# Shift Catalog (Only the 8 allowed shift types for PGY1)
SHIFTS = {
    0:  {"name": "MGH Jr. - AC PGY1 7a-4p",   "start": 7,  "end": 16, "duration": 9,  "type": "Morning",   "site": "MGH"},
    1:  {"name": "MGH Jr. - FT 11a-8p",       "start": 11, "end": 20, "duration": 9,  "type": "Swing",     "site": "MGH"},
    2:  {"name": "MGH Jr. - AC PGY1 1p-11p",   "start": 13, "end": 23, "duration": 10, "type": "Swing",     "site": "MGH"},
    3:  {"name": "MGH Jr. - East Jr 11p-7a",   "start": 23, "end": 7,  "duration": 8,  "type": "Overnight", "site": "MGH"},
    4:  {"name": "BWH Jr.  - Exe Jr 12p-12a",   "start": 12, "end": 0,  "duration": 12, "type": "Swing",     "site": "BWH"},
    5:  {"name": "BWH Jr.  - Exe Jr 3p-12a",    "start": 15, "end": 0,  "duration": 9,  "type": "Swing",     "site": "BWH"},
    6:  {"name": "BWH Jr.  - FF Jr 8a-4p",      "start": 8,  "end": 16, "duration": 8,  "type": "Morning",   "site": "BWH"},
    7:  {"name": "BWH Jr.  - FF Jr 7a-4p",      "start": 7,  "end": 16, "duration": 9,  "type": "Morning",   "site": "BWH"},
}

NIGHT_SHIFT = 3  # MGH East Jr 11p-7a (only overnight shift)

MGH_SHIFTS = (0, 1, 2, 3)
BWH_SHIFTS = (4, 5, 6, 7)

# Base demand matrix (only for the 8 active shifts)
BASE_DEMAND = {
    0:  {MON: 1, TUE: 1, WED: 0, THU: 1, FRI: 1, SAT: 1, SUN: 1},  # AC PGY1 7a-4p (Wed=0 for conf)
    1:  {MON: 1, TUE: 1, WED: 1, THU: 1, FRI: 1, SAT: 1, SUN: 1},  # FT 11a-8p
    2:  {MON: 2, TUE: 2, WED: 1, THU: 2, FRI: 2, SAT: 2, SUN: 1},  # AC PGY1 1p-11p
    3:  {MON: 2, TUE: 2, WED: 2, THU: 2, FRI: 2, SAT: 2, SUN: 2},  # East Jr 11p-7a (nights)
    4:  {MON: 1, TUE: 1, WED: 0, THU: 1, FRI: 1, SAT: 1, SUN: 1},  # Exe Jr 12p-12a
    5:  {MON: 1, TUE: 1, WED: 1, THU: 1, FRI: 1, SAT: 1, SUN: 1},  # Exe Jr 3p-12a
    6:  {MON: 1, TUE: 1, WED: 1, THU: 1, FRI: 1, SAT: 0, SUN: 0},  # FF Jr 8a-4p (weekdays only)
    7:  {MON: 0, TUE: 0, WED: 0, THU: 0, FRI: 0, SAT: 1, SUN: 1},  # FF Jr 7a-4p (wknd only)
}

SHIFT_TYPES = ("Morning", "Swing", "Overnight")
SITES = ("MGH", "BWH")

DAY_SHIFTS = tuple(s for s in SHIFTS if s != NIGHT_SHIFT)

# Wellness balance categories (for the evenness objective)
BALANCE_CATEGORIES = {
    "Morning": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["type"] == "Morning"),
    "Swing": tuple(s for s in DAY_SHIFTS if SHIFTS[s]["type"] == "Swing"),
    "Night": (NIGHT_SHIFT,),
    "MGH": MGH_SHIFTS,
    "BWH": BWH_SHIFTS,
}

ACTIVE_ROLES = ("MGH", "BWH", "Flex")

SHIFT_MIN_PER_HALF = 10
SHIFT_MAX_PER_HALF = 11

# EM-proper core roster (placeholders like "Off Service 1" are not in this set).
EM_PROPER_INTERNS = frozenset({
    "Brian", "Ashleigh", "Sara", "Emily", "Isabella", "Wendy",
    "Daem", "Bailey", "JP", "Roshan", "Mauranda", "Justin",
    "Jethel", "Clifford", "Andrea",
})

# Soft target overnight shifts per MGH half for EM proper (not a hard floor).
NIGHT_TARGET_PER_MGH_HALF = 3

# Objective weights (identical/comparable to PGY4)
W_TIMEOFF = 10_000
W_NIGHTS_STRUCTURE = 200
W_NIGHT_TARGET = 100  # |nights − NIGHT_TARGET| per MGH EM half
W_TOTAL_SPREAD = 150
BALANCE_WEIGHTS = {
    "Total": 150,
    "Weekend": 100,
    "Morning": 30,
    "Swing": 30,
    "Night": 50,
    "MGH": 15,
    "BWH": 15,
}
# Off-service placeholder pool: balance among themselves only (count > nights > weekends).
OS_BALANCE_WEIGHTS = {
    "Total": 200,
    "Night": 100,
    "Weekend": 50,
}
W_EXTRA_SHIFT = 50
W_EXTRA_WEEKEND = 20


def is_off_service(name):
    """Admin placeholders entered at solve time (Off Service 1, …)."""
    return name.startswith("Off Service")


def is_em_proper(name):
    return name in EM_PROPER_INTERNS


# 26 half-blocks in order (block_number, half, start_date, end_date), ISO dates.
HALF_BLOCKS = [
    (1, "a", "2026-06-29", "2026-07-12"),
    (1, "b", "2026-07-13", "2026-07-26"),
    (2, "a", "2026-07-27", "2026-08-09"),
    (2, "b", "2026-08-10", "2026-08-23"),
    (3, "a", "2026-08-24", "2026-09-06"),
    (3, "b", "2026-09-07", "2026-09-20"),
    (4, "a", "2026-09-21", "2026-10-04"),
    (4, "b", "2026-10-05", "2026-10-18"),
    (5, "a", "2026-10-19", "2026-11-01"),
    (5, "b", "2026-11-02", "2026-11-15"),
    (6, "a", "2026-11-16", "2026-11-29"),
    (6, "b", "2026-11-30", "2026-12-13"),
    (7, "a", "2026-12-14", "2026-12-27"),
    (7, "b", "2026-12-28", "2027-01-10"),
    (8, "a", "2027-01-11", "2027-01-24"),
    (8, "b", "2027-01-25", "2027-02-07"),
    (9, "a", "2027-02-08", "2027-02-21"),
    (9, "b", "2027-02-22", "2027-03-07"),
    (10, "a", "2027-03-08", "2027-03-21"),
    (10, "b", "2027-03-22", "2027-04-04"),
    (11, "a", "2027-04-05", "2027-04-18"),
    (11, "b", "2027-04-19", "2027-05-02"),
    (12, "a", "2027-05-03", "2027-05-16"),
    (12, "b", "2027-05-17", "2027-05-30"),
    (13, "a", "2027-05-31", "2027-06-13"),
    (13, "b", "2027-06-14", "2027-06-27"),
]
