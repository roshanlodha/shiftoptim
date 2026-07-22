"""Flask app factory. Admin flow is Run -> Review -> Publish; residents view
the published schedule, manage their own time off, and see their history."""

import csv
import datetime as dt
import io
import json
import os

from flask import Flask, Response, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from schedulebuilder.pgy4.config import BALANCE_CATEGORIES, SHIFT_MIN_PER_HALF, SHIFTS, WEEKEND_DAYS
from schedulebuilder.pgy4.history import category_totals

from . import bridge
from .auth import admin_required, load_logged_in_user, login_required
from .colors import color_map_for_residents
from .db import get_db
from .settings import CATEGORY_ORDER, load_balance_weights, save_balance_weights

CATEGORY_COLUMNS = ["Total"] + list(BALANCE_CATEGORIES) + ["Weekend"]
SHIFT_NAMES = [info["name"] for info in SHIFTS.values()]
SOLVER_TIME_LIMIT = float(os.environ.get("SOLVER_TIME_LIMIT", 60.0))
PGY_LEVEL = 4


def create_app(db_path=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SHIFTOPTIM_SECRET_KEY", "dev-only-change-me")
    if db_path:
        app.config["DB_PATH"] = db_path

    @app.before_request
    def _before_request():
        load_logged_in_user()
        g.pending_trades_count = 0
        if g.user:
            conn = db_conn()
            if g.user["role"] == "admin":
                row = conn.execute("SELECT COUNT(*) FROM trade_requests WHERE status = 'pending_admin'").fetchone()
                g.pending_trades_count = row[0] if row else 0
            elif g.user["role"] == "resident" and g.user["resident_id"]:
                row = conn.execute("SELECT COUNT(*) FROM trade_requests WHERE status = 'pending_peer' AND target_id = ?", (g.user["resident_id"],)).fetchone()
                g.pending_trades_count = row[0] if row else 0

    @app.teardown_appcontext
    def _close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def db_conn():
        if "db" not in g:
            g.db = get_db(app.config.get("DB_PATH"))
        return g.db

    @app.template_filter('human_date')
    def format_human_date(date_str):
        import datetime
        try:
            d = datetime.date.fromisoformat(date_str)
            day = d.day
            if 11 <= day <= 13:
                suffix = 'th'
            else:
                suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
            return d.strftime(f'%B {day}{suffix}')
        except Exception:
            return date_str

    register_routes(app, db_conn)
    return app


def _half_blocks(conn, pgy_level, block_number=None):
    query = (
        "SELECT id, block_number, half, start_date, end_date FROM half_blocks "
        "WHERE pgy_level = ?"
    )
    params = [pgy_level]
    if block_number is not None:
        query += " AND block_number = ?"
        params.append(block_number)
    query += " ORDER BY block_number, half"
    return conn.execute(query, params).fetchall()


def _half_block(conn, pgy_level, block_number, half):
    return conn.execute(
        "SELECT id, block_number, half, start_date, end_date FROM half_blocks "
        "WHERE pgy_level = ? AND block_number = ? AND half = ?",
        (pgy_level, block_number, half),
    ).fetchone()


def _full_blocks(conn, pgy_level):
    return conn.execute(
        "SELECT block_number, MIN(start_date) AS start_date, MAX(end_date) AS end_date "
        "FROM half_blocks WHERE pgy_level = ? GROUP BY block_number ORDER BY block_number",
        (pgy_level,),
    ).fetchall()


def _get_pgy_config(pgy_level):
    cfg, _ = bridge._get_config(pgy_level)
    category_columns = ["Total"] + list(cfg.BALANCE_CATEGORIES) + ["Weekend"]
    shift_names = [info["name"] for info in cfg.SHIFTS.values()]
    return category_columns, shift_names


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
        pgy_level = session.get("pgy_level", 4)
        blocks = _full_blocks(conn, pgy_level)
        runs_by_block = {}
        for run in conn.execute("SELECT * FROM runs WHERE pgy_level = ?", (pgy_level,)).fetchall():
            runs_by_block.setdefault(run["block_number"], {})[run["status"]] = run
        return render_template("admin_dashboard.html", blocks=blocks,
                               runs_by_block=runs_by_block, error=error)

    @app.route("/admin")
    @admin_required
    def admin_dashboard():
        return _dashboard()

    @app.route("/admin/toggle_pgy/<int:pgy_level>")
    @admin_required
    def admin_toggle_pgy(pgy_level):
        if pgy_level in (1, 4):
            session["pgy_level"] = pgy_level
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/audit")
    @admin_required
    def admin_audit():
        conn = db_conn()
        groups = _audit_groups(conn)
        show_prop_row = conn.execute("SELECT value FROM settings WHERE key = 'show_proportions'").fetchone()
        show_proportions = int(show_prop_row["value"]) if show_prop_row else 1
        pgy_level = session.get("pgy_level", 4)
        category_columns, _ = _get_pgy_config(pgy_level)
        return render_template("admin_audit.html", groups=groups,
                               category_columns=category_columns, show_proportions=show_proportions)

    @app.route("/admin/settings", methods=["GET", "POST"])
    @admin_required
    def admin_settings():
        conn = db_conn()
        if request.method == "POST":
            weights = {cat: request.form.get(cat, 0) for cat in CATEGORY_ORDER}
            save_balance_weights(conn, weights)
            show_prop = 1 if request.form.get("show_proportions") else 0
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('show_proportions', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (str(show_prop),)
            )
            conn.commit()
            return redirect(url_for("admin_settings"))
        weights = load_balance_weights(conn)
        show_prop_row = conn.execute("SELECT value FROM settings WHERE key = 'show_proportions'").fetchone()
        show_proportions = int(show_prop_row["value"]) if show_prop_row else 1
        return render_template("admin_settings.html", weights=weights,
                               categories=CATEGORY_ORDER, show_proportions=show_proportions)

    @app.route("/admin/reset", methods=["POST"])
    @admin_required
    def admin_reset_all():
        conn = db_conn()
        conn.execute("DELETE FROM trade_requests")
        conn.execute("DELETE FROM assignments")
        conn.execute("DELETE FROM runs")
        conn.commit()
        return redirect(url_for("admin_dashboard"))

    @app.route("/admin/blocks/<int:block_number>/preview")
    @admin_required
    def admin_block_preview(block_number):
        conn = db_conn()
        pgy_level = session.get("pgy_level", 4)
        halves = conn.execute(
            "SELECT id, half FROM half_blocks WHERE pgy_level = ? AND block_number = ? ORDER BY half",
            (pgy_level, block_number),
        ).fetchall()
        if not halves or len(halves) < 2:
            return jsonify({"error": f"Half-blocks not found for block {block_number}"}), 404
        half_a_id = halves[0]["id"]
        half_b_id = halves[1]["id"]
        
        cfg, _ = bridge._get_config(pgy_level)
        active_roles = cfg.ACTIVE_ROLES

        residents = conn.execute(
            "SELECT id, full_name FROM residents WHERE pgy_level = ? ORDER BY last_name",
            (pgy_level,),
        ).fetchall()
        
        rows = []
        for res in residents:
            rot_a_row = conn.execute(
                "SELECT rotation FROM rotations WHERE resident_id = ? AND half_block_id = ?",
                (res["id"], half_a_id)
            ).fetchone()
            rot_b_row = conn.execute(
                "SELECT rotation FROM rotations WHERE resident_id = ? AND half_block_id = ?",
                (res["id"], half_b_id)
            ).fetchone()
            
            rot_a = rot_a_row["rotation"] if rot_a_row else None
            rot_b = rot_b_row["rotation"] if rot_b_row else None
            
            is_active_a = rot_a in active_roles
            is_active_b = rot_b in active_roles
            
            if is_active_a or is_active_b:
                rows.append({
                    "name": res["full_name"],
                    "role_a": rot_a if is_active_a else "Off",
                    "role_b": rot_b if is_active_b else "Off",
                })
        return jsonify({
            "block_number": block_number,
            "pgy_level": pgy_level,
            "residents": rows
        })

    @app.route("/admin/blocks/<int:block_number>/run", methods=["POST"])
    @admin_required
    def admin_run(block_number):
        pgy_level = session.get("pgy_level", 4)
        cfg, _ = bridge._get_config(pgy_level)
        shift_min = cfg.SHIFT_MIN_PER_HALF
        
        names = request.form.getlist("off_service_name[]")
        sites = request.form.getlist("off_service_site[]")
        half_a_list = request.form.getlist("off_service_half_a[]")
        half_b_list = request.form.getlist("off_service_half_b[]")
        
        off_services = []
        for i in range(len(names)):
            name = names[i].strip()
            if not name:
                continue
            has_a = (i < len(half_a_list) and half_a_list[i] == "1")
            has_b = (i < len(half_b_list) and half_b_list[i] == "1")
            if not has_a and not has_b:
                continue
            
            if has_a and has_b:
                half = "both"
            elif has_a:
                half = "a"
            else:
                half = "b"
                
            off_services.append({
                "name": name,
                "site": sites[i],
                "half": half
            })

        run_id = bridge.run_solver_and_stage_draft(
            db_conn(), pgy_level, block_number, shift_min, SOLVER_TIME_LIMIT, off_services=off_services)
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
        pgy_level = run["pgy_level"]
        category_columns, shift_names = _get_pgy_config(pgy_level)
        half = request.args.get("half", "a")
        hb = _half_block(conn, pgy_level, run["block_number"], half)
        grid = _build_grid(conn, run_id, hb["start_date"], hb["end_date"]) if hb else None
        viewable = _half_blocks(conn, pgy_level, run["block_number"])
        summary_block = _range_summary(conn, run_id, run["block_number"]) if viewable else []
        summary_half = _range_summary(conn, run_id, run["block_number"], half=half) if hb else []
        msg = request.args.get("msg")
        return render_template(
            "admin_review_run.html", run=run, grid=grid,
            summary_block=summary_block, summary_half=summary_half,
            shift_names=shift_names, category_columns=category_columns,
            shift_info=bridge._shift_info_by_name(pgy_level),
            half=half, viewable_halves=viewable, opt_msg=msg,
        )

    @app.route("/admin/runs/<int:run_id>/csv")
    @admin_required
    def admin_download_csv(run_id):
        conn = db_conn()
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return redirect(url_for("admin_dashboard"))
        half = request.args.get("half")  # None / omit = whole block
        return _schedule_csv_response(conn, run_id, run["pgy_level"], run["block_number"], half)

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

    @app.route("/admin/runs/<int:run_id>/optimize", methods=["POST"])
    @admin_required
    def admin_optimize_run(run_id):
        conn = db_conn()
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if run is None:
            return redirect(url_for("admin_dashboard"))
        res = bridge.optimize_block_run(conn, run_id)
        swaps = res["swaps_applied"]
        half = request.args.get("half", "a")
        return redirect(url_for("admin_review_run", run_id=run_id, half=half, msg=f"Optimization finished: {swaps} shift swap(s) executed."))

    # --- Resident -----------------------------------------------------------

    @app.route("/schedule")
    @login_required
    def resident_schedule():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        pgy_level = 4
        resident_last_name = ""
        if resident_id:
            row = conn.execute("SELECT last_name, pgy_level FROM residents WHERE id = ?", (resident_id,)).fetchone()
            if row:
                resident_last_name = row["last_name"]
                pgy_level = row["pgy_level"]

        category_columns, shift_names = _get_pgy_config(pgy_level)

        published = {
            row["block_number"]
            for row in conn.execute(
                "SELECT DISTINCT block_number FROM runs WHERE status = 'published' AND pgy_level = ?",
                (pgy_level,),
            ).fetchall()
        }
        blocks = [b for b in _full_blocks(conn, pgy_level) if b["block_number"] in published]

        block_number = request.args.get("block", type=int)
        half = request.args.get("half", "a")
        if block_number is None and blocks:
            block_number = blocks[-1]["block_number"]

        grid = None
        viewable_halves = []
        run_id = None
        if block_number is not None:
            viewable_halves = _half_blocks(conn, pgy_level, block_number)
            run = conn.execute(
                "SELECT id FROM runs WHERE pgy_level = ? AND block_number = ? AND status = 'published'",
                (pgy_level, block_number),
            ).fetchone()
            hb = _half_block(conn, pgy_level, block_number, half)
            if run and hb:
                run_id = run["id"]
                grid = _build_grid(conn, run_id, hb["start_date"], hb["end_date"])

        calendar_webcal_url = None
        if g.user["role"] == "resident" and resident_id:
            token = bridge.ensure_calendar_token(conn, resident_id)
            https_url = url_for("calendar_feed", token=token, _external=True)
            calendar_webcal_url = https_url.replace("https://", "webcal://").replace(
                "http://", "webcal://"
            )

        return render_template(
            "resident_schedule.html", blocks=blocks, block_number=block_number,
            half=half, viewable_halves=viewable_halves,
            grid=grid, shift_names=shift_names,
            shift_info=bridge._shift_info_by_name(pgy_level),
            resident_last_name=resident_last_name, run_id=run_id,
            calendar_webcal_url=calendar_webcal_url,
        )

    @app.route("/schedule/csv")
    @login_required
    def resident_download_csv():
        # Admins only — residents use the calendar subscribe feed.
        if g.user["role"] != "admin":
            return redirect(url_for("resident_schedule"))
        conn = db_conn()
        resident_id = g.user["resident_id"]
        pgy_level = session.get("pgy_level", 4)
        if resident_id:
            row = conn.execute("SELECT pgy_level FROM residents WHERE id = ?", (resident_id,)).fetchone()
            if row:
                pgy_level = row["pgy_level"]
        block_number = request.args.get("block", type=int)
        half = request.args.get("half")  # None = whole block
        if block_number is None:
            return redirect(url_for("resident_schedule"))
        run = conn.execute(
            "SELECT id FROM runs WHERE pgy_level = ? AND block_number = ? AND status = 'published'",
            (pgy_level, block_number),
        ).fetchone()
        if run is None:
            return redirect(url_for("resident_schedule", block=block_number, half=half or "a"))
        return _schedule_csv_response(conn, run["id"], pgy_level, block_number, half)

    @app.route("/calendar/<token>.ics")
    def calendar_feed(token):
        """Unauthenticated ICS feed for calendar apps (token is the secret)."""
        conn = db_conn()
        resident_id = bridge.resident_id_for_calendar_token(conn, token)
        if resident_id is None:
            return "Not found", 404
        body = bridge.build_resident_ics(conn, resident_id)
        if body is None:
            return "Not found", 404
        return Response(
            body,
            mimetype="text/calendar; charset=utf-8",
            headers={
                "Content-Disposition": 'inline; filename="shiftoptim.ics"',
                "Cache-Control": "no-cache",
            },
        )

    @app.route("/timeoff", methods=["GET", "POST"])
    @login_required
    def resident_timeoff():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        if resident_id is None:
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
        pgy_level = resident["pgy_level"]
        cfg, _ = bridge._get_config(pgy_level)
        if pgy_level == 1:
            from schedulebuilder.pgy1.history import category_totals as cat_totals_fn
        else:
            from schedulebuilder.pgy4.history import category_totals as cat_totals_fn
        category_columns = list(cfg.BALANCE_CATEGORIES) + ["Weekend"]
        shift_names = [info["name"] for info in cfg.SHIFTS.values()]
        duration_by_name = {info["name"]: info["duration"] for info in cfg.SHIFTS.values()}

        history = bridge.load_history_from_db(conn, pgy_level)
        entry = history.get(
            resident["last_name"],
            bridge._empty_entry(shift_names),
        )
        totals = cat_totals_fn(entry)
        # Hide empty wellness categories (Total already omitted from columns).
        category_columns = [c for c in category_columns if totals.get(c, 0)]
        # Bar chart rows: skip shifts with 0 hours. Hours = count * catalog duration.
        shift_log = []
        for sn in shift_names:
            count = entry["shifts"].get(sn, 0)
            hours = count * duration_by_name.get(sn, 0)
            if hours:
                shift_log.append({"name": sn, "count": count, "hours": hours})
        max_hours = max((r["hours"] for r in shift_log), default=1)
        max_count = max((r["count"] for r in shift_log), default=1)
        return render_template(
            "resident_history.html",
            entry=entry,
            totals=totals,
            category_columns=category_columns,
            shift_log=shift_log,
            max_hours=max_hours,
            max_count=max_count,
        )

    @app.route("/resident/settings", methods=["GET", "POST"])
    @login_required
    def resident_settings():
        conn = db_conn()
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("admin_settings"))
            
        error = None
        success = None
        pref_key = f"pref_resident_{resident_id}"
        
        if request.method == "POST":
            form_type = request.form.get("form_type")
            if form_type == "password":
                current_pw = request.form.get("current_password")
                new_pw = request.form.get("new_password")
                confirm_pw = request.form.get("confirm_password")
                
                user_row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (g.user["id"],)).fetchone()
                if not user_row or not check_password_hash(user_row["password_hash"], current_pw):
                    error = "Incorrect current password."
                elif new_pw != confirm_pw:
                    error = "New passwords do not match."
                elif not new_pw:
                    error = "New password cannot be empty."
                else:
                    new_hash = generate_password_hash(new_pw)
                    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, g.user["id"]))
                    conn.commit()
                    success = "Password changed successfully!"
            elif form_type == "preferences":
                pref = request.form.get("preference", "frequent")
                if pref not in ("frequent", "longer"):
                    pref = "frequent"
                conn.execute("UPDATE users SET preference = ? WHERE id = ?", (pref, g.user["id"]))
                conn.commit()
                success = "Preferences saved!"
                
        user_row = conn.execute("SELECT preference FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        user_pref = user_row["preference"] if user_row and user_row["preference"] else "frequent"
            
        return render_template(
            "resident_settings.html",
            preference=user_pref,
            error=error,
            success=success
        )

    # --- Trade requests (resident) -----------------------------------------

    def _published_run_for_resident(conn, resident_id, day):
        """Return run row for the published run whose date range contains day."""
        return conn.execute(
            "SELECT r.id, r.pgy_level, r.block_number FROM runs r "
            "JOIN half_blocks hb ON hb.pgy_level = r.pgy_level "
            "WHERE r.status = 'published' AND ? >= hb.start_date AND ? <= hb.end_date "
            "AND EXISTS (SELECT 1 FROM assignments a WHERE a.run_id = r.id AND a.resident_id = ? AND a.day = ?) "
            "LIMIT 1",
            (day, day, resident_id, day),
        ).fetchone()

    @app.route("/trades/find", methods=["POST"])
    @login_required
    def trades_find():
        """JSON endpoint: returns valid swap candidates for a given shift."""
        if g.user["role"] == "admin":
            resident_id = request.form.get("resident_id", type=int)
            run_id = request.form.get("run_id", type=int)
        else:
            resident_id = g.user["resident_id"]
            run_id = None

        if resident_id is None:
            return jsonify({"error": "No resident linked"}), 403
        day = request.form.get("day")
        shift = request.form.get("shift")
        if not day or not shift:
            return jsonify({"error": "day and shift required"}), 400
        conn = db_conn()
        if not run_id:
            run = _published_run_for_resident(conn, resident_id, day)
            if run is None:
                return jsonify({"error": "No published run found for this shift"}), 404
            run_id = run["id"]
        swaps = bridge.find_valid_swaps(conn, run_id, resident_id, day, shift)
        return jsonify({"run_id": run_id, "swaps": swaps})

    @app.route("/schedule/buddies", methods=["POST"])
    @login_required
    def schedule_buddies():
        """JSON: shift_buddies (same team) + meal_buddies (same site, overlap)."""
        day = request.form.get("day")
        shift = request.form.get("shift")
        if not day or not shift:
            return jsonify({"error": "day and shift required"}), 400

        if g.user["role"] == "admin":
            resident_id = request.form.get("resident_id", type=int)
        else:
            resident_id = g.user["resident_id"]
        if resident_id is None:
            return jsonify({"error": "No resident linked"}), 403

        conn = db_conn()
        row = conn.execute(
            "SELECT pgy_level FROM residents WHERE id = ?", (resident_id,),
        ).fetchone()
        if row is None:
            return jsonify({"error": "Resident not found"}), 404
        pgy_level = row["pgy_level"]

        if g.user["role"] != "admin":
            cfg, _ = bridge._get_config(pgy_level)
            canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)
            rows = conn.execute(
                "SELECT a.shift_name FROM assignments a "
                "JOIN runs r ON r.id = a.run_id "
                "WHERE r.status = 'published' AND a.resident_id = ? AND a.day = ?",
                (resident_id, day),
            ).fetchall()
            if not any(canonicalize(r["shift_name"]) == shift for r in rows):
                return jsonify({"error": "Forbidden"}), 403

        return jsonify(bridge.find_shift_buddies(conn, day, shift, resident_id, pgy_level))

    @app.route("/admin/schedule/swap", methods=["POST"])
    @admin_required
    def admin_schedule_swap():
        """Directly execute a shift swap for the admin."""
        run_id = request.form.get("run_id", type=int)
        req_resident_id = request.form.get("requester_id", type=int)
        req_day = request.form.get("requester_day")
        req_shift = request.form.get("requester_shift")
        tgt_resident_id = request.form.get("target_id", type=int)
        tgt_day = request.form.get("target_day")
        tgt_shift = request.form.get("target_shift")

        if not all([run_id, req_resident_id, req_day, req_shift, tgt_resident_id, tgt_day, tgt_shift]):
            return "Missing parameters", 400

        conn = db_conn()
        # Same PGY class only
        pgys = conn.execute(
            "SELECT id, pgy_level FROM residents WHERE id IN (?, ?)",
            (req_resident_id, tgt_resident_id),
        ).fetchall()
        pgy_map = {r["id"]: r["pgy_level"] for r in pgys}
        if pgy_map.get(req_resident_id) != pgy_map.get(tgt_resident_id):
            return "Cross-PGY swaps are not allowed", 400

        # Verify run exists
        run = conn.execute("SELECT status, block_number FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return "Run not found", 404

        # Swap shift names in assignments table directly
        # Update requester's assignment day -> target's shift
        conn.execute(
            "UPDATE assignments SET shift_name = ? WHERE run_id = ? AND resident_id = ? AND day = ?",
            (tgt_shift, run_id, req_resident_id, req_day),
        )
        # Update target's assignment day -> requester's shift
        conn.execute(
            "UPDATE assignments SET shift_name = ? WHERE run_id = ? AND resident_id = ? AND day = ?",
            (req_shift, run_id, tgt_resident_id, tgt_day),
        )
        conn.commit()

        # Redirect back to referring page or resident schedule
        ref = request.referrer or ""
        if "/admin/review/" in ref:
            return redirect(ref)
        return redirect(url_for("resident_schedule", block=run["block_number"]))

    @app.route("/trades/request", methods=["POST"])
    @login_required
    def trades_request():
        """Create a new pending_peer trade request."""
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("index"))
        conn = db_conn()
        run_id = request.form.get("run_id", type=int)
        req_day = request.form.get("requester_day")
        req_shift = request.form.get("requester_shift")
        tgt_id = request.form.get("target_id", type=int)
        tgt_day = request.form.get("target_day")
        tgt_shift = request.form.get("target_shift")
        if not all([run_id, req_day, req_shift, tgt_id, tgt_day, tgt_shift]):
            return redirect(url_for("resident_schedule"))
        # Verify requester actually holds that shift
        owns = conn.execute(
            "SELECT 1 FROM assignments WHERE run_id=? AND resident_id=? AND day=? AND shift_name=?",
            (run_id, resident_id, req_day, req_shift),
        ).fetchone()
        if not owns:
            return redirect(url_for("resident_schedule"))
        # Same PGY class only (PGY-1↔PGY-1, PGY-4↔PGY-4, …)
        pgys = conn.execute(
            "SELECT id, pgy_level FROM residents WHERE id IN (?, ?)",
            (resident_id, tgt_id),
        ).fetchall()
        pgy_map = {r["id"]: r["pgy_level"] for r in pgys}
        if pgy_map.get(resident_id) is None or pgy_map.get(resident_id) != pgy_map.get(tgt_id):
            return redirect(url_for("resident_schedule"))
        # Prevent duplicate active request on same shift
        dupe = conn.execute(
            "SELECT 1 FROM trade_requests WHERE run_id=? AND requester_id=? AND requester_day=? "
            "AND requester_shift=? AND status IN ('pending_peer','pending_admin')",
            (run_id, resident_id, req_day, req_shift),
        ).fetchone()
        if dupe:
            return redirect(url_for("resident_trades"))
        conn.execute(
            "INSERT INTO trade_requests (run_id, requester_id, requester_day, requester_shift, "
            "target_id, target_day, target_shift) VALUES (?,?,?,?,?,?,?)",
            (run_id, resident_id, req_day, req_shift, tgt_id, tgt_day, tgt_shift),
        )
        conn.commit()
        return redirect(url_for("resident_trades"))

    @app.route("/trades")
    @login_required
    def resident_trades():
        """Resident's inbox (incoming) and outbox (outgoing) trade requests."""
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("index"))
        conn = db_conn()
        incoming = conn.execute(
            "SELECT t.*, req.full_name AS requester_name, tgt.full_name AS target_name "
            "FROM trade_requests t "
            "JOIN residents req ON req.id = t.requester_id "
            "JOIN residents tgt ON tgt.id = t.target_id "
            "WHERE t.target_id = ? ORDER BY t.created_at DESC",
            (resident_id,),
        ).fetchall()
        outgoing = conn.execute(
            "SELECT t.*, req.full_name AS requester_name, tgt.full_name AS target_name "
            "FROM trade_requests t "
            "JOIN residents req ON req.id = t.requester_id "
            "JOIN residents tgt ON tgt.id = t.target_id "
            "WHERE t.requester_id = ? ORDER BY t.created_at DESC",
            (resident_id,),
        ).fetchall()
        return render_template("trades.html", incoming=incoming, outgoing=outgoing)

    @app.route("/trades/<int:trade_id>/respond", methods=["POST"])
    @login_required
    def trades_respond(trade_id):
        """Target resident accepts or denies a pending_peer request."""
        resident_id = g.user["resident_id"]
        if resident_id is None:
            return redirect(url_for("index"))
        conn = db_conn()
        trade = conn.execute(
            "SELECT * FROM trade_requests WHERE id = ? AND target_id = ? AND status = 'pending_peer'",
            (trade_id, resident_id),
        ).fetchone()
        if trade is None:
            return redirect(url_for("resident_trades"))
        action = request.form.get("action")
        if action == "accept":
            conn.execute(
                "UPDATE trade_requests SET status = 'pending_admin' WHERE id = ?", (trade_id,)
            )
        elif action == "deny":
            conn.execute(
                "UPDATE trade_requests SET status = 'peer_denied', resolved_at = datetime('now') WHERE id = ?",
                (trade_id,),
            )
        conn.commit()
        return redirect(url_for("resident_trades"))

    # --- Trade requests (admin) --------------------------------------------

    @app.route("/admin/trades")
    @admin_required
    def admin_trades():
        """Admin view: all trades awaiting admin approval."""
        conn = db_conn()
        pending = conn.execute(
            "SELECT t.*, req.full_name AS requester_name, tgt.full_name AS target_name "
            "FROM trade_requests t "
            "JOIN residents req ON req.id = t.requester_id "
            "JOIN residents tgt ON tgt.id = t.target_id "
            "ORDER BY t.status DESC, t.created_at DESC",
        ).fetchall()
        return render_template("admin_trades.html", trades=pending)

    @app.route("/admin/trades/<int:trade_id>/resolve", methods=["POST"])
    @admin_required
    def admin_trades_resolve(trade_id):
        """Admin approves (swaps assignments) or denies a pending_admin request."""
        conn = db_conn()
        trade = conn.execute(
            "SELECT * FROM trade_requests WHERE id = ? AND status = 'pending_admin'",
            (trade_id,),
        ).fetchone()
        if trade is None:
            return redirect(url_for("admin_trades"))
        action = request.form.get("action")
        if action == "approve":
            bridge.apply_trade(conn, trade_id)  # commits inside
        elif action == "deny":
            conn.execute(
                "UPDATE trade_requests SET status = 'admin_denied', resolved_at = datetime('now') WHERE id = ?",
                (trade_id,),
            )
            conn.commit()
        return redirect(url_for("admin_trades"))


