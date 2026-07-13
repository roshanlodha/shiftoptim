"""CLI entrypoint for the PGY-1 ED schedule builder.

Solves one full 4-week block at a time (e.g. "4", "5"), using the roster/
rotations in data/Final Intern Year 2026-2027 Block Schedules - PGY-1.csv.
"""

import argparse

from .config import SHIFT_MIN_PER_HALF
from .export import export_outputs
from .solver import build_and_solve
from .verify import verify


def main():
    parser = argparse.ArgumentParser(description="Build PGY-1 ED schedule for a full 4-week block.")
    parser.add_argument("blocks", nargs="*", default=["4", "5"],
                         help="Block numbers to solve in order, e.g. 4 5")
    parser.add_argument("--min", type=int, default=SHIFT_MIN_PER_HALF,
                         help="Minimum shifts owed per active 2-week half (default 10)")
    parser.add_argument("--time", type=float, default=60.0)
    args = parser.parse_args()

    history = {}
    for block in args.blocks:
        result = build_and_solve(block, shift_min_per_half=args.min, max_time_seconds=args.time,
                                 history=history)
        if result is None:
            continue
        verify(result)
        export_outputs(result)
        history = result["history"]


if __name__ == "__main__":
    main()
