"""Bridges the DB (rotations/time_off/assignments) to the CP-SAT solver."""

import datetime as dt

def _get_config(pgy_level):
    if pgy_level == 1:
        import schedulebuilder.pgy1.config as cfg
        import schedulebuilder.pgy1.solver as slv
    else:
        import schedulebuilder.pgy4.config as cfg
        import schedulebuilder.pgy4.solver as slv
    return cfg, slv


from .settings import load_balance_weights


def _daterange(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def load_block_from_db(conn, pgy_level, block_number):
    """Returns (dates, residents, role_on, active_halves) keyed by last_name."""
    cfg, _ = _get_config(pgy_level)
    halves = conn.execute(
        "SELECT id, half, start_date, end_date FROM half_blocks "
        "WHERE pgy_level = ? AND block_number = ? ORDER BY half",
        (pgy_level, block_number),
    ).fetchall()
    if not halves:
        raise ValueError(f"No half-blocks found for PGY-{pgy_level} block {block_number}")

    dates = []
    role_on = {}
    active_halves = {}
    residents_seen = []

    for half in halves:
        start = dt.date.fromisoformat(half["start_date"])
        end = dt.date.fromisoformat(half["end_date"])
        half_dates = _daterange(start, end)
        dates.extend(half_dates)

        rows = conn.execute(
            "SELECT res.last_name AS last_name, rot.rotation AS rotation "
            "FROM rotations rot JOIN residents res ON res.id = rot.resident_id "
            "WHERE rot.half_block_id = ? AND rot.rotation IN (?, ?, ?)",
            (half["id"], *cfg.ACTIVE_ROLES),
        ).fetchall()
        for row in rows:
            name = row["last_name"]
            if name not in active_halves:
                residents_seen.append(name)
            active_halves[name] = active_halves.get(name, 0) + 1
            for d in half_dates:
                role_on[(name, d)] = row["rotation"]

    dates = sorted(dates)
    return dates, residents_seen, role_on, active_halves


def load_timeoff_from_db(conn):
    """Returns dict: resident last_name -> list of (start_date, end_date)."""
    rows = conn.execute(
        "SELECT res.last_name AS last_name, t.start_date AS start_date, t.end_date AS end_date "
        "FROM time_off t JOIN residents res ON res.id = t.resident_id"
    ).fetchall()
    requests = {}
    for row in rows:
        requests.setdefault(row["last_name"], []).append(
            (dt.date.fromisoformat(row["start_date"]), dt.date.fromisoformat(row["end_date"]))
        )
    return requests


def hours_per_week(hours_worked, half_blocks_worked):
    """Avg weekly hours over clinical half-blocks (~2 weeks each)."""
    if not hours_worked or not half_blocks_worked:
        return 0.0
    return round(hours_worked / (half_blocks_worked * 2), 1)


def load_history_from_db(conn, pgy_level):
    """Cumulative totals from published runs only."""
    cfg, _ = _get_config(pgy_level)
    shift_names = [info["name"] for info in cfg.SHIFTS.values()]
    history = {}
    canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)
    duration_by_name = {info["name"]: info["duration"] for info in cfg.SHIFTS.values()}

    assignment_rows = conn.execute(
        "SELECT res.last_name AS last_name, a.day AS day, a.shift_name AS shift_name "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "JOIN runs r ON r.id = a.run_id "
        "WHERE r.status = 'published' AND r.pgy_level = ?",
        (pgy_level,),
    ).fetchall()
    for row in assignment_rows:
        entry = history.setdefault(row["last_name"], _empty_entry(shift_names))
        sname = canonicalize(row["shift_name"])
        if sname in entry["shifts"]:
            entry["shifts"][sname] += 1
            entry["hours_worked"] = entry.get("hours_worked", 0) + duration_by_name.get(sname, 0)

        day = dt.date.fromisoformat(row["day"])
        if day.weekday() in cfg.WEEKEND_DAYS:
            entry["weekend"] += 1

    run_pairs = conn.execute(
        "SELECT DISTINCT res.last_name AS last_name, hb.block_number AS block_number, hb.half AS half "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "JOIN runs r ON r.id = a.run_id "
        "JOIN half_blocks hb ON hb.pgy_level = r.pgy_level "
        "AND a.day >= hb.start_date AND a.day <= hb.end_date "
        "WHERE r.status = 'published' AND r.pgy_level = ?",
        (pgy_level,),
    ).fetchall()
    half_block_counts = {}
    for row in run_pairs:
        half_block_counts[row["last_name"]] = half_block_counts.get(row["last_name"], 0) + 1
    for last_name, halves in half_block_counts.items():
        history.setdefault(last_name, _empty_entry(shift_names))["half_blocks_worked"] += halves

    for entry in history.values():
        entry["hours_per_week"] = hours_per_week(
            entry.get("hours_worked", 0), entry.get("half_blocks_worked", 0)
        )

    return history