def _week_chunks(dates):

    weeks, week = [], []
    for d in dates:
        if week and d.weekday() == 0:
            weeks.append(week)
            week = []
        week.append(d)
    if week:
        weeks.append(week)
    return weeks


def _build_grid(conn, run_id, start_date=None, end_date=None):
    query = (
        "SELECT a.day AS day, a.shift_name AS shift_name, "
        "res.id AS resident_id, res.last_name AS last_name, res.full_name AS full_name "
        "FROM assignments a "
        "JOIN residents res ON res.id = a.resident_id "
        "WHERE a.run_id = ?"
    )
    params = [run_id]
    if start_date and end_date:
        query += " AND a.day >= ? AND a.day <= ?"
        params.extend([start_date, end_date])

    rows = conn.execute(query, params).fetchall()
    run_row = conn.execute("SELECT pgy_level FROM runs WHERE id = ?", (run_id,)).fetchone()
    pgy_level = run_row["pgy_level"] if run_row else 4
    cfg, _ = bridge._get_config(pgy_level)
    canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)
    colors = color_map_for_residents(conn, pgy_level)

    cells = {}
    counts = {}
    meta = {}
    for row in rows:
        sname = canonicalize(row["shift_name"])
        cells[(sname, row["day"])] = {
            "last_name": row["last_name"],
            "resident_id": row["resident_id"]
        }
        counts[row["last_name"]] = counts.get(row["last_name"], 0) + 1
        meta[row["last_name"]] = row

    legend = sorted(
        (
            {"full_name": meta[ln]["full_name"], "last_name": ln,
             "color": colors.get(ln, "#3b82f6"), "count": counts[ln]}
             for ln in meta
        ),
        key=lambda item: item["last_name"],
    )
    dates = sorted({row["day"] for row in rows})
    weeks = _week_chunks([dt.date.fromisoformat(iso) for iso in dates])
    return {"weeks": weeks, "cells": cells, "colors": colors, "legend": legend}


