from __future__ import annotations
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from .graph import build_trade_graph, find_cycles
from .utility import utility
from .feasibility import is_valid_swap
from .models import Schedule


@dataclass
class CycleResult:
    cycle: list[str]                 # ordered shift uids
    deltas: dict[str, float]         # resident -> delta utility (vs original snapshot)
    total_delta: float
    moves: list[tuple[str, str, str]]  # (giver, shift_given, shift_received)


def _apply_map(cycle: list[str], sched: Schedule):
    """Cycle [u0,u1,...,uk]: owner of u_t gives u_t, receives u_{t+1 mod k}."""
    k = len(cycle)
    moves = []
    for t in range(k):
        u = cycle[t]; v = cycle[(t + 1) % k]
        giver = sched.shifts[u].owner
        moves.append((giver, u, v))
    return moves


def evaluate_cycle(cycle: list[str], sched: Schedule) -> CycleResult | None:
    moves = _apply_map(cycle, sched)
    # Build proposed shift lists per involved resident.
    involved = {}
    for giver, u, v in moves:
        cur = involved.setdefault(giver, set(s.uid for s in sched.shifts_of(giver)))
        cur.discard(u); cur.add(v)

    deltas = {}
    for name, uids in involved.items():
        r = sched.residents[name]
        current = sched.shifts_of(name)
        proposed = [sched.shifts[x] for x in uids]
        if not is_valid_swap(proposed, current, r.days_off):
            return None
        before = utility(current, r)
        after = utility(proposed, r)
        if after < before - 1e-9:                  # Pareto: nobody worse
            return None
        deltas[name] = after - before

    if not any(d > 1e-9 for d in deltas.values()):  # at least one strictly better
        return None
    return CycleResult(cycle, deltas, sum(deltas.values()), moves)


def apply_cycle(result: CycleResult, sched: Schedule):
    for giver, u, v in result.moves:
        sched.assignment[giver].discard(u)
    for giver, u, v in result.moves:
        sched.assignment[giver].add(v)
        sched.shifts[v] = sched.shifts[v].__class__(  # reassign owner
            **{**sched.shifts[v].__dict__, "owner": giver})


def _resident_shift_set_after(
    name: str,
    orig_uids: set[str],
    trades: list[CycleResult],
) -> set[str]:
    """Return the uid set for ``name`` after applying a list of trades
    (each move is a simple give-u / receive-v for that resident)."""
    uids = set(orig_uids)
    for trade in trades:
        for giver, u, v in trade.moves:
            if giver == name:
                uids.discard(u)
                uids.add(v)
    return uids


def _can_add(
    candidate: CycleResult,
    sched: Schedule,
    orig_uids: dict[str, set[str]],
    orig_util: dict[str, float],
    res_trades: dict[str, list[CycleResult]],
) -> bool:
    """Return True iff adding ``candidate`` to the selected set keeps every
    participant independently feasible and Pareto-improving for every non-empty
    subset of their selected trades that includes the candidate.

    Subsets that do *not* include the candidate were already verified when each
    earlier trade was selected, so we only need to check subsets that include it.
    """
    for name in candidate.deltas:
        r = sched.residents[name]
        orig_shifts = [sched.shifts[uid] for uid in orig_uids[name]]
        prior = res_trades.get(name, [])
        # Enumerate every subset of prior trades combined with the candidate.
        for size in range(len(prior) + 1):
            for combo in combinations(prior, size):
                subset = list(combo) + [candidate]
                uid_set = _resident_shift_set_after(name, orig_uids[name], subset)
                proposed = [sched.shifts[uid] for uid in uid_set]
                if not is_valid_swap(proposed, orig_shifts, r.days_off):
                    return False
                if utility(proposed, r) < orig_util[name] - 1e-9:
                    return False
    return True


def optimize_limited(sched: Schedule, max_swaps_per_person: int, n_max: int) -> list[CycleResult]:
    """Select a set of Pareto-improving trades that are fully independent.

    Every selected trade is evaluated against the original schedule snapshot.
    Any subset of the returned trades, applied in any order, is ACGME-legal
    and leaves no resident's utility below their original value.

    Parameters
    ----------
    max_swaps_per_person : int
        Maximum number of trades any single resident may participate in
        (any role). -1 means unlimited. This also bounds the per-resident
        all-subset verification cost at 2^cap subsets.
    """
    # --- Snapshot the original schedule state. sched is NOT mutated until
    #     after the full selection pass. ---
    orig_uids: dict[str, set[str]] = {
        n: set(uids) for n, uids in sched.assignment.items()
    }
    orig_util: dict[str, float] = {
        n: utility(sched.shifts_of(n), sched.residents[n])
        for n in sched.assignment
    }

    # Build trade graph once against the original schedule.
    G = build_trade_graph(sched, locked=set())

    # Evaluate every cycle against the original snapshot.
    candidates: list[CycleResult] = []
    for cyc in find_cycles(G, n_max):
        res = evaluate_cycle(cyc, sched)
        if res is not None:
            candidates.append(res)

    # Sort by total utility gain, descending.
    candidates.sort(key=lambda r: r.total_delta, reverse=True)

    # Greedy shift-disjoint selection with all-subset independence check.
    used_shifts: set[str] = set()              # shift uids already committed
    participation: dict[str, int] = {}         # resident -> trades selected
    res_trades: dict[str, list[CycleResult]] = {}  # resident -> selected trades
    selected: list[CycleResult] = []

    for cand in candidates:
        # Shift-disjointness: skip if any shift uid is already committed.
        cand_shifts = {u for _, u, v in cand.moves} | {v for _, u, v in cand.moves}
        if cand_shifts & used_shifts:
            continue

        # Per-person participation cap.
        if max_swaps_per_person != -1:
            if any(participation.get(name, 0) + 1 > max_swaps_per_person
                   for name in cand.deltas):
                continue

        # Independence check: every subset of each participant's trades
        # that includes this candidate must be legal and Pareto vs original.
        if not _can_add(cand, sched, orig_uids, orig_util, res_trades):
            continue

        # Accept the candidate.
        selected.append(cand)
        used_shifts |= cand_shifts
        for name in cand.deltas:
            participation[name] = participation.get(name, 0) + 1
            res_trades.setdefault(name, []).append(cand)

    # Apply all selected trades to sched to produce the final schedule.
    # Because selected trades are shift-disjoint, order is irrelevant.
    for trade in selected:
        apply_cycle(trade, sched)

    return selected


def optimize_complete(sched: Schedule, max_swaps_per_person: int, n_max: int) -> list[CycleResult]:
    """Iteratively apply best Pareto-improving cycles, rebuilding the graph at each step.

    This matches the old version of the algorithm, where the trade graph is rebuilt
    from the mutated schedule, and the single best Pareto-improving cycle is applied.
    Shifts from applied cycles are locked to prevent chaining/dependent trades.
    """
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

        # Fairness: prefer cycles involving residents with fewest swaps so far.
        min_swaps = min(swap_count.get(n, 0) for n in sched.assignment)
        priority = [r for r in candidates
                    if any(swap_count.get(n, 0) == min_swaps for n in r.deltas)]
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


def optimize(sched: Schedule, max_swaps_per_person: int, n_max: int, complete: bool = False) -> list[CycleResult]:
    if complete:
        return optimize_complete(sched, max_swaps_per_person, n_max)
    return optimize_limited(sched, max_swaps_per_person, n_max)
