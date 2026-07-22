"""Shift optimization and trade graph engine.

Provides Pareto-improving trade discovery (both Complete and Limited modes)
for resident shift schedules.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from itertools import combinations
from typing import Optional

STREAK_BETA = 5
MIN_REST = datetime.strptime("12", "%H") - datetime.strptime("0", "%H")  # timedelta(hours=12)
MAX_CONSECUTIVE_DAYS = 6
TIME_DIFF_WEIGHT = 0.02


@dataclass(frozen=True)
class Shift:
    uid: str                  # Unique key
    owner: str                # Resident identifier/name
    t_start: datetime         # Start time
    t_end: datetime           # End time
    loc: Optional[str]        # "MGH" | "BWH" | None
    type: Optional[str]       # "Morning" | "Swing" | "Overnight" | None
    work_date: date           # Local calendar date
    summary: str              # Shift name
    is_jeopardy: bool         # Backup shift toggle


@dataclass
class Resident:
    name: str
    loc_pref: str             # "MGH" | "BWH" | "ANY"
    loc_weight: float
    type_pref: str            # "Morning" | "Swing" | "ANY"
    type_weight: float
    days_pref: int            # Ideal consecutive days (2..6)
    days_weight: float
    days_off: frozenset[date] # Dates requiring no shift
    orig_hours: float = 0.0


@dataclass
class Schedule:
    assignment: dict[str, set[str]]      # Resident name -> set of shift uids
    shifts: dict[str, Shift]             # uid -> Shift
    residents: dict[str, Resident]       # Name -> Resident

    def __post_init__(self):
        for name, r in self.residents.items():
            if r.orig_hours == 0.0 and name in self.assignment:
                r_shifts = self.shifts_of(name)
                r.orig_hours = sum((s.t_end - s.t_start).total_seconds() / 3600.0 for s in r_shifts)

    def shifts_of(self, name: str) -> list[Shift]:
        return [self.shifts[u] for u in self.assignment.get(name, set())]


@dataclass
class CycleResult:
    cycle: list[str]                   # Ordered shift uids
    deltas: dict[str, float]           # Resident -> delta utility
    total_delta: float
    moves: list[tuple[str, str, str]]  # (giver, shift_given, shift_received)


# --- Feasibility Checks ---

def _streaks(work_dates: set[date]) -> list[int]:
    if not work_dates:
        return []
    ordered = sorted(work_dates)
    lengths, run = [], 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days == 1:
            run += 1
        else:
            lengths.append(run)
            run = 1
    lengths.append(run)
    return lengths


def _count_violations(shifts: list[Shift]) -> int:
    if not shifts:
        return 0
    ordered = sorted(shifts, key=lambda s: s.t_start)
    rest = sum(1 for a, b in zip(ordered, ordered[1:]) if b.t_start - a.t_end < MIN_REST)
    streak = sum(1 for L in _streaks({s.work_date for s in shifts}) if L > MAX_CONSECUTIVE_DAYS)
    return rest + streak


def _has_overlap(shifts: list[Shift]) -> bool:
    ordered = sorted(shifts, key=lambda s: s.t_start)
    for a, b in zip(ordered, ordered[1:]):
        if b.t_start < a.t_end:
            return True
    return False


def is_valid_swap(proposed: list[Shift], current: list[Shift], days_off: frozenset[date]) -> bool:
    if proposed and current:
        if max(s.work_date for s in proposed) > max(s.work_date for s in current):
            return False
    for s in proposed:
        if s.work_date in days_off:
            return False
    if _has_overlap(proposed):
        return False
    return _count_violations(proposed) <= _count_violations(current)


# --- Utility Functions ---

def phi_loc(shifts: list[Shift], r: Resident) -> float:
    located = [s for s in shifts if s.loc is not None]
    if r.loc_pref == "ANY" or not located:
        return 1.0
    return sum(1 for s in located if s.loc == r.loc_pref) / len(located)


def phi_type(shifts: list[Shift], r: Resident) -> float:
    typed = [s for s in shifts if s.type is not None]
    if r.type_pref == "ANY" or not typed:
        return 1.0
    return sum(1 for s in typed if s.type == r.type_pref) / len(typed)


def phi_str(shifts: list[Shift], r: Resident) -> float:
    runs = _streaks({s.work_date for s in shifts})
    if not runs:
        return 1.0
    mean_dev = sum(abs(L - r.days_pref) for L in runs) / len(runs)
    return max(0.0, 1.0 - mean_dev / STREAK_BETA)


def utility(shifts: list[Shift], r: Resident) -> float:
    base_utility = (
        r.loc_weight * phi_loc(shifts, r)
        + r.type_weight * phi_type(shifts, r)
        + r.days_weight * phi_str(shifts, r)
    )
    if TIME_DIFF_WEIGHT == 0.0:
        return base_utility
    curr_hours = sum((s.t_end - s.t_start).total_seconds() / 3600.0 for s in shifts)
    additional_shift_time = curr_hours - r.orig_hours
    return base_utility - (TIME_DIFF_WEIGHT * additional_shift_time)


# --- Trade Graph Construction ---

def build_trade_graph(sched: Schedule, locked: set[str]) -> dict[str, list[str]]:
    G: dict[str, list[str]] = {u: [] for u in sched.shifts if u not in locked}
    for u, su in sched.shifts.items():
        if u in locked or su.is_jeopardy:
            continue
        owner_u = su.owner
        r_u = sched.residents[owner_u]
        cur_u = sched.shifts_of(owner_u)
        base_u_util = utility(cur_u, r_u)

        for v, sv in sched.shifts.items():
            if v in locked or u == v or sv.is_jeopardy:
                continue
            if sv.owner == owner_u:
                continue
            if (su.type == "Overnight") != (sv.type == "Overnight"):
                continue

            prop_u_uids = (set(s.uid for s in cur_u) - {u}) | {v}
            prop_u = [sched.shifts[x] for x in prop_u_uids]

            if not is_valid_swap(prop_u, cur_u, r_u.days_off):
                continue
            if utility(prop_u, r_u) < base_u_util - 1e-9:
                continue

            G[u].append(v)
    return G


def find_cycles(G: dict[str, list[str]], max_len: int = 3) -> list[list[str]]:
    cycles = []
    nodes = list(G.keys())
    for u in nodes:
        for v in G.get(u, []):
            if v == u:
                continue
            if u in G.get(v, []):
                if u < v:
                    cycles.append([u, v])
            if max_len >= 3:
                for w in G.get(v, []):
                    if w == u or w == v:
                        continue
                    if u in G.get(w, []):
                        if u < v and u < w:
                            cycles.append([u, v, w])
    return cycles


# --- Cycle Evaluation & Execution ---

def _apply_map(cycle: list[str], sched: Schedule):
    k = len(cycle)
    moves = []
    for t in range(k):
        u = cycle[t]
        v = cycle[(t + 1) % k]
        giver = sched.shifts[u].owner
        moves.append((giver, u, v))
    return moves


def evaluate_cycle(cycle: list[str], sched: Schedule) -> CycleResult | None:
    moves = _apply_map(cycle, sched)
    involved: dict[str, set[str]] = {}
    for giver, u, v in moves:
        cur = involved.setdefault(giver, set(s.uid for s in sched.shifts_of(giver)))
        cur.discard(u)
        cur.add(v)

    deltas = {}
    for name, uids in involved.items():
        r = sched.residents[name]
        current = sched.shifts_of(name)
        proposed = [sched.shifts[x] for x in uids]
        if not is_valid_swap(proposed, current, r.days_off):
            return None
        before = utility(current, r)
        after = utility(proposed, r)
        if after < before - 1e-9:
            return None
        deltas[name] = after - before

    if not any(d > 1e-9 for d in deltas.values()):
        return None
    return CycleResult(cycle, deltas, sum(deltas.values()), moves)


def apply_cycle(result: CycleResult, sched: Schedule):
    for giver, u, v in result.moves:
        sched.assignment[giver].discard(u)
    for giver, u, v in result.moves:
        sched.assignment[giver].add(v)
        sched.shifts[v] = Shift(**{**sched.shifts[v].__dict__, "owner": giver})


def optimize_complete(sched: Schedule, max_swaps_per_person: int = -1, n_max: int = 2) -> list[CycleResult]:
    swap_count: Counter = Counter()
    locked: set[str] = set()
    log: list[CycleResult] = []

    while True:
        G = build_trade_graph(sched, locked)
        candidates: list[CycleResult] = []
        for cyc in find_cycles(G, n_max):
            res = evaluate_cycle(cyc, sched)
            if res is None:
                continue
            if max_swaps_per_person != -1:
                beneficiary = max(sorted(res.deltas.keys()), key=lambda n: res.deltas[n])
                if swap_count[beneficiary] + 1 > max_swaps_per_person:
                    continue
            candidates.append(res)

        if not candidates:
            break

        min_swaps = min(swap_count.get(n, 0) for n in sched.assignment)
        priority = [r for r in candidates if any(swap_count.get(n, 0) == min_swaps for n in r.deltas)]
        pool = priority if priority else candidates
        pool.sort(key=lambda r: r.total_delta, reverse=True)
        best = pool[0]

        apply_cycle(best, sched)
        for _, u, v in best.moves:
            locked.add(u)
            locked.add(v)
        beneficiary = max(sorted(best.deltas.keys()), key=lambda n: best.deltas[n])
        swap_count[beneficiary] += 1
        log.append(best)

    return log
