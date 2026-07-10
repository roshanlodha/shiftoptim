"""Flask app factory. Admin flow is Run -> Review -> Publish; residents view
the published schedule, manage their own time off, and see their history."""

import hashlib
import os

from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from schedulebuilder.pgy4.config import BALANCE_CATEGORIES, SHIFT_MIN_PER_HALF, SHIFTS
from schedulebuilder.pgy4.history import category_totals

from . import bridge
from .auth import admin_required, load_logged_in_user, login_required
from .db import get_db

CATEGORY_COLUMNS = list(BALANCE_CATEGORIES) + ["Weekend"]
SHIFT_NAMES = [info["name"] for info in SHIFTS.values()]
SOLVER_TIME_LIMIT = 60.0


def resident_color(username):
    """Deterministic pastel color from a username hash, so a resident keeps
    the same color everywhere and across restarts."""
    hue = int(hashlib.md5(username.encode()).hexdigest(), 16) % 360
    return f"hsl({hue}, 65%, 82%)"


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SHIFTOPTIM_SECRET_KEY", "dev-only-change-me")
    if db_path:
        app.config["DB_PATH"] = db_path

    @app.before_request
    def _before_request():
        load_logged_in_user()

    @app.teardown_appcontext
    def _close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def db_conn():
        if "db" not in g:
            g.db = get_db(app.config.get("DB_PATH"))
        return g.db

    register_routes(app, db_conn)
    return app


def register_routes(app, db_conn):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            username = request.form["username"].strip()
            password = request.form["password"]
            user = db_conn().execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                error = "Invalid username or password."
            else:
                session.clear()
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        if g.user["role"] == "admin":
            return redirect(url_for("admin_dashboard"))
        return redirect(url_for("resident_schedule"))

    # --- Admin: run -> review -> publish -----------------------------------

    def _dashboard(error=None):
        conn = db_conn()
        blocks = conn.execute(
            "SELECT block_number, MIN(start_date) AS start_date, MAX(end_date) AS end_date "
            "FROM half_blocks WHERE pgy_level = 4 GROUP BY block_number ORDER BY block_number"
        ).fetchall()
        runs_by_block = {}
        for run in conn.execute("SELECT * FROM runs WHERE pgy_level = 4").fetchall():
            runs_by_block.setdefault(run["block_number"], {})[run["status"]] = run
        return render_template("admin_dashboard.html", blocks=blocks,
                               runs_by_block=runs_by_block, error=error)

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        return _dashboard()

    @app.route("/admin/blocks/<int:block_number>/run", methods=["POST"])
    @admin_required
    def admin_run(block_number):
        run_id = bridge.run_solver_and_stage_draft(
            db_conn(), 4, block_number, SHIFT_MIN_PER_HALF, SOLVER_TIME_LIMIT)
        if run_id is None:
            return _dashboard(error=f"No feasible schedule found for block {block_number}. "
                                    "Check time-off requests and rotations.")
        return redirect(url_for("admin_review_run", run_id=run_id))

    @app.route("/admin/runs/<int:run_id>")
    @admin_required
    def admin_review_run(run_id):
        conn = db_conn()
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return redirect(url_for("admin_dashboard"))
        grid = _build_grid(conn, run_id)
        return render_template("admin_review_run.html", run=run, grid=grid, shift_names=SHIFT_NAMES)

    @app.route("/admin/runs/<int:run_id>/publish", methods=["POST"])
    @admin_required
    def admin_publish_run(run_id):
        bridge.publish_run(db_conn(), run_id)
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/runs/<int:run_id>/discard", methods=["POST"])
    @admin_required
    def admin_discard_run(run_id):
        bridge.discard_run(db_conn(), run_id)
        return redirect(url_for("admin_dashboard"))

    # --- Resident -----------------------------------------------------------

    @app.route("/schedule")
    @login_required
    def resident_schedule():
        conn = db_conn()
        blocks = [row["block_number"] for row in conn.execute(
            "SELECT DISTINCT block_number FROM runs "
            "WHERE status = 'published' AND pgy_level = 4 ORDER BY block_number"
        ).fetchall()]
        block_number = request.args.get("block", type=int)
        if block_number is None and blocks:
            block_number = blocks[-1]
        grid = None
        if block_number is not None:
            run = conn.execute(
                "SELECT id FROM runs WHERE pgy_level = 4 AND block_number = ? AND status = 'published'",
                (block_number,),
            ).fetchone()
            if run:
                grid = _build_grid(conn, run["id"])
        return render_template(
            "resident_schedule.html", blocks=blocks, block_number=block_number,
            grid=grid, shift_names=SHIFT_NAMES,
        )

    @app.route("/timeoff", methods=["GET", "POST"])
    @login_required
    def resident_timeoff():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        if resident_id is None:  # admin has no resident record
            return redirect(url_for("index"))

        if request.method == "POST":
            action = request.form.get("action")
            if action == "add":
                conn.execute(
                    "INSERT INTO time_off (resident_id, start_date, end_date) VALUES (?, ?, ?)",
                    (resident_id, request.form["start_date"], request.form["end_date"]),
                )
            elif action == "delete":
                conn.execute(
                    "DELETE FROM time_off WHERE id = ? AND resident_id = ?",
                    (request.form["time_off_id"], resident_id),
                )
            conn.commit()
            return redirect(url_for("resident_timeoff"))

        requests_ = conn.execute(
            "SELECT id, start_date, end_date FROM time_off WHERE resident_id = ? ORDER BY start_date",
            (resident_id,),
        ).fetchall()
        return render_template("timeoff.html", requests=requests_)

    @app.route("/history")
    @login_required
    def resident_history():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("index"))
        resident = conn.execute(
            "SELECT last_name, pgy_level FROM residents WHERE id = ?", (resident_id,)
        ).fetchone()
        history = bridge.load_history_from_db(conn, resident["pgy_level"])
        entry = history.get(resident["last_name"],
                            {"half_blocks_worked": 0, "shifts": {sn: 0 for sn in SHIFT_NAMES}, "weekend": 0})
        totals = category_totals(entry)
        return render_template(
            "resident_history.html", entry=entry, totals=totals,
            category_columns=CATEGORY_COLUMNS, shift_names=SHIFT_NAMES,
        )