def _range_summary(conn, run_id, block_number, half=None):
    """Per-resident shift counts for a half-block (half='a'|'b') or full block
    (half=None), with rotation assignment(s)."""
    run_row = conn.execute("SELECT pgy_level FROM runs WHERE id = ?", (run_id,)).fetchone()
    pgy_level = run_row["pgy_level"] if run_row else 4
    halves = _half_blocks(conn, pgy_level, block_number)
    if not halves:
        return []

    if half is not None:
        hb = next((h for h in halves if h["half"] == half), None)
        if hb is None:
            return []
        start_date, end_date = hb["start_date"], hb["end_date"]
        target_halves = [hb]
    else:
        start_date, end_date = halves[0]["start_date"], halves[-1]["end_date"]
        target_halves = halves

    rotations_by_half = {}
    for hb in target_halves:
        rotations_by_half[hb["half"]] = {
            row["last_name"]: row["rotation"]
            for row in conn.execute(
                "SELECT res.last_name AS last_name, rot.rotation AS rotation "
                "FROM rotations rot JOIN residents res ON res.id = rot.resident_id "
                "WHERE rot.half_block_id = ?",
                (hb["id"],),
            ).fetchall()
        }

    rows = conn.execute(
        "SELECT res.full_name AS full_name, res.last_name AS last_name, "
        "a.shift_name AS shift_name, a.day AS day "
        "FROM assignments a JOIN residents res ON res.id = a.resident_id "
        "WHERE a.run_id = ? AND a.day >= ? AND a.day <= ?",
        (run_id, start_date, end_date),
    ).fetchall()

    cfg, _ = bridge._get_config(pgy_level)
    if pgy_level == 1:
        from schedulebuilder.pgy1.history import category_totals as pgy1_category_totals
        cat_totals_fn = pgy1_category_totals
    else:
        from schedulebuilder.pgy4.history import category_totals as pgy4_category_totals
        cat_totals_fn = pgy4_category_totals

    shift_names = [info["name"] for info in cfg.SHIFTS.values()]
    canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)

    by_resident = {}
    for row in rows:
        ln = row["last_name"]
        if ln not in by_resident:
            by_resident[ln] = {
                "full_name": row["full_name"],
                "shifts": {sn: 0 for sn in shift_names},
                "weekend": 0,
            }
        sname = canonicalize(row["shift_name"])
        if sname in by_resident[ln]["shifts"]:
            by_resident[ln]["shifts"][sname] += 1
        if dt.date.fromisoformat(row["day"]).weekday() in cfg.WEEKEND_DAYS:
            by_resident[ln]["weekend"] += 1

    from schedulebuilder.pgy1.config import is_em_proper

    summary = []
    for ln, data in sorted(by_resident.items(), key=lambda x: x[1]["full_name"]):
        roles = []
        for hb in target_halves:
            role = rotations_by_half.get(hb["half"], {}).get(ln)
            if role and role not in roles:
                roles.append(role)
        assignment = " / ".join(roles) if roles else "—"
        entry = {"shifts": data["shifts"], "weekend": data["weekend"]}
        totals = cat_totals_fn(entry)
        is_off = pgy_level == 1 and not is_em_proper(ln)
        summary.append({
            "full_name": data["full_name"],
            "assignment": assignment,
            "shifts": data["shifts"],
            "totals": totals,
            "total": sum(data["shifts"].values()),
            "is_off_service": is_off,
        })
    return summary


