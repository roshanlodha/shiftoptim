def format_log(log) -> str:
    if not log:
        return "No beneficial, ACGME-valid, Pareto-improving swaps found."
    lines = []
    for i, res in enumerate(log, 1):
        lines.append(f"=== Swap {i} (total happiness +{res.total_delta:.3f}) ===")
        for giver, u, v in res.moves:
            lines.append(f"  {giver}: gives {u} -> receives {v} "
                         f"(Δ happiness {res.deltas.get(giver, 0):+.3f})")
    return "\n".join(lines)
