"""Cross-block ledger of shift/weekend counts, carried in/out via data/history.json.

This is a generated running total (not an input). It's JSON-backed so that new
per-resident fields (e.g. weekend counts) can be added without a CSV schema
migration.
"""

import json
import os

from . import config
from .config import BALANCE_CATEGORIES, SHIFTS, WEEKEND_DAYS


def load_history():
    """Returns dict: last_name -> {"half_blocks_worked": n, "shifts": {shift_name: count}, "weekend": count}.

    Returns {} if history.json doesn't exist yet, so the first block balances
    evenly on its own with no carry-in.
    """
    if not os.path.exists(config.HISTORY_JSON):
        return {}
    with open(config.HISTORY_JSON) as f:
        raw = json.load(f)
    shift_names = [info["name"] for info in SHIFTS.values()]
    history = {}
    for name, entry in raw.items():
        shifts = entry.get("shifts", {})
        history[name] = {
            "half_blocks_worked": entry.get("half_blocks_worked", 0),
            "shifts": {sn: shifts.get(sn, 0) for sn in shift_names},
            "weekend": entry.get("weekend", 0),
        }
    return history


def category_totals(entry):
    """Sums a history entry's per-shift counts into the named balance
    categories (Morning/Swing/MGH/BWH/Pedi/FT), plus the standalone weekend
    counter."""
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


def save_history(history):
    os.makedirs(os.path.dirname(config.HISTORY_JSON), exist_ok=True)
    with open(config.HISTORY_JSON, "w") as f:
        json.dump(history, f, indent=2, sort_keys=True)


def is_weekend(date):
    return date.weekday() in WEEKEND_DAYS
