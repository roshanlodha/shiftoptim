import argparse
from pathlib import Path
from shiftmaxxer.ingest import build_schedule
from shiftmaxxer.optimizer import optimize
from shiftmaxxer.report import format_log
from shiftmaxxer.render import render_html
from shiftmaxxer.config import DEFAULT_MAX_SWAPS_PER_PERSON, ALLOW_MULTI_SWAPS
import shiftmaxxer.config as config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ics", default="data/ics")
    ap.add_argument("--prefs", default="data/preferences.csv")
    ap.add_argument("-K", "--max-swaps-per-person", type=int,
                    default=DEFAULT_MAX_SWAPS_PER_PERSON,
                    help="max swaps per person (-1 = unlimited, default: 3)")
    ap.add_argument("-n", "--max-cycle", type=int,
                    default=3 if ALLOW_MULTI_SWAPS else 2)
    ap.add_argument("--allow-jeopardy-swaps", action="store_true",
                    help="allow jeopardy/backup shifts to participate in trading")
    ap.add_argument("--html", default="shiftswap.html",
                    help="output path for HTML report (default: shiftswap.html)")
    args = ap.parse_args()
    assert args.max_cycle <= 3, "max cycle length capped at 3"

    if args.allow_jeopardy_swaps:
        config.ALLOW_JEOPARDY_SWAPS = True

    sched = build_schedule(Path(args.ics), Path(args.prefs))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}

    log = optimize(sched, max_swaps_per_person=args.max_swaps_per_person,
                   n_max=args.max_cycle)

    print(format_log(log, sched))

    html = render_html(sched, log, original_assignment)
    out = Path(args.html)
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML report → {out.resolve()}")


if __name__ == "__main__":
    main()
