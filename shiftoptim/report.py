def format_swap(result, sched=None) -> str:
    """Return a human-readable description of a single proposed swap."""
    lines = [f"Proposed swap (total happiness +{result.total_delta:.3f}):"]
    for giver, u, v in result.moves:
        give_name = sched.shifts[u].summary if sched else u
        recv_name = sched.shifts[v].summary if sched else v
        lines.append(f"  {giver}: gives '{give_name}' -> receives '{recv_name}' "
                     f"(Δ happiness {result.deltas.get(giver, 0):+.3f})")
    return "\n".join(lines)





def format_log(log, sched=None) -> str:
    if not log:
        return "No beneficial, ACGME-valid, Pareto-improving swaps found."
    lines = []
    for i, res in enumerate(log, 1):
        lines.append(f"=== Swap {i} (total happiness +{res.total_delta:.3f}) ===")
        for giver, u, v in res.moves:
            give_name = sched.shifts[u].summary if sched else u
            recv_name = sched.shifts[v].summary if sched else v
            lines.append(f"  {giver}: gives '{give_name}' -> receives '{recv_name}' "
                         f"(Δ happiness {res.deltas.get(giver, 0):+.3f})")
    return "\n".join(lines)
