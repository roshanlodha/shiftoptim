"""Cross-block Morning/Swing/Overnight ledger, carried in/out via data/shift_history.csv.

This is a generated running total (not an input), so it stays CSV-backed even
though the roster and time-off data were moved to hardcoded Python.
"""

import csv
import os

from .config import HISTORY_CSV, SHIFTS, SHIFT_TYPES


def load_history():
    """Returns dict: last_name -> {"half_blocks_worked": n, "shifts": {shift_name: count}}."""
    history = {}
    if not os.path.exists(HISTORY_CSV):
        return history
    shift_names = [info["name"] for info in SHIFTS.values()]
    with open(HISTORY_CSV, newline="") as f:
        for row in csv.DictReader(f):
            history[row["resident"]] = {
                "half_blocks_worked": int(row["half_blocks_worked"]),
                "shifts": {name: int(row.get(name, 0)) for name in shift_names},
            }
    return history


def history_type_totals(entry):
    """Sums a history entry's per-shift counts into Morning/Swing/Overnight totals."""
    totals = {t: 0 for t in SHIFT_TYPES}
    for info in SHIFTS.values():
        totals[info["type"]] += entry["shifts"].get(info["name"], 0)
    return totals


def empty_entry():
    return {"half_blocks_worked": 0, "shifts": {info["name"]: 0 for info in SHIFTS.values()}}


def save_history(history):
    os.makedirs(os.path.dirname(HISTORY_CSV), exist_ok=True)
    shift_names = [info["name"] for info in SHIFTS.values()]
    with open(HISTORY_CSV, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["resident", "half_blocks_worked"] + shift_names + list(SHIFT_TYPES))
        for name, entry in sorted(history.items()):
            totals = history_type_totals(entry)
            writer.writerow(
                [name, entry["half_blocks_worked"]]
                + [entry["shifts"].get(sn, 0) for sn in shift_names]
                + [totals[t] for t in SHIFT_TYPES]
            )