def _half_summary(conn, run_id, block_number, half):
    return _range_summary(conn, run_id, block_number, half=half)


def _schedule_csv_response(conn, run_id, pgy_level, block_number, half=None):
    """CSV grid matching schedulebuilder export format (week chunks)."""
    cfg, _ = bridge._get_config(pgy_level)
    shift_names = [info["name"] for info in cfg.SHIFTS.values()]
    canonicalize = getattr(cfg, "canonical_shift_name", lambda n: n)

    halves = _half_blocks(conn, pgy_level, block_number)
    if not halves:
        return Response("No schedule", status=404)
    if half:
        hb = next((h for h in halves if h["half"] == half), None)
        if hb is None:
            return Response("Half not found", status=404)
        start_date, end_date = hb["start_date"], hb["end_date"]
        label = f"{block_number}{half}"
    else:
        start_date, end_date = halves[0]["start_date"], halves[-1]["end_date"]
        label = str(block_number)

    rows = conn.execute(
        "SELECT a.day AS day, a.shift_name AS shift_name, res.last_name AS last_name "
        "FROM assignments a JOIN residents res ON res.id = a.resident_id "
        "WHERE a.run_id = ? AND a.day >= ? AND a.day <= ?",
        (run_id, start_date, end_date),
    ).fetchall()

    cells = {}
    dates = set()
    for row in rows:
        sn = canonicalize(row["shift_name"])
        cells[(sn, row["day"])] = row["last_name"]
        dates.add(row["day"])

    # Include empty days in range so weeks stay contiguous
    start = dt.date.fromisoformat(start_date)
    end = dt.date.fromisoformat(end_date)
    all_dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]

    buf = io.StringIO()
    writer = csv.writer(buf)
    for i, week_dates in enumerate(_week_chunks(all_dates)):
        if i:
            writer.writerow([])
        writer.writerow(["Shift"] + [d.isoformat() for d in week_dates])
        for sn in shift_names:
            writer.writerow(
                [sn] + [cells.get((sn, d.isoformat()), "") for d in week_dates]
            )

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="block{label}_schedule.csv"',
        },
    )


