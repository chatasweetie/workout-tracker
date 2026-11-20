"""Walk, run, and bike logging, separate from guided workout sessions."""
import sqlite3
from datetime import date, datetime

from flask import redirect, render_template, request, url_for

from app.tracking import optional_number


ACTIVITY_TYPES = {"walk": "Walk", "run": "Run", "bike": "Bike"}


def register_activity_routes(app, get_db):
    @app.route("/activities", methods=["GET", "POST"])
    def activity_log():
        values = {
            "activity_type": "walk",
            "date": date.today().isoformat(),
            "duration_minutes": "",
            "distance_miles": "",
        }
        error = None
        status = 200
        conn = get_db()

        if request.method == "POST":
            values.update({key: request.form.get(key, "") for key in values})
            try:
                if values["activity_type"] not in ACTIVITY_TYPES:
                    raise ValueError("Choose Walk, Run, or Bike.")
                try:
                    activity_date = date.fromisoformat(values["date"])
                except ValueError:
                    raise ValueError("Choose a valid activity date.") from None
                if activity_date.isoformat() != values["date"]:
                    raise ValueError("Choose a valid activity date.")

                duration = optional_number(values["duration_minutes"], "Duration")
                distance = optional_number(values["distance_miles"], "Distance")
                if duration is None or duration <= 0:
                    raise ValueError("Enter a duration greater than zero minutes.")
                if distance is None:
                    raise ValueError("Enter a distance in miles. Zero is allowed.")

                with conn:
                    conn.execute(
                        """
                        INSERT INTO activity_logs
                            (activity_type, date, duration_minutes, distance_miles, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            values["activity_type"], activity_date.isoformat(),
                            duration, distance,
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                return redirect(url_for("activity_log", saved="1"))
            except (TypeError, ValueError, OverflowError) as failure:
                error, status = str(failure), 400
            except sqlite3.Error:
                app.logger.exception("Activity log save failed")
                error = "Could not save this activity. Your entries are still here; please retry."
                status = 500

        activities = conn.execute(
            "SELECT * FROM activity_logs ORDER BY date DESC, id DESC",
        ).fetchall()
        return render_template(
            "activities.html", values=values, activities=activities,
            activity_types=ACTIVITY_TYPES, error=error,
            saved=request.method == "GET" and request.args.get("saved") == "1",
        ), status
