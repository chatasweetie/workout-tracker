import math
from datetime import date, datetime

from flask import abort, redirect, render_template, request, url_for
from app.history_metrics import build_dashboard


def optional_number(value, label, integer=False):
    if value is None or value == "":
        return None

    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number.")

    number = float(value)

    if not math.isfinite(number):
        raise ValueError(f"{label} must be a finite number.")

    if integer:
        if number <= 0 or not number.is_integer():
            raise ValueError(f"{label} must be a positive whole number.")
        return int(number)

    if number < 0:
        raise ValueError(f"{label} cannot be negative.")

    return number


def register_tracking_routes(app, get_db):
    def load_session(session_id):
        session = get_db().execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()

        if session is None:
            abort(404, description="Session not found.")

        return session

    def load_items(session_id):
        conn = get_db()

        rows = conn.execute(
            """
            SELECT
                si.id AS item_id,
                si.exercise_id,
                si.position,
                si.block,
                si.status,
                si.note,
                e.name,
                e.focus,
                e.description,
                e.dose,
                e.image_url,
                e.equipment,
                e.on_floor,
                e.type,
                e.seconds,
                e.per_side
            FROM session_items AS si
            JOIN exercises AS e ON e.id = si.exercise_id
            WHERE si.session_id = ?
            ORDER BY si.position
            """,
            (session_id,),
        ).fetchall()

        items = []

        for row in rows:
            item = dict(row)
            item["review_url"] = url_for(
                "create_exercise_review",
                item_id=item["item_id"],
            )

            item["reviews"] = [
                dict(review)
                for review in conn.execute(
                    """
                    SELECT id, note, created_at
                    FROM exercise_review_notes
                    WHERE exercise_id = ?
                      AND resolved_at IS NULL
                    ORDER BY created_at DESC, id DESC
                    """,
                    (item["exercise_id"],),
                ).fetchall()
            ]
            
            item["sets"] = [
                dict(record)
                for record in conn.execute(
                    """
                    SELECT set_number, reps, weight
                    FROM strength_sets
                    WHERE session_item_id = ?
                    ORDER BY set_number
                    """,
                    (item["item_id"],),
                ).fetchall()
            ]
            item["save_url"] = url_for(
                "save_item",
                item_id=item["item_id"],
            )
            items.append(item)

        return items

    @app.get("/session/<int:session_id>")
    def workout(session_id):
        session = load_session(session_id)

        if session["finished_at"]:
            return redirect(
                url_for("session_summary", session_id=session_id)
            )

        items = load_items(session_id)

        if not items:
            abort(404, description="This session has no exercises.")

        if all(item["status"] != "pending" for item in items):
            conn = get_db()

            with conn:
                conn.execute(
                    """
                    UPDATE sessions
                    SET finished_at = ?
                    WHERE id = ?
                      AND finished_at IS NULL
                    """,
                    (
                        datetime.now().isoformat(timespec="seconds"),
                        session_id,
                    ),
                )

            return redirect(
                url_for("session_summary", session_id=session_id)
            )

        return render_template(
            "workout.html",
            session=session,
            items=items,
        )

    @app.post("/api/items/<int:item_id>")
    def save_item(item_id):
        conn = get_db()

        item = conn.execute(
            """
            SELECT si.*, e.type, s.finished_at
            FROM session_items AS si
            JOIN exercises AS e ON e.id = si.exercise_id
            JOIN sessions AS s ON s.id = si.session_id
            WHERE si.id = ?
            """,
            (item_id,),
        ).fetchone()

        if item is None:
            return {"error": "Exercise occurrence not found."}, 404

        if item["finished_at"]:
            return {"error": "This session is already finished."}, 409

        data = request.get_json()

        if not isinstance(data, dict):
            return {"error": "Expected a JSON object."}, 400

        if "type" in data and data["type"] != item["type"]:
            return {
                "error": "This exercise changed type. Reload the workout before saving."
            }, 409

        status = data.get("status", item["status"])
        note = data.get("note", item["note"])

        if status not in ("pending", "done", "skipped"):
            return {"error": "Invalid exercise status."}, 400

        if note is not None and not isinstance(note, str):
            return {"error": "Notes must be text."}, 400

        # Missing sets preserves existing records; an empty list clears them.
        clean_sets = None

        if "sets" in data:
            raw_sets = data["sets"]

            if not isinstance(raw_sets, list):
                return {"error": "Sets must be a list."}, 400

            if item["type"] != "strength" and raw_sets:
                return {
                    "error": "Only strength exercises accept sets."
                }, 400

            clean_sets = []

            try:
                for row in raw_sets:
                    if not isinstance(row, dict):
                        raise ValueError("Each set must be an object.")

                    reps = optional_number(
                        row.get("reps"),
                        "Reps",
                        integer=True,
                    )
                    weight = optional_number(
                        row.get("weight"),
                        "Weight",
                    )

                    if reps is None and weight is None:
                        continue

                    clean_sets.append((reps, weight))

            except (TypeError, ValueError, OverflowError) as error:
                return {"error": str(error)}, 400

            if item["type"] != "strength":
                clean_sets = None

        completed_at = None

        if status == "done":
            completed_at = (
                item["completed_at"]
                if item["status"] == "done" and item["completed_at"]
                else datetime.now().isoformat(timespec="seconds")
            )

        with conn:
            # 1. Save completion/skipping and notes.
            conn.execute(
                """
                UPDATE session_items
                SET status = ?, note = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    note,
                    completed_at,
                    item_id,
                ),
            )

            # 2. Save actual strength performance.
            if clean_sets is not None:
                conn.execute(
                    """
                    DELETE FROM strength_sets
                    WHERE session_item_id = ?
                    """,
                    (item_id,),
                )

                conn.executemany(
                    """
                    INSERT INTO strength_sets
                        (session_item_id, set_number, reps, weight)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (item_id, number, reps, weight)
                        for number, (reps, weight)
                        in enumerate(clean_sets, start=1)
                    ],
                )

            # 3. Automatically finish when no pending exercises remain.
            conn.execute(
                """
                UPDATE sessions
                SET finished_at = ?
                WHERE id = ?
                  AND finished_at IS NULL
                  AND EXISTS (
                      SELECT 1
                      FROM session_items
                      WHERE session_id = sessions.id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM session_items
                      WHERE session_id = sessions.id
                        AND status = 'pending'
                  )
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    item["session_id"],
                ),
            )

        return {
            "ok": True,
            "status": status,
            "completed_at": completed_at,
        }

    @app.post("/session/<int:session_id>/finish")
    def finish_session(session_id):
        session = load_session(session_id)
        conn = get_db()

        pending = conn.execute(
            """
            SELECT COUNT(*)
            FROM session_items
            WHERE session_id = ? AND status = 'pending'
            """,
            (session_id,),
        ).fetchone()[0]

        if pending:
            return {
                "error": (
                    f"{pending} exercises are still pending. "
                    "Complete or skip them before finishing."
                )
            }, 409

        if not session["finished_at"]:
            with conn:
                conn.execute(
                    "UPDATE sessions SET finished_at = ? WHERE id = ?",
                    (
                        datetime.now().isoformat(timespec="seconds"),
                        session_id,
                    ),
                )

        return {
            "ok": True,
            "redirect": url_for(
                "session_summary",
                session_id=session_id,
            ),
        }

    @app.get("/session/<int:session_id>/summary")
    def session_summary(session_id):
        session = load_session(session_id)

        session_date = datetime.fromisoformat(
            session["date"]
        ).date()

        display_date = (
            f"{session_date.strftime('%A, %b')} "
            f"{session_date.day}, {session_date.year}"
        )

        def display_time(value):
            if not value:
                return "Not finished"

            timestamp = datetime.fromisoformat(value)

            return timestamp.strftime("%I:%M %p").lstrip("0").lower()

        return render_template(
            "summary.html",
            session=session,
            items=load_items(session_id),
            display_date=display_date,
            started_time=display_time(session["started_at"]),
            finished_time=display_time(session["finished_at"]),
        )

    @app.get("/history")
    def history():
        conn = get_db()
        sessions = conn.execute(
            """
            SELECT
                s.*,
                COUNT(si.id) AS total,
                SUM(CASE WHEN si.status = 'done' THEN 1 ELSE 0 END)
                    AS done_count,
                SUM(CASE WHEN si.status = 'skipped' THEN 1 ELSE 0 END)
                    AS skipped_count,
                SUM(CASE WHEN si.status = 'pending' THEN 1 ELSE 0 END)
                    AS pending_count
            FROM sessions AS s
            LEFT JOIN session_items AS si ON si.session_id = s.id
            GROUP BY s.id
            """
        ).fetchall()

        activities = conn.execute("SELECT * FROM activity_logs").fetchall()
        entries = [
            {**dict(session), "kind": "workout", "recorded_at": session["started_at"]}
            for session in sessions
        ]
        entries.extend(
            {**dict(activity), "kind": "activity", "recorded_at": activity["created_at"]}
            for activity in activities
        )
        entries.sort(
            key=lambda entry: (
                entry["date"], entry["recorded_at"], entry["kind"], entry["id"],
            ),
            reverse=True,
        )
        today = datetime.now().date()
        month_text = request.args.get("month", today.strftime("%Y-%m"))
        selected_day = request.args.get("day")
        exercise_text = request.args.get("exercise_id")
        try:
            month = date.fromisoformat(month_text + "-01")
            if month.isoformat()[:7] != month_text:
                raise ValueError("Choose a month in YYYY-MM format.")
            if selected_day is not None and date.fromisoformat(selected_day).isoformat() != selected_day:
                raise ValueError("Choose a day in YYYY-MM-DD format.")
            exercise_id = int(exercise_text) if exercise_text is not None else None
            dashboard = build_dashboard(conn, sessions, activities, today, month, exercise_id)
        except ValueError as error:
            abort(400, description=f"Invalid history filter: {error}")
        if selected_day:
            entries = [entry for entry in entries if entry["date"] == selected_day]
        return render_template(
            "history.html", entries=entries, dashboard=dashboard, selected_day=selected_day,
        )