def _audit_groups(conn):
    """Cumulative wellness totals per resident, grouped by PGY level."""
    groups = []
    pgy_levels = conn.execute(
        "SELECT DISTINCT pgy_level FROM residents ORDER BY pgy_level"
    ).fetchall()
    for pgy_row in pgy_levels:
        pgy_level = pgy_row["pgy_level"]
        cfg, _ = bridge._get_config(pgy_level)
        if pgy_level == 1:
            from schedulebuilder.pgy1.history import category_totals as pgy1_category_totals
            cat_totals_fn = pgy1_category_totals
        else:
            from schedulebuilder.pgy4.history import category_totals as pgy4_category_totals
            cat_totals_fn = pgy4_category_totals

        category_columns = ["Total"] + list(cfg.BALANCE_CATEGORIES) + ["Weekend"]
        shift_names = [info["name"] for info in cfg.SHIFTS.values()]

        history = bridge.load_history_from_db(conn, pgy_level)
        residents = conn.execute(
            "SELECT full_name, last_name FROM residents WHERE pgy_level = ? ORDER BY last_name",
            (pgy_level,),
        ).fetchall()
        rows = []
        for res in residents:
            # Off-service placeholders (PGY-1 solver) stay out of the wellness audit.
            if res["full_name"].startswith("Off Service") or res["last_name"].startswith("Off Service"):
                continue
            entry = history.get(
                res["last_name"],
                {"half_blocks_worked": 0, "shifts": {sn: 0 for sn in shift_names}, "weekend": 0},
            )
            totals = cat_totals_fn(entry)
            rows.append({
                "full_name": res["full_name"],
                "half_blocks_worked": entry["half_blocks_worked"],
                "totals": totals,
                "total_shifts": sum(entry["shifts"].values()),
                "cell_styles": {},
            })

        # Calculate group averages for category columns to find anomalies
        for c in category_columns:
            sum_totals = sum(r["totals"].get(c, 0) for r in rows)
            sum_shifts = sum(r["total_shifts"] for r in rows)
            group_avg_prop = sum_totals / sum_shifts if sum_shifts > 0 else 0
            
            for r in rows:
                if r["total_shifts"] > 0:
                    r_prop = r["totals"].get(c, 0) / r["total_shifts"]
                    diff = r_prop - group_avg_prop
                    # Using a threshold of 18% absolute difference for gross anomalies
                    if diff > 0.18:
                        r["cell_styles"][c] = "anomaly-high"
                    elif diff < -0.18:
                        r["cell_styles"][c] = "anomaly-low"
                    else:
                        r["cell_styles"][c] = ""
                else:
                    r["cell_styles"][c] = ""

        groups.append((pgy_level, rows))
    return groups
