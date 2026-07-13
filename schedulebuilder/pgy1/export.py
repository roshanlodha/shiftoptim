"""Writes PGY-1 block schedule grid and summary CSVs."""

import csv
import os

from .config import BALANCE_CATEGORIES, OUTPUT_DIR, SHIFTS, WEEKEND_DAYS
from .history import category_totals

CATEGORY_COLUMNS = list(BALANCE_CATEGORIES) + ["Weekend"]


def _week_chunks(dates):
    """Split sorted block dates into calendar weeks (Mon–Sun)."""
    weeks, week = [], []
    for d in dates:
        if week and d.weekday() == 0:
            weeks.append(week)
            week = []
        week.append(d)
    if week:
        weeks.append(week)
    return weeks


def export_grid(result):
    dates = result["dates"]
    assignments = result["assignments"]
    grid_path = os.path.join(OUTPUT_DIR, f"pgy1_block{result['block']}_grid.csv")
    with open(grid_path, "w", newline="") as f:
        writer = csv.writer(f)
        for i, week_dates in enumerate(_week_chunks(dates)):
            if i:
                writer.writerow([])
            writer.writerow(["Shift"] + [d.isoformat() for d in week_dates])
            for s, info in SHIFTS.items():
                # For each date, find if any resident works this shift
                # Note: assignments has keys (date, shift_id)
                # For PGY-1, multiple residents could work the same shift
                # Let's write them comma-separated
                row = [info["name"]]
                for d in week_dates:
                    res_names = []
                    # Find all residents assigned to this (d, s)
                    for (ad, asid), name in assignments.items():
                        if ad == d and asid == s:
                            res_names.append(name)
                    row.append(", ".join(sorted(res_names)))
                writer.writerow(row)
    return grid_path


def export_shift_summary(result):
    """One row per resident: count of each shift worked, plus wellness-balance subtotals."""
    residents = result["residents"]
    solver = result["solver"]
    works = result["works"]
    dates = result["dates"]
    shift_names = [info["name"] for info in SHIFTS.values()]

    summary_path = os.path.join(OUTPUT_DIR, f"pgy1_block{result['block']}_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["resident"] + shift_names + CATEGORY_COLUMNS + ["total"])
        for r, name in enumerate(residents):
            counts = {info["name"]: 0 for info in SHIFTS.values()}
            weekend = 0
            for d, date in enumerate(dates):
                for s, info in SHIFTS.items():
                    if solver.Value(works[(r, d, s)]):
                        counts[info["name"]] += 1
                        if date.weekday() in WEEKEND_DAYS:
                            weekend += 1
            entry = {"shifts": counts, "weekend": weekend}
            totals = category_totals(entry)
            writer.writerow(
                [name]
                + [counts[sn] for sn in shift_names]
                + [totals[c] for c in CATEGORY_COLUMNS]
                + [sum(counts.values())]
            )
    return summary_path


def export_outputs(result):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    block = result["block"]

    grid_path = export_grid(result)
    summary_path = export_shift_summary(result)
    print(f"[Block {block}] Wrote {grid_path} and {summary_path}")

    print(f"[Block {block}] Per-resident summary (cumulative to date):")
    for name in result["residents"]:
        entry = result["history"][name]
        totals = category_totals(entry)
        print(
            f"  - {name:20s} half_blocks_worked={entry['half_blocks_worked']} "
            + " ".join(f"{c}={totals[c]:>3}" for c in CATEGORY_COLUMNS)
        )
