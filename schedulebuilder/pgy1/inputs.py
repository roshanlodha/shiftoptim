import csv
import datetime as dt
import os
import re

from .config import BASE_YEAR, HALF_BLOCKS, REPO_ROOT

PGY1_CSV = os.path.join(REPO_ROOT, "data", "Final Intern Year 2026-2027 Block Schedules - PGY-1.csv")


def _daterange(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def load_block(block_num):
    """Loads one full block (both halves) from the PGY-1 block schedule CSV.

    Returns:
        dates: sorted list of all dates in the block.
        residents: list of resident names active in at least one half of the ED.
        role_on: dict (name, date) -> role string ("MGH" / "BWH" / "Flex")
        active_halves: dict name -> number of halves (1 or 2) the resident is active.
    """
    block_num = int(block_num)
    if block_num < 4 or block_num > 13:
        raise ValueError("PGY-1 block schedules only cover blocks 4 through 13.")

    # Find the block dates
    half_a = next(hb for hb in HALF_BLOCKS if hb[0] == block_num and hb[1] == "a")
    half_b = next(hb for hb in HALF_BLOCKS if hb[0] == block_num and hb[1] == "b")

    start_a = dt.date.fromisoformat(half_a[2])
    end_a = dt.date.fromisoformat(half_a[3])
    start_b = dt.date.fromisoformat(half_b[2])
    end_b = dt.date.fromisoformat(half_b[3])

    dates_a = _daterange(start_a, end_a)
    dates_b = _daterange(start_b, end_b)
    dates = sorted(dates_a + dates_b)

    # Read the CSV
    if not os.path.exists(PGY1_CSV):
        raise FileNotFoundError(f"PGY-1 block schedules CSV not found at {PGY1_CSV}")

    with open(PGY1_CSV) as f:
        r = csv.reader(f)
        rows = list(r)

    # Map column index for block B
    # CSV starts at Block 4a in column 1
    col_a = 2 * (block_num - 4) + 1
    col_b = 2 * (block_num - 4) + 2

    residents_seen = []
    role_on = {}
    active_halves = {}

    for row in rows[5:20]:
        label = row[0].strip()
        m = re.match(r"R\d+:\s*(.*)", label)
        if not m:
            continue
        name = m.group(1).strip()
        
        rot_a = row[col_a].strip()
        rot_b = row[col_b].strip()

        is_active = False
        if rot_a in ("MGH", "BWH", "Flex"):
            active_halves[name] = active_halves.get(name, 0) + 1
            is_active = True
            for d in dates_a:
                role_on[(name, d)] = rot_a

        if rot_b in ("MGH", "BWH", "Flex"):
            active_halves[name] = active_halves.get(name, 0) + 1
            is_active = True
            for d in dates_b:
                role_on[(name, d)] = rot_b

        if is_active:
            residents_seen.append(name)

    return dates, residents_seen, role_on, active_halves


def load_timeoff():
    """Returns dict: resident last name -> list of (start_date, end_date)."""
    # No config-based time off for PGY-1. Webapp will pass this directly.
    return {}
