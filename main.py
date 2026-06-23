import argparse
from pathlib import Path
from shiftmaxxer.ingest import build_schedule
from shiftmaxxer.optimizer import optimize
from shiftmaxxer.report import format_log
from shiftmaxxer.config import DEFAULT_MAX_TOTAL_SWAPS, DEFAULT_MAX_CYCLE_LENGTH


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ics", default="data/ics")
    ap.add_argument("--prefs", default="data/preferences.csv")
    ap.add_argument("-K", "--max-swaps", type=int, default=DEFAULT_MAX_TOTAL_SWAPS)
    ap.add_argument("-n", "--max-cycle", type=int, default=DEFAULT_MAX_CYCLE_LENGTH)
    args = ap.parse_args()
    assert args.max_cycle <= 3, "max cycle length capped at 3"

    sched = build_schedule(Path(args.ics), Path(args.prefs))
    log = optimize(sched, K=args.max_swaps, n_max=args.max_cycle)
    print(format_log(log))


if __name__ == "__main__":
    main()