def load_prior_last_shifts(conn, pgy_level, block_number):
    """Published assignments on the calendar day before this block starts."""
    cfg, _ = _get_config(pgy_level)
    halves = conn.execute(
        "SELECT start_date FROM half_blocks "
        "WHERE pgy_level = ? AND block_number = ? ORDER BY half",
        (pgy_level, block_number),
    ).fetchall()
    if not halves:
        return {}
    start_date = min(dt.date.fromisoformat(h["start_date"]) for h in halves)
    prior_day = (start_date - dt.timedelta(days=1)).isoformat()
    canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)
    name_to_id = {info["name"]: sid for sid, info in cfg.SHIFTS.items()}

    rows = conn.execute(
        "SELECT res.last_name AS last_name, a.shift_name AS shift_name "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "JOIN runs r ON r.id = a.run_id "
        "WHERE r.status = 'published' AND r.pgy_level = ? AND a.day = ?",
        (pgy_level, prior_day),
    ).fetchall()
    prior = {}
    for row in rows:
        sname = canonicalize(row["shift_name"])
        shift_id = name_to_id.get(sname)
        if shift_id is not None:
            prior[row["last_name"]] = shift_id
    return prior


def _empty_entry(shift_names):
    return {
        "half_blocks_worked": 0,
        "shifts": {sn: 0 for sn in shift_names},
        "weekend": 0,
        "hours_worked": 0,
        "hours_per_week": 0.0,
    }


def _process_off_services(conn, pgy_level, block_number, off_services):
    if not off_services:
        return
    for os_res in off_services:
        name = os_res["name"].strip()
        if not name:
            continue
        site = os_res["site"]
        half = os_res["half"]
        
        # Find or insert resident
        row = conn.execute(
            "SELECT id FROM residents WHERE last_name = ? AND pgy_level = ?",
            (name, pgy_level)
        ).fetchone()
        if row:
            res_id = row["id"]
        else:
            cur = conn.execute(
                "INSERT INTO residents (full_name, last_name, pgy_level) VALUES (?, ?, ?)",
                (name, name, pgy_level)
            )
            res_id = cur.lastrowid
            
        # Insert/update rotation for target half-blocks
        target_halves = ["a", "b"] if half == "both" else [half]
        for h in target_halves:
            hb_row = conn.execute(
                "SELECT id FROM half_blocks WHERE pgy_level = ? AND block_number = ? AND half = ?",
                (pgy_level, block_number, h)
            ).fetchone()
            if hb_row:
                hb_id = hb_row["id"]
                conn.execute(
                    "INSERT INTO rotations (resident_id, half_block_id, rotation) VALUES (?, ?, ?) "
                    "ON CONFLICT(resident_id, half_block_id) DO UPDATE SET rotation = excluded.rotation",
                    (res_id, hb_id, site)
                )
    conn.commit()


