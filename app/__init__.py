import os
import sqlite3
from datetime import datetime, timedelta
from app.reviews import register_review_routes
from app.exercise_editing import register_exercise_edit_routes


from flask import (
    Flask,
    abort,
    g,
    redirect,
    render_template,
    request,
    url_for,
)

import config
from backup import BACKUP_DIR, backup_if_due
from import_data import FILES
from db import (
    DB_PATH,
    close_expired_sessions,
    get_connection,
    init_db,
)
from selection import day_type_for_weekday, make_rng, plan_day
from app.tracking import register_tracking_routes


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)

    app.config.from_mapping(
        DATABASE=DB_PATH,
        BACKUP_DIR=os.environ.get("WORKOUT_BACKUP_DIR", str(BACKUP_DIR)),
        EXERCISE_CSV_FILES=FILES.copy(),
    )

    if test_config is not None:
        app.config.update(test_config)

    def get_db():
        if "db" not in g:
            g.db = get_connection(app.config["DATABASE"])
        return g.db

    @app.teardown_appcontext
    def close_db(error=None):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # Create missing tables, but do not import CSV data automatically.
    with app.app_context():
        init_db(get_db())

    @app.get("/")
    def home():
        now = datetime.now()
        today = now.date()
        yesterday = today - timedelta(days=1)

        conn = get_db()
        expired_count = close_expired_sessions(conn, now)

        backup_error = False
        try:
            backup_if_due(app.config["DATABASE"], app.config["BACKUP_DIR"])
        except (OSError, sqlite3.Error, ValueError):
            app.logger.exception("Automatic database backup failed")
            backup_error = True

        resumable_sessions = conn.execute(
            """
            SELECT id, date, day_type, started_at
            FROM sessions
            WHERE finished_at IS NULL
              AND date = ?
            ORDER BY id DESC
            """,
            (yesterday.isoformat(),),
        ).fetchall()

        # Avoid a leading zero on single-digit dates.
        display_date = (
            f"{today.strftime('%A %b')} {today.day}"
        )

        return render_template(
            "index.html",
            today=display_date,
            day_type=day_type_for_weekday(today.weekday()),
            resumable_sessions=resumable_sessions,
            expired_count=expired_count,
            backup_error=backup_error,
        )

    @app.post("/start")
    def start_session():
        now = datetime.now()
        day_type = request.form.get("day_type")

        if day_type not in ("full", "flex"):
            abort(400, description="Choose a full or flexibility workout.")

        conn = get_db()

        exercises = conn.execute(
            """
            SELECT *
            FROM exercises
            WHERE active = 1
            ORDER BY id
            """
        ).fetchall()

        history_rows = conn.execute(
            """
            SELECT
                exercise_id,
                COUNT(*) AS times_done,
                MAX(completed_at) AS last_done
            FROM session_items
            WHERE status = 'done'
            GROUP BY exercise_id
            """
        ).fetchall()

        history = {
            row["exercise_id"]: {
                "times_done": row["times_done"],
                "last_done": row["last_done"],
            }
            for row in history_rows
        }

        # Validate template capacity before calling the selector.
        stretches = [
            exercise for exercise in exercises
            if exercise["type"] == "stretch"
            and exercise["focus"] != config.BALANCE_AREA
        ]
        balance = [
            exercise for exercise in exercises
            if exercise["type"] == "stretch"
            and exercise["focus"] == config.BALANCE_AREA
        ]
        strength = [
            exercise for exercise in exercises
            if exercise["type"] == "strength"
            and exercise["focus"] != config.BALANCE_AREA
        ]

        if day_type == "full":
            requirements = [
                ("non-Balance stretches", stretches, config.BLOCK_SIZE * 2),
                ("strength exercises", strength, config.BLOCK_SIZE),
            ]
        else:
            requirements = [
                ("Balance stretches", balance, config.FLEX_BALANCE),
                (
                    "non-Balance stretches",
                    stretches,
                    config.FLEX_STRETCHES - config.FLEX_BALANCE,
                ),
            ]

        for label, pool, required in requirements:
            if len(pool) < required:
                abort(
                    400,
                    description=(
                        f"This workout requires {required} {label}; "
                        f"only {len(pool)} are active."
                    ),
                )

        plan = plan_day(day_type, exercises, history, make_rng())

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO sessions (date, day_type, started_at)
                VALUES (?, ?, ?)
                """,
                (
                    now.date().isoformat(),
                    day_type,
                    now.isoformat(timespec="seconds"),
                ),
            )
            session_id = cursor.lastrowid

            conn.executemany(
                """
                INSERT INTO session_items
                    (session_id, position, block, exercise_id)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        session_id,
                        item["position"],
                        item["block"],
                        item["exercise"]["id"],
                    )
                    for item in plan
                ],
            )

        return redirect(url_for("workout", session_id=session_id))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/exercises")
    def exercises():
        rows = get_db().execute(
            """
            SELECT
                e.*,
                COUNT(si.id) AS times_done,
                MAX(si.completed_at) AS last_done
            FROM exercises AS e
            LEFT JOIN session_items AS si
                ON si.exercise_id = e.id
                AND si.status = 'done'
            WHERE e.active = 1
            GROUP BY e.id
            ORDER BY e.type, e.focus, e.name
            """
        ).fetchall()

        return render_template(
            "exercises.html",
            exercises=rows,
        )

    register_review_routes(app, get_db)
    register_tracking_routes(app, get_db)
    register_exercise_edit_routes(app, get_db)

    return app