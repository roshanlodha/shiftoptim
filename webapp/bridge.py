"""Bridges the DB (rotations/time_off/history_baseline/assignments) to the
existing CP-SAT solver, and writes results back as a draft run + assignments.

Mirrors schedulebuilder.pgy4.inputs.load_block / load_timeoff / history.load_history,
but reads from SQLite instead of config.ini / history.json.
"""

import datetime as dt

from schedulebuilder.pgy4.config import ACTIVE_ROLES, SHIFTS, WEEKEND_DAYS
from schedulebuilder.pgy4.solver import build_and_solve


def _daterange(start, end):
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def load_block_from_db(conn, pgy_level, block_number):
    """Returns (dates, residents, role_on, active_halves) like inputs.load_block(),
    keyed by resident last_name, derived from the rotations table (no manual
    roster re-entry needed)."""
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
            (half["id"], *ACTIVE_ROLES),
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


def load_history_from_db(conn, pgy_level):
    """Carry-in totals = history_baseline + all published assignments for this
    PGY level, aggregated the same way schedulebuilder.pgy4.history does."""
    shift_names = [info["name"] for info in SHIFTS.values()]
    history = {}

    baseline_rows = conn.execute(
        "SELECT res.last_name AS last_name, hb.shift_name AS shift_name, hb.count AS count "
        "FROM history_baseline hb JOIN residents res ON res.id = hb.resident_id "
        "WHERE res.pgy_level = ?",
        (pgy_level,),
    ).fetchall()
    for row in baseline_rows:
        entry = history.setdefault(row["last_name"], _empty_entry(shift_names))
        if row["shift_name"] == "half_blocks_worked":
            entry["half_blocks_worked"] += row["count"]
        elif row["shift_name"] == "weekend":
            entry["weekend"] += row["count"]
        elif row["shift_name"] in entry["shifts"]:
            entry["shifts"][row["shift_name"]] += row["count"]

    assignment_rows = conn.execute(
        "SELECT res.last_name AS last_name, a.day AS day, a.shift_name AS shift_name "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "JOIN runs r ON r.id = a.run_id "
        "WHERE r.status = 'published' AND r.pgy_level = ?",
        (pgy_level,),
    ).fetchall()
    half_block_counts = {}
    for row in assignment_rows:
        entry = history.setdefault(row["last_name"], _empty_entry(shift_names))
        if row["shift_name"] in entry["shifts"]:
            entry["shifts"][row["shift_name"]] += 1
        day = dt.date.fromisoformat(row["day"])
        if day.weekday() in WEEKEND_DAYS:
            entry["weekend"] += 1

    # half_blocks_worked from published runs: count distinct (resident, run) pairs,
    # since each run covers one full block (2 halves).
    run_pairs = conn.execute(
        "SELECT DISTINCT a.resident_id AS resident_id, a.run_id AS run_id, res.last_name AS last_name "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "JOIN runs r ON r.id = a.run_id "
        "WHERE r.status = 'published' AND r.pgy_level = ?",
        (pgy_level,),
    ).fetchall()
    for row in run_pairs:
        half_block_counts[row["last_name"]] = half_block_counts.get(row["last_name"], 0) + 2
    for last_name, halves in half_block_counts.items():
        history.setdefault(last_name, _empty_entry(shift_names))["half_blocks_worked"] += halves

    return history


def _empty_entry(shift_names):
    return {"half_blocks_worked": 0, "shifts": {sn: 0 for sn in shift_names}, "weekend": 0}


def run_solver_and_stage_draft(conn, pgy_level, block_number, shift_min_per_half, max_time_seconds):
    """Solves the block and inserts a new draft run + its assignments. Returns
    the run id, or None if no feasible schedule was found."""
    block_input = load_block_from_db(conn, pgy_level, block_number)
    timeoff = load_timeoff_from_db(conn)
    history = load_history_from_db(conn, pgy_level)

    result = build_and_solve(
        block_number,
        shift_min_per_half=shift_min_per_half,
        max_time_seconds=max_time_seconds,
        block_input=block_input,
        timeoff=timeoff,
        history=history,
    )
    if result is None:
        return None

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

    for (date, shift_id), name in result["assignments"].items():
        conn.execute(
            "INSERT INTO assignments (run_id, resident_id, day, shift_name) VALUES (?, ?, ?, ?)",
            (run_id, resident_id_by_name[name], date.isoformat(), SHIFTS[shift_id]["name"]),
        )
    conn.commit()
    return run_id


def publish_run(conn, run_id):
    """Marks a run published, discarding any other run for the same
    pgy_level/block_number so only one published run remains authoritative."""
    run = conn.execute("SELECT pgy_level, block_number FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"No run with id {run_id}")
    conn.execute(
        "UPDATE runs SET status = 'discarded' WHERE pgy_level = ? AND block_number = ? AND status = 'published'",
        (run["pgy_level"], run["block_number"]),
    )
    conn.execute("UPDATE runs SET status = 'published' WHERE id = ?", (run_id,))
    conn.commit()


def discard_run(conn, run_id):
    conn.execute("UPDATE runs SET status = 'discarded' WHERE id = ? AND status = 'draft'", (run_id,))
    conn.commit()