def run_solver_and_stage_draft(conn, pgy_level, block_number, shift_min_per_half, max_time_seconds, off_services=None):
    """Solves the block and inserts a new draft run + its assignments."""
    _process_off_services(conn, pgy_level, block_number, off_services)
    block_input = load_block_from_db(conn, pgy_level, block_number)
    timeoff = load_timeoff_from_db(conn)
    history = load_history_from_db(conn, pgy_level)
    prior_last_shifts = load_prior_last_shifts(conn, pgy_level, block_number)
    balance_weights = load_balance_weights(conn)

    cfg, slv = _get_config(pgy_level)

    result = slv.build_and_solve(
        block_number,
        shift_min_per_half=shift_min_per_half,
        max_time_seconds=max_time_seconds,
        block_input=block_input,
        timeoff=timeoff,
        history=history,
        balance_weights=balance_weights,
        prior_last_shifts=prior_last_shifts,
    )
    if result is None:
        return None

    for old in conn.execute(
        "SELECT id FROM runs WHERE pgy_level = ? AND block_number = ? AND status = 'draft'",
        (pgy_level, block_number),
    ).fetchall():
        _delete_run(conn, old["id"])

    resident_id_by_name = {
        row["last_name"]: row["id"]
        for row in conn.execute(
            "SELECT id, last_name FROM residents WHERE pgy_level = ?", (pgy_level,)
        ).fetchall()
    }

    cur = conn.execute(
        "INSERT INTO runs (pgy_level, block_number, status, min_shifts, time_limit) "
        "VALUES (?, ?, 'draft', ?, ?) RETURNING id",
        (pgy_level, block_number, shift_min_per_half, max_time_seconds),
    )
    run_id = cur.fetchone()[0]

    # result["assignments"] is dict:
    # For PGY-1: (date, name) -> shift_id
    # For PGY-4: (date, shift_id) -> name
    if pgy_level == 1:
        for (date, name), shift_id in result["assignments"].items():
            conn.execute(
                "INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, ?, ?)",
                (run_id, resident_id_by_name[name], date.isoformat(), cfg.SHIFTS[shift_id]["name"]),
            )
    else:
        for (date, shift_id), name in result["assignments"].items():
            conn.execute(
                "INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, ?, ?)",
                (run_id, resident_id_by_name[name], date.isoformat(), cfg.SHIFTS[shift_id]["name"]),
            )
    conn.commit()
    return run_id


def _delete_run(conn, run_id):
    conn.execute("DELETE FROM trade_requests WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM assignments WHERE run_id = ?", (run_id,))
    conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))


def publish_run(conn, run_id):
    run = conn.execute("SELECT pgy_level, block_number FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run with id {run_id}")
    for old in conn.execute(
        "SELECT id FROM runs WHERE pgy_level = ? AND block_number = ? AND status = 'published' AND id != ?",
        (run["pgy_level"], run["block_number"], run_id),
    ).fetchall():
        _delete_run(conn, old["id"])
    conn.execute("UPDATE runs SET status = 'published' WHERE id = ?", (run_id,))
    conn.commit()


def discard_run(conn, run_id):
    run = conn.execute("SELECT id FROM runs WHERE id = ? AND status = 'draft'", (run_id,)).fetchone()
    if run is not None:
        _delete_run(conn, run_id)
    conn.commit()


# ---------------------------------------------------------------------------
# Shift trade helpers
# ---------------------------------------------------------------------------

def _load_run_assignments(conn, run_id):
    """Return {(resident_id, iso_date): shift_name} for an entire run."""
    rows = conn.execute(
        "SELECT resident_id, day, shift_name FROM assignments WHERE run_id = ?", (run_id,)
    ).fetchall()
    return {(r["resident_id"], r["day"]): r["shift_name"] for r in rows}


