import argparse
import sys
from pathlib import Path

# Archived shift-swap tool; keep imports working when run from repo root.
_SHIFTSWAP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_SHIFTSWAP_ROOT))

from shiftoptim.ingest import build_schedule
from shiftoptim.optimizer import optimize
from shiftoptim.report import format_log
from shiftoptim.render import render_html
from shiftoptim.config import DEFAULT_MAX_SWAPS_PER_PERSON, ALLOW_MULTI_SWAPS
import shiftoptim.config as config


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ics", default=str(_SHIFTSWAP_ROOT / "data" / "schedule.ics"))
    ap.add_argument("--prefs", default=str(_SHIFTSWAP_ROOT / "data" / "preferences.csv"))
    ap.add_argument("-K", "--max-swaps-per-person", type=int,
                    default=DEFAULT_MAX_SWAPS_PER_PERSON,
                    help="max swaps per person (-1 = unlimited, default: 3)")
    ap.add_argument("-n", "--max-cycle", type=int,
                    default=3 if ALLOW_MULTI_SWAPS else 2)
    ap.add_argument("--allow-jeopardy-swaps", action="store_true",
                    help="allow jeopardy/backup shifts to participate in trading")
    ap.add_argument("--html", default="shiftswap.html",
                    help="output path for HTML report (default: shiftswap.html)")
    ap.add_argument("--complete", action="store_true",
                    help="run complete mode (iterative graph rebuilding)")
    args = ap.parse_args()
    assert args.max_cycle <= 3, "max cycle length capped at 3"

    if args.allow_jeopardy_swaps:
        config.ALLOW_JEOPARDY_SWAPS = True

    sched = build_schedule(Path(args.ics), Path(args.prefs))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}

    log = optimize(sched, max_swaps_per_person=args.max_swaps_per_person,
                   n_max=args.max_cycle, complete=args.complete)

    print(format_log(log, sched))

    html = render_html(sched, log, original_assignment)
    out = Path(args.html)
    out.write_text(html, encoding="utf-8")
    print(f"\nHTML report → {out.resolve()}")


if __name__ == "__main__":
    main()
