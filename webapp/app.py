"""Flask app factory: admin manages inputs/runs, residents view published
schedules and their own history."""

import datetime as dt
import os

from flask import Flask, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

from schedulebuilder.pgy4.config import ACTIVE_ROLES, BALANCE_CATEGORIES, SHIFTS
from schedulebuilder.pgy4.history import category_totals

from . import bridge
from .auth import admin_required, load_logged_in_user, login_required
from .db import get_db

CATEGORY_COLUMNS = list(BALANCE_CATEGORIES) + ["Weekend"]
SHIFT_NAMES = [info["name"] for info in SHIFTS.values()]
ROTATION_OPTIONS = ("MGB", "MGB Nights", "Flex", "Vacation", "Elective", "Elective/LTD", "NWH", "Teaching")


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

    app.teardown_appcontext(_close_db)

    def db_conn():
        if "db" not in g:
            g.db = get_db(app.config.get("DB_PATH"))
        return g.db

    app.get_db_conn = db_conn

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

    # --- Admin -----------------------------------------------------------

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        conn = db_conn()
        blocks = conn.execute(
            "SELECT DISTINCT block_number FROM half_blocks WHERE pgy_level = 4 ORDER BY block_number"
        ).fetchall()
        runs = conn.execute(
            "SELECT id, block_number, status, min_shifts, time_limit, created_at "
            "FROM runs WHERE pgy_level = 4 ORDER BY created_at DESC"
        ).fetchall()
        return render_template("admin_dashboard.html", blocks=blocks, runs=runs)

    @app.route("/admin/blocks/<int:block_number>/rotations", methods=["GET", "POST"])
    @admin_required
    def admin_rotations(block_number):
        conn = db_conn()
        if request.method == "POST":
            for key, value in request.form.items():
                if not key.startswith("rotation_"):
                    continue
                resident_id, half_block_id = key[len("rotation_"):].split("_")
                conn.execute(
                    "UPDATE rotations SET rotation = ? WHERE resident_id = ? AND half_block_id = ?",
                    (value, resident_id, half_block_id),
                )
            conn.commit()
            return redirect(url_for("admin_rotations", block_number=block_number))

        halves = conn.execute(
            "SELECT id, half, start_date, end_date FROM half_blocks "
            "WHERE pgy_level = 4 AND block_number = ? ORDER BY half",
            (block_number,),
        ).fetchall()
        residents = conn.execute(
            "SELECT id, full_name, last_name FROM residents WHERE pgy_level = 4 ORDER BY last_name"
        ).fetchall()
        rotations = {}
        for row in conn.execute(
            "SELECT resident_id, half_block_id, rotation FROM rotations "
            "WHERE half_block_id IN (SELECT id FROM half_blocks WHERE pgy_level = 4 AND block_number = ?)",
            (block_number,),
        ).fetchall():
            rotations[(row["resident_id"], row["half_block_id"])] = row["rotation"]
        return render_template(
            "admin_rotations.html",
            block_number=block_number,
            halves=halves,
            residents=residents,
            rotations=rotations,
            options=ROTATION_OPTIONS,
        )

    @app.route("/admin/time_off", methods=["GET", "POST"])
    @admin_required
    def admin_time_off():
        conn = db_conn()
        if request.method == "POST":
            action = request.form.get("action")
            if action == "add":
                conn.execute(
                    "INSERT INTO time_off (resident_id, start_date, end_date) VALUES (?, ?, ?)",
                    (request.form["resident_id"], request.form["start_date"], request.form["end_date"]),
                )
            elif action == "delete":
                conn.execute("DELETE FROM time_off WHERE id = ?", (request.form["time_off_id"],))
            conn.commit()
            return redirect(url_for("admin_time_off"))

        residents = conn.execute(
            "SELECT id, full_name FROM residents WHERE pgy_level = 4 ORDER BY full_name"
        ).fetchall()
        time_off = conn.execute(
            "SELECT t.id, t.start_date, t.end_date, res.full_name AS full_name "
            "FROM time_off t JOIN residents res ON res.id = t.resident_id "
            "WHERE res.pgy_level = 4 ORDER BY t.start_date"
        ).fetchall()
        return render_template("admin_time_off.html", residents=residents, time_off=time_off)

    @app.route("/admin/blocks/<int:block_number>/run", methods=["POST"])
    @admin_required
    def admin_run(block_number):
        conn = db_conn()
        min_shifts = int(request.form.get("min_shifts", 8))
        time_limit = float(request.form.get("time_limit", 60))
        run_id = bridge.run_solver_and_stage_draft(conn, 4, block_number, min_shifts, time_limit)
        if run_id is None:
            return render_template("admin_dashboard.html", error="No feasible schedule found.",
                                    blocks=conn.execute(
                                        "SELECT DISTINCT block_number FROM half_blocks WHERE pgy_level = 4 ORDER BY block_number"
                                    ).fetchall(),
                                    runs=conn.execute(
                                        "SELECT id, block_number, status, min_shifts, time_limit, created_at "
                                        "FROM runs WHERE pgy_level = 4 ORDER BY created_at DESC"
                                    ).fetchall())
        return redirect(url_for("admin_review_run", run_id=run_id))

    @app.route("/admin/runs/<int:run_id>")
    @admin_required
    def admin_review_run(run_id):
        conn = db_conn()
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
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

    # --- Resident ----------------------------------------------------------

    @app.route("/schedule")
    @login_required
    def resident_schedule():
        conn = db_conn()
        blocks = [row["block_number"] for row in conn.execute(
            "SELECT DISTINCT r.block_number AS block_number FROM runs r "
            "WHERE r.status = 'published' AND r.pgy_level = 4 ORDER BY r.block_number"
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

    @app.route("/history")
    @login_required
    def resident_history():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("index"))
        pgy_level = conn.execute("SELECT pgy_level FROM residents WHERE id = ?", (resident_id,)).fetchone()["pgy_level"]
        history = bridge.load_history_from_db(conn, pgy_level)
        last_name = conn.execute("SELECT last_name FROM residents WHERE id = ?", (resident_id,)).fetchone()["last_name"]
        entry = history.get(last_name, {"half_blocks_worked": 0, "shifts": {sn: 0 for sn in SHIFT_NAMES}, "weekend": 0})
        totals = category_totals(entry)
        return render_template(
            "resident_history.html", entry=entry, totals=totals,
            category_columns=CATEGORY_COLUMNS, shift_names=SHIFT_NAMES,
        )


def _build_grid(conn, run_id):
    """Returns (dates, {(shift_name, date_iso): resident_full_name})."""
    rows = conn.execute(
        "SELECT a.day AS day, a.shift_name AS shift_name, res.full_name AS full_name "
        "FROM assignments a JOIN residents res ON res.id = a.resident_id WHERE a.run_id = ?",
        (run_id,),
    ).fetchall()
    dates = sorted({row["day"] for row in rows})
    cells = {(row["shift_name"], row["day"]): row["full_name"] for row in rows}
    return {"dates": dates, "cells": cells}
