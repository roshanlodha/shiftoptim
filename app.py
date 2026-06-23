from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

import pandas as pd
from flask import Flask, Response, jsonify, render_template, request

import shiftmaxxer.config as config
from shiftmaxxer.graph import build_trade_graph, find_cycles
from shiftmaxxer.ingest import _extract_gdrive_id, load_all_ics, load_preferences
from shiftmaxxer.models import Resident, Schedule
from shiftmaxxer.optimizer import CycleResult, apply_cycle, evaluate_cycle, swap_key
from shiftmaxxer.render import _fmt_time, build_payload, render_html

app = Flask(__name__)
app.secret_key = "shiftmaxxer-live-dev"

ICS_DIR = Path("data/ics")
PREFS_CSV = Path("data/preferences.csv")

# In-memory session store — single-user dev tool, no persistence needed.
SESSIONS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Background setup: download ICS files and build schedule
# ---------------------------------------------------------------------------

def _setup_bg(session_id: str, progress_q: "queue.Queue[dict]",
              max_swaps: int, n_max: int, allow_jeopardy: bool) -> None:
    """Run in a background thread. Emits dicts onto progress_q."""
    try:
        df = pd.read_csv(PREFS_CSV)
        expected = ["timestamp", "resident", "location_pref", "time_pref",
                    "days_off", "location_weight", "time_weight",
                    "days_pref", "days_weight", "calendar_ics"]
        if len(df.columns) == len(expected):
            df.columns = expected

        ICS_DIR.mkdir(parents=True, exist_ok=True)
        rows = [(str(r["resident"]).strip(), str(r.get("calendar_ics", "")).strip())
                for _, r in df.iterrows()]
        total = len(rows)

        for i, (name, url) in enumerate(rows):
            dest = ICS_DIR / f"{name}.ics"
            if dest.exists():
                progress_q.put({"type": "download", "name": name,
                                 "status": "cached", "done": i + 1, "total": total})
                continue
            fid = _extract_gdrive_id(url) if url and url != "nan" else None
            if not fid:
                progress_q.put({"type": "download", "name": name,
                                 "status": "skipped", "done": i + 1, "total": total})
                continue
            progress_q.put({"type": "download", "name": name,
                             "status": "downloading", "done": i, "total": total})
            dl = f"https://drive.google.com/uc?export=download&id={fid}"
            try:
                urllib.request.urlretrieve(dl, dest)
                progress_q.put({"type": "download", "name": name,
                                 "status": "done", "done": i + 1, "total": total})
            except urllib.error.URLError as exc:
                progress_q.put({"type": "download", "name": name,
                                 "status": "error", "error": str(exc),
                                 "done": i + 1, "total": total})

        progress_q.put({"type": "build", "message": "Parsing ICS files…"})
        if allow_jeopardy:
            config.ALLOW_JEOPARDY_SWAPS = True

        shifts_list = load_all_ics(ICS_DIR)
        residents = load_preferences(PREFS_CSV)
        shifts = {s.uid: s for s in shifts_list}
        assignment: dict[str, set[str]] = {name: set() for name in residents}
        for s in shifts_list:
            assignment.setdefault(s.owner, set()).add(s.uid)
        for owner in assignment:
            if owner not in residents:
                residents[owner] = Resident(owner, "ANY", 0, "ANY", 0, 4, 0, frozenset())
        sched = Schedule(assignment=assignment, shifts=shifts, residents=residents)
        orig = {n: set(uids) for n, uids in sched.assignment.items()}

        progress_q.put({"type": "build", "message": "Building trade graph…"})
        G = build_trade_graph(sched, set())
        n_candidates = sum(
            1 for cyc in find_cycles(G, n_max)
            if evaluate_cycle(cyc, sched) is not None
        )

        SESSIONS[session_id].update({
            "sched": sched,
            "original_assignment": orig,
            "locked": set(),
            "swap_count": Counter(),
            "rejected": set(),
            "log": [],
            "pending_swap": None,
            "status": "ready",
            "max_swaps": max_swaps,
            "n_max": n_max,
            "accepted": 0,
            "rejected_count": 0,
        })
        progress_q.put({"type": "ready", "candidates": n_candidates})

    except Exception as exc:
        import traceback
        progress_q.put({"type": "error", "message": str(exc),
                        "trace": traceback.format_exc()})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _next_candidate(session: dict) -> CycleResult | None:
    sched = session["sched"]
    G = build_trade_graph(sched, session["locked"])
    candidates: list[CycleResult] = []
    for cyc in find_cycles(G, session["n_max"]):
        res = evaluate_cycle(cyc, sched)
        if res is None:
            continue
        if swap_key(res) in session["rejected"]:
            continue
        ms = session["max_swaps"]
        if ms != -1:
            ben = max(sorted(res.deltas.keys()), key=lambda n: res.deltas[n])
            if session["swap_count"][ben] + 1 > ms:
                continue
        candidates.append(res)
    if not candidates:
        return None
    min_sw = min(session["swap_count"].get(n, 0) for n in sched.assignment)
    priority = [r for r in candidates
                if any(session["swap_count"].get(n, 0) == min_sw for n in r.deltas)]
    pool = priority if priority else candidates
    pool.sort(key=lambda r: r.total_delta, reverse=True)
    return pool[0]


