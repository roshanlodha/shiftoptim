import networkx as nx
from .feasibility import is_valid_swap
from .utility import utility
from .models import Schedule
from . import config


def build_trade_graph(sched: Schedule) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(sched.shifts.keys())

    # Precompute each resident's current shifts and baseline utility.
    base_shifts = {n: sched.shifts_of(n) for n in sched.assignment}
    base_util   = {n: utility(base_shifts[n], sched.residents[n])
                   for n in sched.assignment}

    shifts = sched.shifts
    for u, su in shifts.items():
        # If jeopardy swaps are disabled, pin jeopardy shifts entirely.
        if su.is_jeopardy and not config.ALLOW_JEOPARDY_SWAPS:
            continue
        i = su.owner; ri = sched.residents[i]
        for v, sv in shifts.items():
            if sv.owner == i:                      # can't trade with yourself
                continue
            # Jeopardy ↔ regular cross-trading is never allowed.
            if su.is_jeopardy != sv.is_jeopardy:
                continue
            if sv.work_date in ri.days_off:        # explicit day-off rejection
                continue
            proposed = [s for s in base_shifts[i] if s.uid != u] + [sv]
            if not is_valid_swap(proposed, base_shifts[i], ri.days_off):
                continue
            if utility(proposed, ri) >= base_util[i]:
                G.add_edge(u, v)
    return G


def find_cycles(G: nx.DiGraph, n_max: int) -> list[list[str]]:
    assert n_max <= 3, "edge model only valid for cycle length <= 3"
    if n_max == 2:
        # Fast path: mutual edges only.
        seen, out = set(), []
        for u, v in G.edges():
            if G.has_edge(v, u) and (v, u) not in seen:
                seen.add((u, v))
                out.append([u, v])
        return out
    return [c for c in nx.simple_cycles(G, length_bound=n_max) if len(c) >= 2]
