from dataclasses import dataclass
from .graph import build_trade_graph, find_cycles
from .utility import utility
from .feasibility import is_valid
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
        proposed = [sched.shifts[x] for x in uids]
        if not is_valid(proposed, r.days_off):
            return None
        before = utility(sched.shifts_of(name), r)
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


def optimize(sched: Schedule, K: int, n_max: int) -> list[CycleResult]:
    executed, log = 0, []
    while executed < K:
        G = build_trade_graph(sched)
        candidates = []
        for cyc in find_cycles(G, n_max):
            res = evaluate_cycle(cyc, sched)
            if res and (executed + len(res.cycle)) <= K:
                candidates.append(res)
        if not candidates:
            break
        candidates.sort(key=lambda r: r.total_delta, reverse=True)
        best = candidates[0]
        apply_cycle(best, sched)
        executed += len(best.cycle)
        log.append(best)
    return log
