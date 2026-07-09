"""CLI entrypoint for the PGY-4 ED schedule builder.

Solves one full 4-week block at a time (e.g. "4", "5"), using the hardcoded
roster/time-off data in schedulebuilder.roster / schedulebuilder.timeoff, and
carries cross-block Morning/Swing/Overnight balance via data/shift_history.csv.
"""

import argparse

from .config import SHIFT_MIN_PER_HALF
from .export import export_outputs
from .history import save_history
from .solver import build_and_solve
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description="Build PGY-4 ED schedule for a full 4-week block.")
    parser.add_argument("blocks", nargs="*", default=["4", "5"],
                         help="Block numbers to solve in order, e.g. 4 5")
    parser.add_argument("--min", type=int, default=SHIFT_MIN_PER_HALF,
                         help="Minimum shifts owed per active 2-week half (default 8)")
    parser.add_argument("--time", type=float, default=60.0)
    args = parser.parse_args()

    for block in args.blocks:
        result = build_and_solve(block, shift_min_per_half=args.min, max_time_seconds=args.time)
        if result is None:
            continue
        verify(result)
        export_outputs(result)
        save_history(result["history"])


if __name__ == "__main__":
    main()
