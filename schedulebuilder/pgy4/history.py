"""Cross-block ledger helpers: empty entries and category rollups used by the
solver objective and the web UI. Persistent history lives in published
assignments (SQLite), not files."""

from .config import BALANCE_CATEGORIES, SHIFTS, WEEKEND_DAYS


def category_totals(entry):
    """Sums a history entry's per-shift counts into balance categories."""
    shift_names_by_id = {sid: info["name"] for sid, info in SHIFTS.items()}
    totals = {}
    for category, shift_ids in BALANCE_CATEGORIES.items():
        totals[category] = sum(entry["shifts"].get(shift_names_by_id[sid], 0) for sid in shift_ids)
    totals["Weekend"] = entry.get("weekend", 0)
    return totals


def empty_entry():
    return {
        "half_blocks_worked": 0,
        "shifts": {info["name"]: 0 for info in SHIFTS.values()},
        "weekend": 0,
    }


def is_weekend(date):
    return date.weekday() in WEEKEND_DAYS
