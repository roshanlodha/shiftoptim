"""Writes the per-block schedule grid and shift-count summary CSVs."""

import csv
import os

from .config import OUTPUT_DIR, SHIFT_TYPES, SHIFTS
from .history import history_type_totals


def export_grid(result):
    dates = result["dates"]
    assignments = result["assignments"]
    grid_path = os.path.join(OUTPUT_DIR, f"block{result['block']}_grid.csv")
    with open(grid_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Shift"] + [d.isoformat() for d in dates])
        for s, info in SHIFTS.items():
            row = [info["name"]] + [assignments.get((d, s), "") for d in dates]
            writer.writerow(row)
    return grid_path


def export_shift_summary(result):
    """One row per resident: count of each shift worked THIS block, plus
    Morning/Swing/Overnight subtotals and a total, for the block just solved
    (not the cumulative cross-block history)."""
    residents = result["residents"]
    solver = result["solver"]
    works = result["works"]
    num_days = len(result["dates"])
    shift_names = [info["name"] for info in SHIFTS.values()]

    summary_path = os.path.join(OUTPUT_DIR, f"block{result['block']}_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["resident"] + shift_names + list(SHIFT_TYPES) + ["total"])
        for r, name in enumerate(residents):
            counts = {info["name"]: 0 for info in SHIFTS.values()}
            for d in range(num_days):
                for s, info in SHIFTS.items():
                    if solver.Value(works[(r, d, s)]):
                        counts[info["name"]] += 1
            entry = {"shifts": counts}
            totals = history_type_totals(entry)
            writer.writerow(
                [name]
                + [counts[sn] for sn in shift_names]
                + [totals[t] for t in SHIFT_TYPES]
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
        totals = history_type_totals(entry)
        print(
            f"  - {name:20s} half_blocks_worked={entry['half_blocks_worked']} "
            f"Morning={totals['Morning']:>3} Swing={totals['Swing']:>3} Overnight={totals['Overnight']:>3}"
        )