def _serialize_swap(result: CycleResult, sched: Schedule) -> dict:
    moves = []
    for giver, u, v in result.moves:
        su, sv = sched.shifts[u], sched.shifts[v]
        moves.append({
            "giver": giver,
            "giveUid": u,
            "giveSummary": su.summary,
            "giveDate": su.work_date.isoformat(),
            "giveLoc": su.loc,
            "giveType": su.type,
            "giveStart": _fmt_time(su.t_start),
            "giveEnd": _fmt_time(su.t_end),
            "recvUid": v,
            "recvSummary": sv.summary,
            "recvDate": sv.work_date.isoformat(),
            "recvLoc": sv.loc,
            "recvType": sv.type,
            "recvStart": _fmt_time(sv.t_start),
            "recvEnd": _fmt_time(sv.t_end),
            "delta": round(result.deltas.get(giver, 0), 4),
        })
    return {"totalDelta": round(result.total_delta, 4), "moves": moves}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("live.html")


@app.route("/api/init", methods=["POST"])
def api_init():
    data = request.get_json(force=True) or {}
    sid = str(uuid.uuid4())
    max_swaps = int(data.get("maxSwaps", -1))
    n_max = int(data.get("nMax", 2))
    allow_jeopardy = bool(data.get("allowJeopardy", False))

    pq: queue.Queue = queue.Queue()
    SESSIONS[sid] = {"status": "loading", "progress_q": pq}

    threading.Thread(
        target=_setup_bg,
        args=(sid, pq, max_swaps, n_max, allow_jeopardy),
        daemon=True,
    ).start()
    return jsonify({"sessionId": sid})


@app.route("/api/progress/<sid>")
def api_progress(sid):
    if sid not in SESSIONS:
        return Response(
            'data: {"type":"error","message":"Session not found"}\n\n',
            mimetype="text/event-stream",
        )

    def generate():
        q = SESSIONS[sid]["progress_q"]
        while True:
            try:
                evt = q.get(timeout=30)
                yield f"data: {json.dumps(evt)}\n\n"
                if evt["type"] in ("ready", "error"):
                    break
            except queue.Empty:
                yield 'data: {"type":"ping"}\n\n'

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/next/<sid>")
def api_next(sid):
    session = SESSIONS.get(sid)
    if not session or session.get("status") != "ready":
        return jsonify({"error": "Session not ready"}), 400

    cand = _next_candidate(session)
    if cand is None:
        session["status"] = "done"
        return jsonify({
            "type": "done",
            "accepted": session["accepted"],
            "rejected": session["rejected_count"],
        })

    session["pending_swap"] = cand
    return jsonify({"type": "swap", "swap": _serialize_swap(cand, session["sched"])})


@app.route("/api/decide/<sid>", methods=["POST"])
def api_decide(sid):
    session = SESSIONS.get(sid)
    if not session or session.get("status") != "ready":
        return jsonify({"error": "Session not ready"}), 400

    data = request.get_json(force=True) or {}
    decision = data.get("decision")
    cand: CycleResult | None = session.get("pending_swap")

    if cand is None:
        return jsonify({"error": "No pending swap"}), 400

    if decision == "accept":
        apply_cycle(cand, session["sched"])
        for _, u, v in cand.moves:
            session["locked"].add(u)
            session["locked"].add(v)
        ben = max(sorted(cand.deltas.keys()), key=lambda n: cand.deltas[n])
        session["swap_count"][ben] += 1
        session["log"].append(cand)
        session["accepted"] += 1
    elif decision == "reject":
        session["rejected"].add(swap_key(cand))
        session["rejected_count"] += 1
    else:
        return jsonify({"error": "Invalid decision"}), 400

    session["pending_swap"] = None
    return jsonify({"ok": True})


@app.route("/api/report/<sid>")
def api_report(sid):
    session = SESSIONS.get(sid)
    if not session or session.get("status") not in ("ready", "done"):
        return "Session not found or not ready", 404
    return render_html(session["sched"], session["log"], session["original_assignment"])


if __name__ == "__main__":
    app.run(debug=True, threaded=True)