def _load_run_assignments_with_prior(conn, run_id):
    """Run assignments plus published prior-day shifts for cross-block rest checks."""
    base = _load_run_assignments(conn, run_id)
    run = conn.execute("SELECT pgy_level FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        return base
    first_day_row = conn.execute(
        "SELECT MIN(day) AS day FROM assignments WHERE run_id = ?", (run_id,)
    ).fetchone()
    if not first_day_row or not first_day_row["day"]:
        return base
    prior_day = (dt.date.fromisoformat(first_day_row["day"]) - dt.timedelta(days=1)).isoformat()
    prior_rows = conn.execute(
        "SELECT a.resident_id, a.day, a.shift_name "
        "FROM assignments a "
        "JOIN runs r ON r.id = a.run_id "
        "WHERE r.status = 'published' AND r.pgy_level = ? AND a.day = ?",
        (run["pgy_level"], prior_day),
    ).fetchall()
    merged = dict(base)
    for row in prior_rows:
        key = (row["resident_id"], row["day"])
        if key not in merged:
            merged[key] = row["shift_name"]
    return merged


def _shift_info_by_name(pgy_level):
    """Name → SHIFTS entry mapping dynamically fetched per pgy_level."""
    cfg, _ = _get_config(pgy_level)
    by_name = {info["name"]: info for info in cfg.SHIFTS.values()}
    for old, new in getattr(cfg, "SHIFT_NAME_ALIASES", {}).items():
        if new in by_name:
            by_name[old] = by_name[new]
    return by_name


def _acgme_ok(assignments_map, resident_id, run_id, conn):
    """
    Check ACGME hard constraints for one resident given a (possibly mutated)
    assignments_map {(resident_id, iso_date): shift_name}.
    Returns True if all constraints pass.
    Checks:
      - ≥shift-duration (min 8h) rest between consecutive shifts
      - ≤60 ED hours in any rolling 7-day window
      - ≥1 completely free day per 7-day window
    """
    run_row = conn.execute("SELECT pgy_level FROM runs WHERE id = ?", (run_id,)).fetchone()
    pgy_level = run_row["pgy_level"] if run_row else 4
    cfg, _ = _get_config(pgy_level)

    by_name = _shift_info_by_name(pgy_level)

    # Collect this resident's assigned (date, shift_info) sorted by date
    entries = []
    for (rid, iso), sname in sorted(assignments_map.items()):
        if rid != resident_id:
            continue
        info = by_name.get(sname)
        if info is None:
            continue
        entries.append((dt.date.fromisoformat(iso), info))
    entries.sort(key=lambda x: x[0])

    if not entries:
        return True

    # Rest constraint: gap between consecutive shifts
    for i in range(len(entries) - 1):
        d1, info1 = entries[i]
        d2, info2 = entries[i + 1]
        # Only relevant for back-to-back days
        if (d2 - d1).days > 1:
            continue
        end1 = info1["end"] + (24 if info1["type"] == "Overnight" else 0)
        start2 = info2["start"] + 24  # next day
        rest = start2 - end1
        required = max(8, info1["duration"])
        if rest < required:
            return False

    # Build a date range covering all worked days
    all_dates = sorted({d for d, _ in entries})
    if not all_dates:
        return True
    start_d = all_dates[0]
    end_d = all_dates[-1]
    total_days = (end_d - start_d).days + 1

    # Build per-day lookup: date -> shift info (or None)
    day_map = {d: info for d, info in entries}

    # Rolling 7-day windows
    for w in range(total_days - 6):
        window = [start_d + dt.timedelta(days=w + i) for i in range(7)]
        ed_hours = sum(day_map[d]["duration"] for d in window if d in day_map)
        if ed_hours > 60:
            return False
        # Free day: not worked AND not recovering from previous-night overnight
        free_days = 0
        for i, d in enumerate(window):
            if d in day_map:
                continue
            prev = d - dt.timedelta(days=1)
            prev_info = day_map.get(prev)
            if prev_info and prev_info["type"] == "Overnight":
                continue  # recovering from overnight counts as not free
            free_days += 1
        if free_days < 1:
            return False

    return True


def find_valid_swaps(conn, run_id, requester_resident_id, requester_day, requester_shift):
    """
    Return list of swap candidates that keep BOTH residents ACGME-compliant.
    Each candidate: {target_id, target_name, target_day, target_shift}
    Only checks ACGME constraints (rest, 60h/wk, 1 free day/wk).
    """
    run_row = conn.execute("SELECT pgy_level FROM runs WHERE id = ?", (run_id,)).fetchone()
    pgy_level = run_row["pgy_level"] if run_row else 4
    cfg, _ = _get_config(pgy_level)

    base = _load_run_assignments_with_prior(conn, run_id)
    by_name = _shift_info_by_name(pgy_level)

    # Get all residents in this run (excluding requester)
    other_ids = {rid for (rid, _) in base if rid != requester_resident_id}

    # Name lookup
    res_rows = conn.execute("SELECT id, full_name, last_name FROM residents").fetchall()
    name_by_id = {r["id"]: r["full_name"] for r in res_rows}
    last_by_id = {r["id"]: r["last_name"] for r in res_rows}

    # Active trades: block shifts already in a pending trade
    active_trades = conn.execute(
        "SELECT requester_id, requester_day, requester_shift, "
        "target_id, target_day, target_shift "
        "FROM trade_requests WHERE run_id = ? AND status IN ('pending_peer','pending_admin')",
        (run_id,),
    ).fetchall()
    blocked = set()
    for t in active_trades:
        blocked.add((t["requester_id"], t["requester_day"], t["requester_shift"]))
        blocked.add((t["target_id"], t["target_day"], t["target_shift"]))

    # Requester's own shift must not be blocked
    if (requester_resident_id, requester_day, requester_shift) in blocked:
        return []

    results = []
    for target_id in other_ids:
        # Find all of this target's shifts
        target_shifts = [
            (iso, sname)
            for (rid, iso), sname in base.items()
            if rid == target_id
        ]
        for target_day, target_shift in target_shifts:
            if (target_id, target_day, target_shift) in blocked:
                continue
            # Simulate swap
            swapped = dict(base)
            swapped[(requester_resident_id, requester_day)] = target_shift
            swapped[(target_id, target_day)] = requester_shift
            # Check both residents are still ACGME-compliant
            if _acgme_ok(swapped, requester_resident_id, run_id, conn) and \
               _acgme_ok(swapped, target_id, run_id, conn):
                tinfo = by_name.get(target_shift, {})
                results.append({
                    "target_id": target_id,
                    "target_name": name_by_id.get(target_id, str(target_id)),
                    "target_last": last_by_id.get(target_id, str(target_id)),
                    "target_day": target_day,
                    "target_shift": target_shift,
                    "target_type": tinfo.get("type", ""),
                })

    # Sort by date then name
    results.sort(key=lambda x: (x["target_day"], x["target_last"]))
    return results


def apply_trade(conn, trade_id):
    """Swap the two assignment rows and mark the trade approved."""
    trade = conn.execute(
        "SELECT run_id, requester_id, requester_day, requester_shift, "
        "target_id, target_day, target_shift FROM trade_requests WHERE id = ?",
        (trade_id,),
    ).fetchone()
    if trade is None:
        raise ValueError(f"Trade {trade_id} not found")

    run_id = trade["run_id"]
    # Update requester's assignment day → target's shift
    conn.execute(
        "UPDATE assignments SET shift_name = ? WHERE run_id = ? AND resident_id = ? AND day = ?",
        (trade["target_shift"], run_id, trade["requester_id"], trade["requester_day"]),
    )
    # Update target's assignment day → requester's shift
    conn.execute(
        "UPDATE assignments SET shift_name = ? WHERE run_id = ? AND resident_id = ? AND day = ?",
        (trade["requester_shift"], run_id, trade["target_id"], trade["target_day"]),
    )
    conn.execute(
        "UPDATE trade_requests SET status = 'approved', resolved_at = datetime('now') WHERE id = ?",
        (trade_id,),
    )
    conn.commit()

