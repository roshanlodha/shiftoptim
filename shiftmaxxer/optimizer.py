from dataclasses import dataclass
from .graph import build_trade_graph, find_cycles
from .utility import utility
from .feasibility import is_valid_swap
from .models import Schedule


@dataclass
class CycleResult:
    cycle: list[str]                 # ordered shift uids
    deltas: dict[str, float]         # resident -> delta utility
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


def optimize(sched: Schedule, max_swaps_per_person: int, n_max: int) -> list[CycleResult]:
    """Iteratively apply best Pareto-improving cycles.

    Parameters
    ----------
    max_swaps_per_person : int
        Maximum number of swaps any single resident may participate in.
        -1 means unlimited.
    """
    from collections import Counter
    swap_count: Counter = Counter()   # resident name -> swaps used
    log: list[CycleResult] = []

    while True:
        G = build_trade_graph(sched)
        candidates = []
        for cyc in find_cycles(G, n_max):
            res = evaluate_cycle(cyc, sched)
            if res is None:
                continue
            # Per-person cap check (-1 = unlimited)
            if max_swaps_per_person != -1:
                involved_names = set(res.deltas.keys())
                if any(swap_count[n] + 1 > max_swaps_per_person
                       for n in involved_names):
                    continue
            candidates.append(res)
        if not candidates:
            break
        # Fairness: prefer swaps involving residents with fewest swaps so far.
        # This prevents one pair from monopolizing the swap budget and
        # leaving others with no uncapped partners.
        min_swaps = min(swap_count.get(n, 0) for n in sched.assignment)
        priority = [r for r in candidates
                    if any(swap_count.get(n, 0) == min_swaps
                           for n in r.deltas)]
        pool = priority if priority else candidates
        pool.sort(key=lambda r: r.total_delta, reverse=True)
        best = pool[0]
        apply_cycle(best, sched)
        for name in best.deltas:
            swap_count[name] += 1
        log.append(best)
    return log
