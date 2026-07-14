"""Builds and solves the CP-SAT model for one full 4-week block for PGY-1."""

from ortools.sat.python import cp_model

from . import constraints, objective
from .config import SHIFTS, SHIFT_MIN_PER_HALF, WEEKEND_DAYS
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
    """Solves one full block for PGY-1."""
    dates, residents, role_on, active_halves = block_input if block_input is not None else load_block(block)
    num_residents = len(residents)

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

    # Add hard constraints
    constraints.add_all_hard_constraints(
        model, works, dates, residents, role_on,
        shift_min_per_half, shift_min_per_half + 1,
        _prior_shifts_by_index(residents, prior_last_shifts),
    )

    # Add soft constraints
    penalties = []
    timeoff_violations = objective.add_timeoff_penalties(
        model, works, dates, residents, timeoff, penalties
    )
    objective.add_night_structure_penalties(model, works, dates, residents, penalties)
    objective.add_night_target_penalties(model, works, dates, residents, role_on, penalties)
    objective.add_evenness_penalties(
        model, works, dates, residents, role_on, history, active_halves, penalties,
        balance_weights=balance_weights
    )

    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_time_seconds
    solver.parameters.num_search_workers = 2
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print(f"[Block {block}] No feasible schedule found.")
        return None

    # Report time-off violations
    violated = [(name, date, s) for name, date, s, v in timeoff_violations if solver.Value(v)]
    if violated:
        print(f"[Block {block}] WARNING: {len(violated)} time-off request(s) violated:")
        for name, date, s in violated:
            print(f"  - {name} scheduled for {SHIFTS[s]['name']} on {date} despite requested time off")

    # Assignments map: (date, name) -> shift_id
    assignments = {}
    for r, name in enumerate(residents):
        for d in range(len(dates)):
            for s in SHIFTS:
                if solver.Value(works[(r, d, s)]):
                    assignments[(dates[d], name)] = s

    # Update cumulative history
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
