"""Builds and solves the CP-SAT model for one full 4-week block."""

from ortools.sat.python import cp_model

from . import constraints, objective
from .config import EXTRA_SHIFT, SHIFT_MIN_PER_HALF, SHIFTS, WEEKEND_DAYS
from .history import empty_entry
from .inputs import load_block, load_timeoff


def _prior_shifts_by_index(residents, prior_last_shifts):
    if not prior_last_shifts:
        return None
    by_index = {}
    for r, name in enumerate(residents):
        if name in prior_last_shifts:
            by_index[r] = prior_last_shifts[name]
    return by_index or None


def build_and_solve(block, shift_min_per_half=SHIFT_MIN_PER_HALF, max_time_seconds=60.0,
                     block_input=None, timeoff=None, history=None, balance_weights=None,
                     prior_last_shifts=None):
    """Solves one full block.

    By default loads roster/dates from config.ini and time off from config.ini.
    Callers (e.g. the web app) pass `block_input`, `timeoff`, and `history`
    directly. History defaults to {} when omitted.
    """
    dates, residents, role_on, active_halves = block_input if block_input is not None else load_block(block)
    num_residents = len(residents)

    def role_at(name, d):
        return role_on.get((name, dates[d]))

    if timeoff is None:
        timeoff = load_timeoff()
    if history is None:
        history = {}

    model = cp_model.CpModel()
    works = {
        (r, d, s): model.NewBoolVar(f"works_r{r}_d{d}_s{s}")
        for r in range(num_residents)
        for d in range(len(dates))
        for s in SHIFTS
    }

    constraints.add_all_hard_constraints(model, works, dates, residents, role_at,
                                          active_halves, shift_min_per_half,
                                          _prior_shifts_by_index(residents, prior_last_shifts))

    penalties = []
    timeoff_violations = objective.add_timeoff_penalties(
        model, works, dates, residents, timeoff, penalties)
    objective.add_nights_and_flex_penalties(model, works, dates, residents, role_at, penalties)
    objective.add_relief_shift_penalties(model, works, dates, num_residents, penalties)
    objective.add_isolated_night_penalties(model, works, num_residents, len(dates), penalties)
    objective.add_split_weekend_penalties(model, works, dates, num_residents, penalties)
    objective.add_evenness_penalties(
        model, works, dates, residents, role_at, history, active_halves, penalties,
        balance_weights=balance_weights)

    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_seconds
    solver.parameters.num_search_workers = 2
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"[Block {block}] No feasible schedule found.")
        return None

    violated = [(name, date, s) for name, date, s, v in timeoff_violations if solver.Value(v)]
    if violated:
        print(f"[Block {block}] WARNING: {len(violated)} time-off request(s) violated:")
        for name, date, s in violated:
            print(f"  - {name} scheduled for {SHIFTS[s]['name']} on {date} despite requested time off")

    extra_used = [(name, dates[d]) for r, name in enumerate(residents) for d in range(len(dates))
                  if solver.Value(works[(r, d, EXTRA_SHIFT)])]
    if extra_used:
        print(f"[Block {block}] Relief shift (FF/Ex Swing) used {len(extra_used)} time(s):")
        for name, date in extra_used:
            print(f"  - {name} on {date} ({date.strftime('%A')})")

    assignments = {}
    for r, name in enumerate(residents):
        for d in range(len(dates)):
            for s in SHIFTS:
                if solver.Value(works[(r, d, s)]):
                    assignments[(dates[d], s)] = name

    for r, name in enumerate(residents):
        entry = history.setdefault(name, empty_entry())
        entry["half_blocks_worked"] += active_halves[name]
        for d in range(len(dates)):
            for s, info in SHIFTS.items():
                if solver.Value(works[(r, d, s)]):
                    entry["shifts"][info["name"]] = entry["shifts"].get(info["name"], 0) + 1
                    if dates[d].weekday() in WEEKEND_DAYS:
                        entry["weekend"] = entry.get("weekend", 0) + 1

    return {
        "block": block,
        "dates": dates,
        "residents": residents,
        "active_halves": active_halves,
        "assignments": assignments,
        "history": history,
        "solver": solver,
        "works": works,
        "num_residents": num_residents,
    }