def _week_chunks(dates):
    """Split sorted ISO date strings into Mon-Sun calendar weeks."""
    import datetime as dt

    weeks, week = [], []
    for iso in dates:
        d = dt.date.fromisoformat(iso)
        if week and d.weekday() == 0:
            weeks.append(week)
            week = []
        week.append(d)
    if week:
        weeks.append(week)
    return weeks


def _build_grid(conn, run_id):
    """Calendar-grid payload: weekly Mon-Sun chunks, cells keyed by
    (shift_name, iso_date) -> last name, a color per resident (hashed from
    their username), and a legend with per-block shift counts."""
    rows = conn.execute(
        "SELECT a.day AS day, a.shift_name AS shift_name, "
        "res.last_name AS last_name, res.full_name AS full_name, u.username AS username "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "LEFT JOIN users u ON u.resident_id = res.id "
        "WHERE a.run_id = ?",
        (run_id,),
    ).fetchall()

    cells = {}
    counts = {}
    meta = {}
    for row in rows:
        cells[(row["shift_name"], row["day"])] = row["last_name"]
        counts[row["last_name"]] = counts.get(row["last_name"], 0) + 1
        meta[row["last_name"]] = row

    colors = {
        last_name: resident_color(row["username"] or last_name)
        for last_name, row in meta.items()
    }
    legend = sorted(
        (
            {"full_name": meta[ln]["full_name"], "last_name": ln,
             "color": colors[ln], "count": counts[ln]}
            for ln in meta
        ),
        key=lambda item: item["last_name"],
    )
    weeks = _week_chunks(sorted({row["day"] for row in rows}))
    return {"weeks": weeks, "cells": cells, "colors": colors, "legend": legend}
